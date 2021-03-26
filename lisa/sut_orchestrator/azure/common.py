# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from dataclasses import InitVar, dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Optional, Union

from azure.mgmt.compute import ComputeManagementClient  # type: ignore
from azure.mgmt.marketplaceordering import MarketplaceOrderingAgreements  # type: ignore
from azure.mgmt.network import NetworkManagementClient  # type: ignore
from azure.mgmt.storage import StorageManagementClient  # type: ignore
from dataclasses_json import dataclass_json

from lisa import schema
from lisa.environment import Environment
from lisa.node import Node
from lisa.util import LisaException

if TYPE_CHECKING:
    from .platform_ import AzurePlatform

AZURE = "azure"


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
class AzureVmGallerySchema:
    publisher: str = "Canonical"
    offer: str = "UbuntuServer"
    sku: str = "18.04-LTS"
    version: str = "Latest"


@dataclass_json()
@dataclass
class AzureNodeSchema:
    name: str = ""
    vm_size: str = ""
    location: str = ""
    gallery_raw: Optional[Union[Dict[Any, Any], str]] = field(
        default=None, metadata=schema.metadata(data_key="gallery")
    )
    vhd: str = ""
    nic_count: int = 1
    # for gallery image, which need to accept terms
    purchase_plan: Optional[AzureVmPurchasePlanSchema] = None

    _gallery: InitVar[Optional[AzureVmGallerySchema]] = None

    @property
    def gallery(self) -> Optional[AzureVmGallerySchema]:
        # this is a safe guard and prevent mypy error on typing
        if not hasattr(self, "_gallery"):
            self._gallery: Optional[AzureVmGallerySchema] = None
        gallery: Optional[AzureVmGallerySchema] = self._gallery
        if not gallery:
            if isinstance(self.gallery_raw, dict):
                # Users decide the cases of image names,
                #  the inconsistent cases cause the mismatched error in notifiers.
                # The lower() normalizes the image names,
                #  it has no impact on deployment.
                self.gallery_raw = dict(
                    (k, v.lower()) for k, v in self.gallery_raw.items()
                )
                gallery = AzureVmGallerySchema.schema().load(  # type: ignore
                    self.gallery_raw
                )
                # this step makes gallery_raw is validated, and filter out any unwanted
                # content.
                self.gallery_raw = gallery.to_dict()  # type: ignore
            elif self.gallery_raw:
                assert isinstance(
                    self.gallery_raw, str
                ), f"actual: {type(self.gallery_raw)}"
                # Users decide the cases of image names,
                #  the inconsistent cases cause the mismatched error in notifiers.
                # The lower() normalizes the image names,
                #  it has no impact on deployment.
                gallery_strings = re.split(r"[:\s]+", self.gallery_raw.strip().lower())

                if len(gallery_strings) == 4:
                    gallery = AzureVmGallerySchema(*gallery_strings)
                    # gallery_raw is used
                    self.gallery_raw = gallery.to_dict()  # type: ignore
                else:
                    raise LisaException(
                        f"Invalid value for the provided gallery "
                        f"parameter: '{self.gallery_raw}'."
                        f"The gallery parameter should be in the format: "
                        f"'<Publisher> <Offer> <Sku> <Version>' "
                        f"or '<Publisher>:<Offer>:<Sku>:<Version>'"
                    )
            self._gallery = gallery
        return gallery

    @gallery.setter
    def gallery(self, value: Optional[AzureVmGallerySchema]) -> None:
        self._gallery = value
        if value is None:
            self.gallery_raw = None
        else:
            self.gallery_raw = value.to_dict()  # type: ignore

    def get_image_name(self) -> str:
        result = ""
        if self.vhd:
            result = self.vhd
        elif self.gallery:
            assert isinstance(
                self.gallery_raw, dict
            ), f"actual type: {type(self.gallery_raw)}"
            result = " ".join([x for x in self.gallery_raw.values()])
        return result


def get_compute_client(platform: Any) -> ComputeManagementClient:
    # there is cycle import, if assert type.
    # so it just use typing here only, no assertion.
    azure_platform: AzurePlatform = platform
    return ComputeManagementClient(
        credential=azure_platform.credential,
        subscription_id=azure_platform.subscription_id,
    )


def get_network_client(platform: Any) -> ComputeManagementClient:
    # there is cycle import, if assert type.
    # so it just use typing here only, no assertion.
    azure_platform: AzurePlatform = platform
    return NetworkManagementClient(
        credential=azure_platform.credential,
        subscription_id=azure_platform.subscription_id,
    )


def get_storage_client(platform: Any) -> ComputeManagementClient:
    azure_platform: AzurePlatform = platform
    return StorageManagementClient(
        credential=azure_platform.credential,
        subscription_id=azure_platform.subscription_id,
    )


def get_storage_account_name(platform: Any, location: str) -> str:
    azure_platform: AzurePlatform = platform
    subscription_id_postfix = azure_platform.subscription_id[-8:]
    # name should be shorter than 24 charactor
    return f"lisas{location[0:11]}{subscription_id_postfix}"


def get_marketplace_ordering_client(platform: Any) -> MarketplaceOrderingAgreements:
    azure_platform: AzurePlatform = platform
    return MarketplaceOrderingAgreements(
        credential=azure_platform.credential,
        subscription_id=azure_platform.subscription_id,
    )


def get_node_context(node: Node) -> NodeContext:
    return node.get_context(NodeContext)


def get_environment_context(environment: Environment) -> EnvironmentContext:
    return environment.get_context(EnvironmentContext)


def wait_operation(operation: Any) -> Any:
    # to support timeout in future
    return operation.wait()
