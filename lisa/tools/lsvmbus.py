import re
from typing import Any, List, cast

from lisa.executable import Tool
from lisa.operating_system import Debian, Linux, Redhat, Suse, Ubuntu
from lisa.util import LisaException

from .wget import Wget

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
PATTERN_VMBUSES = re.compile(r"(VMBUS ID[\w\W]*?)(?=VMBUS ID|\Z)", re.MULTILINE)


class ChannelVPMap:
    def __init__(self, rel_id: str, cpu: str) -> None:
        self.rel_id = rel_id
        self.target_cpu = cpu


class VmBus:
    # VMBUS ID  1: Class_ID = {525074dc-8985-46e2-8057-a307dc18a502}
    # - [Dynamic Memory]
    __pattern_vmbus = re.compile(
        r"^VMBUS ID\s+(?P<index>\d+): Class_ID = {?(?P<class_id>.+?)}?"
        r" - \[?(?P<name>.+?)\]?\r$",
        re.MULTILINE,
    )
    # Device_ID = {00000000-0000-8899-0000-000000000000}
    __pattern_device = re.compile(
        r"([\w\W]*?)Device_ID = {?(?P<device_id>.+?)}?\r$", re.MULTILINE
    )
    # Rel_ID=12, target_cpu=2
    # Rel_ID=15, target_cpu=1
    # Rel_ID=16, target_cpu=2
    # Rel_ID=17, target_cpu=3
    __pattern_channels = re.compile(r"(Rel_ID[\w\W]*?)(?=Rel_ID|\Z)", re.MULTILINE)

    __pattern_channel = re.compile(
        r"([\w\W]*?)(Rel_ID=(?P<rel_id>\d+), target_cpu=(?P<cpu>\d+))", re.MULTILINE
    )

    def __init__(self, vmbus_raw: str) -> None:
        self.parse(vmbus_raw)

    def parse(self, raw_str: str) -> Any:
        matched_vmbus = self.__pattern_vmbus.match(raw_str)
        matched_device = self.__pattern_device.match(raw_str)
        channel_vp_map_list: List[ChannelVPMap] = []
        raw_channels = re.finditer(self.__pattern_channels, raw_str)
        for channel in raw_channels:
            matched_channel = self.__pattern_channel.match(channel.group())
            if matched_channel:
                channel_vp_map = ChannelVPMap(
                    matched_channel.group("rel_id"), matched_channel.group("cpu")
                )
            else:
                raise LisaException("cannot find matched channel")
            channel_vp_map_list.append(channel_vp_map)
        if matched_vmbus:
            self.id = matched_vmbus.group("index")
            self.vmbus_name = matched_vmbus.group("name")
            self.class_id = matched_vmbus.group("class_id")
        else:
            raise LisaException("cannot find matched vm bus")
        if matched_device:
            self.device_id = matched_device.group("device_id")
        else:
            raise LisaException("cannot find matched device id")
        self.channel_vp_map = channel_vp_map_list


class Lsvmbus(Tool):
    _lsvmbus_repo = (
        "https://raw.githubusercontent.com/torvalds/linux/master/tools/hv/lsvmbus"
    )

    @property
    def command(self) -> str:
        return self._command

    @property
    def can_install(self) -> bool:
        return True

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._command = "lsvmbus"
        self._vmbuses: List[VmBus] = []

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
        return _exists

    def install(self) -> bool:
        linux_os: Linux = cast(Linux, self.node.os)
        package_name = ""
        if isinstance(linux_os, Redhat):
            package_name = "hyperv-tools"
        elif isinstance(linux_os, Suse):
            package_name = "hyper-v"
        elif isinstance(linux_os, Ubuntu) and not isinstance(linux_os, Debian):
            package_name = "linux-cloud-tools-common"
        if package_name:
            linux_os.install_packages(package_name)
        else:
            wget_tool = self.node.tools[Wget]
            file_path = wget_tool.get(self._lsvmbus_repo, "$HOME/.local/bin")
            # make the download file executable
            self.node.execute(f"chmod +x {file_path}")
            self._command = file_path
        return self._check_exists()

    def get_vmbuses(self, force_run: bool = False) -> List[VmBus]:
        cached_result = None
        if (not self._vmbuses) or force_run:
            cached_result = self.run("-vv", shell=True)
            if cached_result.exit_code != 0 and (not self._command.startswith("sudo")):
                self._command = f"sudo {self._command}"
                cached_result = self.run("-vv", shell=True)
                if cached_result.exit_code != 0:
                    raise LisaException(
                        f"get unexpected non-zero exit code {cached_result.exit_code} "
                        f"when run {self.command} -vv."
                    )
            raw_list = re.finditer(PATTERN_VMBUSES, cached_result.stdout)
            for vmbus_raw in raw_list:
                vmbus = VmBus(vmbus_raw.group())
                self._vmbuses.append(vmbus)

        return self._vmbuses
