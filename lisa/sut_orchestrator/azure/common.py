# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from dataclasses import InitVar, dataclass, field
from threading import Lock
from time import sleep
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from azure.mgmt.compute import ComputeManagementClient  # type: ignore
from azure.mgmt.marketplaceordering import MarketplaceOrderingAgreements  # type: ignore
from azure.mgmt.network import NetworkManagementClient  # type: ignore
from azure.mgmt.resource import ResourceManagementClient  # type: ignore
from azure.mgmt.storage import StorageManagementClient  # type: ignore
from azure.mgmt.storage.models import Sku, StorageAccountCreateParameters  # type:ignore
from azure.storage.blob import BlobServiceClient, ContainerClient  # type: ignore
from dataclasses_json import dataclass_json
from marshmallow import validate

from lisa import schema
from lisa.environment import Environment
from lisa.node import Node
from lisa.util import LisaException, constants
from lisa.util.logger import Logger
from lisa.util.parallel import check_cancelled
from lisa.util.perf_timer import create_timer

if TYPE_CHECKING:
    from .platform_ import AzurePlatform

AZURE = "azure"
AZURE_SHARED_RG_NAME = "lisa_shared_resource"


# when call sdk APIs, it's easy to have conflict on access auth files. Use lock
# to prevent it happens.
_global_credential_access_lock = Lock()


@dataclass
class EnvironmentContext:
    resource_group_name: str = ""
    resource_group_is_created: bool = False


@dataclass
class NodeContext:
    resource_group_name: str = ""
    vm_name: str = ""
    username: str = ""
    password: str = ""
    private_key_file: str = ""


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
    offer: str = "UbuntuServer"
    sku: str = "18.04-LTS"
    version: str = "Latest"


@dataclass_json()
@dataclass
class SharedImageGallerySchema:
    subscription_id: str = ""
    image_gallery: str = ""
    image_definition: str = ""
    image_version: str = ""


@dataclass_json()
@dataclass
class AzureNodeSchema:
    name: str = ""
    vm_size: str = ""
    location: str = ""
    # Required by shared gallery images which are present in
    # subscription different from where LISA is run
    subscription_id: str = ""
    marketplace_raw: Optional[Union[Dict[Any, Any], str]] = field(
        default=None, metadata=schema.metadata(data_key="marketplace")
    )
    shared_gallery_raw: Optional[Union[Dict[Any, Any], str]] = field(
        default=None, metadata=schema.metadata(data_key="shared_gallery")
    )
    vhd: str = ""
    nic_count: int = 1
    enable_sriov: bool = False
    data_disk_count: int = 0
    data_disk_caching_type: str = field(
        default=constants.DATADISK_CACHING_TYPE_NONE,
        metadata=schema.metadata(
            validate=validate.OneOf(
                [
                    constants.DATADISK_CACHING_TYPE_NONE,
                    constants.DATADISK_CACHING_TYPE_READONLY,
                    constants.DATADISK_CACHING_TYPE_READYWRITE,
                ]
            )
        ),
    )
    data_disk_iops: int = 500
    data_disk_size: int = 32
    disk_type: str = ""

    # for marketplace image, which need to accept terms
    purchase_plan: Optional[AzureVmPurchasePlanSchema] = None

    _marketplace: InitVar[Optional[AzureVmMarketplaceSchema]] = None

    _shared_gallery: InitVar[Optional[SharedImageGallerySchema]] = None

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
            if len(shared_gallery_strings) == 4:
                shared_gallery = SharedImageGallerySchema(*shared_gallery_strings)
                # shared_gallery_raw is used
                self.shared_gallery_raw = shared_gallery.to_dict()  # type: ignore
            elif len(shared_gallery_strings) == 3:
                shared_gallery = SharedImageGallerySchema(
                    self.subscription_id, *shared_gallery_strings
                )
                # shared_gallery_raw is used
                self.shared_gallery_raw = shared_gallery.to_dict()  # type: ignore
            else:
                raise LisaException(
                    f"Invalid value for the provided shared gallery "
                    f"parameter: '{self.shared_gallery_raw}'."
                    f"The shared gallery parameter should be in the format: "
                    f"'<subscription_id>/<image_gallery>/<image_definition>"
                    f"/<image_version>' or '<image_gallery>/<image_definition>"
                    f"/<image_version>'"
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

    def get_image_name(self) -> str:
        result = ""
        if self.vhd:
            result = self.vhd
        elif self.shared_gallery:
            assert isinstance(
                self.shared_gallery_raw, dict
            ), f"actual type: {type(self.shared_gallery_raw)}"
            result = " ".join([x for x in self.shared_gallery_raw.values()])
        elif self.marketplace:
            assert isinstance(
                self.marketplace_raw, dict
            ), f"actual type: {type(self.marketplace_raw)}"
            result = " ".join([x for x in self.marketplace_raw.values()])
        return result


def get_compute_client(
    platform: "AzurePlatform", api_version: Optional[str] = None
) -> ComputeManagementClient:
    return ComputeManagementClient(
        credential=platform.credential,
        subscription_id=platform.subscription_id,
        api_version=api_version,
    )


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
    subscription_id: str, location: str, type: str = "s"
) -> str:
    subscription_id_postfix = subscription_id[-8:]
    # name should be shorter than 24 charactor
    return f"lisa{type}{location[0:11]}{subscription_id_postfix}"


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


def wait_operation(operation: Any) -> Any:
    check_cancelled()
    return operation.wait()


def get_or_create_storage_container(
    storage_account_name: str, container_name: str, credential: Any
) -> ContainerClient:
    """
    Create a Azure Storage container if it does not exist.
    """
    blob_service_client = BlobServiceClient(
        f"https://{storage_account_name}.blob.core.windows.net", credential
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
            sku=Sku(name="Standard_LRS"), kind="StorageV2", location=location
        )
        operation = storage_client.storage_accounts.begin_create(
            resource_group_name=resource_group_name,
            account_name=account_name,
            parameters=parameters,
        )
        wait_operation(operation)


def check_or_create_resource_group(
    credential: Any,
    subscription_id: str,
    resource_group_name: str,
    location: str,
    log: Logger,
) -> None:
    rm_client = get_resource_management_client(credential, subscription_id)
    global _global_credential_access_lock
    with _global_credential_access_lock:
        az_shared_rg_exists = rm_client.resource_groups.check_existence(
            resource_group_name
        )
    if not az_shared_rg_exists:
        log.info(f"Creating Resource group: '{resource_group_name}'")

        with _global_credential_access_lock:
            rm_client.resource_groups.create_or_update(
                resource_group_name, {"location": location}
            )


def wait_copy_blob(
    blob_client: Any,
    vhd_path: str,
    log: Logger,
    timeout: int = 60 * 30,
) -> None:
    log.info(f"copying vhd: {vhd_path}")

    timeout_timer = create_timer()
    while timeout_timer.elapsed(False) < timeout:
        props = blob_client.get_blob_properties()
        if props.copy.status == "success":
            break
        # the copy is very slow, it may need several minutes. check it every
        # 2 seconds.
        sleep(2)
    if timeout_timer.elapsed() >= timeout:
        raise LisaException(f"wait copying VHD timeout: {vhd_path}")

    log.debug("vhd copied")


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
        metadata=schema.metadata(
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
        metadata=schema.metadata(
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
        metadata=schema.metadata(
            validate=validate.OneOf(DataDiskCreateOption.get_create_option())
        ),
    )


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
                    f"IOPS {data_disk_iops} is invaild for disk type {disk_type}."
                )
            min_iops = min(iops)
            return iops_dict[min_iops]
        else:
            raise LisaException(f"Data disk type {disk_type} is unsupported.")
