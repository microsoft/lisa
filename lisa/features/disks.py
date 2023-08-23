# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from functools import partial
from typing import Any, List, Optional, Type

from assertpy.assertpy import assert_that

from lisa import schema
from lisa.feature import Feature
from lisa.tools import Mount
from lisa.tools.mount import PartitionInfo


class Disk(Feature):
    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return schema.DiskOptionSettings

    @classmethod
    def can_disable(cls) -> bool:
        return False

    def enabled(self) -> bool:
        return True

    def get_partition_with_mount_point(self, mount_point: str) -> PartitionInfo:
        partition_info = self._node.tools[Mount].get_partition_info()
        matched_partitions = [
            partition
            for partition in partition_info
            if partition.mount_point == mount_point
        ]
        assert_that(
            matched_partitions,
            f"Exactly one partition with mount point {mount_point} should be present",
        ).is_length(1)

        partition = matched_partitions[0]
        self._log.debug(f"disk: {partition}, mount_point: {mount_point}")

        return partition

    def get_raw_data_disks(self) -> List[str]:
        raise NotImplementedError

    def get_all_disks(self) -> List[str]:
        raise NotImplementedError

    def add_data_disk(
        self,
        count: int,
        disk_type: schema.DiskType = schema.DiskType.StandardHDDLRS,
        size_in_gb: int = 20,
    ) -> List[str]:
        raise NotImplementedError

    def remove_data_disk(self, names: Optional[List[str]] = None) -> None:
        raise NotImplementedError

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self.disks: List[str] = []

    def get_resource_disk_mount_point(self) -> str:
        raise NotImplementedError


DiskEphemeral = partial(
    schema.DiskOptionSettings, os_disk_type=schema.DiskType.Ephemeral
)
DiskPremiumSSDLRS = partial(
    schema.DiskOptionSettings,
    data_disk_type=schema.DiskType.PremiumSSDLRS,
    os_disk_type=schema.DiskType.PremiumSSDLRS,
)
DiskStandardHDDLRS = partial(
    schema.DiskOptionSettings,
    data_disk_type=schema.DiskType.StandardHDDLRS,
    os_disk_type=schema.DiskType.StandardHDDLRS,
)
DiskStandardSSDLRS = partial(
    schema.DiskOptionSettings,
    data_disk_type=schema.DiskType.StandardSSDLRS,
    os_disk_type=schema.DiskType.StandardSSDLRS,
)
DiskUltraSSDLRS = partial(
    schema.DiskOptionSettings, data_disk_type=schema.DiskType.UltraSSDLRS
)
