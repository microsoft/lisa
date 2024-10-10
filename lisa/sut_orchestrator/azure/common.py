# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import hashlib
import json
import os
import re
import sys
from dataclasses import InitVar, dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache, partial
from pathlib import Path, PurePath
from threading import Lock
from time import sleep, time
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    List,
    Optional,
    Tuple,
    Type,
    Union,
)

import requests
from assertpy import assert_that
from azure.core.exceptions import ResourceExistsError
from azure.keyvault.certificates import (
    CertificateClient,
    CertificatePolicy,
    KeyVaultCertificate,
)
from azure.keyvault.secrets import SecretClient
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.compute.models import (
    CommunityGalleryImage,
    GalleryImage,
    VirtualMachine,
)
from azure.mgmt.keyvault import KeyVaultManagementClient
from azure.mgmt.keyvault.models import (
    AccessPolicyEntry,
    Permissions,
    VaultCreateOrUpdateParameters,
    VaultProperties,
)
from azure.mgmt.marketplaceordering import MarketplaceOrderingAgreements  # type: ignore
from azure.mgmt.msi import ManagedServiceIdentityClient
from azure.mgmt.network import NetworkManagementClient  # type: ignore
from azure.mgmt.network.models import (  # type: ignore
    PrivateDnsZoneConfig,
    PrivateDnsZoneGroup,
    PrivateEndpoint,
    PrivateLinkServiceConnection,
    PrivateLinkServiceConnectionState,
    Subnet,
)
from azure.mgmt.privatedns import PrivateDnsManagementClient  # type: ignore
from azure.mgmt.privatedns.models import (  # type: ignore
    ARecord,
    PrivateZone,
    RecordSet,
    SubResource,
    VirtualNetworkLink,
)
from azure.mgmt.resource import (  # type: ignore
    ResourceManagementClient,
    SubscriptionClient,
)
from azure.mgmt.storage import StorageManagementClient
from azure.mgmt.storage.models import Sku, StorageAccountCreateParameters
from azure.storage.blob import (
    BlobClient,
    BlobSasPermissions,
    BlobServiceClient,
    ContainerClient,
    ContentSettings,
    generate_blob_sas,
)
from azure.storage.fileshare import ShareServiceClient
from dataclasses_json import dataclass_json
from marshmallow import fields, validate
from msrestazure.azure_cloud import AZURE_PUBLIC_CLOUD, Cloud  # type: ignore
from PIL import Image, UnidentifiedImageError
from requests.exceptions import ChunkedEncodingError
from retry import retry

from lisa import feature, schema, search_space
from lisa.environment import Environment, load_environments
from lisa.feature import Features
from lisa.features.security_profile import SecurityProfileType
from lisa.node import Node, RemoteNode, local
from lisa.secret import PATTERN_HEADTAIL, PATTERN_URL, add_secret, replace
from lisa.tools import Ls
from lisa.util import (
    LisaException,
    LisaTimeoutException,
    check_till_timeout,
    constants,
    field_metadata,
    get_matched_str,
    strip_strs,
)
from lisa.util.logger import Logger
from lisa.util.parallel import check_cancelled
from lisa.util.perf_timer import create_timer

if TYPE_CHECKING:
    from .platform_ import AzurePlatform

AZURE_SHARED_RG_NAME = "lisa_shared_resource"
AZURE_VIRTUAL_NETWORK_NAME = "lisa-virtualNetwork"
AZURE_SUBNET_PREFIX = "lisa-subnet-"

NIC_NAME_PATTERN = re.compile(r"Microsoft.Network/networkInterfaces/(.*)", re.M)
PATTERN_PUBLIC_IP_NAME = re.compile(
    r"providers/Microsoft.Network/publicIPAddresses/(.*)", re.M
)
# /subscriptions/xxxx/resourceGroups/xxxx/providers/Microsoft.Compute/galleries/xxxx
# /subscriptions/xxxx/resourceGroups/xxxx/providers/Microsoft.Storage/storageAccounts/xxxx
RESOURCE_GROUP_PATTERN = re.compile(r"resourceGroups/(.*)/providers", re.M)
# https://sc.blob.core.windows.net/container/xxxx/xxxx/xxxx.vhd
STORAGE_CONTAINER_BLOB_PATTERN = re.compile(
    r"https://(?P<sc>.*)"
    r"(?:\.blob\.core\.windows\.net|blob\.storage\.azure\.net)"
    r"/(?P<container>[^/]+)/?/(?P<blob>.*)",
    re.M,
)

# https://abcdefg.blob.core.windows.net/abcdefg?sv=2020-08-04&
# st=2022-01-19T06%3A25%3A16Z&se=2022-01-19T06%3A25%3A00Z&sr=b&
# sp=r&sig=DdBu3FTHQr1%2BzIY%2FdS054IlsDQ1RdfjfL3FgRgexgeo%3D
# https://abcdefg.blob.storage.azure.net/1b33rftmpdhs/abcdefg?
# sv=2018-03-28&sr=b&si=11111111-feff-4312-bba2-3ca6eabf9b24&
# sig=xdZaRwJBwu3P2pYbQ3uEmymlovFwHrtQNVWDHyK48sg%3D
SAS_URL_PATTERN = re.compile(
    r"^https://.*?(?:\.blob\.core\.windows\.net|"
    r"blob\.storage\.azure\.net)/.*?\?sv=[^&]+?(?:&st=[^&]+)?"
    r"(?:&se=(?P<year>[\d]{4})-(?P<month>[\d]{2})-(?P<day>[\d]{2}).*?)|.*?&sig=.*?$"
)
SAS_COPIED_CONTAINER_NAME = "lisa-sas-copied"

# The timeout hours of the blob with copy pending status
# If the blob is still copy pending status after the timeout hours, it can be deleted
BLOB_COPY_PENDING_TIMEOUT_HOURS = 6
_global_sas_vhd_copy_lock = Lock()

# when call sdk APIs, it's easy to have conflict on access auth files. Use lock
# to prevent it happens.
global_credential_access_lock = Lock()
# if user uses lisa for the first time in parallel, there will be a possibility
# to create the same storage account at the same time.
# add a lock to prevent it happens.
_global_storage_account_check_create_lock = Lock()
_global_download_blob_lock = Lock()

MARKETPLACE_IMAGE_KEYS = ["publisher", "offer", "sku", "version"]
SIG_IMAGE_KEYS = [
    "subscription_id",
    "resource_group_name",
    "image_gallery",
    "image_definition",
    "image_version",
]
CG_IMAGE_KEYS = [
    "location",
    "image_gallery",
    "image_definition",
    "image_version",
]
PURCHASE_PLAN_KEYS = ["name", "product", "publisher"]

# IMDS is a REST API that's available at a well-known, non-routable IP address (169.254.169.254). # noqa: E501
METADATA_ENDPOINT = "http://169.254.169.254/metadata/instance?api-version=2021-02-01"


@dataclass
class EnvironmentContext:
    resource_group_name: str = ""
    resource_group_is_specified: bool = False
    provision_time: float = 0


@dataclass
class NodeContext:
    resource_group_name: str = ""
    vm_name: str = ""
    username: str = ""
    password: str = ""
    private_key_file: str = ""
    use_public_address: bool = True
    public_ip_address: str = ""
    private_ip_address: str = ""
    location: str = ""
    subscription_id: str = ""


@dataclass_json()
@dataclass
class AzureVmPurchasePlanSchema:
    name: str
    product: str
    publisher: str


@dataclass_json
@dataclass
class AzureImageSchema(schema.ImageSchema):
    architecture: Union[
        schema.ArchitectureType, search_space.SetSpace[schema.ArchitectureType]
    ] = field(  # type: ignore
        default_factory=partial(
            search_space.SetSpace,
            is_allow_set=True,
            items=[schema.ArchitectureType.x64, schema.ArchitectureType.Arm64],
        ),
        metadata=field_metadata(
            decoder=partial(
                search_space.decode_nullable_set_space,
                base_type=schema.ArchitectureType,
                is_allow_set=True,
                default_values=[
                    schema.ArchitectureType.x64,
                    schema.ArchitectureType.Arm64,
                ],
            )
        ),
    )
    disk_controller_type: Optional[
        Union[
            search_space.SetSpace[schema.DiskControllerType], schema.DiskControllerType
        ]
    ] = field(  # type:ignore
        default_factory=partial(
            search_space.SetSpace,
            is_allow_set=True,
            items=[schema.DiskControllerType.SCSI, schema.DiskControllerType.NVME],
        ),
        metadata=field_metadata(
            decoder=partial(
                search_space.decode_nullable_set_space,
                base_type=schema.DiskControllerType,
                is_allow_set=True,
                default_values=[
                    schema.DiskControllerType.SCSI,
                    schema.DiskControllerType.NVME,
                ],
            )
        ),
    )
    hyperv_generation: Optional[
        Union[search_space.SetSpace[int], int]
    ] = field(  # type:ignore
        default_factory=partial(
            search_space.SetSpace,
            is_allow_set=True,
            items=[1, 2],
        ),
        metadata=field_metadata(
            decoder=partial(search_space.decode_set_space_by_type, base_type=int)
        ),
    )
    network_data_path: Optional[
        Union[search_space.SetSpace[schema.NetworkDataPath], schema.NetworkDataPath]
    ] = field(  # type: ignore
        default_factory=partial(
            search_space.SetSpace,
            is_allow_set=True,
            items=[
                schema.NetworkDataPath.Synthetic,
                schema.NetworkDataPath.Sriov,
            ],
        ),
        metadata=field_metadata(
            decoder=partial(
                search_space.decode_set_space_by_type,
                base_type=schema.NetworkDataPath,
            )
        ),
    )
    security_profile: Union[
        search_space.SetSpace[SecurityProfileType], SecurityProfileType
    ] = field(  # type:ignore
        default_factory=partial(
            search_space.SetSpace,
            is_allow_set=True,
            items=[
                SecurityProfileType.Standard,
                SecurityProfileType.SecureBoot,
                SecurityProfileType.CVM,
                SecurityProfileType.Stateless,
            ],
        ),
        metadata=field_metadata(
            decoder=partial(
                search_space.decode_nullable_set_space,
                base_type=SecurityProfileType,
                is_allow_set=True,
                default_values=[
                    SecurityProfileType.Standard,
                    SecurityProfileType.SecureBoot,
                    SecurityProfileType.CVM,
                    SecurityProfileType.Stateless,
                ],
            )
        ),
    )

    def load_from_platform(self, platform: "AzurePlatform") -> None:
        """
        Load image features from Azure platform.
        Relevant image tags will be used to populate the schema.
        """
        raw_features = self._get_info(platform)
        if raw_features:
            self._parse_info(raw_features, platform._log)

    def _get_info(self, platform: "AzurePlatform") -> Dict[str, Any]:
        """Get raw image tags from Azure platform."""
        raise NotImplementedError()

    def _parse_info(self, raw_features: Dict[str, Any], log: Logger) -> None:
        """Parse raw image tags to AzureImageSchema"""
        self._parse_architecture(raw_features, log)
        self._parse_disk_controller_type(raw_features, log)
        self._parse_hyperv_generation(raw_features, log)
        self._parse_network_data_path(raw_features, log)
        self._parse_security_profile(raw_features, log)

    def _parse_architecture(self, raw_features: Dict[str, Any], log: Logger) -> None:
        arch = raw_features.get("architecture")
        if arch == "Arm64":
            self.architecture = schema.ArchitectureType.Arm64
        elif arch == "x64":
            self.architecture = schema.ArchitectureType.x64

    def _parse_disk_controller_type(
        self, raw_features: Dict[str, Any], log: Logger
    ) -> None:
        disk_controller_type = raw_features.get("DiskControllerTypes")
        if (
            isinstance(disk_controller_type, str)
            and disk_controller_type.lower() == "scsi"
        ):
            self.disk_controller_type = schema.DiskControllerType.SCSI
        elif (
            isinstance(disk_controller_type, str)
            and disk_controller_type.lower() == "nvme"
        ):
            self.disk_controller_type = schema.DiskControllerType.NVME

    def _parse_hyperv_generation(
        self, raw_features: Dict[str, Any], log: Logger
    ) -> None:
        try:
            gen = raw_features.get("hyper_v_generation")
            if gen:
                self.hyperv_generation = int(gen.strip("V"))
        except (TypeError, ValueError, AttributeError):
            log.debug(
                "Failed to parse Hyper-V generation: "
                f"{raw_features.get('hyper_v_generation')}"
            )

    def _parse_network_data_path(
        self, raw_features: Dict[str, Any], log: Logger
    ) -> None:
        network_data_path = raw_features.get("IsAcceleratedNetworkSupported")
        if network_data_path == "False":
            self.network_data_path = schema.NetworkDataPath.Synthetic

    def _parse_security_profile(
        self, raw_features: Dict[str, Any], log: Logger
    ) -> None:
        security_profile = raw_features.get("SecurityType")
        capabilities: List[SecurityProfileType] = []
        if security_profile in ["TrustedLaunchSupported", "TrustedLaunch"]:
            capabilities.append(SecurityProfileType.Standard)
            capabilities.append(SecurityProfileType.SecureBoot)
        elif security_profile in (
            "TrustedLaunchAndConfidentialVmSupported",
            "ConfidentialVmSupported",
        ):
            capabilities.append(SecurityProfileType.CVM)
            capabilities.append(SecurityProfileType.Stateless)
        else:
            capabilities.append(SecurityProfileType.Standard)

        self.security_profile = search_space.SetSpace(True, capabilities)


def _get_image_tags(image: Any) -> Dict[str, Any]:
    """
    Marketplace, Shared Image Gallery, and Community Gallery images
    have similar structures for image tags. This function extracts
    the tags and converts to a dictionary.
    """
    image_tags: Dict[str, Any] = {}
    if not image:
        return image_tags
    if hasattr(image, "hyper_v_generation") and image.hyper_v_generation:
        image_tags["hyper_v_generation"] = image.hyper_v_generation
    if hasattr(image, "architecture") and image.architecture:
        image_tags["architecture"] = image.architecture
    if (
        hasattr(image, "features")
        and image.features
        and isinstance(image.features, Iterable)
    ):
        for feat in image.features:
            image_tags[feat.name] = feat.value
    return image_tags


@dataclass_json()
@dataclass
class AzureVmMarketplaceSchema(AzureImageSchema):
    publisher: str = "Canonical"
    offer: str = "0001-com-ubuntu-server-jammy"
    sku: str = "22_04-lts"
    version: str = "Latest"

    def __hash__(self) -> int:
        return hash(f"{self.publisher}/{self.offer}/{self.sku}/{self.version}")

    def _get_info(self, platform: "AzurePlatform") -> Dict[str, Any]:
        for location in platform.find_marketplace_image_location():
            image_info = platform.get_image_info(location, self)
            if image_info:
                return _get_image_tags(image_info)
        return {}


@dataclass_json()
@dataclass
class SharedImageGallerySchema(AzureImageSchema):
    subscription_id: str = ""
    resource_group_name: Optional[str] = None
    image_gallery: str = ""
    image_definition: str = ""
    image_version: str = ""

    def __hash__(self) -> int:
        return hash(
            f"/subscriptions/{self.subscription_id}/resourceGroups/"
            f"{self.resource_group_name}/providers/Microsoft.Compute/galleries/"
            f"{self.image_gallery}/images/{self.image_definition}/versions/"
            f"{self.image_version}"
        )

    def query_platform(self, platform: "AzurePlatform") -> GalleryImage:
        assert self.resource_group_name, "'resource_group_name' must not be 'None'"
        compute_client = get_compute_client(
            platform, subscription_id=self.subscription_id
        )
        sig = compute_client.gallery_images.get(
            resource_group_name=self.resource_group_name,
            gallery_name=self.image_gallery,
            gallery_image_name=self.image_definition,
        )
        assert isinstance(sig, GalleryImage), f"actual: {type(sig)}"
        return sig

    def resolve_version(self, platform: "AzurePlatform") -> None:
        compute_client = get_compute_client(
            platform, subscription_id=self.subscription_id
        )
        if not self.resource_group_name:
            # /subscriptions/xxxx/resourceGroups/xxxx/providers/Microsoft.Compute/
            # galleries/xxxx
            rg_pattern = re.compile(r"resourceGroups/(.*)/providers", re.M)
            galleries = compute_client.galleries.list()
            for gallery in galleries:
                if gallery.name and gallery.name.lower() == self.image_gallery:
                    assert gallery.id, "'gallery.id' must not be 'None'"
                    self.resource_group_name = get_matched_str(gallery.id, rg_pattern)
                    break
        if not self.resource_group_name:
            raise LisaException(f"did not find matched gallery {self.image_gallery}")

        if self.image_version.lower() == "latest":
            gallery_images = (
                compute_client.gallery_image_versions.list_by_gallery_image(
                    resource_group_name=self.resource_group_name,
                    gallery_name=self.image_gallery,
                    gallery_image_name=self.image_definition,
                )
            )
            time: Optional[datetime] = None
            for image in gallery_images:
                assert image, "'image' must not be 'None'"
                assert image.name, "'image.name' must not be 'None'"
                gallery_image = compute_client.gallery_image_versions.get(
                    resource_group_name=self.resource_group_name,
                    gallery_name=self.image_gallery,
                    gallery_image_name=self.image_definition,
                    gallery_image_version_name=image.name,
                    expand="ReplicationStatus",
                )
                if not time:
                    time = gallery_image.publishing_profile.published_date
                    assert image, "'image' must not be 'None'"
                    assert image.name, "'image.name' must not be 'None'"
                    self.image_version = image.name
                elif gallery_image.publishing_profile.published_date > time:
                    time = gallery_image.publishing_profile.published_date
                    assert image, "'image' must not be 'None'"
                    assert image.name, "'image.name' must not be 'None'"
                    self.image_version = image.name

    def _get_info(self, platform: "AzurePlatform") -> Dict[str, Any]:
        self.resolve_version(platform)
        sig_info = self.query_platform(platform)
        return _get_image_tags(sig_info)


@dataclass_json()
@dataclass
class VhdSchema(AzureImageSchema):
    vhd_path: str = ""
    vmgs_path: Optional[str] = None

    def load_from_platform(self, platform: "AzurePlatform") -> None:
        return


@dataclass_json()
@dataclass
class CommunityGalleryImageSchema(AzureImageSchema):
    image_gallery: str = ""
    image_definition: str = ""
    image_version: str = ""
    location: str = ""

    def __hash__(self) -> int:
        return hash(
            f"{self.image_gallery}/{self.image_definition}/{self.image_version}"
        )

    def query_platform(self, platform: "AzurePlatform") -> CommunityGalleryImage:
        compute_client = get_compute_client(platform)
        cgi = compute_client.community_gallery_images.get(
            location=self.location,
            public_gallery_name=self.image_gallery,
            gallery_image_name=self.image_definition,
        )
        assert isinstance(cgi, CommunityGalleryImage), f"actual: {type(cgi)}"
        return cgi

    def _get_info(self, platform: "AzurePlatform") -> Dict[str, Any]:
        self.resolve_version(platform)
        cgi_info = self.query_platform(platform)
        return _get_image_tags(cgi_info)

    def resolve_version(self, platform: "AzurePlatform") -> None:
        compute_client = get_compute_client(platform)
        if self.image_version.lower() == "latest":
            community_gallery_images_list = (
                compute_client.community_gallery_image_versions.list(
                    location=self.location,
                    public_gallery_name=self.image_gallery,
                    gallery_image_name=self.image_definition,
                )
            )
            time: Optional[datetime] = None
            for image in community_gallery_images_list:
                assert image, "'image' must not be 'None'"
                assert image.name, "'image.name' must not be 'None'"
                community_gallery_image_version = (
                    compute_client.community_gallery_image_versions.get(
                        location=self.location,
                        public_gallery_name=self.image_gallery,
                        gallery_image_name=self.image_definition,
                        gallery_image_version_name=image.name,
                    )
                )
                if not time:
                    time = community_gallery_image_version.published_date
                    self.image_version = image.name
                elif community_gallery_image_version.published_date > time:
                    time = community_gallery_image_version.published_date
                    self.image_version = image.name


@dataclass_json()
@dataclass
class AzureCapability:
    location: str
    vm_size: str
    capability: schema.NodeSpace
    resource_sku: Dict[str, Any]

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        # reload features settings with platform specified types.
        convert_to_azure_node_space(self.capability)


@dataclass_json()
@dataclass
class AzureLocation:
    updated_time: datetime = field(
        default_factory=datetime.now,
        metadata=field_metadata(
            fields.DateTime,
            encoder=datetime.isoformat,
            decoder=datetime.fromisoformat,
            format="iso",
        ),
    )
    location: str = ""
    capabilities: Dict[str, AzureCapability] = field(default_factory=dict)


@dataclass_json()
@dataclass
class AzureNodeSchema:
    name: str = ""
    # It decides the real computer name. It cannot be too long.
    short_name: str = ""
    vm_size: str = ""
    # Specifies the minimum OS disk size. The size of the disk that gets provisioned
    # may be larger than this depending on other requirements set by VHD, marketplace
    # image etc but it will never be smaller.
    osdisk_size_in_gb: int = 30
    # Force to maximize capability of the vm size. It bypass requirements on
    # test cases, and uses to force run performance tests on any vm size.
    maximize_capability: bool = False

    location: str = ""
    # Required by shared gallery images which are present in
    # subscription different from where LISA is run
    subscription_id: str = ""
    purchase_plan_raw: Optional[Union[Dict[Any, Any], str]] = field(
        default=None, metadata=field_metadata(data_key="purchase_plan")
    )
    marketplace_raw: Optional[Union[Dict[Any, Any], str]] = field(
        default=None, metadata=field_metadata(data_key="marketplace")
    )
    shared_gallery_raw: Optional[Union[Dict[Any, Any], str]] = field(
        default=None, metadata=field_metadata(data_key="shared_gallery")
    )
    vhd_raw: Optional[Union[Dict[Any, Any], str]] = field(
        default=None, metadata=field_metadata(data_key="vhd")
    )
    community_gallery_image_raw: Optional[Union[Dict[Any, Any], str]] = field(
        default=None, metadata=field_metadata(data_key="community_gallery_image")
    )
    hyperv_generation: int = field(
        default=1,
        metadata=field_metadata(validate=validate.OneOf([1, 2])),
    )
    # for marketplace image, which need to accept terms
    _purchase_plan: InitVar[Optional[AzureVmPurchasePlanSchema]] = None

    # the linux and Windows has different settings. If it's not specified, it's
    # True by default for SIG and vhd, and is parsed from marketplace
    # image.
    is_linux: Optional[bool] = None

    _marketplace: InitVar[Optional[AzureVmMarketplaceSchema]] = None

    _shared_gallery: InitVar[Optional[SharedImageGallerySchema]] = None

    _vhd: InitVar[Optional[VhdSchema]] = None

    _orignal_vhd_path: str = ""

    _community_gallery_image: InitVar[Optional[CommunityGalleryImageSchema]] = None

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        # trim whitespace of values.
        strip_strs(
            self,
            [
                "name",
                "short_name",
                "vm_size",
                "location",
                "subscription_id",
                "marketplace_raw",
                "shared_gallery_raw",
                "vhd_raw",
                "community_gallery_image_raw",
                "data_disk_caching_type",
                "os_disk_type",
                "data_disk_type",
                "purchase_plan_raw",
            ],
        )
        self.location = self.location.lower()
        # If vhd contains sas token, need add mask
        if isinstance(self.vhd_raw, str):
            add_secret(self.vhd_raw, PATTERN_URL)

    @property
    def purchase_plan(self) -> Optional[AzureVmPurchasePlanSchema]:
        purchase_plan = self._parse_image(
            "purchase_plan",
            AzureVmPurchasePlanSchema,
            PURCHASE_PLAN_KEYS,
            self.purchase_plan_raw,
        )
        if isinstance(self.purchase_plan_raw, str):
            self.purchase_plan_raw = self.purchase_plan_raw.strip()

            if self.purchase_plan_raw:
                purchase_plan_strings = re.split(r"[:\s]+", self.purchase_plan_raw)

                if len(purchase_plan_strings) == 3:
                    purchase_plan = AzureVmPurchasePlanSchema(
                        name=purchase_plan_strings[0],
                        product=purchase_plan_strings[1],
                        publisher=purchase_plan_strings[2],
                    )
                    # purchase_plan_raw is used
                    self.purchase_plan_raw = purchase_plan.to_dict()
                else:
                    raise LisaException(
                        f"Invalid value for the provided purchase_plan "
                        f"parameter: '{self.purchase_plan_raw}'."
                        f"The purchase_plan parameter should be in the format: "
                        f"'<name> <product> <publisher>' "
                    )
        self._purchase_plan = purchase_plan
        return (
            purchase_plan
            if isinstance(purchase_plan, AzureVmPurchasePlanSchema)
            else None
        )

    @purchase_plan.setter
    def purchase_plan(self, value: Optional[AzureVmPurchasePlanSchema]) -> None:
        self._parse_image_raw("purchase_plan", value)

    @property
    def marketplace(self) -> Optional[AzureVmMarketplaceSchema]:
        marketplace = self._parse_image(
            "marketplace",
            AzureVmMarketplaceSchema,
            MARKETPLACE_IMAGE_KEYS,
            self.marketplace_raw,
        )
        if isinstance(self.marketplace_raw, str):
            self.marketplace_raw = self.marketplace_raw.strip()

            if self.marketplace_raw:
                # Users decide the cases of image names,
                #  the inconsistent cases cause the mismatched error in notifiers.
                # The lower() normalizes the image names,
                #  it has no impact on deployment.
                marketplace_strings = re.split(r"[:\s]+", self.marketplace_raw.lower())

                if len(marketplace_strings) == 4:
                    marketplace = AzureVmMarketplaceSchema(
                        publisher=marketplace_strings[0],
                        offer=marketplace_strings[1],
                        sku=marketplace_strings[2],
                        version=marketplace_strings[3],
                    )
                    # marketplace_raw is used
                    self.marketplace_raw = marketplace.to_dict()
                else:
                    raise LisaException(
                        f"Invalid value for the provided marketplace "
                        f"parameter: '{self.marketplace_raw}'."
                        f"The marketplace parameter should be in the format: "
                        f"'<Publisher> <Offer> <Sku> <Version>' "
                        f"or '<Publisher>:<Offer>:<Sku>:<Version>'"
                    )
        self._marketplace = marketplace
        return (
            marketplace if isinstance(marketplace, AzureVmMarketplaceSchema) else None
        )

    @marketplace.setter
    def marketplace(self, value: Optional[AzureVmMarketplaceSchema]) -> None:
        self._parse_image_raw("marketplace", value)

    @property
    def shared_gallery(self) -> Optional[SharedImageGallerySchema]:
        shared_gallery = self._parse_image(
            "shared_gallery",
            SharedImageGallerySchema,
            SIG_IMAGE_KEYS,
            self.shared_gallery_raw,
        )
        if (
            isinstance(shared_gallery, SharedImageGallerySchema)
            and not shared_gallery.subscription_id
        ):
            shared_gallery.subscription_id = self.subscription_id
        if isinstance(self.shared_gallery_raw, str):
            self.shared_gallery_raw = self.shared_gallery_raw.strip()
            if self.shared_gallery_raw:
                # Users decide the cases of image names,
                #  the inconsistent cases cause the mismatched error in notifiers.
                # The lower() normalizes the image names,
                #  it has no impact on deployment.
                shared_gallery_strings = re.split(
                    r"[/]+", self.shared_gallery_raw.strip().lower()
                )
                if len(shared_gallery_strings) == 5:
                    shared_gallery = SharedImageGallerySchema(
                        subscription_id=shared_gallery_strings[0],
                        resource_group_name=shared_gallery_strings[1],
                        image_gallery=shared_gallery_strings[2],
                        image_definition=shared_gallery_strings[3],
                        image_version=shared_gallery_strings[4],
                    )
                elif len(shared_gallery_strings) == 3:
                    shared_gallery = SharedImageGallerySchema(
                        subscription_id=self.subscription_id,
                        image_gallery=shared_gallery_strings[0],
                        image_definition=shared_gallery_strings[1],
                        image_version=shared_gallery_strings[2],
                    )
                else:
                    raise LisaException(
                        f"Invalid value for the provided shared gallery "
                        f"parameter: '{self.shared_gallery_raw}'."
                        f"The shared gallery parameter should be in the format: "
                        f"'<subscription_id>/<resource_group_name>/<image_gallery>/"
                        f"<image_definition>/<image_version>' or '<image_gallery>/"
                        f"<image_definition>/<image_version>'"
                    )
                self.shared_gallery_raw = shared_gallery.to_dict()
        self._shared_gallery = shared_gallery
        return (
            shared_gallery
            if isinstance(shared_gallery, SharedImageGallerySchema)
            else None
        )

    @shared_gallery.setter
    def shared_gallery(self, value: Optional[SharedImageGallerySchema]) -> None:
        self._parse_image_raw("shared_gallery", value)

    @property
    def vhd(self) -> Optional[VhdSchema]:
        # this is a safe guard and prevent mypy error on typing
        if not hasattr(self, "_vhd"):
            self._vhd: Optional[VhdSchema] = None
        vhd: Optional[VhdSchema] = self._vhd
        if vhd:
            return vhd
        if isinstance(self.vhd_raw, dict):
            vhd = schema.load_by_type(VhdSchema, self.vhd_raw)
            if not vhd.vhd_path:
                vhd = None
            else:
                add_secret(vhd.vhd_path, PATTERN_URL)
                self._orignal_vhd_path = replace(vhd.vhd_path, mask=PATTERN_URL)
                if vhd.vmgs_path:
                    add_secret(vhd.vmgs_path, PATTERN_URL)
                # this step makes vhd_raw is validated, and
                # filter out any unwanted content.
                self.vhd_raw = vhd.to_dict()  # type: ignore
        elif self.vhd_raw:
            assert isinstance(self.vhd_raw, str), f"actual: {type(self.vhd_raw)}"
            vhd = VhdSchema(vhd_path=self.vhd_raw)
            add_secret(vhd.vhd_path, PATTERN_URL)
            self._orignal_vhd_path = replace(vhd.vhd_path, mask=PATTERN_URL)
            self.vhd_raw = vhd.to_dict()  # type: ignore
        self._vhd = vhd
        if vhd:
            return vhd
        else:
            return None

    @vhd.setter
    def vhd(self, value: Optional[VhdSchema]) -> None:
        self._parse_image_raw("vhd", value)

    @property
    def community_gallery_image(self) -> Optional[CommunityGalleryImageSchema]:
        community_gallery_image = self._parse_image(
            "community_gallery_image",
            CommunityGalleryImageSchema,
            CG_IMAGE_KEYS,
            self.community_gallery_image_raw,
        )
        if isinstance(self.community_gallery_image_raw, str):
            self.community_gallery_image_raw = self.community_gallery_image_raw.strip()
            if self.community_gallery_image_raw:
                community_gallery_image_strings = re.split(
                    r"[/]+", self.community_gallery_image_raw.lower()
                )
                if len(community_gallery_image_strings) == 4:
                    community_gallery_image = CommunityGalleryImageSchema(
                        location=community_gallery_image_strings[0],
                        image_gallery=community_gallery_image_strings[1],
                        image_definition=community_gallery_image_strings[2],
                        image_version=community_gallery_image_strings[3],
                    )
                    self.community_gallery_image_raw = community_gallery_image.to_dict()
                else:
                    raise LisaException(
                        "Invalid value for the provided community gallery image"
                        f"parameter: '{self.community_gallery_image_raw}'."
                        "The community gallery image parameter should be in the"
                        " format: '<location>/<image_gallery>/<image_definition>"
                        "/<image_version>'"
                    )
        self._community_gallery_image = community_gallery_image
        return (
            community_gallery_image
            if isinstance(community_gallery_image, CommunityGalleryImageSchema)
            else None
        )

    @community_gallery_image.setter
    def community_gallery_image(
        self, value: Optional[CommunityGalleryImageSchema]
    ) -> None:
        self._parse_image_raw("community_gallery_image", value)

    @property
    def image(self) -> Optional[AzureImageSchema]:
        if self.marketplace:
            return self.marketplace
        elif self.shared_gallery:
            return self.shared_gallery
        elif self.community_gallery_image:
            return self.community_gallery_image
        elif self.vhd:
            return self.vhd
        return None

    @image.setter
    def image(self, value: Optional[AzureImageSchema]) -> None:
        if isinstance(value, AzureVmMarketplaceSchema):
            self.marketplace = value
        elif isinstance(value, SharedImageGallerySchema):
            self.shared_gallery = value
        elif isinstance(value, CommunityGalleryImageSchema):
            self.community_gallery_image = value
        elif isinstance(value, VhdSchema):
            self.vhd = value
        else:
            raise LisaException(f"unsupported image type: {type(value)}")

    def get_image_name(self) -> str:
        result = ""
        if self._orignal_vhd_path:
            result = self._orignal_vhd_path
        elif self.shared_gallery:
            assert isinstance(
                self.shared_gallery_raw, dict
            ), f"actual type: {type(self.shared_gallery_raw)}"
            if self.shared_gallery.resource_group_name:
                result = "/".join(
                    [getattr(self.shared_gallery, k, "") for k in SIG_IMAGE_KEYS]
                )
            else:
                result = (
                    f"{self.shared_gallery.image_gallery}/"
                    f"{self.shared_gallery.image_definition}/"
                    f"{self.shared_gallery.image_version}"
                )
        elif self.community_gallery_image:
            assert isinstance(
                self.community_gallery_image_raw, dict
            ), f"actual type: {type(self.community_gallery_image_raw)}"
            result = "/".join(
                [self.community_gallery_image_raw.get(k, "") for k in CG_IMAGE_KEYS]
            )
        elif self.marketplace:
            assert isinstance(
                self.marketplace_raw, dict
            ), f"actual type: {type(self.marketplace_raw)}"
            result = " ".join(
                [self.marketplace_raw.get(k, "") for k in MARKETPLACE_IMAGE_KEYS]
            )
        return result

    def update_raw(self) -> None:
        self._parse_image_raw("purchase_plan", self.purchase_plan)
        self._parse_image_raw("marketplace", self.marketplace)
        self._parse_image_raw("shared_gallery", self.shared_gallery)
        self._parse_image_raw("vhd", self.vhd)
        self._parse_image_raw("community_gallery_image", self.community_gallery_image)

    def _parse_image(
        self,
        prop_name: str,
        schema_type: Type[
            Union[
                VhdSchema,
                AzureImageSchema,
                SharedImageGallerySchema,
                CommunityGalleryImageSchema,
                AzureVmPurchasePlanSchema,
            ]
        ],
        keys: List[str],
        raw_data: Optional[Union[Dict[Any, Any], str]],
    ) -> Any:
        if not hasattr(self, f"_{prop_name}"):
            setattr(self, f"_{prop_name}", None)
        prop_value = getattr(self, f"_{prop_name}")

        if prop_value:
            return prop_value

        if isinstance(raw_data, dict):
            normalized_data = {
                k: (v.lower() if isinstance(v, str) and hasattr(schema_type, k) else v)
                for k, v in raw_data.items()
            }
            prop_value = schema.load_by_type(schema_type, normalized_data)

            # Check if all required keys have values
            if all(getattr(prop_value, key) for key in keys):
                setattr(self, f"{prop_name}_raw", prop_value.to_dict())
            else:
                setattr(self, f"{prop_name}_raw", None)

        return prop_value

    def _parse_image_raw(
        self,
        prop_name: str,
        value: Optional[
            Union[
                VhdSchema,
                AzureImageSchema,
                SharedImageGallerySchema,
                CommunityGalleryImageSchema,
                AzureVmPurchasePlanSchema,
            ]
        ],
    ) -> None:
        setattr(self, f"_{prop_name}", value)
        if value is not None:
            raw_value = (
                value.to_dict() if hasattr(value, "to_dict") else value  # type: ignore
            )
        else:
            raw_value = None

        setattr(self, f"{prop_name}_raw", raw_value)


@dataclass_json()
@dataclass
class AzureNodeArmParameter(AzureNodeSchema):
    nic_count: int = 1
    enable_sriov: bool = False
    os_disk_type: str = ""
    data_disk_type: str = ""
    disk_controller_type: str = ""
    security_profile: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_node_runbook(cls, runbook: AzureNodeSchema) -> "AzureNodeArmParameter":
        parameters = runbook.to_dict()  # type: ignore
        keys_to_rename = {
            "marketplace": "marketplace_raw",
            "purchase_plan": "purchase_plan_raw",
            "shared_gallery": "shared_gallery_raw",
            "community_gallery_image": "community_gallery_image_raw",
            "vhd": "vhd_raw",
        }

        for old_key, new_key in keys_to_rename.items():
            if old_key in parameters:
                parameters[new_key] = parameters.pop(old_key)

        arm_parameters = AzureNodeArmParameter(**parameters)

        return arm_parameters


class DataDiskCreateOption:
    DATADISK_CREATE_OPTION_TYPE_EMPTY: str = "Empty"
    DATADISK_CREATE_OPTION_TYPE_FROM_IMAGE: str = "FromImage"
    DATADISK_CREATE_OPTION_TYPE_ATTACH: str = "Attach"

    @staticmethod
    def get_create_option() -> List[str]:
        return [
            DataDiskCreateOption.DATADISK_CREATE_OPTION_TYPE_EMPTY,
            DataDiskCreateOption.DATADISK_CREATE_OPTION_TYPE_FROM_IMAGE,
            DataDiskCreateOption.DATADISK_CREATE_OPTION_TYPE_ATTACH,
        ]


@dataclass_json()
@dataclass
class DataDiskSchema:
    caching_type: str = field(
        default=constants.DATADISK_CACHING_TYPE_NONE,
        metadata=field_metadata(
            validate=validate.OneOf(
                [
                    constants.DATADISK_CACHING_TYPE_NONE,
                    constants.DATADISK_CACHING_TYPE_READONLY,
                    constants.DATADISK_CACHING_TYPE_READYWRITE,
                ]
            )
        ),
    )
    size: int = 32
    iops: int = 0
    throughput: int = 0  # MB/s
    type: str = field(
        default=schema.DiskType.StandardHDDLRS,
        metadata=field_metadata(
            validate=validate.OneOf(
                [
                    schema.DiskType.StandardHDDLRS,
                    schema.DiskType.StandardSSDLRS,
                    schema.DiskType.PremiumSSDLRS,
                    schema.DiskType.PremiumV2SSDLRS,
                    schema.DiskType.UltraSSDLRS,
                    schema.DiskType.Ephemeral,
                ]
            )
        ),
    )
    create_option: str = field(
        default=DataDiskCreateOption.DATADISK_CREATE_OPTION_TYPE_EMPTY,
        metadata=field_metadata(
            validate=validate.OneOf(DataDiskCreateOption.get_create_option())
        ),
    )


@dataclass_json()
@dataclass
class AvailabilityArmParameter:
    availability_type: str = constants.AVAILABILITY_DEFAULT
    availability_set_tags: Dict[str, str] = field(default_factory=dict)
    availability_set_properties: Dict[str, Any] = field(default_factory=dict)
    availability_zones: List[int] = field(default_factory=list)


@dataclass_json()
@dataclass
class AzureArmParameter:
    vhd_storage_name: str = ""
    location: str = ""
    admin_username: str = ""
    admin_password: str = ""
    admin_key_data: str = ""
    subnet_count: int = 1
    availability_options: AvailabilityArmParameter = field(
        default_factory=AvailabilityArmParameter
    )
    shared_resource_group_name: str = AZURE_SHARED_RG_NAME
    nodes: List[AzureNodeArmParameter] = field(default_factory=list)
    data_disks: List[DataDiskSchema] = field(default_factory=list)
    vm_tags: Dict[str, Any] = field(default_factory=dict)
    tags: Dict[str, Any] = field(default_factory=dict)
    ip_service_tags: Dict[str, str] = field(default_factory=dict)

    virtual_network_resource_group: str = ""
    virtual_network_name: str = AZURE_VIRTUAL_NETWORK_NAME
    subnet_prefix: str = AZURE_SUBNET_PREFIX
    is_ultradisk: bool = False

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        add_secret(self.admin_username, PATTERN_HEADTAIL)
        add_secret(self.admin_password)
        add_secret(self.admin_key_data)


def get_compute_client(
    platform: "AzurePlatform",
    api_version: Optional[str] = None,
    subscription_id: str = "",
) -> ComputeManagementClient:
    if not subscription_id:
        subscription_id = platform.subscription_id
    return ComputeManagementClient(
        credential=platform.credential,
        subscription_id=subscription_id,
        api_version=api_version,
        base_url=platform.cloud.endpoints.resource_manager,
        credential_scopes=[platform.cloud.endpoints.resource_manager + "/.default"],
    )


def create_update_private_endpoints(
    platform: "AzurePlatform",
    resource_group_name: str,
    location: str,
    subnet_id: str,
    private_link_service_id: str,
    group_ids: List[str],
    log: Logger,
) -> Any:
    network = get_network_client(platform)
    private_endpoint_name = "pe_test"
    status = "Approved"
    description = "Auto-Approved"
    private_endpoint = network.private_endpoints.begin_create_or_update(
        resource_group_name=resource_group_name,
        private_endpoint_name=private_endpoint_name,
        parameters=PrivateEndpoint(
            location=location,
            subnet=Subnet(id=subnet_id),
            private_link_service_connections=[
                PrivateLinkServiceConnection(
                    name=private_endpoint_name,
                    private_link_service_id=private_link_service_id,
                    group_ids=group_ids,
                    private_link_service_connection_state=(
                        PrivateLinkServiceConnectionState(
                            status=status, description=description
                        )
                    ),
                )
            ],
        ),
    )
    log.debug(f"create private endpoints: {private_endpoint_name}")
    result = private_endpoint.result()
    return result.custom_dns_configs[0].ip_addresses[0]


def delete_private_endpoints(
    platform: "AzurePlatform",
    resource_group_name: str,
    log: Logger,
) -> None:
    network = get_network_client(platform)
    private_endpoint_name = "pe_test"
    try:
        network.private_endpoints.get(
            resource_group_name=resource_group_name,
            private_endpoint_name=private_endpoint_name,
        )
        log.debug(f"found private endpoints: {private_endpoint_name}")
        network.private_endpoints.begin_delete(
            resource_group_name=resource_group_name,
            private_endpoint_name=private_endpoint_name,
        )
        log.debug(f"delete private endpoints: {private_endpoint_name}")
    except Exception:
        log.debug(f"not find private endpoints: {private_endpoint_name}")


def get_private_dns_management_client(
    platform: "AzurePlatform",
) -> PrivateDnsManagementClient:
    return PrivateDnsManagementClient(
        credential=platform.credential,
        subscription_id=platform.subscription_id,
        base_url=platform.cloud.endpoints.resource_manager,
        credential_scopes=[platform.cloud.endpoints.resource_manager + "/.default"],
    )


def create_update_private_zones(
    platform: "AzurePlatform",
    resource_group_name: str,
    log: Logger,
) -> Any:
    private_dns_client = get_private_dns_management_client(platform)
    private_zone_name = "privatelink"
    private_zone_location = "global"
    private_zone_name = ".".join(
        [private_zone_name, "file", platform.cloud.suffixes.storage_endpoint]
    )
    private_zones = private_dns_client.private_zones.begin_create_or_update(
        resource_group_name=resource_group_name,
        private_zone_name=private_zone_name,
        parameters=PrivateZone(location=private_zone_location),  # or Private
    )
    log.debug(f"create private zone: {private_zone_name}")
    result = private_zones.result()
    return result.id


def delete_private_zones(
    platform: "AzurePlatform",
    resource_group_name: str,
    log: Logger,
) -> None:
    private_dns_client = get_private_dns_management_client(platform)
    private_zone_name = "privatelink"
    private_zone_name = ".".join(
        [private_zone_name, "file", platform.cloud.suffixes.storage_endpoint]
    )
    try:
        private_dns_client.private_zones.get(
            resource_group_name=resource_group_name,
            private_zone_name=private_zone_name,
        )
        log.debug(f"found private zone: {private_zone_name}")
        timer = create_timer()
        while timer.elapsed(False) < 60:
            try:
                private_dns_client.private_zones.begin_delete(
                    resource_group_name=resource_group_name,
                    private_zone_name=private_zone_name,
                )
                log.debug(f"delete private zone: {private_zone_name}")
                break
            except Exception as identifier:
                if (
                    "Can not delete resource before nested resources are deleted"
                    in str(identifier)
                ):
                    sleep(1)
                    continue
    except Exception:
        log.debug(f"not find private zone: {private_zone_name}")


def create_update_record_sets(
    platform: "AzurePlatform",
    resource_group_name: str,
    ipv4_address: str,
    log: Logger,
) -> None:
    private_dns_client = get_private_dns_management_client(platform)
    private_zone_name = "privatelink"
    relative_record_set_name = "privatelink"
    record_type = "A"
    private_zone_name = ".".join(
        [private_zone_name, "file", platform.cloud.suffixes.storage_endpoint]
    )
    private_dns_client.record_sets.create_or_update(
        resource_group_name=resource_group_name,
        private_zone_name=private_zone_name,
        relative_record_set_name=relative_record_set_name,
        record_type=record_type,
        parameters=RecordSet(ttl=10, a_records=[ARecord(ipv4_address=ipv4_address)]),
    )
    log.debug(f"create record sets: {relative_record_set_name}")


def delete_record_sets(
    platform: "AzurePlatform",
    resource_group_name: str,
    log: Logger,
) -> None:
    private_dns_client = get_private_dns_management_client(platform)
    private_zone_name = "privatelink"
    relative_record_set_name = "privatelink"
    record_type = "A"
    private_zone_name = ".".join(
        [private_zone_name, "file", platform.cloud.suffixes.storage_endpoint]
    )
    try:
        private_dns_client.record_sets.get(
            resource_group_name=resource_group_name,
            private_zone_name=private_zone_name,
            relative_record_set_name=relative_record_set_name,
            record_type=record_type,
        )
        log.debug(f"found record sets: {relative_record_set_name}")
        private_dns_client.record_sets.delete(
            resource_group_name=resource_group_name,
            private_zone_name=private_zone_name,
            relative_record_set_name=relative_record_set_name,
            record_type=record_type,
        )
        log.debug(f"delete record sets: {relative_record_set_name}")
    except Exception:
        log.debug(f"not find record sets: {relative_record_set_name}")


def create_update_virtual_network_links(
    platform: "AzurePlatform",
    resource_group_name: str,
    virtual_network_resource_id: str,
    log: Logger,
) -> None:
    private_dns_client = get_private_dns_management_client(platform)
    private_zone_name = "privatelink"
    virtual_network_link_name = "vnetlink"
    registration_enabled = False
    virtual_network_link_location = "global"
    private_zone_name = ".".join(
        [private_zone_name, "file", platform.cloud.suffixes.storage_endpoint]
    )
    private_dns_client.virtual_network_links.begin_create_or_update(
        resource_group_name=resource_group_name,
        private_zone_name=private_zone_name,
        virtual_network_link_name=virtual_network_link_name,
        parameters=VirtualNetworkLink(
            registration_enabled=registration_enabled,
            location=virtual_network_link_location,
            virtual_network=SubResource(id=virtual_network_resource_id),
        ),
    )
    log.debug(f"create virtual network link: {virtual_network_link_name}")


def delete_virtual_network_links(
    platform: "AzurePlatform",
    resource_group_name: str,
    log: Logger,
) -> None:
    private_dns_client = get_private_dns_management_client(platform)
    private_zone_name = "privatelink"
    virtual_network_link_name = "vnetlink"
    private_zone_name = ".".join(
        [private_zone_name, "file", platform.cloud.suffixes.storage_endpoint]
    )
    try:
        private_dns_client.virtual_network_links.get(
            resource_group_name=resource_group_name,
            private_zone_name=private_zone_name,
            virtual_network_link_name=virtual_network_link_name,
        )
        log.debug(f"find virtual network link: {virtual_network_link_name}")
        private_dns_client.virtual_network_links.begin_delete(
            resource_group_name=resource_group_name,
            private_zone_name=private_zone_name,
            virtual_network_link_name=virtual_network_link_name,
        )
        log.debug(f"delete virtual network link: {virtual_network_link_name}")
    except Exception:
        log.debug(f"not find virtual network link: {virtual_network_link_name}")


def create_update_private_dns_zone_groups(
    platform: "AzurePlatform",
    resource_group_name: str,
    private_dns_zone_id: str,
    log: Logger,
) -> None:
    network_client = get_network_client(platform)
    private_dns_zone_group_name = "default"
    private_endpoint_name = "pe_test"
    private_dns_zone_name = "privatelink"
    private_dns_zone_name = ".".join(
        [private_dns_zone_name, "file", platform.cloud.suffixes.storage_endpoint]
    )
    # network_client.private_dns_zone_groups.delete()
    network_client.private_dns_zone_groups.begin_create_or_update(
        resource_group_name=resource_group_name,
        private_dns_zone_group_name=private_dns_zone_group_name,
        private_endpoint_name=private_endpoint_name,
        parameters=PrivateDnsZoneGroup(
            name=private_dns_zone_group_name,
            private_dns_zone_configs=[
                PrivateDnsZoneConfig(
                    name=private_dns_zone_name,
                    private_dns_zone_id=private_dns_zone_id,
                )
            ],
        ),
    )
    log.debug(f"create private dns zone group: {private_dns_zone_group_name}")


def delete_private_dns_zone_groups(
    platform: "AzurePlatform",
    resource_group_name: str,
    log: Logger,
) -> None:
    network_client = get_network_client(platform)
    private_dns_zone_group_name = "default"
    private_endpoint_name = "pe_test"
    try:
        network_client.private_dns_zone_groups.get(
            resource_group_name=resource_group_name,
            private_endpoint_name=private_endpoint_name,
            private_dns_zone_group_name=private_dns_zone_group_name,
        )
        log.debug(f"found private dns zone group: {private_dns_zone_group_name}")
        network_client.private_dns_zone_groups.begin_delete(
            resource_group_name=resource_group_name,
            private_endpoint_name=private_endpoint_name,
            private_dns_zone_group_name=private_dns_zone_group_name,
        )
        log.debug(f"delete private dns zone group: {private_dns_zone_group_name}")
    except Exception:
        log.debug(f"not find private dns zone group: {private_dns_zone_group_name}")


def get_virtual_networks(
    platform: "AzurePlatform", resource_group_name: str
) -> Dict[str, List[str]]:
    network_client = get_network_client(platform)
    virtual_networks_list = network_client.virtual_networks.list(
        resource_group_name=resource_group_name
    )
    virtual_network_dict: Dict[str, List[str]] = {}
    for virtual_network in virtual_networks_list:
        virtual_network_dict[virtual_network.id] = [
            x.id for x in virtual_network.subnets
        ]
    return virtual_network_dict


def get_network_client(platform: "AzurePlatform") -> NetworkManagementClient:
    return NetworkManagementClient(
        credential=platform.credential,
        subscription_id=platform.subscription_id,
        base_url=platform.cloud.endpoints.resource_manager,
        credential_scopes=[platform.cloud.endpoints.resource_manager + "/.default"],
    )


def get_storage_client(
    credential: Any, subscription_id: str, cloud: Cloud
) -> StorageManagementClient:
    return StorageManagementClient(
        credential=credential,
        subscription_id=subscription_id,
        base_url=cloud.endpoints.resource_manager,
        credential_scopes=[cloud.endpoints.resource_manager + "/.default"],
    )


def get_resource_management_client(
    credential: Any, subscription_id: str, cloud: Cloud
) -> ResourceManagementClient:
    return ResourceManagementClient(
        credential=credential,
        subscription_id=subscription_id,
        base_url=cloud.endpoints.resource_manager,
        credential_scopes=[cloud.endpoints.resource_manager + "/.default"],
    )


def get_managed_service_identity_client(
    platform: "AzurePlatform",
    subscription_id: str = "",
) -> ManagedServiceIdentityClient:
    if not subscription_id:
        subscription_id = platform.subscription_id
    return ManagedServiceIdentityClient(
        credential=platform.credential,
        subscription_id=subscription_id,
        base_url=platform.cloud.endpoints.resource_manager,
        credential_scopes=[platform.cloud.endpoints.resource_manager + "/.default"],
    )


def get_storage_account_name(
    subscription_id: str, location: str, type_: str = "s"
) -> str:
    subscription_id_postfix = subscription_id[-8:]
    # name should be shorter than 24 character
    return f"lisa{type_}{location[:11]}{subscription_id_postfix}"


def get_marketplace_ordering_client(
    platform: "AzurePlatform",
) -> MarketplaceOrderingAgreements:
    return MarketplaceOrderingAgreements(
        credential=platform.credential,
        subscription_id=platform.subscription_id,
        base_url=platform.cloud.endpoints.resource_manager,
        credential_scopes=[platform.cloud.endpoints.resource_manager + "/.default"],
    )


def get_node_context(node: Node) -> NodeContext:
    return node.get_context(NodeContext)


def get_environment_context(environment: Environment) -> EnvironmentContext:
    return environment.get_context(EnvironmentContext)


def wait_operation(
    operation: Any, time_out: int = sys.maxsize, failure_identity: str = ""
) -> Any:
    timer = create_timer()
    wait_result: Any = None
    if failure_identity:
        failure_identity = f"{failure_identity} failed:"
    else:
        failure_identity = "Azure operation failed:"
    while time_out > timer.elapsed(False):
        check_cancelled()
        if operation.done():
            break
        wait_result = operation.wait(1)
        if wait_result:
            raise LisaException(f"{failure_identity} {wait_result}")
    if time_out < timer.elapsed():
        raise LisaTimeoutException(
            f"{failure_identity} timeout after {time_out} seconds."
        )
    result = operation.result()
    if result:
        result = result.as_dict()

    return result


def get_storage_credential(
    credential: Any,
    subscription_id: str,
    cloud: Cloud,
    account_name: str,
    resource_group_name: str,
) -> Any:
    """
    return a shared key credential. This credential doesn't need extra
     permissions to access blobs.
    """
    storage_client = get_storage_client(credential, subscription_id, cloud)
    key = storage_client.storage_accounts.list_keys(
        account_name=account_name, resource_group_name=resource_group_name
    ).keys[0]
    return {"account_name": account_name, "account_key": key.value}


def generate_user_delegation_sas_token(
    container_name: str,
    blob_name: str,
    cloud: Cloud = AZURE_PUBLIC_CLOUD,
    credential: Optional[Any] = None,
    account_name: Optional[str] = None,
    connection_string: Optional[str] = None,
    writable: bool = False,
    expired_hours: int = 1,
) -> Any:
    blob_service_client = get_blob_service_client(
        cloud=cloud,
        credential=credential,
        account_name=account_name,
        connection_string=connection_string,
    )
    start_time = datetime.now(timezone.utc)
    expiry_time = start_time + timedelta(hours=expired_hours)
    user_delegation_key = blob_service_client.get_user_delegation_key(
        start_time, expiry_time
    )
    assert account_name, "account_name is required"
    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=container_name,
        blob_name=blob_name,
        user_delegation_key=user_delegation_key,
        permission=BlobSasPermissions(read=True, write=writable),
        expiry=expiry_time,
        start=start_time,
    )
    return sas_token


def get_blob_service_client(
    cloud: Cloud = AZURE_PUBLIC_CLOUD,
    credential: Optional[Any] = None,
    account_name: Optional[str] = None,
    connection_string: Optional[str] = None,
) -> BlobServiceClient:
    """
    Create a Azure Storage container if it does not exist.
    """
    blob_service_client: BlobServiceClient
    if connection_string:
        blob_service_client = BlobServiceClient.from_connection_string(
            connection_string
        )
    else:
        assert (
            account_name
        ), "account_name is required, if connection_string is not set."

        blob_service_client = BlobServiceClient(
            f"https://{account_name}.blob.{cloud.suffixes.storage_endpoint}",
            credential,
        )
    return blob_service_client


def get_or_create_storage_container(
    container_name: str,
    cloud: Cloud = AZURE_PUBLIC_CLOUD,
    credential: Optional[Any] = None,
    account_name: Optional[str] = None,
    connection_string: Optional[str] = None,
    allow_create: bool = True,
) -> ContainerClient:
    """
    Create a Azure Storage container if it does not exist.
    """
    blob_service_client = get_blob_service_client(
        cloud=cloud,
        credential=credential,
        account_name=account_name,
        connection_string=connection_string,
    )
    container_client = blob_service_client.get_container_client(container_name)
    if not container_client.exists():
        if allow_create:
            container_client.create_container()
        else:
            raise LisaException(f"container {container_name} does not exist.")
    return container_client


def check_or_create_storage_account(
    credential: Any,
    subscription_id: str,
    cloud: Cloud,
    account_name: str,
    resource_group_name: str,
    location: str,
    log: Logger,
    sku: str = "Standard_LRS",
    kind: str = "StorageV2",
    enable_https_traffic_only: bool = True,
    allow_shared_key_access: bool = False,
    allow_blob_public_access: bool = False,
) -> None:
    # check and deploy storage account.
    # storage account can be deployed inside of arm template, but if the concurrent
    # is too big, Azure may not able to delete deployment script on time. so there
    # will be error like below
    # Creating the deployment 'name' would exceed the quota of '800'.
    storage_client = get_storage_client(credential, subscription_id, cloud)
    with _global_storage_account_check_create_lock:
        try:
            storage_client.storage_accounts.get_properties(
                account_name=account_name,
                resource_group_name=resource_group_name,
            )
            log.debug(f"found storage account: {account_name}")
        except Exception:
            log.debug(f"creating storage account: {account_name}")
            parameters = StorageAccountCreateParameters(
                sku=Sku(name=sku),
                kind=kind,
                location=location,
                enable_https_traffic_only=enable_https_traffic_only,
                allow_shared_key_access=allow_shared_key_access,
                allow_blob_public_access=allow_blob_public_access,
            )
            operation = storage_client.storage_accounts.begin_create(
                resource_group_name=resource_group_name,
                account_name=account_name,
                parameters=parameters,
            )
            wait_operation(operation)


def delete_storage_account(
    credential: Any,
    subscription_id: str,
    cloud: Cloud,
    account_name: str,
    resource_group_name: str,
    log: Logger,
) -> None:
    storage_client = get_storage_client(credential, subscription_id, cloud)
    try:
        storage_client.storage_accounts.get_properties(
            account_name=account_name,
            resource_group_name=resource_group_name,
        )
        log.debug(f"found storage account: {account_name}")
        storage_client.storage_accounts.delete(
            account_name=account_name,
            resource_group_name=resource_group_name,
        )
        log.debug(f"delete storage account: {account_name}")
    except Exception:
        log.debug(f"not find storage account: {account_name}")


def check_or_create_resource_group(
    credential: Any,
    subscription_id: str,
    cloud: Cloud,
    resource_group_name: str,
    location: str,
    log: Logger,
    managed_by: str = "",
) -> None:
    with get_resource_management_client(
        credential, subscription_id, cloud
    ) as rm_client:
        with global_credential_access_lock:
            az_shared_rg_exists = rm_client.resource_groups.check_existence(
                resource_group_name
            )
        if not az_shared_rg_exists:
            log.info(f"Creating Resource group: '{resource_group_name}'")

            rg_properties = {"location": location}
            if managed_by:
                log.debug(f"Using managed_by resource group: '{managed_by}'")
                rg_properties["managed_by"] = managed_by

            with global_credential_access_lock:
                rm_client.resource_groups.create_or_update(
                    resource_group_name,
                    rg_properties,
                )
            check_till_timeout(
                lambda: rm_client.resource_groups.check_existence(resource_group_name)
                is True,
                timeout_message=f"wait for {resource_group_name} created",
            )


def copy_vhd_to_storage(
    platform: "AzurePlatform",
    storage_name: str,
    src_vhd_sas_url: str,
    dst_vhd_name: str,
    log: Logger,
) -> str:
    # get original vhd's hash key for comparing.
    original_key: Optional[bytearray] = None
    original_blob_client: BlobClient = BlobClient.from_blob_url(src_vhd_sas_url)
    properties = original_blob_client.get_blob_properties()
    content_settings: Optional[ContentSettings] = properties.content_settings
    if content_settings:
        original_key = content_settings.get("content_md5", None)  # type: ignore

    container_client = get_or_create_storage_container(
        credential=platform.credential,
        cloud=platform.cloud,
        account_name=storage_name,
        container_name=SAS_COPIED_CONTAINER_NAME,
    )
    full_vhd_path = f"{container_client.url}/{dst_vhd_name}"

    # lock here to prevent a vhd is copied in multi-thread
    cached_key: Optional[bytearray] = None
    with _global_sas_vhd_copy_lock:
        blobs = container_client.list_blobs(name_starts_with=dst_vhd_name)
        blob_client = container_client.get_blob_client(dst_vhd_name)
        vhd_exists = False
        for blob in blobs:
            if blob:
                # check if hash key matched with original key.
                if blob.content_settings:
                    cached_key = blob.content_settings.get(
                        "content_md5", None
                    )  # type: ignore
                if is_stuck_copying(blob_client, log):
                    # Delete the stuck vhd.
                    blob_client.delete_blob(delete_snapshots="include")
                elif original_key and cached_key:
                    if original_key == cached_key:
                        log.debug("the sas url is copied already, use it directly.")
                        vhd_exists = True
                    else:
                        log.debug("found cached vhd, but the hash key mismatched.")
                else:
                    log.debug(
                        "No md5 content either in original blob or current blob. "
                        "Then no need to check the hash key"
                    )
                    vhd_exists = True

        if not vhd_exists:
            azcopy_path = platform._azure_runbook.azcopy_path
            if azcopy_path:
                log.info(f"AzCopy path: {azcopy_path}")
                if not os.path.exists(azcopy_path):
                    raise LisaException(f"{azcopy_path} does not exist")

                sas_token = generate_user_delegation_sas_token(
                    container_name=blob_client.container_name,
                    blob_name=blob_client.blob_name,
                    credential=platform.credential,
                    cloud=platform.cloud,
                    account_name=storage_name,
                    writable=True,
                )
                dst_vhd_sas_url = f"{full_vhd_path}?{sas_token}"
                log.info(f"copying vhd by azcopy {dst_vhd_name}")
                try:
                    local().execute(
                        f"{azcopy_path} copy {src_vhd_sas_url} {dst_vhd_sas_url} --recursive=true",  # noqa: E501
                        expected_exit_code=0,
                        expected_exit_code_failure_message=(
                            "Azcopy failed to copy the blob"
                        ),
                        timeout=60 * 60,
                    )
                except Exception as identifier:
                    blob_client.delete_blob(delete_snapshots="include")
                    raise LisaException(f"{identifier}")

                # Set metadata to mark the blob copied by AzCopy successfully
                metadata = {"AzCopyStatus": "Success"}
                blob_client.set_blob_metadata(metadata)
            else:
                blob_client.start_copy_from_url(
                    src_vhd_sas_url, metadata=None, incremental_copy=False
                )

        wait_copy_blob(blob_client, dst_vhd_name, log)

    return full_vhd_path


def wait_copy_blob(
    blob_client: Any,
    vhd_path: str,
    log: Logger,
    timeout: int = 60 * 60,
) -> None:
    log.info(f"copying vhd: {vhd_path}")
    if blob_client.get_blob_properties().copy.status:
        check_till_timeout(
            lambda: blob_client.get_blob_properties().copy.status == "success",
            timeout_message=f"copying VHD: {vhd_path}",
            timeout=timeout,
            interval=2,
        )
    else:
        # If the blob is copied by AzCopy, the copy.status is None.
        # Confirm the copy operation is success by checking the metadata.
        check_till_timeout(
            lambda: blob_client.get_blob_properties().metadata.get("AzCopyStatus", None)
            == "Success",
            timeout_message=f"copying VHD: {vhd_path}",
            timeout=timeout,
            interval=2,
        )
    log.info("vhd copied")


def get_share_service_client(
    credential: Any,
    subscription_id: str,
    cloud: Cloud,
    account_name: str,
    resource_group_name: str,
) -> ShareServiceClient:
    shared_key_credential = get_storage_credential(
        credential=credential,
        subscription_id=subscription_id,
        cloud=cloud,
        account_name=account_name,
        resource_group_name=resource_group_name,
    )
    share_service_client = ShareServiceClient(
        f"https://{account_name}.file.{cloud.suffixes.storage_endpoint}",
        shared_key_credential,
    )
    return share_service_client


def get_or_create_file_share(
    credential: Any,
    subscription_id: str,
    cloud: Cloud,
    account_name: str,
    file_share_name: str,
    resource_group_name: str,
    log: Logger,
    protocols: str = "SMB",
) -> str:
    """
    Create a Azure Storage file share if it does not exist.
    """
    share_service_client = get_share_service_client(
        credential,
        subscription_id,
        cloud,
        account_name,
        resource_group_name,
    )
    all_shares = list(share_service_client.list_shares())
    if file_share_name not in (x.name for x in all_shares):
        log.debug(f"creating file share {file_share_name} with protocols {protocols}")
        share_service_client.create_share(file_share_name, protocols=protocols)
    return str("//" + share_service_client.primary_hostname + "/" + file_share_name)


def delete_file_share(
    credential: Any,
    subscription_id: str,
    cloud: Cloud,
    account_name: str,
    file_share_name: str,
    resource_group_name: str,
    log: Logger,
) -> None:
    """
    Delete Azure Storage file share
    """
    share_service_client = get_share_service_client(
        credential,
        subscription_id,
        cloud,
        account_name,
        resource_group_name,
    )
    log.debug(f"deleting file share {file_share_name}")
    share_service_client.delete_share(file_share_name)


def save_console_log(
    resource_group_name: str,
    vm_name: str,
    platform: "AzurePlatform",
    log: Logger,
    saved_path: Optional[Path],
    screenshot_file_name: str = "serial_console",
) -> bytes:
    compute_client = get_compute_client(platform)
    with global_credential_access_lock:
        try:
            diagnostic_data = (
                compute_client.virtual_machines.retrieve_boot_diagnostics_data(
                    resource_group_name=resource_group_name, vm_name=vm_name
                )
            )
        except ResourceExistsError as identifier:
            log.debug(f"fail to get serial console log. {identifier}")
            return b""
    if saved_path:
        screenshot_raw_name = saved_path / f"{screenshot_file_name}.bmp"
        screenshot_response = requests.get(
            diagnostic_data.console_screenshot_blob_uri, timeout=60
        )
        screenshot_raw_name.write_bytes(screenshot_response.content)
        try:
            with Image.open(screenshot_raw_name) as image:
                image.save(
                    saved_path / f"{screenshot_file_name}.png", "PNG", optimize=True
                )
        except UnidentifiedImageError:
            log.debug(
                "The screenshot is not generated. "
                "The reason may be the VM is not started."
            )
        screenshot_raw_name.unlink()

    try:
        log_response = requests.get(
            diagnostic_data.serial_console_log_blob_uri, timeout=60
        )
        if log_response.status_code == 404:
            log.debug(
                "The serial console is not generated. "
                "The reason may be the VM is not started."
            )
    except ChunkedEncodingError as ex:
        log.debug(f"ChunkedEncodingError occurred: {ex}")
        return b""
    except Exception as ex:
        log.debug(f"Failed to save console log: {ex}")
        return b""

    return log_response.content


def load_environment(
    platform: "AzurePlatform",
    resource_group_name: str,
    use_public_address: bool,
    log: Logger,
) -> Environment:
    """
    reverse load environment from a resource group.
    """

    # create mock environment from environments
    environment_runbook = schema.Environment()
    if environment_runbook.nodes_raw is None:
        environment_runbook.nodes_raw = []

    vms_map: Dict[str, VirtualMachine] = {}
    compute_client = get_compute_client(platform)
    vms = compute_client.virtual_machines.list(resource_group_name)
    for vm in vms:
        node_schema = schema.RemoteNode(name=vm.name)
        environment_runbook.nodes_raw.append(node_schema)
        vms_map[vm.name] = vm

    environments = load_environments(
        schema.EnvironmentRoot(environments=[environment_runbook])
    )
    environment = next(x for x in environments.values())

    platform_runbook: schema.Platform = platform.runbook

    for node in environment.nodes.list():
        assert isinstance(node, RemoteNode)

        vm = vms_map.get(node.name)
        assert_that(vm).described_as(
            f"Cannot find vm with name {node.name}. Make sure the VM exists in "
            f"resource group {resource_group_name}"
        ).is_not_none()

        node_context = get_node_context(node)
        node_context.vm_name = node.name
        node_context.resource_group_name = resource_group_name

        node_context.username = platform_runbook.admin_username
        node_context.password = platform_runbook.admin_password
        node_context.private_key_file = platform_runbook.admin_private_key_file
        node_context.location = vm.location
        node_context.subscription_id = platform.subscription_id

        (
            node_context.public_ip_address,
            node_context.private_ip_address,
        ) = get_primary_ip_addresses(
            platform, resource_group_name, vms_map[node_context.vm_name]
        )
        node_context.use_public_address = use_public_address
        node.set_connection_info(
            address=node_context.private_ip_address,
            use_public_address=node_context.use_public_address,
            public_address=node_context.public_ip_address,
            username=node_context.username,
            password=node_context.password,
            private_key_file=node_context.private_key_file,
        )

        node.features = Features(node, platform)

    environment_context = get_environment_context(environment)
    environment_context.resource_group_is_specified = False
    environment_context.resource_group_name = resource_group_name

    platform.initialize_environment(environment, log)

    return environment


def get_vm(platform: "AzurePlatform", node: Node) -> Any:
    context = node.get_context(NodeContext)
    compute_client = get_compute_client(platform=platform)
    vm = compute_client.virtual_machines.get(
        context.resource_group_name, context.vm_name
    )

    return vm


@retry(exceptions=LisaException, tries=150, delay=2)
def get_primary_ip_addresses(
    platform: "AzurePlatform", resource_group_name: str, vm: VirtualMachine
) -> Tuple[str, str]:
    network_client = get_network_client(platform)

    assert vm.network_profile, "no network profile found"
    assert isinstance(
        vm.network_profile.network_interfaces, List
    ), f"actual: {type(vm.network_profile.network_interfaces)}"
    for network_interface in vm.network_profile.network_interfaces:
        assert isinstance(
            network_interface.id, str
        ), f"actual: {type(network_interface.id)}"
        nic_name = get_matched_str(network_interface.id, NIC_NAME_PATTERN)
        nic = network_client.network_interfaces.get(resource_group_name, nic_name)
        if nic.primary:
            if not nic.ip_configurations[0].public_ip_address:
                raise LisaException(f"no public address found in nic {nic.name}")
            public_ip_name = get_matched_str(
                nic.ip_configurations[0].public_ip_address.id, PATTERN_PUBLIC_IP_NAME
            )
            public_ip_address = network_client.public_ip_addresses.get(
                resource_group_name,
                public_ip_name,
            )
            return (
                public_ip_address.ip_address,
                nic.ip_configurations[0].private_ip_address,
            )
    raise LisaException(f"fail to find primary nic for vm {vm.name}")


# find resource based on type name from resources section in arm template
def find_by_name(resources: Any, type_name: str) -> Any:
    return next(x for x in resources if x["type"] == type_name)


def get_vhd_details(platform: "AzurePlatform", vhd_path: str) -> Any:
    matched = STORAGE_CONTAINER_BLOB_PATTERN.match(vhd_path)
    assert matched, f"fail to get matched info from {vhd_path}"
    sc_name = matched.group("sc")
    container_name = matched.group("container")
    blob_name = matched.group("blob")
    subscription_id = platform.subscription_id
    found_sc = find_storage_account(platform, sc_name, subscription_id)
    if not found_sc:
        subscription_client = SubscriptionClient(platform.credential)
        for subscription in subscription_client.subscriptions.list():
            found_sc = find_storage_account(
                platform, sc_name, subscription.subscription_id
            )
            if found_sc:
                subscription_id = subscription.subscription_id
                break
    assert found_sc, f"storage account {sc_name} not found in any subscriptions allowed"

    rg = get_matched_str(found_sc.id, RESOURCE_GROUP_PATTERN)
    return {
        "location": found_sc.location,
        "resource_group_name": rg,
        "account_name": sc_name,
        "container_name": container_name,
        "blob_name": blob_name,
        "subscription": subscription_id,
    }


def find_storage_account(
    platform: "AzurePlatform", sc_name: str, subscription_id: str
) -> Any:
    storage_client = get_storage_client(
        platform.credential, subscription_id, platform.cloud
    )
    # sometimes it will fail for below reason if list storage accounts like this way
    # [x for x in storage_client.storage_accounts.list() if x.name == sc_name]
    # failure - Message: Resource provider 'Microsoft.Storage' failed to return collection response for type 'storageAccounts'.  # noqa: E501
    sc_list = storage_client.storage_accounts.list()
    found_sc = None
    for sc in sc_list:
        if sc.name.lower() == sc_name.lower():
            found_sc = sc
            break
    return found_sc


def get_token(platform: "AzurePlatform") -> str:
    token = platform.credential.get_token(platform.cloud.endpoints.resource_manager)
    return token.token


def _generate_sas_token_for_vhd(
    platform: "AzurePlatform", result_dict: Dict[str, str]
) -> Any:
    sc_name = result_dict["account_name"]
    container_name = result_dict["container_name"]
    blob_name = result_dict["blob_name"]

    source_container_client = get_or_create_storage_container(
        credential=platform.credential,
        cloud=platform.cloud,
        account_name=sc_name,
        container_name=container_name,
    )
    source_blob = source_container_client.get_blob_client(blob_name)
    sas_token = generate_user_delegation_sas_token(
        container_name=source_blob.container_name,
        blob_name=source_blob.blob_name,
        credential=platform.credential,
        cloud=platform.cloud,
        account_name=sc_name,
    )
    source_url = source_blob.url + "?" + sas_token
    return source_url


@lru_cache(maxsize=10)  # noqa: B019
def get_deployable_vhd_path(
    platform: "AzurePlatform", vhd_path: str, location: str, log: Logger
) -> str:
    """
    The sas url is not able to create a vm directly, so this method check if
    the vhd_path is a sas url. If so, copy it to a location in current
    subscription, so it can be deployed.
    """
    matches = SAS_URL_PATTERN.match(vhd_path)
    if not matches:
        vhd_details = get_vhd_details(platform, vhd_path)
        vhd_location = vhd_details["location"]
        if (
            location == vhd_location
            and vhd_details["subscription"] == platform.subscription_id
        ):
            return vhd_path
        else:
            vhd_path = _generate_sas_token_for_vhd(platform, vhd_details)
            matches = SAS_URL_PATTERN.match(vhd_path)
            assert matches, f"fail to generate sas url for {vhd_path}"
            log.debug(
                f"the vhd location {location} is not same with running case "
                f"location {vhd_location}, generate a sas url for source vhd, "
                f"it needs to be copied into location {location}."
            )
    else:
        log.debug("found the vhd is a sas url, it may need to be copied.")

    original_vhd_path = vhd_path

    storage_name = get_storage_account_name(
        subscription_id=platform.subscription_id, location=location, type_="t"
    )

    check_or_create_storage_account(
        platform.credential,
        platform.subscription_id,
        platform.cloud,
        storage_name,
        platform._azure_runbook.shared_resource_group_name,
        location,
        log,
    )

    normalized_vhd_name = constants.NORMALIZE_PATTERN.sub("-", vhd_path)
    year = matches["year"] if matches["year"] else "9999"
    month = matches["month"] if matches["month"] else "01"
    day = matches["day"] if matches["day"] else "01"
    # use the expire date to generate the path. It's easy to identify when
    # the cache can be removed.
    vhd_path = f"{year}{month}{day}/{normalized_vhd_name}.vhd"
    full_vhd_path = copy_vhd_to_storage(
        platform, storage_name, original_vhd_path, vhd_path, log
    )
    log.debug(
        f"deployable vhd is cached at: {full_vhd_path}. "
        f"original vhd url: {original_vhd_path}"
    )

    # Add substitutes for these normalized vhd names. Replace them with the original
    # vhd name without SAS when printing
    # e.g.
    # full_vhd_path: https://lisatwestus3xx.blob.core.windows.net/lisa-sas-copied/99990101/https---userstorageaccount-blob-core-windows-net-vhds-fortinet-blob-6-7-4-vhd-sv-2019-xx.vhd  # noqa: E501
    # replace it with: https://userstorageaccount.blob.core.windows.net/vhds/fortinet/blob-6.7.4.vhd?***  # noqa: E501
    # vhd_path: 99990101/https---userstorageaccount-blob-core-windows-net-vhds-fortinet-blob-6-7-4-vhd-sv-2019-xx.vhd  # noqa: E501
    # replace it with: fortinet/blob-6.7.4.vhd
    original_vhd_path_without_sas = replace(original_vhd_path, mask=PATTERN_URL)
    add_secret(
        vhd_path,
        sub="/".join(original_vhd_path_without_sas.split("/")[4:]).rstrip("?*"),
    )
    add_secret(full_vhd_path, sub=original_vhd_path_without_sas)
    # In the returned message from Azure when creating VM, the blob url might contain
    # the default blob port 8443, so also add substitute for the vhd path with 8443 port
    full_vhd_path_with_port = "/".join(
        x + ":8443" if i == 2 else x for i, x in enumerate(full_vhd_path.split("/"))
    )
    add_secret(full_vhd_path_with_port, sub=original_vhd_path_without_sas)

    return full_vhd_path


def is_stuck_copying(blob_client: BlobClient, log: Logger) -> bool:
    props = blob_client.get_blob_properties()
    copy_status = props.copy.status
    if copy_status == "pending":
        if props.creation_time:
            delta_hours = (datetime.now(timezone.utc) - props.creation_time).seconds / (
                60 * 60
            )
        else:
            delta_hours = 0

        if delta_hours > BLOB_COPY_PENDING_TIMEOUT_HOURS:
            log.debug(
                "the blob is pending more than "
                f"{BLOB_COPY_PENDING_TIMEOUT_HOURS} hours."
            )
            return True
    return False


def check_or_create_gallery(
    platform: "AzurePlatform",
    gallery_resource_group_name: str,
    gallery_name: str,
    gallery_location: str = "",
    gallery_description: str = "",
) -> Any:
    try:
        # get gallery
        compute_client = get_compute_client(platform)
        gallery = compute_client.galleries.get(
            resource_group_name=gallery_resource_group_name,
            gallery_name=gallery_name,
        )
    except Exception as ex:
        # create the gallery if specified gallery name doesn't exist
        if "ResourceNotFound" in str(ex):
            gallery_post_body = {
                "location": gallery_location,
                "description": gallery_description,
            }
            operation = compute_client.galleries.begin_create_or_update(
                gallery_resource_group_name,
                gallery_name,
                gallery_post_body,
            )
            gallery = wait_operation(operation)
        else:
            raise LisaException(ex)
    return gallery


def check_or_create_gallery_image(
    platform: "AzurePlatform",
    gallery_resource_group_name: str,
    gallery_name: str,
    gallery_image_name: str,
    gallery_image_location: str,
    gallery_image_publisher: str,
    gallery_image_offer: str,
    gallery_image_sku: str,
    gallery_image_ostype: str,
    gallery_image_osstate: str,
    gallery_image_hyperv_generation: int,
    gallery_image_architecture: str,
    gallery_image_securitytype: str,
) -> None:
    try:
        compute_client = get_compute_client(platform)
        compute_client.gallery_images.get(
            gallery_resource_group_name,
            gallery_name,
            gallery_image_name,
        )
    except Exception as ex:
        # create the gallery image if specified gallery name doesn't exist
        if "ResourceNotFound" in str(ex):
            image_post_body: Dict[str, Any] = {}
            image_post_body = {
                "location": gallery_image_location,
                "os_type": gallery_image_ostype,
                "os_state": gallery_image_osstate,
                "hyper_v_generation": f"V{gallery_image_hyperv_generation}",
                "architecture": gallery_image_architecture,
                "identifier": {
                    "publisher": gallery_image_publisher,
                    "offer": gallery_image_offer,
                    "sku": gallery_image_sku,
                },
                "features": [
                    {
                        "name": "DiskControllerTypes",
                        "value": "SCSI,NVMe",
                    },
                ],
            }

            if gallery_image_securitytype:
                image_post_body["features"] = [
                    {
                        "name": "SecurityType",
                        "value": gallery_image_securitytype,
                    }
                ]
            operation = compute_client.gallery_images.begin_create_or_update(
                gallery_resource_group_name,
                gallery_name,
                gallery_image_name,
                image_post_body,
            )
            wait_operation(operation)
        else:
            raise LisaException(ex)


def check_or_create_gallery_image_version(
    platform: "AzurePlatform",
    gallery_resource_group_name: str,
    gallery_name: str,
    gallery_image_name: str,
    gallery_image_version: str,
    gallery_image_location: str,
    regional_replica_count: int,
    storage_account_type: str,
    host_caching_type: str,
    vhd_path: str,
    vhd_resource_group_name: str,
    vhd_storage_account_name: str,
    gallery_image_target_regions: List[str],
) -> None:
    try:
        compute_client = get_compute_client(platform)
        compute_client.gallery_image_versions.get(
            gallery_resource_group_name,
            gallery_name,
            gallery_image_name,
            gallery_image_version,
        )
    except Exception as ex:
        # create the gallery if specified gallery name doesn't exist
        if "ResourceNotFound" in str(ex):
            target_regions: List[Dict[str, str]] = []
            for target_region in gallery_image_target_regions:
                target_regions.append(
                    {
                        "name": target_region,
                        "regional_replica_count": str(regional_replica_count),
                        "storage_account_type": storage_account_type,
                    }
                )
            image_version_post_body = {
                "location": gallery_image_location,
                "publishing_profile": {"target_regions": target_regions},
                "storageProfile": {
                    "osDiskImage": {
                        "hostCaching": host_caching_type,
                        "source": {
                            "uri": vhd_path,
                            "id": (
                                f"/subscriptions/{platform.subscription_id}/"
                                f"resourceGroups/{vhd_resource_group_name}"
                                "/providers/Microsoft.Storage/storageAccounts/"
                                f"{vhd_storage_account_name}"
                            ),
                        },
                    },
                },
            }
            operation = compute_client.gallery_image_versions.begin_create_or_update(
                gallery_resource_group_name,
                gallery_name,
                gallery_image_name,
                gallery_image_version,
                image_version_post_body,
            )
            wait_operation(operation)
        else:
            raise LisaException(ex)


def check_blob_exist(
    platform: "AzurePlatform",
    account_name: str,
    container_name: str,
    resource_group_name: str,
    blob_name: str,
    raise_error: bool = True,
) -> None:
    container_client = get_or_create_storage_container(
        credential=platform.credential,
        cloud=platform.cloud,
        account_name=account_name,
        container_name=container_name,
        allow_create=False,
    )
    blob_client = container_client.get_blob_client(blob_name)
    blob_exist = blob_client.exists()
    if raise_error and not blob_exist:
        raise LisaException(f"Blob {blob_name} does not exist.")


def download_blob(
    account_name: str,
    container_name: str,
    blob_name: str,
    file_path: Path,
    log: Logger,
    cloud: Cloud = AZURE_PUBLIC_CLOUD,
    credential: Optional[Any] = None,
    subscription_id: Optional[str] = None,
    resource_group_name: Optional[str] = None,
    connection_string: Optional[str] = None,
) -> PurePath:
    container_client = get_or_create_storage_container(
        container_name=container_name,
        credential=credential,
        cloud=cloud,
        account_name=account_name,
        connection_string=connection_string,
        allow_create=False,
    )
    blob_client = container_client.get_blob_client(blob_name)
    if not blob_client.exists():
        raise LisaException(f"Blob {blob_name} not found in container {container_name}")
    try:
        with _global_download_blob_lock:
            blob_properties = blob_client.get_blob_properties()
            if file_path.exists():
                blob_hash = blob_properties.content_settings.content_md5
                if blob_hash:
                    blob_hash_hex = "".join(f"{byte:02x}" for byte in blob_hash)
                    if _calculate_hash(file_path) == blob_hash_hex:
                        log.debug(
                            f"Blob {blob_name} already exists in {file_path}. "
                            "No need to download again."
                        )
                        return file_path

            blob_size = blob_properties["size"]
            downloaded_size = 0
            start_time = time()
            log_interval = 10
            next_log_time = start_time + log_interval
            with open(file_path, "wb") as file:
                download_stream = blob_client.download_blob()
                for chunk in download_stream.chunks():
                    file.write(chunk)
                    downloaded_size += len(chunk)
                    percentage = (downloaded_size / blob_size) * 100
                    current_time = time()
                    if current_time >= next_log_time:
                        log.debug(
                            f"Downloaded {downloaded_size}/{blob_size} bytes "
                            f"({percentage:.2f}% complete)"
                        )
                        next_log_time = current_time + log_interval

            log.debug("Blob downloaded successfully.")
    except Exception as e:
        raise LisaException("An error occurred during blob download.") from e
    return file_path


def _calculate_hash(file_path: Path) -> str:
    hash_func = hashlib.md5()
    with open(file_path, "rb") as file:
        for chunk in iter(lambda: file.read(4096), b""):
            hash_func.update(chunk)
    return hash_func.hexdigest()


def list_blobs(
    account_name: str,
    container_name: str,
    cloud: Cloud = AZURE_PUBLIC_CLOUD,
    credential: Optional[Any] = None,
    subscription_id: Optional[str] = None,
    resource_group_name: Optional[str] = None,
    connection_string: Optional[str] = None,
    include: str = "",
    name_starts_with: str = "",
) -> List[Any]:
    container_client = get_or_create_storage_container(
        container_name=container_name,
        credential=credential,
        cloud=cloud,
        account_name=account_name,
        connection_string=connection_string,
        allow_create=False,
    )
    if name_starts_with:
        return list(container_client.list_blobs(name_starts_with=name_starts_with))
    if include:
        return list(container_client.list_blobs(include=include))
    return list(container_client.list_blobs())


class DataDisk:
    # refer https://docs.microsoft.com/en-us/azure/virtual-machines/disks-types
    IOPS_SIZE_DICT: Dict[schema.DiskType, Dict[int, int]] = {
        schema.DiskType.PremiumSSDLRS: {
            120: 4,
            240: 64,
            500: 128,
            1100: 256,
            2300: 512,
            5000: 1024,
            7500: 2048,
            16000: 8192,
            18000: 16384,
            20000: 32767,
        },
        schema.DiskType.StandardHDDLRS: {
            500: 32,
            1300: 8192,
            2000: 16384,
        },
        schema.DiskType.StandardSSDLRS: {
            500: 4,
            2000: 8192,
            4000: 16384,
            6000: 32767,
        },
    }

    @staticmethod
    def get_size(disk_type: schema.DiskType, data_disk_iops: int = 1) -> int:
        if disk_type in [
            schema.DiskType.PremiumSSDLRS,
            schema.DiskType.StandardHDDLRS,
            schema.DiskType.StandardSSDLRS,
        ]:
            iops_dict = DataDisk.IOPS_SIZE_DICT[disk_type]
            iops = [key for key in iops_dict.keys() if key >= data_disk_iops]
            if not iops:
                raise LisaException(
                    f"IOPS {data_disk_iops} is invalid for disk type {disk_type}."
                )
            min_iops = min(iops)
            return iops_dict[min_iops]
        else:
            raise LisaException(f"Data disk type {disk_type} is unsupported.")


def get_certificate_client(
    vault_url: str, platform: "AzurePlatform"
) -> CertificateClient:
    return CertificateClient(vault_url, platform.credential)


def get_secret_client(vault_url: str, platform: "AzurePlatform") -> SecretClient:
    return SecretClient(vault_url, platform.credential)


def get_key_vault_management_client(
    platform: "AzurePlatform",
) -> KeyVaultManagementClient:
    return KeyVaultManagementClient(platform.credential, platform.subscription_id)


def get_tenant_id(credential: Any) -> Any:
    # Initialize the Subscription client
    subscription_client = SubscriptionClient(credential)
    # Get the subscription
    subscription = next(subscription_client.subscriptions.list())
    return subscription.tenant_id


def get_azurevm_metadata() -> Any:
    headers = {"Metadata": "true"}
    try:
        response = requests.get(METADATA_ENDPOINT, headers=headers, timeout=10)
        response.raise_for_status()
        metadata = response.json()
        return metadata
    except Exception:
        return ""


def get_azurevm_name() -> str:
    meta_data = get_azurevm_metadata()
    if meta_data:
        return str(meta_data["compute"]["name"])
    else:
        return ""


def get_resource_group_name() -> str:
    meta_data = get_azurevm_metadata()
    if meta_data:
        return str(meta_data["compute"]["resourceGroupName"])
    else:
        return ""


def get_managed_identity_object_id(
    platform: "AzurePlatform", resource_group_name: str, vm_name: str
) -> str:
    compute_client = get_compute_client(
        platform, subscription_id=platform.subscription_id
    )

    vm_identity = compute_client.virtual_machines.get(
        resource_group_name, vm_name
    ).identity

    user_assigned_identity_resource_id = ""
    # Check if the VM has user-assigned managed identity
    if vm_identity and vm_identity.type == "UserAssigned":
        user_assigned_identity_id = vm_identity.user_assigned_identities
        if user_assigned_identity_id:
            # Iterate over user-assigned identities
            for _, identity_value in user_assigned_identity_id.items():
                user_assigned_identity_resource_id = identity_value.principal_id
            if user_assigned_identity_resource_id:
                return user_assigned_identity_resource_id

    # Check if the VM has system-assigned managed identity
    if vm_identity and vm_identity.type == "SystemAssigned":
        return str(vm_identity.principal_id)
    return ""


def get_identity_id(
    platform: "AzurePlatform", application_id: Optional[str] = None
) -> Any:
    if not application_id:
        application_id = os.environ.get("AZURE_CLIENT_ID", "")

    if not application_id:
        # if the run machine resides on Azure
        # get the object ID of the managed identity
        if get_resource_group_name() and get_azurevm_name():
            object_id = get_managed_identity_object_id(
                platform, get_resource_group_name(), get_azurevm_name()
            )
            if object_id:
                return object_id

    base_url = "https://graph.microsoft.com/"
    api_version = "v1.0"
    # If application_id is not provided or is None, use /me endpoint
    if application_id:
        endpoint = f"servicePrincipals(appId='{application_id}')"
    else:
        endpoint = "me"
    graph_api_url = f"{base_url}{api_version}/{endpoint}"
    token = platform.credential.get_token("https://graph.microsoft.com/.default").token
    # Set up the API call headers
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Set a timeout of 10 seconds for the request
    response = requests.get(graph_api_url, headers=headers, timeout=10)

    if response.status_code != 200:
        raise LisaException(
            f"Failed to retrieve user object ID. "
            f"Status code: {response.status_code}. "
            f"Response: {response.text}"
        )
    return response.json().get("id")


def add_system_assign_identity(
    platform: "AzurePlatform",
    resource_group_name: str,
    vm_name: str,
    location: str,
    log: Logger,
) -> Any:
    compute_client = get_compute_client(platform)
    params_identity = {"type": "SystemAssigned"}
    params_create = {"location": location, "identity": params_identity}

    vm_poller = compute_client.virtual_machines.begin_update(
        resource_group_name,
        vm_name,
        params_create,
    )
    vm_result = vm_poller.result()
    object_id_vm = vm_result.identity.principal_id
    log.debug(f"VM object ID assigned: {object_id_vm}")

    if not object_id_vm:
        raise ValueError(
            "Cannot retrieve managed identity after set system assigned identity on vm"
        )

    return object_id_vm


def add_user_assign_identity(
    platform: "AzurePlatform",
    resource_group_name: str,
    vm_name: str,
    identify_id: str,
    log: Logger,
) -> None:
    compute_client = get_compute_client(platform)
    identity: Dict[str, Any] = {identify_id: {}}
    params_identity = {"type": "UserAssigned", "userAssignedIdentities": identity}
    params_create = {"identity": params_identity}

    operation = compute_client.virtual_machines.begin_update(
        resource_group_name,
        vm_name,
        params_create,
    )
    wait_operation(operation)
    log.debug(f"{identify_id} is assigned to vm {vm_name} successfully")


def add_tag_for_vm(
    platform: "AzurePlatform",
    resource_group_name: str,
    vm_name: str,
    tag: Dict[str, str],
    log: Logger,
) -> None:
    compute_client = get_compute_client(platform)
    vm = compute_client.virtual_machines.get(resource_group_name, vm_name)
    vm.tags.update(tag)
    params = {"tags": vm.tags}

    operation = compute_client.virtual_machines.begin_update(
        resource_group_name,
        vm_name,
        params,
    )
    wait_operation(operation)
    log.debug(f"tag: {tag} has been added in {vm_name} successfully")


def get_matching_key_vault_name(
    platform: "AzurePlatform",
    location: str,
    resource_group: str,
    pattern: str = ".*",
) -> Any:
    """
    Get the name of a Key Vault that exists in a specific region and resource group
    and matches the given pattern.
    """
    key_vault_client = get_key_vault_management_client(platform)
    key_vaults = key_vault_client.vaults.list_by_resource_group(resource_group)

    for vault in key_vaults:
        if vault.location == location:
            if re.fullmatch(pattern, vault.name):
                return vault.name
    return None


def create_keyvault(
    platform: "AzurePlatform",
    location: str,
    vault_name: str,
    resource_group_name: str,
    vault_properties: VaultProperties,
) -> Any:
    keyvault_client = get_key_vault_management_client(platform)

    parameters = VaultCreateOrUpdateParameters(
        location=location, properties=vault_properties
    )
    keyvault_poller = keyvault_client.vaults.begin_create_or_update(
        resource_group_name, vault_name, parameters
    )

    return keyvault_poller.result()


def assign_access_policy(
    platform: "AzurePlatform",
    resource_group_name: str,
    tenant_id: str,
    object_id: str,
    vault_name: str,
) -> Any:
    keyvault_client = get_key_vault_management_client(platform)

    permissions = Permissions(keys=["all"], secrets=["all"], certificates=["all"])
    # Fetch the current policies and add the new policy
    vault = keyvault_client.vaults.get(resource_group_name, vault_name)
    current_policies = vault.properties.access_policies
    new_policy = AccessPolicyEntry(
        tenant_id=tenant_id,
        object_id=object_id,
        permissions=permissions,
    )
    current_policies.append(new_policy)

    # Update the vault with the new policies
    vault.properties.access_policies = current_policies
    keyvault_poller = keyvault_client.vaults.begin_create_or_update(
        resource_group_name, vault_name, vault
    )

    return keyvault_poller.result()


@retry(tries=5, delay=1)
def create_certificate(
    platform: "AzurePlatform",
    vault_url: str,
    cert_name: str,
    log: Logger,
) -> str:
    certificate_client = get_certificate_client(vault_url, platform)
    secret_client = get_secret_client(vault_url, platform)

    cert_policy = CertificatePolicy.get_default()

    # Create certificate
    create_certificate_result = certificate_client.begin_create_certificate(
        cert_name, policy=cert_policy
    )
    log.debug(
        f"Certificate '{cert_name}' has been created. "
        f"Result: {create_certificate_result}"
    )
    certificate_client.update_certificate_properties(
        certificate_name=cert_name, enabled=True
    )

    secret_id: Optional[str] = secret_client.get_secret(name=cert_name).id
    if secret_id:
        # Example: "https://example.vault.azure.net/secrets/Cert-123/SomeVersion"
        # Expected match for 'cert_url':
        # "https://example.vault.azure.net/secrets/Cert-123"
        match = re.match(
            r"(?P<cert_url>https://.+?/secrets/.+?)(?:/[^/]+)?$", secret_id
        )
        if match:
            secret_url_without_version = match.group("cert_url")
            return secret_url_without_version
        else:
            raise LisaException(
                f"Failed to parse the URL pattern of secret ID: '{secret_id}'."
            )
    else:
        raise LisaException(f"Failed to retrieve secret ID:'{cert_name}'.")


def check_certificate_existence(
    vault_url: str, cert_name: str, log: Logger, platform: "AzurePlatform"
) -> bool:
    certificate_client = CertificateClient(
        vault_url=vault_url, credential=platform.credential
    )

    try:
        certificate = certificate_client.get_certificate(cert_name)
        log.debug(f"Cert found '{certificate.name}'")
        return True
    except Exception as e:
        if "not found" in str(e).lower():
            log.debug(f"Certificate '{cert_name}' does not exist.")
            return False
        else:
            # Directly raise an exception without logging an error
            raise LisaException(
                f"Unexpected error checking certificate '{cert_name}': {e}"
            )


@retry(tries=10, delay=1)
def rotate_certificate(
    platform: "AzurePlatform",
    vault_url: str,
    cert_name: str,
    log: Logger,
) -> None:
    certificate_client = get_certificate_client(vault_url, platform)

    # Retrieve the old version of the certificate
    if not certificate_client.get_certificate(cert_name):
        error_message = f"Failed to retrieve old version of certificate: {cert_name}"
        raise LisaException(error_message)

    cert_policy = CertificatePolicy.get_default()

    # Create only the specified certificate
    # Create certificate
    create_certificate_poller = certificate_client.begin_create_certificate(
        cert_name, policy=cert_policy
    )
    create_certificate_result = create_certificate_poller.result()

    # Handle possible None value
    if (
        isinstance(create_certificate_result, KeyVaultCertificate)
        and hasattr(create_certificate_result, "properties")
        and create_certificate_result.properties
    ):
        new_certificate_version = create_certificate_result.properties.version
        log.debug(
            f"New version of certificate '{cert_name}': {new_certificate_version}. "
            "Certificate rotated."
        )
    else:
        error_message = "Failed to retrieve properties from create certificate result."
        raise LisaException(error_message)

    certificate_client.update_certificate_properties(
        certificate_name=cert_name, enabled=True
    )


@retry(tries=10, delay=1)
def delete_certificate(
    platform: "AzurePlatform",
    vault_url: str,
    cert_name: str,
    log: Logger,
) -> bool:
    certificate_client = get_certificate_client(vault_url, platform)

    try:
        certificate_client.begin_delete_certificate(cert_name)
        log.debug(f"Certificate {cert_name} deleted successfully.")
        return True
    except Exception:
        error_message = f"Failed to delete certificate: {cert_name}"
        raise LisaException(error_message)


def is_cloud_init_enabled(node: Node) -> bool:
    ls_tool = node.tools[Ls]

    if ls_tool.path_exists(
        "/var/log/cloud-init.log", sudo=True
    ) and ls_tool.path_exists("/var/lib/cloud/instance", sudo=True):
        return True
    return False


@retry(tries=10, delay=1, jitter=(0.5, 1))
def load_location_info_from_file(
    cached_file_name: Path, log: Logger
) -> Optional[AzureLocation]:
    loaded_obj: Optional[AzureLocation] = None
    if cached_file_name.exists():
        try:
            with open(cached_file_name, "r") as f:
                loaded_data: Dict[str, Any] = json.load(f)
            loaded_obj = schema.load_by_type(AzureLocation, loaded_data)
        except Exception as identifier:
            # if schema changed, There may be exception, remove cache and retry
            # Note: retry on this method depends on decorator
            log.debug(f"error on loading cache, delete cache and retry. {identifier}")
            cached_file_name.unlink()
            raise identifier
    return loaded_obj


def convert_to_azure_node_space(node_space: schema.NodeSpace) -> None:
    if not node_space:
        return

    from .platform_ import AzurePlatform

    feature.reload_platform_features(node_space, AzurePlatform.supported_features())

    if node_space.disk:
        from . import features

        node_space.disk = schema.load_by_type(
            features.AzureDiskOptionSettings, node_space.disk
        )
    if node_space.network_interface:
        node_space.network_interface = schema.load_by_type(
            schema.NetworkInterfaceOptionSettings, node_space.network_interface
        )
