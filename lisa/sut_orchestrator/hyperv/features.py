from lisa import schema
from lisa.feature import Feature
from lisa.tools import HyperV, Lsblk
from lisa.util import LisaException
from lisa.util.logger import get_logger
from typing import Type, Any, List, Optional, Dict
from lisa.schema import PartitionInfo
class Disk(Feature):
class Disk(Feature):
    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return schema.DiskOptionSettings

    @classmethod
    def name(cls) -> str:
        return "Disk"

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._log = get_logger("disk")
        self._hyperv = self._node.tools[HyperV]

    def add_data_disk(
        self,
        count: int,
        disk_type: schema.DiskType = schema.DiskType.StandardHDDLRS,
        size_in_gb: int = 20,
        lun: int = -1,
    ) -> List[str]:
        disk_names = []
        for i in range(count):
            self._hyperv.create_data_disk(disk_name, size_in_gb)
            self._hyperv.attach_data_disk(self._node.name, disk_name)
            self._hyperv.attach_disk(self._node.name, disk_name)
            disk_names.append(disk_name)
        return disk_names

    def remove_data_disk(self, names: Optional[List[str]] = None) -> None:
        if names is None:
            names = self.get_data_disks()
            self._hyperv.detach_data_disk(self._node.name, name)
            self._hyperv.delete_data_disk(name)
            self._hyperv.delete_disk(name)

    def get_data_disks(self) -> List[str]:
        disks = self._node.tools[Lsblk].get_disks()
        data_disks = [disk.device_name for disk in disks if not disk.is_os_disk]
        return data_disks

    def get_resource_disk_mount_point(self) -> str:
        raise NotImplementedError("Resource disk is not supported on Hyper-V platform.")

    def get_resource_disks(self) -> List[str]:
        raise NotImplementedError("Resource disk is not supported on Hyper-V platform.")

    def get_resource_disk_type(self) -> schema.ResourceDiskType:
        raise NotImplementedError("Resource disk is not supported on Hyper-V platform.")

    def get_luns(self) -> Dict[str, int]:
        raise NotImplementedError("LUNs are not supported on Hyper-V platform.")

        raise NotImplementedError(
            "OS boot partition is not supported on Hyper-V platform."
        )
        raise NotImplementedError("OS boot partition is not supported on Hyper-V platform.")

    def get_disk_type(self, disk: str) -> schema.StorageInterfaceType:
        if "nvme" in disk:
            return schema.StorageInterfaceType.NVME
        elif "sd" in disk:
            return schema.StorageInterfaceType.SCSI
        else:
            raise LisaException(f"Unknown disk type {disk}")

    def get_os_disk_controller_type(self) -> schema.DiskControllerType:
        return schema.DiskControllerType.SCSI