# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from dataclasses_json import dataclass_json
from marshmallow import validate

from lisa import schema
from lisa.environment import Environment
from lisa.node import Node
from lisa.util import LisaException, constants, field_metadata


@dataclass
class EnvironmentContext:
    key_pair_name: str = ""
    security_group_name: str = ""
    security_group_id: str = ""
    security_group_is_created: bool = False


@dataclass
class NodeContext:
    instance_id: str = ""
    vm_name: str = ""
    username: str = ""
    password: str = ""
    private_key_file: str = ""


@dataclass_json()
@dataclass
class AwsVmMarketplaceSchema:
    # Ubuntu Server 18.04 with SQL Server 2019 Express Edition AMI provided by Amazon
    imageid: str = "ami-0340a222114f27094"


@dataclass_json()
@dataclass
class AwsNodeSchema:
    name: str = ""
    vm_size: str = ""
    location: str = ""

    marketplace_raw: Optional[str] = field(
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

    def __post_init__(self) -> None:
        # Caching for marketplace image
        self._marketplace: Optional[AwsVmMarketplaceSchema] = None

    @property
    def marketplace(self) -> AwsVmMarketplaceSchema:
        if self._marketplace is None:
            assert isinstance(
                self.marketplace_raw, str
            ), f"actual: {type(self.marketplace_raw)}"
            self.marketplace_raw = self.marketplace_raw.strip()
            if self.marketplace_raw:
                self._marketplace = AwsVmMarketplaceSchema(self.marketplace_raw)
            else:
                self._marketplace = AwsVmMarketplaceSchema()

        return self._marketplace

    @marketplace.setter
    def marketplace(self, value: Optional[AwsVmMarketplaceSchema]) -> None:
        self._marketplace = value

    def get_image_id(self) -> str:
        return self.marketplace.imageid


def get_node_context(node: Node) -> NodeContext:
    return node.get_context(NodeContext)


def get_environment_context(environment: Environment) -> EnvironmentContext:
    return environment.get_context(EnvironmentContext)


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
    # StandardHDDLRS/StandardSSDLRS/PremiumSSDLRS are mapped to volume type st1/gp2/io1.
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
