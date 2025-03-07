import re
from typing import Any, Dict, List, Optional, Type
from lisa import features, schema
from lisa.node import Node
from lisa.operating_system import BSD
from lisa.sut_orchestrator.hyperv.context import get_node_context
from lisa.tools import Ls
from lisa.tools.hyperv import HyperV
from lisa.util import LisaException
from assertpy import assert_that

from lisa import Logger, features, schema, search_space
from lisa.environment import Environment
from lisa.feature import Feature
from lisa.features.availability import AvailabilityType
from lisa.features.gpu import ComputeSDK
from lisa.features.hibernation import HibernationSettings
from lisa.features.resize import ResizeAction
from lisa.features.security_profile import (
    FEATURE_NAME_SECURITY_PROFILE,
    SecurityProfileType,
)
from lisa.features.startstop import VMStatus
from lisa.node import Node, RemoteNode
from lisa.operating_system import BSD
from lisa.search_space import RequirementMethod
from lisa.secret import add_secret
from lisa.tools import (
    Cat,
    Curl,
    Dmesg,
    Find,
    IpInfo,
    LisDriver,
    Ls,
    Lsblk,
    Lspci,
    Modprobe,
    Nvmecli,
    Rm,
    Sed,
)
from lisa.tools.echo import Echo
from lisa.tools.kernel_config import KernelConfig
from lisa.tools.lsblk import DiskInfo
from lisa.util import (
    LisaException,
    LisaTimeoutException,
    NotMeetRequirementException,
    SkippedException,
    UnsupportedOperationException,
    check_till_timeout,
    constants,
    field_metadata,
    find_patterns_in_lines,
    generate_random_chars,
    get_matched_str,
    set_filtered_fields,
)


class HypervFeatureMixin:
    def _initialize_information(self, node: Node) -> None:
        node_context = get_node_context(node)
        self._vm_name = node_context.vm_name
        if not node_context.host:
            raise LisaException("Hyper-V feature requires a remote node as the host.")
        self._hyperv = node_context.host.tools[HyperV]


class Disk(HypervFeatureMixin, features.Disk):
    # /sys/block/sda = > sda
    # /sys/block/sdb = > sdb
    DISK_LABEL_PATTERN = re.compile(r"/sys/block/(?P<label>sd\w*)", re.M)

    # =>       40  369098672  da1  GPT  (176G)
    DISK_LABEL_PATTERN_BSD = re.compile(
        r"^=>\s+\d+\s+\d+\s+(?P<label>\w*)\s+\w+\s+\(\w+\)", re.M
    )

    # /dev/disk/by-path/acpi-VMBUS:01-vmbus-4c90db37b55b40c6af19473e1cd96cc6-lun-0
    SCSI_PATTERN = re.compile(r"/dev/disk/by-path/.*VMBUS.*-lun-[0-9][0-9]?$", re.M)
    # /dev/disk/azure/scsi1/lun0
    # SCSI_PATTERN = re.compile(r"/dev/disk/azure/scsi[0-9]/lun[0-9][0-9]?$", re.M)

    @classmethod
    def name(cls) -> str:
        return "Disk"

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)

    def get_all_disks(self) -> List[str]:
        if isinstance(self._node.os, BSD):
            disk_label_pattern = self.DISK_LABEL_PATTERN_BSD
            cmd_result = self._node.execute("gpart show", shell=True, sudo=True)
        else:
            disk_label_pattern = self.DISK_LABEL_PATTERN
            cmd_result = self._node.execute("ls -d /dev/sd*", shell=True, sudo=True)
        matched = find_patterns_in_lines(cmd_result.stdout, [disk_label_pattern])
        assert matched[0], "not found the matched disk label"
        return list(set(matched[0]))

    def _get_os_disk(self) -> str:
        cmd_result = self._node.execute(
            "readlink -f '/dev/disk/cloud/azure_root'", shell=True, sudo=True
        )
        return cmd_result.stdout

    def get_raw_data_disks(self) -> List[str]:
        # get azure scsi attached disks
        scsi_disks = self._get_scsi_data_disks()
        assert_that(len(scsi_disks)).described_as(
            "no data disks info found under /dev/"
        ).is_greater_than(0)
        assert scsi_disks, "not find data disks"
        disk_array = [""] * len(scsi_disks)
        for disk in scsi_disks:
            # readlink -f /dev/disk/azure/scsi1/lun0
            # /dev/sdc
            cmd_result = self._node.execute(
                f"readlink -f {disk}", shell=True, sudo=True
            )
            # /dev/disk/by-path/acpi-VMBUS:01-vmbus-4c90db37b55b40c6af19473e1cd96cc6-lun-2
            disk_array[int(disk.split("-")[-1])] = cmd_result.stdout
        return disk_array

    def _get_scsi_data_disks(self) -> List[str]:
        ls_tools = self._node.tools[Ls]
        # ls -ld /dev/disk/by-path/acpi-VMBUS* - get all scsi disks including os disk
        # lrwxrwxrwx 1 root root  9 Mar  7 08:05 /dev/disk/by-path/acpi-VMBUS:01-vmbus-00000000000088990000000000000000-lun-0 -> ../../sde  # noqa: E501
        # lrwxrwxrwx 1 root root 10 Mar  7 08:05 /dev/disk/by-path/acpi-VMBUS:01-vmbus-00000000000088990000000000000000-lun-0-part1 -> ../../sde1  # noqa: E501
        # lrwxrwxrwx 1 root root 10 Mar  7 08:05 /dev/disk/by-path/acpi-VMBUS:01-vmbus-00000000000088990000000000000000-lun-0-part2 -> ../../sde2  # noqa: E501
        # lrwxrwxrwx 1 root root  9 Mar  7 08:05 /dev/disk/by-path/acpi-VMBUS:01-vmbus-4c90db37b55b40c6af19473e1cd96cc6-lun-0 -> ../../sda  # noqa: E501
        # lrwxrwxrwx 1 root root  9 Mar  7 08:05 /dev/disk/by-path/acpi-VMBUS:01-vmbus-4c90db37b55b40c6af19473e1cd96cc6-lun-1 -> ../../sdb  # noqa: E501
        all_disks = ls_tools.list("/dev/disk/by-path", sudo=True)
        print(all_disks)  # debug
        assert self._node.capability.disk
        if len(all_disks) == 0:
            raise LisaException(
                "Attached SCSI data disks are not found on the VM"
            )

        os_disk = self._get_os_disk()
        scsi_disks = []
        for disk in all_disks:
            cmd_result = self._node.execute(
                f"readlink -f {disk}", shell=True, sudo=True
            )
            if (
                not cmd_result.stdout.startswith(os_disk)
                and get_matched_str(disk, self.SCSI_PATTERN) != ""
            ):
                scsi_disks.append(disk)
        return scsi_disks

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
