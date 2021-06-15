import re
from pathlib import PurePath
from typing import Any, Dict, List, cast

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.util import LisaException

from .find import Find


class DeviceChannel:
    # ethtool device channel info is in format -
    # ~$ ethtool -l eth0
    #   Channel parameters for eth0:
    #   Pre-set maximums:
    #   RX:             0
    #   TX:             0
    #   Other:          0
    #   Combined:       1
    #   Current hardware settings:
    #   RX:             0
    #   TX:             0
    #   Other:          0
    #   Combined:       1
    __max_settings_pattern = re.compile(
        r"Pre-set maximums:(\s+)(?P<settings>.*?)Current hardware settings:",
        re.DOTALL,
    )
    __current_settings_pattern = re.compile(
        r"Current hardware settings:(\s+)(?P<settings>.*?)$", re.DOTALL
    )
    __channel_count_param_pattern = re.compile(
        r"(?P<param>Combined):( +)(?P<value>.*)$", re.MULTILINE
    )

    def __init__(self, interface: str, device_channel_raw: str) -> None:
        self._parse_channel_info(interface, device_channel_raw)

    def _parse_channel_info(self, interface: str, raw_str: str) -> None:
        current_settings = self.__current_settings_pattern.match(raw_str)
        max_settings = self.__max_settings_pattern.match(raw_str)
        if (not current_settings) or (not max_settings):
            raise LisaException(
                "Cannot get device channel current and/or max settings information"
            )

        current_param = self.__channel_count_param_pattern.match(
            current_settings.group("settings")
        )
        max_param = self.__channel_count_param_pattern.match(
            max_settings.group("settings")
        )
        if (not current_param) or (not max_param):
            raise LisaException("Cannot get device channel current and/or max count")

        self.device_name = interface
        self.current_channels = int(current_param.group("value"))
        self.max_channels = int(max_param.group("value"))


class DeviceFeatures:
    # ethtool device feature info is in format -
    # ~$ ethtool -k eth0
    #       Features for eth0:
    #       rx-checksumming: on
    #       tx-checksumming: on
    #           tx-checksum-ipv4: on
    #           tx-checksum-ip-generic: off [fixed]
    #           tx-checksum-ipv6: on
    #           tx-checksum-fcoe-crc: off [fixed]
    #           tx-checksum-sctp: off [fixed]
    #         scatter-gather: on
    __feature_info_pattern = re.compile(
        r"Features for (?P<interface>[\w]*):[\s]*(?P<value>.*?)$", re.DOTALL
    )
    __feature_settings_pattern = re.compile(
        r"^[\s]*(?P<name>.*):(?P<value>.*?)?$", re.MULTILINE
    )

    def __init__(self, device: str, device_feature_raw: str) -> None:
        self._parse_feature_info(device, device_feature_raw)

    def _parse_feature_info(self, device: str, raw_str: str) -> None:
        matched_features_info = self.__feature_info_pattern.match(raw_str)
        if not matched_features_info:
            raise LisaException("Cannot get device's features settings info")

        self.device_name = device
        self.enabled_features = []
        for row in matched_features_info.group("value").splitlines():
            feature_info = self.__feature_settings_pattern.match(row)
            if not feature_info:
                raise LisaException(
                    "Could not get feature setting in the defined pattern."
                )
            if "on" in feature_info.group("value"):
                self.enabled_features.append(feature_info.group("name"))


class Ethtool(Tool):
    @property
    def command(self) -> str:
        return "ethtool"

    @property
    def can_install(self) -> bool:
        return True

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._command = "ethtool"
        self._device_list: List[str] = []
        self._device_channel_map: Dict[str, DeviceChannel] = {}
        self._device_features_map: Dict[str, DeviceFeatures] = {}

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("ethtool")
        return self._check_exists()

    def _get_device_list(self) -> None:
        if self._device_list:
            return

        find_tool = self.node.tools[Find]
        netdirs = find_tool.find_files(
            PurePath("/sys/devices"),
            name_pattern="net",
            path_pattern="*vmbus*",
            ignore_case=True,
        )
        for netdir in netdirs:
            if not netdir:
                continue
            cmd_result = self.node.execute(f"ls {netdir}")
            if cmd_result.exit_code != 0:
                raise LisaException(
                    "Could not find the network device under path {netdir}"
                    f" exit_code: {cmd_result.exit_code}"
                    f" stderr: {cmd_result.stderr}"
                )
            self._device_list.append(cmd_result.stdout)

        if not self._device_list:
            raise LisaException("Did not find any synthetic network interface.")

    def get_device_channels_info(
        self,
        interface: str,
    ) -> DeviceChannel:
        if interface in self._device_channel_map.keys():
            return self._device_channel_map[interface]

        result = self.run(f"-l {interface}")
        if result.exit_code != 0:
            raise LisaException(
                f"ethtool -l {interface} command got non-zero"
                f" exit_code: {result.exit_code}"
                f" stderr: {result.stderr}"
            )
        device_channel_info = DeviceChannel(interface, result.stdout)
        self._device_channel_map[interface] = device_channel_info
        return device_channel_info

    def get_device_enabled_features(self, interface: str) -> DeviceFeatures:
        if interface in self._device_features_map.keys():
            return self._device_features_map[interface]

        result = self.run(f"-k {interface}")
        if result.exit_code != 0:
            raise LisaException(
                f"ethtool -k {interface} command got non-zero"
                f" exit_code: {result.exit_code}"
                f" stderr: {result.stderr}"
            )
        device_feature = DeviceFeatures(interface, result.stdout)
        self._device_features_map[interface] = device_feature

        return device_feature

    def get_all_device_channels_info(self) -> List[DeviceChannel]:
        devices_channel_list = []
        self._get_device_list()
        for device in self._device_list:
            devices_channel_list.append(self.get_device_channels_info(device))

        return devices_channel_list

    def get_all_device_enabled_features(self) -> List[DeviceFeatures]:
        devices_features_list = []
        self._get_device_list()
        for device in self._device_list:
            devices_features_list.append(self.get_device_enabled_features(device))

        return devices_features_list
