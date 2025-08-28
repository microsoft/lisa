# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from functools import partial
from typing import Any, Dict, List, Optional, Type, Union

from lisa import schema
from lisa.feature import Feature
from lisa.operating_system import BSD
from lisa.tools import Ls, Mount
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

    def get_partition_with_mount_point(
        self, mount_point: str
    ) -> Union[PartitionInfo, None]:
        partition_info = self._node.tools[Mount].get_partition_info()
        matched_partitions = [
            partition
            for partition in partition_info
            if partition.mount_point == mount_point
        ]

        if matched_partitions:
            partition = matched_partitions[0]
            self._log.debug(f"disk: {partition}, mount_point: {mount_point}")
            return partition
        else:
            return None

    def check_resource_disk_mounted(self) -> bool:
        return False

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
        self._os_disk_controller_type: Optional[schema.DiskControllerType] = None

    def get_resource_disk_mount_point(self) -> str:
        raise NotImplementedError

    def get_resource_disks(self) -> List[str]:
        return []

    def get_resource_disk_type(self) -> schema.ResourceDiskType:
        return schema.ResourceDiskType.SCSI

    def get_luns(self) -> Dict[str, int]:
        raise NotImplementedError

    # Get boot partition of VM by looking for "/boot", "/boot/efi", and "/efi"
    def get_os_boot_partition(self) -> Optional[PartitionInfo]:
        # We need to access /efi and /boot to force systemd to
        # mount the boot partition on some distros.
        self._node.tools[Ls].path_exists("/efi", sudo=True)
        self._node.tools[Ls].path_exists("/boot", sudo=True)

        partition_info = self._node.tools[Mount].get_partition_info()
        boot_partition: Optional[PartitionInfo] = None
        for partition in partition_info:
            if partition.mount_point.startswith(
                "/boot"
            ) or partition.mount_point.startswith("/efi"):
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

    def get_disk_type(self, disk: str) -> schema.StorageInterfaceType:
        if isinstance(self._node.os, BSD):
            # Sample disk names in FreeBSD:
            # /dev/da1p1 -> SCSI
            # /dev/nvd1p1 -> NVME
            if "da" in disk:
                disk_type = schema.StorageInterfaceType.SCSI
            elif ("nvd" in disk) or ("nvme" in disk):
                disk_type = schema.StorageInterfaceType.NVME
            else:
                raise LisaException(f"Unknown disk type {disk}")
        else:
            # Sample disk names in Linux:
            # /dev/sda1 -> SCSI
            # /dev/nvme0n1p1 -> NVME
            if "nvme" in disk:
                disk_type = schema.StorageInterfaceType.NVME
            elif "sd" in disk:
                disk_type = schema.StorageInterfaceType.SCSI
            else:
                raise LisaException(f"Unknown disk type {disk}")
        return disk_type

    # Get disk controller type from the VM by checking the boot partition
    def get_os_disk_controller_type(self) -> schema.DiskControllerType:
        if self._os_disk_controller_type is None:
            boot_partition = self.get_os_boot_partition()
            assert boot_partition, "'boot_partition' must not be 'None'"
            self._os_disk_controller_type = schema.DiskControllerType(
                self.get_disk_type(boot_partition.disk)
            )
        return self._os_disk_controller_type


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
