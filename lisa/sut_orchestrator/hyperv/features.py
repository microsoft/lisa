from typing import Any, Dict, List, Optional, Type

from lisa import features, schema
from lisa.node import Node
from lisa.sut_orchestrator.hyperv.context import get_node_context
from lisa.tools.hyperv import HyperV
from lisa.util import LisaException


class HypervFeatureMixin:
    def _initialize_information(self, node: Node) -> None:
        node_context = get_node_context(node)
        self._vm_name = node_context.vm_name
        if not node_context.host:
            raise LisaException("Hyper-V feature requires a remote node as the host.")
        self._hyperv = node_context.host.tools[HyperV]


class Disk(HypervFeatureMixin, features.Disk):
    # /dev/disk/azure/scsi1/lun0
    # /dev/disk/azure/scsi1/lun63
    SCSI_PATTERN = re.compile(r"/dev/disk/azure/scsi[0-9]/lun[0-9][0-9]?$", re.M)

    @classmethod
    def name(cls) -> str:
        return "Disk"

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)

    def _get_scsi_data_disks(self) -> List[str]:
        # This method restuns azure data disks attached to you given VM.
        # refer here to get data disks from folder /dev/disk/azure/scsi1
        # Example: /dev/disk/azure/scsi1/lun0
        # https://docs.microsoft.com/en-us/troubleshoot/azure/virtual-machines/troubleshoot-device-names-problems#identify-disk-luns  # noqa: E501
        ls_tools = self._node.tools[Ls]
        files = ls_tools.list("/dev/disk/azure/scsi1", sudo=True)

        azure_scsi_disks = []
        assert self._node.capability.disk
        assert isinstance(self._node.capability.disk.max_data_disk_count, int)
        azure_scsi_disks = [
            x for x in files if get_matched_str(x, self.SCSI_PATTERN) != ""
        ]
        return azure_scsi_disks

    def add_data_disk(
        self,
        count: int,
        disk_type: schema.DiskType = schema.DiskType.StandardHDDLRS,
        size_in_gb: int = 20,
        lun: int = -1,
    ) -> List[str]:
        disk_names = []
        for i in range(count):
            disk_name = f"data_disk_{i}"
            self._hyperv.create_disk(disk_name, size_in_gb)
            self._hyperv.attach_disk(self._node.name, disk_name)
            disk_names.append(disk_name)
        return disk_names

    def remove_data_disk(self, names: Optional[List[str]] = None) -> None:
        if names is None:
            return
        for disk_name in names:
            self._hyperv.delete_disk(self._node.name, disk_name)

    def get_resource_disk_mount_point(self) -> str:
        raise NotImplementedError("Resource disk is not supported on Hyper-V platform.")

    def get_resource_disks(self) -> List[str]:
        raise NotImplementedError("Resource disk is not supported on Hyper-V platform.")

    def get_resource_disk_type(self) -> schema.ResourceDiskType:
        raise NotImplementedError("Resource disk is not supported on Hyper-V platform.")

    def get_luns(self) -> Dict[str, int]:
        raise NotImplementedError("LUNs are not supported on Hyper-V platform.")

    def get_disk_type(self, disk: str) -> schema.StorageInterfaceType:
        if "nvme" in disk:
            return schema.StorageInterfaceType.NVME
        elif "sd" in disk:
            return schema.StorageInterfaceType.SCSI
        else:
            raise LisaException(f"Unknown disk type {disk}")

    def get_os_disk_controller_type(self) -> schema.DiskControllerType:
        return schema.DiskControllerType.SCSI
