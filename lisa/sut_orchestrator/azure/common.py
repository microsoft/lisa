# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import sys
from dataclasses import InitVar, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from time import sleep
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

import requests
from azure.mgmt.compute import ComputeManagementClient  # type: ignore
from azure.mgmt.compute.models import VirtualMachine  # type: ignore
from azure.mgmt.marketplaceordering import MarketplaceOrderingAgreements  # type: ignore
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
from azure.mgmt.resource import ResourceManagementClient  # type: ignore
from azure.mgmt.storage import StorageManagementClient  # type: ignore
from azure.mgmt.storage.models import (  # type: ignore
    Sku,
    StorageAccountCreateParameters,
)
from azure.storage.blob import (
    AccountSasPermissions,
    BlobSasPermissions,
    BlobServiceClient,
    ContainerClient,
    ResourceTypes,
    generate_account_sas,
    generate_blob_sas,
)
from azure.storage.fileshare import ShareServiceClient  # type: ignore
from dataclasses_json import dataclass_json
from marshmallow import validate
from PIL import Image, UnidentifiedImageError
from retry import retry

from lisa import schema
from lisa.environment import Environment, load_environments
from lisa.feature import Features
from lisa.node import Node, RemoteNode
from lisa.secret import PATTERN_HEADTAIL, PATTERN_URL, add_secret
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


PATTERN_NIC_NAME = re.compile(r"Microsoft.Network/networkInterfaces/(.*)", re.M)
PATTERN_PUBLIC_IP_NAME = re.compile(
    r"providers/Microsoft.Network/publicIPAddresses/(.*)", re.M
)

# when call sdk APIs, it's easy to have conflict on access auth files. Use lock
# to prevent it happens.
global_credential_access_lock = Lock()


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
    public_ip_address: str = ""
    private_ip_address: str = ""


@dataclass_json()
@dataclass
class AzureVmPurchasePlanSchema:
    name: str
    product: str
    publisher: str


@dataclass_json()
@dataclass
class AzureVmMarketplaceSchema:
    publisher: str = "Canonical"
    offer: str = "0001-com-ubuntu-server-jammy"
    sku: str = "22_04-lts"
    version: str = "Latest"

    def __hash__(self) -> int:
        return hash(f"{self.publisher}/{self.offer}/{self.sku}/{self.version}")


@dataclass_json()
@dataclass
class SharedImageGallerySchema:
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


@dataclass_json()
@dataclass
class VhdSchema:
    vhd_path: str = ""
    vmgs_path: Optional[str] = None


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
    marketplace_raw: Optional[Union[Dict[Any, Any], str]] = field(
        default=None, metadata=field_metadata(data_key="marketplace")
    )
    shared_gallery_raw: Optional[Union[Dict[Any, Any], str]] = field(
        default=None, metadata=field_metadata(data_key="shared_gallery")
    )
    vhd_raw: Optional[Union[Dict[Any, Any], str]] = field(
        default=None, metadata=field_metadata(data_key="vhd")
    )

    hyperv_generation: int = field(
        default=1,
        metadata=field_metadata(validate=validate.OneOf([1, 2])),
    )
    # for marketplace image, which need to accept terms
    purchase_plan: Optional[AzureVmPurchasePlanSchema] = None

    # the linux and Windows has different settings. If it's not specified, it's
    # True by default for SIG and vhd, and is parsed from marketplace
    # image.
    is_linux: Optional[bool] = None

    _marketplace: InitVar[Optional[AzureVmMarketplaceSchema]] = None

    _shared_gallery: InitVar[Optional[SharedImageGallerySchema]] = None

    _vhd: InitVar[Optional[VhdSchema]] = None

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
                "data_disk_caching_type",
                "disk_type",
            ],
        )
        # If vhd contains sas token, need add mask
        if isinstance(self.vhd_raw, str):
            add_secret(self.vhd_raw, PATTERN_URL)

    @property
    def marketplace(self) -> Optional[AzureVmMarketplaceSchema]:
        # this is a safe guard and prevent mypy error on typing
        if not hasattr(self, "_marketplace"):
            self._marketplace: Optional[AzureVmMarketplaceSchema] = None
        marketplace: Optional[AzureVmMarketplaceSchema] = self._marketplace
        if not marketplace:
            if isinstance(self.marketplace_raw, dict):
                # Users decide the cases of image names,
                #  the inconsistent cases cause the mismatched error in notifiers.
                # The lower() normalizes the image names,
                #  it has no impact on deployment.
                self.marketplace_raw = dict(
                    (k, v.lower()) for k, v in self.marketplace_raw.items()
                )
                marketplace = schema.load_by_type(
                    AzureVmMarketplaceSchema, self.marketplace_raw
                )
                # this step makes marketplace_raw is validated, and
                # filter out any unwanted content.
                self.marketplace_raw = marketplace.to_dict()  # type: ignore
            elif self.marketplace_raw:
                assert isinstance(
                    self.marketplace_raw, str
                ), f"actual: {type(self.marketplace_raw)}"

                self.marketplace_raw = self.marketplace_raw.strip()

                if self.marketplace_raw:
                    # Users decide the cases of image names,
                    #  the inconsistent cases cause the mismatched error in notifiers.
                    # The lower() normalizes the image names,
                    #  it has no impact on deployment.
                    marketplace_strings = re.split(
                        r"[:\s]+", self.marketplace_raw.lower()
                    )

                    if len(marketplace_strings) == 4:
                        marketplace = AzureVmMarketplaceSchema(*marketplace_strings)
                        # marketplace_raw is used
                        self.marketplace_raw = marketplace.to_dict()  # type: ignore
                    else:
                        raise LisaException(
                            f"Invalid value for the provided marketplace "
                            f"parameter: '{self.marketplace_raw}'."
                            f"The marketplace parameter should be in the format: "
                            f"'<Publisher> <Offer> <Sku> <Version>' "
                            f"or '<Publisher>:<Offer>:<Sku>:<Version>'"
                        )
            self._marketplace = marketplace
        return marketplace

    @marketplace.setter
    def marketplace(self, value: Optional[AzureVmMarketplaceSchema]) -> None:
        self._marketplace = value
        if value is None:
            self.marketplace_raw = None
        else:
            self.marketplace_raw = value.to_dict()  # type: ignore

    @property
    def shared_gallery(self) -> Optional[SharedImageGallerySchema]:
        # this is a safe guard and prevent mypy error on typing
        if not hasattr(self, "_shared_gallery"):
            self._shared_gallery: Optional[SharedImageGallerySchema] = None
        shared_gallery: Optional[SharedImageGallerySchema] = self._shared_gallery
        if shared_gallery:
            return shared_gallery
        if isinstance(self.shared_gallery_raw, dict):
            # Users decide the cases of image names,
            #  the inconsistent cases cause the mismatched error in notifiers.
            # The lower() normalizes the image names,
            #  it has no impact on deployment.
            self.shared_gallery_raw = dict(
                (k, v.lower()) for k, v in self.shared_gallery_raw.items()
            )
            shared_gallery = schema.load_by_type(
                SharedImageGallerySchema, self.shared_gallery_raw
            )
            if not shared_gallery.subscription_id:
                shared_gallery.subscription_id = self.subscription_id
            # this step makes shared_gallery_raw is validated, and
            # filter out any unwanted content.
            self.shared_gallery_raw = shared_gallery.to_dict()  # type: ignore
        elif self.shared_gallery_raw:
            assert isinstance(
                self.shared_gallery_raw, str
            ), f"actual: {type(self.shared_gallery_raw)}"
            # Users decide the cases of image names,
            #  the inconsistent cases cause the mismatched error in notifiers.
            # The lower() normalizes the image names,
            #  it has no impact on deployment.
            shared_gallery_strings = re.split(
                r"[/]+", self.shared_gallery_raw.strip().lower()
            )
            if len(shared_gallery_strings) == 5:
                shared_gallery = SharedImageGallerySchema(*shared_gallery_strings)
                # shared_gallery_raw is used
                self.shared_gallery_raw = shared_gallery.to_dict()  # type: ignore
            elif len(shared_gallery_strings) == 3:
                shared_gallery = SharedImageGallerySchema(
                    self.subscription_id, None, *shared_gallery_strings
                )
                # shared_gallery_raw is used
                self.shared_gallery_raw = shared_gallery.to_dict()  # type: ignore
            else:
                raise LisaException(
                    f"Invalid value for the provided shared gallery "
                    f"parameter: '{self.shared_gallery_raw}'."
                    f"The shared gallery parameter should be in the format: "
                    f"'<subscription_id>/<resource_group_name>/<image_gallery>/"
                    f"<image_definition>/<image_version>' or '<image_gallery>/"
                    f"<image_definition>/<image_version>'"
                )
        self._shared_gallery = shared_gallery
        return shared_gallery

    @shared_gallery.setter
    def shared_gallery(self, value: Optional[SharedImageGallerySchema]) -> None:
        self._shared_gallery = value
        if value is None:
            self.shared_gallery_raw = None
        else:
            self.shared_gallery_raw = value.to_dict()  # type: ignore

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
            add_secret(vhd.vhd_path, PATTERN_URL)
            if vhd.vmgs_path:
                add_secret(vhd.vmgs_path, PATTERN_URL)
            # this step makes vhd_raw is validated, and
            # filter out any unwanted content.
            self.vhd_raw = vhd.to_dict()  # type: ignore
        elif self.vhd_raw is not None:
            assert isinstance(self.vhd_raw, str), f"actual: {type(self.vhd_raw)}"
            vhd = VhdSchema(self.vhd_raw)
            add_secret(vhd.vhd_path, PATTERN_URL)
            self.vhd_raw = vhd.to_dict()  # type: ignore
        self._vhd = vhd
        if vhd:
            return vhd
        else:
            return None

    @vhd.setter
    def vhd(self, value: Optional[VhdSchema]) -> None:
        self._vhd = value
        if value is None:
            self.vhd_raw = None
        else:
            self.vhd_raw = self._vhd.to_dict()  # type: ignore

    def get_image_name(self) -> str:
        result = ""
        if self.vhd and self.vhd.vhd_path:
            result = self.vhd.vhd_path
        elif self.shared_gallery:
            assert isinstance(
                self.shared_gallery_raw, dict
            ), f"actual type: {type(self.shared_gallery_raw)}"
            if self.shared_gallery.resource_group_name:
                result = "/".join([x for x in self.shared_gallery_raw.values()])
            else:
                result = (
                    f"{self.shared_gallery.image_gallery}/"
                    f"{self.shared_gallery.image_definition}/"
                    f"{self.shared_gallery.image_version}"
                )
        elif self.marketplace:
            assert isinstance(
                self.marketplace_raw, dict
            ), f"actual type: {type(self.marketplace_raw)}"
            result = " ".join([x for x in self.marketplace_raw.values()])
        return result


@dataclass_json()
@dataclass
class AzureNodeArmParameter(AzureNodeSchema):
    nic_count: int = 1
    enable_sriov: bool = False
    disk_type: str = ""
    disk_controller_type: str = ""

    @classmethod
    def from_node_runbook(cls, runbook: AzureNodeSchema) -> "AzureNodeArmParameter":
        parameters = runbook.to_dict()  # type: ignore
        if "marketplace" in parameters:
            parameters["marketplace_raw"] = parameters["marketplace"]
            del parameters["marketplace"]
        if "shared_gallery" in parameters:
            parameters["shared_gallery_raw"] = parameters["shared_gallery"]
            del parameters["shared_gallery"]
        if "vhd" in parameters:
            parameters["vhd_raw"] = parameters["vhd"]
            del parameters["vhd"]

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
    type: str = field(
        default=schema.DiskType.StandardHDDLRS,
        metadata=field_metadata(
            validate=validate.OneOf(
                [
                    schema.DiskType.StandardHDDLRS,
                    schema.DiskType.StandardSSDLRS,
                    schema.DiskType.PremiumSSDLRS,
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
class AzureArmParameter:
    storage_name: str = ""
    vhd_storage_name: str = ""
    location: str = ""
    admin_username: str = ""
    admin_password: str = ""
    admin_key_data: str = ""
    subnet_count: int = 1
    shared_resource_group_name: str = AZURE_SHARED_RG_NAME
    availability_set_tags: Dict[str, str] = field(default_factory=dict)
    availability_set_properties: Dict[str, Any] = field(default_factory=dict)
    nodes: List[AzureNodeArmParameter] = field(default_factory=list)
    data_disks: List[DataDiskSchema] = field(default_factory=list)
    use_availability_sets: bool = False
    vm_tags: Dict[str, Any] = field(default_factory=dict)

    virtual_network_resource_group: str = ""
    virtual_network_name: str = AZURE_VIRTUAL_NETWORK_NAME
    subnet_prefix: str = AZURE_SUBNET_PREFIX

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
    )


def create_update_private_endpoints(
    platform: "AzurePlatform",
    resource_group_name: str,
    location: str,
    subnet_id: str,
    private_link_service_id: str,
    group_ids: List[str],
    log: Logger,
    private_endpoint_name: str = "pe_test",
    status: str = "Approved",
    description: str = "Auto-Approved",
) -> Any:
    network = get_network_client(platform)
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
    private_endpoint_name: str = "pe_test",
) -> None:
    network = get_network_client(platform)
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
    )


def create_update_private_zones(
    platform: "AzurePlatform",
    resource_group_name: str,
    log: Logger,
    private_zone_name: str = "privatelink.file.core.windows.net",
    private_zone_location: str = "global",
) -> Any:
    private_dns_client = get_private_dns_management_client(platform)
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
    private_zone_name: str = "privatelink.file.core.windows.net",
) -> None:
    private_dns_client = get_private_dns_management_client(platform)
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
    private_zone_name: str = "privatelink.file.core.windows.net",
    relative_record_set_name: str = "privatelink",
    record_type: str = "A",
) -> None:
    private_dns_client = get_private_dns_management_client(platform)
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
    private_zone_name: str = "privatelink.file.core.windows.net",
    relative_record_set_name: str = "privatelink",
    record_type: str = "A",
) -> None:
    private_dns_client = get_private_dns_management_client(platform)
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
    private_zone_name: str = "privatelink.file.core.windows.net",
    virtual_network_link_name: str = "vnetlink",
    registration_enabled: bool = False,
    virtual_network_link_location: str = "global",
) -> None:
    private_dns_client = get_private_dns_management_client(platform)
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
    private_zone_name: str = "privatelink.file.core.windows.net",
    virtual_network_link_name: str = "vnetlink",
) -> None:
    private_dns_client = get_private_dns_management_client(platform)
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
    private_dns_zone_group_name: str = "default",
    private_endpoint_name: str = "pe_test",
    private_dns_zone_name: str = "privatelink.file.core.windows.net",
) -> None:
    network_client = get_network_client(platform)
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
    private_dns_zone_group_name: str = "default",
    private_endpoint_name: str = "pe_test",
) -> None:
    network_client = get_network_client(platform)
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


def get_network_client(platform: "AzurePlatform") -> ComputeManagementClient:
    return NetworkManagementClient(
        credential=platform.credential,
        subscription_id=platform.subscription_id,
    )


def get_storage_client(
    credential: Any, subscription_id: str
) -> StorageManagementClient:
    return StorageManagementClient(
        credential=credential,
        subscription_id=subscription_id,
    )


def get_resource_management_client(
    credential: Any, subscription_id: str
) -> ResourceManagementClient:
    return ResourceManagementClient(
        credential=credential, subscription_id=subscription_id
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
    credential: Any, subscription_id: str, account_name: str, resource_group_name: str
) -> Any:
    """
    return a shared key credential. This credential doesn't need extra
     permissions to access blobs.
    """
    storage_client = get_storage_client(credential, subscription_id)
    key = storage_client.storage_accounts.list_keys(
        account_name=account_name, resource_group_name=resource_group_name
    ).keys[0]
    return {"account_name": account_name, "account_key": key.value}


def generate_blob_sas_token(
    credential: Any,
    subscription_id: str,
    account_name: str,
    resource_group_name: str,
    container_name: str,
    file_name: str,
    expired_hours: int = 2,
) -> Any:
    shared_key_credential = get_storage_credential(
        credential=credential,
        subscription_id=subscription_id,
        account_name=account_name,
        resource_group_name=resource_group_name,
    )

    sas_token = generate_blob_sas(
        account_name=shared_key_credential["account_name"],
        account_key=shared_key_credential["account_key"],
        container_name=container_name,
        blob_name=file_name,
        permission=BlobSasPermissions(read=True),  # type: ignore
        expiry=datetime.utcnow() + timedelta(hours=expired_hours),
    )
    return sas_token


def generate_sas_token(
    credential: Any,
    subscription_id: str,
    account_name: str,
    resource_group_name: str,
    expired_hours: int = 2,
    writable: bool = False,
) -> Any:
    shared_key_credential = get_storage_credential(
        credential=credential,
        subscription_id=subscription_id,
        account_name=account_name,
        resource_group_name=resource_group_name,
    )
    resource_types = ResourceTypes(  # type: ignore
        service=True, container=True, object=True
    )
    sas_token = generate_account_sas(
        account_name=shared_key_credential["account_name"],
        account_key=shared_key_credential["account_key"],
        resource_types=resource_types,
        permission=AccountSasPermissions(read=True, write=writable),  # type: ignore
        expiry=datetime.utcnow() + timedelta(hours=expired_hours),
    )
    return sas_token


def get_blob_service_client(
    credential: Any,
    subscription_id: str,
    account_name: str,
    resource_group_name: str,
) -> BlobServiceClient:
    """
    Create a Azure Storage container if it does not exist.
    """
    shared_key_credential = get_storage_credential(
        credential=credential,
        subscription_id=subscription_id,
        account_name=account_name,
        resource_group_name=resource_group_name,
    )
    blob_service_client = BlobServiceClient(
        f"https://{account_name}.blob.core.windows.net", shared_key_credential
    )
    return blob_service_client


def get_or_create_storage_container(
    credential: Any,
    subscription_id: str,
    account_name: str,
    container_name: str,
    resource_group_name: str,
) -> ContainerClient:
    """
    Create a Azure Storage container if it does not exist.
    """
    blob_service_client = get_blob_service_client(
        credential, subscription_id, account_name, resource_group_name
    )
    container_client = blob_service_client.get_container_client(container_name)
    if not container_client.exists():
        container_client.create_container()
    return container_client


def check_or_create_storage_account(
    credential: Any,
    subscription_id: str,
    account_name: str,
    resource_group_name: str,
    location: str,
    log: Logger,
    sku: str = "Standard_LRS",
    kind: str = "StorageV2",
    enable_https_traffic_only: bool = True,
) -> None:
    # check and deploy storage account.
    # storage account can be deployed inside of arm template, but if the concurrent
    # is too big, Azure may not able to delete deployment script on time. so there
    # will be error like below
    # Creating the deployment 'name' would exceed the quota of '800'.
    storage_client = get_storage_client(credential, subscription_id)
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
    account_name: str,
    resource_group_name: str,
    log: Logger,
) -> None:
    storage_client = get_storage_client(credential, subscription_id)
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
    resource_group_name: str,
    location: str,
    log: Logger,
) -> None:
    with get_resource_management_client(credential, subscription_id) as rm_client:
        with global_credential_access_lock:
            az_shared_rg_exists = rm_client.resource_groups.check_existence(
                resource_group_name
            )
        if not az_shared_rg_exists:
            log.info(f"Creating Resource group: '{resource_group_name}'")

            with global_credential_access_lock:
                rm_client.resource_groups.create_or_update(
                    resource_group_name, {"location": location}
                )
            check_till_timeout(
                lambda: rm_client.resource_groups.check_existence(resource_group_name)
                is True,
                timeout_message=f"wait for {resource_group_name} created",
            )


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
    account_name: str,
    resource_group_name: str,
) -> ShareServiceClient:
    shared_key_credential = get_storage_credential(
        credential=credential,
        subscription_id=subscription_id,
        account_name=account_name,
        resource_group_name=resource_group_name,
    )
    share_service_client = ShareServiceClient(
        f"https://{account_name}.file.core.windows.net",
        shared_key_credential,
    )
    return share_service_client


def get_or_create_file_share(
    credential: Any,
    subscription_id: str,
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
        credential, subscription_id, account_name, resource_group_name
    )
    all_shares = list(share_service_client.list_shares())
    if file_share_name not in (x.name for x in all_shares):
        log.debug(f"creating file share {file_share_name} with protocols {protocols}")
        share_service_client.create_share(file_share_name, protocols=protocols)
    return str("//" + share_service_client.primary_hostname + "/" + file_share_name)


def delete_file_share(
    credential: Any,
    subscription_id: str,
    account_name: str,
    file_share_name: str,
    resource_group_name: str,
    log: Logger,
) -> None:
    """
    Delete Azure Storage file share
    """
    share_service_client = get_share_service_client(
        credential, subscription_id, account_name, resource_group_name
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
        diagnostic_data = (
            compute_client.virtual_machines.retrieve_boot_diagnostics_data(
                resource_group_name=resource_group_name, vm_name=vm_name
            )
        )
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

    log_response = requests.get(diagnostic_data.serial_console_log_blob_uri, timeout=60)
    if log_response.status_code == 404:
        log.debug(
            "The serial console is not generated. "
            "The reason may be the VM is not started."
        )
    return log_response.content


def load_environment(
    platform: "AzurePlatform", resource_group_name: str, log: Logger
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

        node_context = get_node_context(node)
        node_context.vm_name = node.name
        node_context.resource_group_name = resource_group_name

        node_context.username = platform_runbook.admin_username
        node_context.password = platform_runbook.admin_password
        node_context.private_key_file = platform_runbook.admin_private_key_file
        (
            node_context.public_ip_address,
            node_context.private_ip_address,
        ) = get_primary_ip_addresses(
            platform, resource_group_name, vms_map[node_context.vm_name]
        )
        node.set_connection_info(
            address=node_context.private_ip_address,
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
    for network_interface in vm.network_profile.network_interfaces:
        nic_name = get_matched_str(network_interface.id, PATTERN_NIC_NAME)
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
