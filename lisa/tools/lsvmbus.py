import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Set, Type

from lisa.base_tools.wget import Wget
from lisa.executable import Tool
from lisa.operating_system import Redhat, Suse, Ubuntu
from lisa.tools import Dmesg
from lisa.util import LisaException, find_groups_in_lines

from .ln import Ln
from .python import Python

# segment output of lsvmbus -vv
# VMBUS ID  1: Class_ID = {525074dc-8985-46e2-8057-a307dc18a502}
# - [Dynamic Memory]
# \r\n\t
# Device_ID = {1eccfd72-4b41-45ef-b73a-4a6e44c12924}
# \r\n\t
# Sysfs path: /sys/bus/vmbus/devices/1eccfd72-4b41-45ef-b73a-4a6e44c12924
# \r\n\t
# Rel_ID=1, target_cpu=0
# \r\n\r\n
# VMBUS ID  2: Class_ID = {32412632-86cb-44a2-9b5c-50d1417354f5}
# - Synthetic IDE Controller\r\n\t
# Device_ID = {00000000-0000-8899-0000-000000000000}
# \r\n\t
# Sysfs path: /sys/bus/vmbus/devices/00000000-0000-8899-0000-000000000000
# \r\n\t
# Rel_ID=2, target_cpu=0
# \r\n\r\n
PATTERN_VMBUS_DEVICE = re.compile(r"(VMBUS ID[\w\W]*?)(?=VMBUS ID|\Z)", re.MULTILINE)


class ChannelVPMap:
    def __init__(self, vmbus_id: str, rel_id: str, cpu: str) -> None:
        self.vmbus_id = vmbus_id
        self.rel_id = rel_id
        self.target_cpu = cpu

    def __str__(self) -> str:
        return "(vmbus_id: {0}, rel_id: {1}, target_cpu: {2})".format(
            self.vmbus_id, self.rel_id, self.target_cpu
        )

    def __repr__(self) -> str:
        return self.__str__()


@dataclass
class VmBusDevice:
    name: str = ""
    device_id: str = ""
    class_id: str = ""
    channel_vp_map: List[ChannelVPMap] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"(name: {self.name}, device_id: {self.device_id},"
            f" class_id: {self.class_id},"
            f" channel_vp_map: {self.channel_vp_map})"
        )

    def __repr__(self) -> str:
        return self.__str__()

    def __hash__(self) -> int:
        return hash((self.name, self.device_id))


class LinuxVmBusDeviceParser(VmBusDevice):
    # VMBUS ID  1: Class_ID = {525074dc-8985-46e2-8057-a307dc18a502}
    # - [Dynamic Memory]
    __pattern_vmbus_device_info = re.compile(
        r"^VMBUS ID\s+(?P<index>\d+): Class_ID = {?(?P<class_id>.+?)}?"
        r" - \[?(?P<name>.+?)\]?\r$",
        re.MULTILINE,
    )
    # Device_ID = {00000000-0000-8899-0000-000000000000}
    __pattern_device_info = re.compile(
        r"([\w\W]*?)Device_ID = {?(?P<device_id>.+?)}?\r$", re.MULTILINE
    )
    # Rel_ID=12, target_cpu=2
    # Rel_ID=15, target_cpu=1
    # Rel_ID=16, target_cpu=2
    # Rel_ID=17, target_cpu=3
    __pattern_channels_info = re.compile(r"(Rel_ID[\w\W]*?)(?=Rel_ID|\Z)", re.MULTILINE)

    __pattern_channel_info = re.compile(
        r"([\w\W]*?)(Rel_ID=(?P<rel_id>\d+), target_cpu=(?P<cpu>\d+))", re.MULTILINE
    )

    def __init__(self, vmbus_device_raw: str) -> None:
        self.parse(vmbus_device_raw)

    def parse(self, raw_str: str) -> Any:
        matched_vmbus_device_info = self.__pattern_vmbus_device_info.match(raw_str)
        matched_device_info = self.__pattern_device_info.match(raw_str)
        if matched_vmbus_device_info:
            self.id = matched_vmbus_device_info.group("index")
            self.name = matched_vmbus_device_info.group("name")
            self.class_id = matched_vmbus_device_info.group("class_id")
        else:
            raise LisaException("cannot find matched vmbus device")
        if matched_device_info:
            self.device_id = matched_device_info.group("device_id")
        else:
            raise LisaException("cannot find matched device id")
        channel_vp_map_list: List[ChannelVPMap] = []
        raw_channels_info = re.finditer(self.__pattern_channels_info, raw_str)
        for channel in raw_channels_info:
            matched_channel = self.__pattern_channel_info.match(channel.group())
            if matched_channel:
                channel_vp_map = ChannelVPMap(
                    self.id,
                    matched_channel.group("rel_id"),
                    matched_channel.group("cpu"),
                )
            else:
                raise LisaException("cannot find matched channel")
            channel_vp_map_list.append(channel_vp_map)

        self.channel_vp_map = channel_vp_map_list

    def __str__(self) -> str:
        return (
            f"id : {self.id}, name : {self.name}, class id : {self.class_id}, "
            f"device id : {self.device_id}, channel map : {self.channel_vp_map}"
        )

    def __repr__(self) -> str:
        return self.__str__()


class Lsvmbus(Tool):
    __pattern_not_found = re.compile(r"(.*WARNING: lsvmbus not found for kernel*)")

    _lsvmbus_repo = (
        "https://raw.githubusercontent.com/torvalds/linux/master/tools/hv/lsvmbus"
    )

    @property
    def command(self) -> str:
        return self._command

    @classmethod
    def _freebsd_tool(cls) -> Optional[Type[Tool]]:
        return LsvmbusFreeBSD

    @property
    def can_install(self) -> bool:
        return True

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._command = "lsvmbus"
        self._vmbus_devices: List[VmBusDevice] = []
        cmd_result = self.node.execute("which python", sudo=True)
        if 0 != cmd_result.exit_code:
            ln = self.node.tools[Ln]
            self.node.tools.get(Python)
            ln.create_link("/bin/python3", "/usr/bin/python")

    def _check_exists(self) -> bool:
        _exists = super()._check_exists()

        if not _exists:
            previous_command = self._command
            self._command = "$HOME/.local/bin/lsvmbus"
            _exists = super()._check_exists()
            if not _exists:
                self._command = previous_command
            self._command = "/usr/sbin/lsvmbus"
            _exists = super()._check_exists()
            if not _exists:
                self._command = previous_command

        if _exists and isinstance(self.node.os, Ubuntu):
            # fix for issue happen on Canonical UbuntuServer 16.04-LTS 16.04.201703020
            # lsvmbus exists by default, but it doesn't give expected results, still
            # download lsvmbus src
            # WARNING: lsvmbus not found for kernel 4.4.0-65
            #   You may need to install the following packages for this specific kernel:
            #     linux-tools-4.4.0-65-generic
            #     linux-cloud-tools-4.4.0-65-generic
            #   You may also want to install one of the following packages to keep up to
            # date:
            #     linux-tools-generic
            #     linux-cloud-tools-generic
            cmd_result = self.run(shell=True)
            if self.__pattern_not_found.match(cmd_result.stdout):
                _exists = False

        return _exists

    def _install_from_src(self) -> None:
        wget_tool = self.node.tools[Wget]
        file_path = wget_tool.get(
            self._lsvmbus_repo, "$HOME/.local/bin", executable=True
        )
        self._command = file_path

    def install(self) -> bool:
        package_name = ""
        if isinstance(self.node.os, Redhat):
            package_name = "hyperv-tools"
            self.node.os.install_packages(package_name)
        elif isinstance(self.node.os, Suse):
            package_name = "hyper-v"
            self.node.os.install_packages(package_name)
        elif isinstance(self.node.os, Ubuntu):
            package_name = "linux-cloud-tools-common"
            self.node.os.install_packages(package_name)
            cmd_result = self.run(shell=True)
            # this is to handle lsvmbus exist by default, but broken in
            # Canonical UbuntuServer 16.04-LTS 16.04.201703020
            # refer to similar logic in _check_exists above
            if self.__pattern_not_found.match(cmd_result.stdout):
                self._install_from_src()

        if not self._check_exists():
            if package_name:
                self._log.info(
                    f"failed to install lsvmbus by package '{package_name}',"
                    f" trying to install by downloading src."
                )
            self._install_from_src()

        return self._check_exists()

    def get_device_channels(self, force_run: bool = False) -> List[VmBusDevice]:
        if (not self._vmbus_devices) or force_run:
            self._vmbus_devices = []
            result = self.run("-vv", force_run=force_run, shell=True)
            if result.exit_code != 0:
                result = self.run(
                    "-vv",
                    force_run=force_run,
                    shell=True,
                    sudo=True,
                    expected_exit_code=0,
                )
            raw_list = re.finditer(PATTERN_VMBUS_DEVICE, result.stdout)
            for vmbus_raw in raw_list:
                vmbus_device = LinuxVmBusDeviceParser(vmbus_raw.group())
                self._vmbus_devices.append(vmbus_device)

        return self._vmbus_devices


class LsvmbusFreeBSD(Lsvmbus):
    # pcib2: <Hyper-V PCI Express Pass Through> on vmbus0
    # FORMAT: <device>: <description> on <vmbus><vmbus_id>
    _DEVICE_REGEX = re.compile(
        r"^(?P<device>\w+): <(?P<description>.*)> on vmbus(?P<vmbus_id>\d+)$"
    )

    @property
    def command(self) -> str:
        return ""

    def _check_exists(self) -> bool:
        return True

    @property
    def can_install(self) -> bool:
        return False

    def get_device_channels(self, force_run: bool = False) -> List[VmBusDevice]:
        output = self.node.tools[Dmesg].run(sudo=force_run).stdout
        groups = find_groups_in_lines(output, self._DEVICE_REGEX, True)
        devices: Set[VmBusDevice] = set()
        for group in groups:
            device = VmBusDevice(name=group["description"], device_id=group["device"])
            devices.add(device)

        return list(devices)
