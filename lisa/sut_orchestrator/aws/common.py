# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import sys
from dataclasses import InitVar, dataclass, field
from typing import Any, Dict, List, Optional, Union

from dataclasses_json import dataclass_json
from marshmallow import validate

from lisa import schema
from lisa.environment import Environment
from lisa.node import Node
from lisa.util import LisaException, constants, field_metadata
from lisa.util.parallel import check_cancelled
from lisa.util.perf_timer import create_timer


@dataclass
class EnvironmentContext:
    key_pair_name: str = ""
    security_group_name: str = ""
    security_group_id: str = ""
    security_group_is_created: bool = False


@dataclass
class NodeContext:
    intsance_id: str = ""
    vm_name: str = ""
    username: str = ""
    password: str = ""
    private_key_file: str = ""


@dataclass_json()
@dataclass
class AwsVmMarketplaceSchema:
    # amazon/AWS Deep Learning AMI GPU CUDA 11.2.1 (Ubuntu 20.04) 20220208
    imageid: str = "ami-097324d9d7113bccb"


@dataclass_json()
@dataclass
class AwsNodeSchema:
    name: str = ""
    vm_size: str = ""
    location: str = ""

    marketplace_raw: Optional[Union[Dict[Any, Any], str]] = field(
        default=None, metadata=field_metadata(data_key="marketplace")
    )

    nic_count: int = 1
    enable_sriov: bool = False
    data_disk_count: int = 0
    data_disk_caching_type: str = field(
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
    data_disk_iops: int = 500
    data_disk_size: int = 32
    disk_type: str = ""

    # for marketplace image, which need to accept terms
    _marketplace: InitVar[Optional[AwsVmMarketplaceSchema]] = None

    @property
    def marketplace(self) -> Optional[AwsVmMarketplaceSchema]:
        # this is a safe guard and prevent mypy error on typing
        if not hasattr(self, "_marketplace"):
            self._marketplace: Optional[AwsVmMarketplaceSchema] = None
        marketplace: Optional[AwsVmMarketplaceSchema] = self._marketplace
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
                    AwsVmMarketplaceSchema, self.marketplace_raw
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

                    if len(marketplace_strings) == 1:
                        marketplace = AwsVmMarketplaceSchema(*marketplace_strings)
                        # marketplace_raw is used
                        self.marketplace_raw = marketplace.to_dict()  # type: ignore
                    else:
                        raise LisaException(
                            f"Invalid value for the provided marketplace "
                            f"parameter: '{self.marketplace_raw}'."
                            f"The marketplace parameter should be in the format: "
                            f"'<'ImageId'>'"
                        )
            self._marketplace = marketplace
        return marketplace

    @marketplace.setter
    def marketplace(self, value: Optional[AwsVmMarketplaceSchema]) -> None:
        self._marketplace = value
        if value is None:
            self.marketplace_raw = None
        else:
            self.marketplace_raw = value.to_dict()  # type: ignore

    def get_image_id(self) -> str:
        result = ""
        if self.marketplace:
            assert isinstance(
                self.marketplace_raw, dict
            ), f"actual type: {type(self.marketplace_raw)}"
            result = self.marketplace_raw["imageid"]
        return result


def get_node_context(node: Node) -> NodeContext:
    return node.get_context(NodeContext)


def get_environment_context(environment: Environment) -> EnvironmentContext:
    return environment.get_context(EnvironmentContext)


def wait_operation(operation: Any, time_out: int = sys.maxsize) -> Any:
    timer = create_timer()
    while time_out > timer.elapsed(False):
        check_cancelled()
        if operation.done():
            break
        operation.wait(1)
    if time_out < timer.elapsed():
        raise Exception(
            f"timeout on wait Azure operation completed after {time_out} seconds."
        )


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
    iops: int = 500
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


class DataDisk:
    # refer https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ebs-volume-types.html
    # StandardHDDLRS/StandardSSDLRS/PremiumSSDLRS are mapped to valumn type st1/gp2/io1.
    IOPS_SIZE_DICT: Dict[schema.DiskType, Dict[int, int]] = {
        schema.DiskType.PremiumSSDLRS: {
            64000: 4,
        },
        schema.DiskType.StandardHDDLRS: {
            500: 125,
        },
        schema.DiskType.StandardSSDLRS: {
            16000: 1,
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
