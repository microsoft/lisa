# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from functools import partial
from typing import Any, Dict, List, Optional, Type

from assertpy.assertpy import assert_that

from lisa import schema
from lisa.feature import Feature
from lisa.operating_system import BSD
from lisa.tools import Mount
from lisa.tools.mount import PartitionInfo
from lisa.util import LisaException, get_matched_str


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

    def get_hardware_disk_controller_type(self) -> schema.DiskControllerType:
        raise NotImplementedError

    def add_data_disk(
        self,
        count: int,
        disk_type: schema.DiskType = schema.DiskType.StandardHDDLRS,
        size_in_gb: int = 20,
        lun: int = -1,
    ) -> List[str]:
        raise NotImplementedError

    def remove_data_disk(self, names: Optional[List[str]] = None) -> None:
        raise NotImplementedError

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self.disks: List[str] = []

    def get_resource_disk_mount_point(self) -> str:
        raise NotImplementedError

    def get_luns(self) -> Dict[str, int]:
        raise NotImplementedError

    # Get boot partition of VM by looking for "/boot" and "/boot/efi"
    def get_os_boot_partition(self) -> Optional[PartitionInfo]:
        partition_info = self._node.tools[Mount].get_partition_info()
        boot_partition: Optional[PartitionInfo] = None
        for partition in partition_info:
            if partition.mount_point.startswith("/boot"):
                boot_partition = partition
                if isinstance(self._node.os, BSD):
                    # Get the device name from the GPT since they are abstracted
                    # Ex. /boot is mounted on /gpt/efiesp
                    # This is the output of gpart show.
                    # Name           Status  Components
                    # gpt/efiesp     N/A     da0p1
                    # gpt/rootfs     N/A     da0p2
                    _get_device_from_gpt_bsd_regex = re.compile(
                        r"\n?" + re.escape(boot_partition.disk) + r"\s*\S*\s*(\S*)"
                    )
                    cmd = "glabel status"
                    output = self._node.execute(cmd).stdout
                    dev = get_matched_str(output, _get_device_from_gpt_bsd_regex)
                    boot_partition.disk = dev
                break
        return boot_partition

    # Get disk controller type from the VM by checking the boot partition
    def get_os_disk_controller_type(self) -> schema.DiskControllerType:
        boot_partition = self.get_os_boot_partition()
        assert boot_partition, "'boot_partition' must not be 'None'"
        if isinstance(self._node.os, BSD):
            if boot_partition.disk.startswith("da"):
                os_disk_controller_type = schema.DiskControllerType.SCSI
            elif boot_partition.disk.startswith("nvd"):
                os_disk_controller_type = schema.DiskControllerType.NVME
            else:
                raise LisaException(f"Unknown OS boot disk type {boot_partition.disk}")
        else:
            if boot_partition.disk.startswith("nvme"):
                os_disk_controller_type = schema.DiskControllerType.NVME
            elif boot_partition.disk.startswith("sd"):
                os_disk_controller_type = schema.DiskControllerType.SCSI
            else:
                raise LisaException(f"Unknown OS boot disk type {boot_partition.disk}")
        return os_disk_controller_type


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
DiskPremiumV2SSDLRS = partial(
    schema.DiskOptionSettings,
    data_disk_type=schema.DiskType.PremiumV2SSDLRS,
)
DiskUltraSSDLRS = partial(
    schema.DiskOptionSettings, data_disk_type=schema.DiskType.UltraSSDLRS
)
