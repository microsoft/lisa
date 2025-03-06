from typing import Any, Dict, List, Optional, Type

from lisa import features, schema
from lisa.node import Node
from lisa.sut_orchestrator.hyperv.context import get_node_context
from lisa.util import LisaException


class HypervFeatureMixin:
    def _initialize_information(self, node: Node) -> None:
        node_context = get_node_context(node)
        self._vm_name = node_context.vm_name


class Disk(HypervFeatureMixin, features.Disk):
    @classmethod
    def name(cls) -> str:
        return "Disk"

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)
        node_context = get_node_context(self._node)
        self._hyperv = node_context.hyperv

    def add_data_disk(
        self,
        count: int,
        disk_type: schema.DiskType = schema.DiskType.StandardHDDLRS,
        size_in_gb: int = 20,
        disk_names = []
        for i in range(count):
            disk_name = f"data_disk_{i}"
            self._hyperv.create_data_disk(disk_name, size_in_gb)
            self._hyperv.attach_data_disk(self._node.name, disk_name)
            self._hyperv.attach_disk(self._node.name, disk_name)
            disk_names.append(disk_name)
        return disk_names
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
