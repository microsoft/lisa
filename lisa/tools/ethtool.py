import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Type, cast

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.util import (
    LisaException,
    UnsupportedOperationException,
    find_group_in_lines,
    find_groups_in_lines,
)

from .find import Find
from .ip import Ip
from .lscpu import Lscpu

# Few ethtool device settings follow similar pattern like -
#   ethtool device channel info from "ethtool -l eth0"
#   ethtool ring buffer setting info from "ethtool -g eth0"
# ~$ ethtool -g eth0
#   Ring parameters for eth0:
#   Pre-set maximums:
#   RX:             18811
#   RX Mini:        0
#   RX Jumbo:       0
#   TX:             2560
#   Current hardware settings:
#   RX:             9709
#   RX Mini:        0
#   RX Jumbo:       0
#   TX:             170
_max_settings_pattern = re.compile(
    r"Pre-set maximums:[\s+](?P<settings>.*?)Current hardware settings:",
    re.DOTALL,
)
_current_settings_pattern = re.compile(
    r"Current hardware settings:[\s+](?P<settings>.*?)$", re.DOTALL
)

# Some device settings are retrieved like below -
#
# ~$ ethtool eth0
#       Settings for eth0:
#           Supported ports: [ ]
#           Supported link modes:   Not reported
#           Speed: 50000Mb/s
#           Duplex: Full
#           Port: Other
#           PHYAD: 0
#           Transceiver: internal
#           Auto-negotiation: off
# Cannot get wake-on-lan settings: Operation not permitted
#           Current message level: 0x000000f7 (247)
#                                  drv probe link ifdown ifup rx_err tx_err
#           Link detected: yes

_settings_info_pattern = re.compile(
    r"Settings for (?P<interface>[\w]*):[\s]*(?P<value>.*?)$", re.DOTALL
)
_link_settings_pattern = re.compile(
    r"^[ \t]*(?P<name>.*):[ \t]*(?P<value>.*?)?$", re.MULTILINE
)
# Current message level: 0x000000f7 (247)
_msg_level_number_pattern = re.compile(
    r"Current message level:[\s]*(?P<value>\w*).*?$", re.MULTILINE
)
# Current message level: 0x000000f7 (247)
#                        drv probe link ifdown ifup rx_err tx_err
_msg_level_name_pattern = re.compile(
    r"Current message level:.*\n[\s]*(?P<value>.*?)?$", re.MULTILINE
)


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
    _channel_count_param_pattern = re.compile(
        r"(?P<param>Combined):[ \t]*(?P<value>.*)$", re.MULTILINE
    )

    def __init__(self, interface: str, device_channel_raw: str) -> None:
        self._parse_channel_info(interface, device_channel_raw)

    def _parse_channel_info(self, interface: str, raw_str: str) -> None:
        current_settings = _current_settings_pattern.search(raw_str)
        max_settings = _max_settings_pattern.search(raw_str)
        if (not current_settings) or (not max_settings):
            raise LisaException(
                f"Cannot get {interface} device channel current and/or"
                " max settings information"
            )

        current_param = self._channel_count_param_pattern.search(
            current_settings.group("settings")
        )
        max_param = self._channel_count_param_pattern.search(
            max_settings.group("settings")
        )
        if (not current_param) or (not max_param):
            raise LisaException(
                f"Cannot get {interface} channel current and/or max count"
            )

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
    _feature_info_pattern = re.compile(
        r"Features for (?P<interface>[\w]*):[\s]*(?P<value>.*?)$", re.DOTALL
    )
    _feature_settings_pattern = re.compile(
        r"^[\s]*(?P<name>.*):(?P<value>.*?)?$", re.MULTILINE
    )

    def __init__(self, interface: str, enabled_features: List[str]) -> None:
        self.device_name = interface
        self.enabled_features = enabled_features


class DeviceLinkSettings:
    def __init__(
        self,
        interface: str,
        device_settings_raw: Optional[str] = None,
        link_settings: Optional[Dict[str, str]] = None,
    ) -> None:
        self.device_name = interface
        if device_settings_raw:
            self._parse_link_settings_info(interface, device_settings_raw)
        if link_settings:
            self.link_settings = link_settings

    def _parse_link_settings_info(self, interface: str, raw_str: str) -> None:
        matched_link_settings_info = _settings_info_pattern.search(raw_str)
        if not matched_link_settings_info:
            raise LisaException(f"Cannot get {interface} link settings info")

        self.link_settings = {}

        for row in matched_link_settings_info.group("value").splitlines():
            link_setting_info = _link_settings_pattern.match(row)
            if not link_setting_info:
                continue
            self.link_settings[
                link_setting_info.group("name")
            ] = link_setting_info.group("value")

        if not self.link_settings:
            raise LisaException(
                f"Could not get any link settings for device {interface}"
                " in the defined pattern"
            )

        # capture the message level settings as well for efficiency
        msg_level_number_pattern = _msg_level_number_pattern.search(raw_str)
        msg_level_name_pattern = _msg_level_name_pattern.search(raw_str)
        if msg_level_number_pattern and msg_level_name_pattern:
            self.msg_level_number = msg_level_number_pattern.group("value")
            self.msg_level_name = msg_level_name_pattern.group("value")


class DeviceMessageLevel:
    def __init__(
        self,
        interface: str,
        device_settings_raw: Optional[str] = None,
        msg_level_number: Optional[str] = None,
        msg_level_name: Optional[str] = None,
    ) -> None:
        self.device_name = interface
        if device_settings_raw:
            self._parse_msg_level_info(interface, device_settings_raw)
        if msg_level_number:
            self.msg_level_number = msg_level_number
        if msg_level_name:
            self.msg_level_name = msg_level_name

    def _parse_msg_level_info(self, interface: str, raw_str: str) -> None:
        matched_settings_info = _settings_info_pattern.search(raw_str)
        if not matched_settings_info:
            raise LisaException(f"Cannot get {interface} settings info")

        msg_level_number_pattern = _msg_level_number_pattern.search(raw_str)
        msg_level_name_pattern = _msg_level_name_pattern.search(raw_str)
        if (not msg_level_number_pattern) or (not msg_level_name_pattern):
            raise LisaException(
                f"Cannot get {interface} device message level information."
            )

        self.msg_level_number = msg_level_number_pattern.group("value")
        self.msg_level_name = msg_level_name_pattern.group("value")

        # capture the link settings as well for efficiency
        self.link_settings: Dict[str, str] = {}
        for row in matched_settings_info.group("value").splitlines():
            link_setting_info = _link_settings_pattern.match(row)
            if not link_setting_info:
                continue
            self.link_settings[
                link_setting_info.group("name")
            ] = link_setting_info.group("value")


class DeviceRingBufferSettings:
    # ~$ ethtool -g eth0
    #   Ring parameters for eth0:
    #   Pre-set maximums:
    #   RX:             18811
    #   RX Mini:        0
    #   RX Jumbo:       0
    #   TX:             2560
    _ring_buffer_settings_pattern = re.compile(
        r"(?P<param>.*):[ \t]*(?P<value>.*)$", re.MULTILINE
    )

    def __init__(self, interface: str, device_ring_buffer_settings_raw: str) -> None:
        self._parse_ring_buffer_settings_info(
            interface, device_ring_buffer_settings_raw
        )

    def _parse_ring_buffer_settings_info(self, interface: str, raw_str: str) -> None:
        current_settings_info = _current_settings_pattern.search(raw_str)
        max_settings_info = _max_settings_pattern.search(raw_str)
        if (not current_settings_info) or (not max_settings_info):
            raise LisaException(
                f"Cannot get {interface} device ring buffer current and/or"
                " max settings information"
            )

        self.device_name = interface
        self.current_ring_buffer_settings: Dict[str, str] = {}
        self.max_ring_buffer_settings: Dict[str, str] = {}
        for row in current_settings_info.group("settings").splitlines():
            current_setting = self._ring_buffer_settings_pattern.match(row)
            if not current_setting:
                continue
            self.current_ring_buffer_settings[
                current_setting.group("param")
            ] = current_setting.group("value")

        if not self.current_ring_buffer_settings:
            raise LisaException(
                f"Could not get current ring buffer settings for device {interface}"
                " in the defined pattern"
            )

        for row in max_settings_info.group("settings").splitlines():
            max_setting = self._ring_buffer_settings_pattern.match(row)
            if not max_setting:
                continue
            self.max_ring_buffer_settings[
                max_setting.group("param")
            ] = max_setting.group("value")

        if not self.max_ring_buffer_settings:
            raise LisaException(
                f"Could not get max ring buffer settings for device {interface}"
                " in the defined pattern"
            )


class DeviceGroLroSettings:
    # ethtool device feature info is in format -
    # ~$ ethtool -k eth0
    #       Features for eth0:
    #       generic-receive-offload: on
    #       large-receive-offload: off [fixed]

    _gro_settings_pattern = re.compile(
        r"^generic-receive-offload:[\s+](?P<value>.*?)?$", re.MULTILINE
    )
    _lro_settings_pattern = re.compile(
        r"^large-receive-offload:[\s+](?P<value>.*?)?$", re.MULTILINE
    )

    def __init__(self, interface: str, device_gro_lro_settings_raw: str) -> None:
        self._parse_gro_lro_settings_info(interface, device_gro_lro_settings_raw)

    def _parse_gro_lro_settings_info(self, interface: str, raw_str: str) -> None:
        gro_setting_pattern = self._gro_settings_pattern.search(raw_str)
        lro_setting_pattern = self._lro_settings_pattern.search(raw_str)
        if (not gro_setting_pattern) or (not lro_setting_pattern):
            raise LisaException(
                f"Cannot get {interface} device gro and/or lro settings information"
            )

        self.interface = interface

        self.gro_setting = True if "on" in gro_setting_pattern.group("value") else False
        self.gro_fixed = (
            True if "[fixed]" in gro_setting_pattern.group("value") else False
        )

        self.lro_setting = True if "on" in lro_setting_pattern.group("value") else False
        self.lro_fixed = (
            True if "[fixed]" in lro_setting_pattern.group("value") else False
        )


class DeviceSgSettings:
    # ethtool device feature info is in format -
    # ~$ ethtool -k eth0
    #       Features for eth0:
    #       scatter-gather: on
    #               tx-scatter-gather: on
    #               tx-scatter-gather-fraglist: off [fixed]

    _sg_settings_pattern = re.compile(
        r"([\w\W]*?)tx-scatter-gather:[\s+](?P<value>.*?)?$", re.MULTILINE
    )

    def __init__(self, interface: str, device_gro_lro_settings_raw: str) -> None:
        self._parse_sg_settings_info(interface, device_gro_lro_settings_raw)

    def _parse_sg_settings_info(self, interface: str, raw_str: str) -> None:
        sg_setting_pattern = self._sg_settings_pattern.search(raw_str)
        if not sg_setting_pattern:
            raise LisaException(
                f"Cannot get {interface} device sg settings information"
            )

        self.interface = interface

        self.sg_setting = True if "on" in sg_setting_pattern.group("value") else False
        self.sg_fixed = (
            True if "[fixed]" in sg_setting_pattern.group("value") else False
        )


class DeviceRssHashKey:
    # ethtool device rss hash key info is in format:
    # ethtool -x eth0
    #   RX flow hash indirection table for eth0 with 4 RX ring(s):
    #   0:      0     1     2     3     0     1     2     3
    #   8:      0     1     2     3     0     1     2     3
    #   16:     0     1     2     3     0     1     2     3
    #   24:     0     1     2     3     0     1     2     3
    #   32:     0     1     2     3     0     1     2     3
    #   40:     0     1     2     3     0     1     2     3
    #   48:     0     1     2     3     0     1     2     3
    #   56:     0     1     2     3     0     1     2     3
    #   64:     0     1     2     3     0     1     2     3
    #   72:     0     1     2     3     0     1     2     3
    #   80:     0     1     2     3     0     1     2     3
    #   88:     0     1     2     3     0     1     2     3
    #   96:     0     1     2     3     0     1     2     3
    #   104:    0     1     2     3     0     1     2     3
    #   112:    0     1     2     3     0     1     2     3
    #   120:    0     1     2     3     0     1     2     3
    #   RSS hash key:
    #   6d:5a:56:da:25:5b:0e:c2:41:67:25:3d:43:a3:8f:b0:d0:ca:2b:cb:ae:7b:30:b4:77:cb:2d:a3:80:30:f2:0c:6a:42:b7:3b:be:ac:01:fa

    _rss_hash_key_pattern = re.compile(
        r"^RSS hash key:\s+(?P<value>[0-9a-f:]+)", re.MULTILINE
    )

    def __init__(self, interface: str, device_rss_hash_info_raw: str) -> None:
        self._parse_rss_hash_key(interface, device_rss_hash_info_raw)

    def _parse_rss_hash_key(self, interface: str, raw_str: str) -> None:
        hash_key_pattern = self._rss_hash_key_pattern.search(raw_str)
        if not hash_key_pattern:
            raise LisaException(
                f"Cannot get {interface} device rss hash key information"
            )

        self.interface = interface
        self.rss_hash_key = hash_key_pattern.group("value")


class DeviceRxHashLevel:
    # ethtool device rx hash level is in the below format
    # ethtool -n eth0 rx-flow-hash tcp4
    #   TCP over IPV4 flows use these fields for computing Hash flow key:
    #   IP SA
    #   IP DA
    #   L4 bytes 0 & 1 [TCP/UDP src port]
    #   L4 bytes 2 & 3 [TCP/UDP dst port]

    _rx_hash_level_pattern = re.compile(
        r".*Hash flow key:[\s+](?P<value>.*?)?$", re.DOTALL
    )
    _tcp_udp_rx_hash_level_enable_pattern = re.compile(
        r".*TCP/UDP src port.*\s+.*TCP/UDP dst port.*$", re.MULTILINE
    )

    def __init__(self, interface: str, protocol: str, raw_str: str) -> None:
        self.interface = interface
        self.protocol_hash_map: Dict[str, bool] = {}
        self._parse_rx_hash_level(interface, protocol, raw_str)

    def _parse_rx_hash_level(self, interface: str, protocol: str, raw_str: str) -> None:
        hash_level_pattern = self._rx_hash_level_pattern.search(raw_str)
        if not hash_level_pattern:
            raise LisaException(
                f"Cannot get {interface} rx hash level information for {protocol}"
            )

        self.protocol_hash_map[protocol] = (
            True
            if self._tcp_udp_rx_hash_level_enable_pattern.search(raw_str)
            else False
        )


class DeviceStatistics:
    # NIC statistics:
    #     tx_scattered: 0
    #     tx_no_memory: 0
    _statistics_pattern = re.compile(r"^\s+(?P<name>.*?)\: +?(?P<value>\d*?)\r?$")
    # FreeBSD NIC statistics:
    # dev.hn.0.tx.0.packets: 0
    # dev.hn.0.rx.0.packets: 0
    # dev.mce.0.txstat0tc0.packets: 0
    # dev.mce.0.rxstat0.packets: 0
    _bsd_statistics_pattern = re.compile(
        r"^dev\.\w+\.\d+.(?P<name>.*?)\: +?(?P<value>\d+?)\r?$"
    )

    def __init__(
        self, interface: str, device_statistics_raw: str, bsd: bool = False
    ) -> None:
        self._parse_statistics_info(interface, device_statistics_raw, bsd)

    def _parse_statistics_info(self, interface: str, raw_str: str, bsd: bool) -> None:
        statistics: Dict[str, int] = {}
        if bsd:
            items = find_groups_in_lines(raw_str, self._bsd_statistics_pattern)
        else:
            items = find_groups_in_lines(raw_str, self._statistics_pattern)
        statistics = {x["name"]: int(x["value"]) for x in items}

        self.interface = interface
        self.counters = statistics


@dataclass
class DeviceSettings:
    interface: str
    device_channel: Optional[DeviceChannel] = None
    device_features: Optional[DeviceFeatures] = None
    device_link_settings: Optional[DeviceLinkSettings] = None
    device_msg_level: Optional[DeviceMessageLevel] = None
    device_ringbuffer_settings: Optional[DeviceRingBufferSettings] = None
    device_gro_lro_settings: Optional[DeviceGroLroSettings] = None
    device_rss_hash_key: Optional[DeviceRssHashKey] = None
    device_rx_hash_level: Optional[DeviceRxHashLevel] = None
    device_sg_settings: Optional[DeviceSgSettings] = None
    device_firmware_version: Optional[str] = None
    device_statistics: Optional[DeviceStatistics] = None


class Ethtool(Tool):
    # ethtool -i eth0
    #   driver: hv_netvsc
    #   version:
    #   firmware-version: N/A
    _firmware_version_pattern = re.compile(
        r"^firmware-version:[\s+](?P<value>.*?)?$", re.MULTILINE
    )

    @classmethod
    def _freebsd_tool(cls) -> Optional[Type[Tool]]:
        return EthtoolFreebsd

    @property
    def command(self) -> str:
        return "ethtool"

    @property
    def can_install(self) -> bool:
        return True

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._command = "ethtool"
        self._device_set: Set[str] = set()
        self._device_settings_map: Dict[str, DeviceSettings] = {}

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("ethtool")
        return self._check_exists()

    def get_device_driver(self, interface: str) -> str:
        _device_driver_pattern = re.compile(
            r"^[\s]*driver:(?P<value>.*?)?$", re.MULTILINE
        )

        cmd_result = self.run(f"-i {interface}", shell=True)
        cmd_result.assert_exit_code(
            message=f"Could not find the driver information for {interface}"
        )
        driver_info = re.search(_device_driver_pattern, cmd_result.stdout)
        if not driver_info:
            raise LisaException(f"No driver information found for device {interface}")

        return driver_info.group("value")

    def get_device_list(self, force_run: bool = False) -> Set[str]:
        if (not force_run) and self._device_set:
            return self._device_set

        find_tool = self.node.tools[Find]
        netdirs = find_tool.find_files(
            self.node.get_pure_path("/sys/devices"),
            name_pattern="net",
            path_pattern=["*vmbus*", "*MSFT*"],
            ignore_case=True,
        )
        for netdir in netdirs:
            if not netdir:
                continue
            cmd_result = self.node.execute(f"ls {netdir}")
            cmd_result.assert_exit_code(message="Could not find the network device.")
            for result in cmd_result.stdout.split():
                # add only the network devices with netvsc driver
                driver = self.get_device_driver(result)
                if "hv_netvsc" in driver:
                    self._device_set.add(result)

        if not self._device_set:
            raise LisaException("Did not find any synthetic network interface.")

        return self._device_set

    def get_device_channels_info(
        self, interface: str, force_run: bool = False
    ) -> DeviceChannel:
        device = self._get_or_create_device_setting(interface)
        if not force_run and device.device_channel:
            return device.device_channel

        result = self.run(f"-l {interface}", force_run=force_run, shell=True)
        if (result.exit_code != 0) and ("Operation not supported" in result.stdout):
            raise UnsupportedOperationException(
                "ethtool -l {interface} operation not supported."
            )
        result.assert_exit_code(
            message=f"Couldn't get device {interface} channels info."
        )

        device_channel_info = DeviceChannel(interface, result.stdout)

        # Find the vCPU count to accurately get max channels for the device.
        lscpu = self.node.tools[Lscpu]
        vcpu_count = lscpu.get_thread_count(force_run=True)

        device_channel_info.max_channels = min(
            device_channel_info.max_channels, vcpu_count
        )
        device.device_channel = device_channel_info
        return device_channel_info

    def change_device_channels_info(
        self,
        interface: str,
        channel_count: int,
    ) -> DeviceChannel:
        change_result = self.run(
            f"-L {interface} combined {channel_count}",
            sudo=True,
            shell=True,
            force_run=True,
        )
        change_result.assert_exit_code(
            message=f" Couldn't change device {interface} channels count."
        )

        return self.get_device_channels_info(interface, force_run=True)

    def get_device_enabled_features(
        self, interface: str, force_run: bool = False
    ) -> DeviceFeatures:
        device = self._get_or_create_device_setting(interface)
        if not force_run and device.device_features:
            return device.device_features

        result = self.run(
            f"-k {interface}",
            force_run=force_run,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Unable to get device {interface} features."
            ),
        )
        enabled_features = self.feature_from_device_info(result.stdout)
        return DeviceFeatures(interface, enabled_features)

    def get_device_gro_lro_settings(
        self, interface: str, force_run: bool = False
    ) -> DeviceGroLroSettings:
        device = self._get_or_create_device_setting(interface)
        if not force_run and device.device_gro_lro_settings:
            return device.device_gro_lro_settings

        result = self.run(f"-k {interface}", force_run=force_run, sudo=True, shell=True)
        result.assert_exit_code()

        device.device_gro_lro_settings = DeviceGroLroSettings(interface, result.stdout)
        return device.device_gro_lro_settings

    def change_device_gro_lro_settings(
        self, interface: str, gro_setting: bool, lro_setting: bool
    ) -> DeviceGroLroSettings:
        gro = "on" if gro_setting else "off"
        lro = "on" if lro_setting else "off"
        change_result = self.run(
            f"-K {interface} gro {gro} lro {lro}",
            sudo=True,
            force_run=True,
            shell=True,
        )
        change_result.assert_exit_code(
            message=f" Couldn't change device {interface} GRO LRO settings."
        )

        return self.get_device_gro_lro_settings(interface, force_run=True)

    def get_device_link_settings(self, interface: str) -> DeviceLinkSettings:
        device = self._get_or_create_device_setting(interface)
        if device.device_link_settings:
            return device.device_link_settings

        result = self.run(interface, shell=True)
        result.assert_exit_code()

        link_settings = DeviceLinkSettings(interface, result.stdout)
        device.device_link_settings = link_settings

        # Caching the message level settings if captured in DeviceLinkSettings.
        # Not returning this info from this method. Only caching.
        if link_settings.msg_level_number and link_settings.msg_level_name:
            msg_level_settings = DeviceMessageLevel(
                interface,
                msg_level_number=link_settings.msg_level_number,
                msg_level_name=link_settings.msg_level_name,
            )
            device.device_msg_level = msg_level_settings

        return link_settings

    def get_device_msg_level(
        self, interface: str, force_run: bool = False
    ) -> DeviceMessageLevel:
        device = self._get_or_create_device_setting(interface)
        if not force_run and device.device_msg_level:
            return device.device_msg_level

        result = self.run(interface, force_run=force_run, shell=True)
        if (result.exit_code != 0) and ("Operation not supported" in result.stdout):
            raise UnsupportedOperationException(
                f"ethtool {interface} operation not supported."
            )
        result.assert_exit_code(
            message=f"Couldn't get device {interface} message level information"
        )

        msg_level_settings = DeviceMessageLevel(interface, result.stdout)
        device.device_msg_level = msg_level_settings

        # caching the link settings if captured in DeviceMessageLevel.
        # will not this info from this method. Only caching.
        if msg_level_settings.link_settings:
            link_settings = DeviceLinkSettings(
                interface, link_settings=msg_level_settings.link_settings
            )
            device.device_link_settings = link_settings

        return msg_level_settings

    def set_unset_device_message_flag_by_name(
        self, interface: str, msg_flag: List[str], flag_set: bool
    ) -> DeviceMessageLevel:
        if flag_set:
            result = self.run(
                f"-s {interface} msglvl {' on '.join(msg_flag)} on",
                sudo=True,
                force_run=True,
                shell=True,
            )
            result.assert_exit_code(
                message=f" Couldn't set device {interface} message flag/s {msg_flag}."
            )
        else:
            result = self.run(
                f"-s {interface} msglvl {' off '.join(msg_flag)} off",
                sudo=True,
                force_run=True,
                shell=True,
            )
            result.assert_exit_code(
                message=f" Couldn't unset device {interface} message flag/s {msg_flag}."
            )

        return self.get_device_msg_level(interface, force_run=True)

    def set_device_message_flag_by_num(
        self, interface: str, msg_flag: str
    ) -> DeviceMessageLevel:
        result = self.run(
            f"-s {interface} msglvl {msg_flag}",
            sudo=True,
            force_run=True,
            shell=True,
        )
        result.assert_exit_code(
            message=f" Couldn't set device {interface} message flag {msg_flag}."
        )

        return self.get_device_msg_level(interface, force_run=True)

    def get_device_ring_buffer_settings(
        self, interface: str, force_run: bool = False
    ) -> DeviceRingBufferSettings:
        device = self._get_or_create_device_setting(interface)
        if not force_run and device.device_ringbuffer_settings:
            return device.device_ringbuffer_settings

        result = self.run(f"-g {interface}", force_run=force_run, shell=True)
        if (result.exit_code != 0) and ("Operation not supported" in result.stdout):
            raise UnsupportedOperationException(
                f"ethtool -g {interface} operation not supported."
            )
        result.assert_exit_code(
            message=f"Couldn't get device {interface} ring buffer settings."
        )

        device.device_ringbuffer_settings = DeviceRingBufferSettings(
            interface, result.stdout
        )
        return device.device_ringbuffer_settings

    def change_device_ring_buffer_settings(
        self, interface: str, rx: int, tx: int
    ) -> DeviceRingBufferSettings:
        change_result = self.run(
            f"-G {interface} rx {rx} tx {tx}",
            sudo=True,
            force_run=True,
            shell=True,
        )
        change_result.assert_exit_code(
            message=f" Couldn't change device {interface} ring buffer settings."
        )

        return self.get_device_ring_buffer_settings(interface, force_run=True)

    def get_device_rss_hash_key(
        self, interface: str, force_run: bool = False
    ) -> DeviceRssHashKey:
        device = self._get_or_create_device_setting(interface)
        if not force_run and device.device_rss_hash_key:
            return device.device_rss_hash_key

        result = self.run(f"-x {interface}", force_run=force_run, shell=True)
        if (result.exit_code != 0) and ("Operation not supported" in result.stdout):
            raise UnsupportedOperationException(
                f"ethtool -x {interface} operation not supported."
            )
        result.assert_exit_code(
            message=f"Couldn't get device {interface} ring buffer settings."
        )
        device.device_rss_hash_key = DeviceRssHashKey(interface, result.stdout)

        return device.device_rss_hash_key

    def change_device_rss_hash_key(
        self, interface: str, hash_key: str
    ) -> DeviceRssHashKey:
        result = self.run(
            f"-X {interface} hkey {hash_key}",
            sudo=True,
            force_run=True,
            shell=True,
        )
        if (result.exit_code != 0) and ("Operation not supported" in result.stdout):
            raise UnsupportedOperationException(
                f"Changing RSS hash key with 'ethtool -X {interface}' not supported."
            )
        result.assert_exit_code(
            message=f" Couldn't change device {interface} hash key."
        )

        return self.get_device_rss_hash_key(interface, force_run=True)

    def get_device_rx_hash_level(
        self, interface: str, protocol: str, force_run: bool = False
    ) -> DeviceRxHashLevel:
        device = self._get_or_create_device_setting(interface)
        if (
            not force_run
            and device.device_rx_hash_level
            and (protocol in device.device_rx_hash_level.protocol_hash_map.keys())
        ):
            return device.device_rx_hash_level

        result = self.run(
            f"-n {interface} rx-flow-hash {protocol}", force_run=force_run, shell=True
        )
        if "Operation not supported" in result.stdout:
            raise UnsupportedOperationException(
                f"ethtool -n {interface} operation not supported."
            )
        result.assert_exit_code(
            message=f"Couldn't get device {interface} RX flow hash level for"
            f" protocol {protocol}."
        )

        if device.device_rx_hash_level:
            device.device_rx_hash_level._parse_rx_hash_level(
                interface, protocol, result.stdout
            )
            device_rx_hash_level = device.device_rx_hash_level
        else:
            device_rx_hash_level = DeviceRxHashLevel(interface, protocol, result.stdout)
        device.device_rx_hash_level = device_rx_hash_level

        return device_rx_hash_level

    def change_device_rx_hash_level(
        self, interface: str, protocol: str, enable: bool
    ) -> DeviceRxHashLevel:
        param = "sd"
        if enable:
            param = "sdfn"

        result = self.run(
            f"-N {interface} rx-flow-hash {protocol} {param}",
            sudo=True,
            shell=True,
            force_run=True,
        )
        if "Operation not supported" in result.stdout:
            raise UnsupportedOperationException(
                f"ethtool -N {interface} rx-flow-hash {protocol} {param}"
                " operation not supported."
            )
        result.assert_exit_code(
            message=f" Couldn't change device {interface} hash level for {protocol}."
        )

        return self.get_device_rx_hash_level(interface, protocol, force_run=True)

    def get_device_sg_settings(
        self, interface: str, force_run: bool = False
    ) -> DeviceSgSettings:
        device = self._get_or_create_device_setting(interface)
        if not force_run and device.device_sg_settings:
            return device.device_sg_settings

        result = self.run(f"-k {interface}", force_run=force_run, shell=True)
        result.assert_exit_code()

        device.device_sg_settings = DeviceSgSettings(interface, result.stdout)
        return device.device_sg_settings

    def change_device_sg_settings(
        self, interface: str, sg_setting: bool
    ) -> DeviceSgSettings:
        sg = "on" if sg_setting else "off"
        change_result = self.run(
            f"-K {interface} sg {sg}",
            sudo=True,
            shell=True,
            force_run=True,
        )
        change_result.assert_exit_code(
            message=f" Couldn't change device {interface} scatter-gather settings."
        )

        return self.get_device_sg_settings(interface, force_run=True)

    def get_device_statistics(
        self, interface: str, force_run: bool = False
    ) -> DeviceStatistics:
        device = self._get_or_create_device_setting(interface)
        if not force_run and device.device_statistics:
            return device.device_statistics

        result = self.run(f"-S {interface}", force_run=True, shell=True)
        if (result.exit_code != 0) and (
            "Operation not supported" in result.stdout
            or "no stats available" in result.stdout
        ):
            raise UnsupportedOperationException(
                f"ethtool -S {interface} operation not supported."
            )
        result.assert_exit_code(message=f"Couldn't get device {interface} statistics.")

        device.device_statistics = DeviceStatistics(interface, result.stdout)
        return device.device_statistics

    def get_device_statistics_delta(
        self, interface: str, previous_statistics: Dict[str, int]
    ) -> Dict[str, int]:
        """
        use this method to get the delta of an operation.
        """
        new_statistics = self.get_device_statistics(
            interface=interface, force_run=True
        ).counters

        for key, value in previous_statistics.items():
            new_statistics[key] = new_statistics.get(key, 0) - value
        self._log.debug(f"none-zero delta statistics on {interface}:")
        self._log.debug(
            {key: value for key, value in new_statistics.items() if value != 0}
        )

        return new_statistics

    def get_device_firmware_version(
        self, interface: str, force_run: bool = False
    ) -> str:
        device = self._get_or_create_device_setting(interface)
        if not force_run and device.device_firmware_version:
            return device.device_firmware_version

        result = self.run(f"-i {interface}", force_run=force_run, shell=True)
        if (result.exit_code != 0) and ("Operation not supported" in result.stdout):
            raise UnsupportedOperationException(
                f"ethtool -i {interface} operation not supported."
            )
        result.assert_exit_code(
            message=f"Couldn't get device {interface} firmware version info."
        )

        firmware_version_pattern = self._firmware_version_pattern.search(result.stdout)
        if not firmware_version_pattern:
            raise LisaException(
                f"Cannot get {interface} device firmware version information"
            )
        firmware_version = firmware_version_pattern.group("value")

        device.device_firmware_version = firmware_version
        return firmware_version

    def get_all_device_channels_info(self) -> List[DeviceChannel]:
        devices_channel_list = []
        devices = self.get_device_list()
        for device in devices:
            devices_channel_list.append(self.get_device_channels_info(device))

        return devices_channel_list

    def get_all_device_enabled_features(
        self, force_run: bool = False
    ) -> List[DeviceFeatures]:
        devices_features_list = []
        devices = self.get_device_list(force_run)
        for device in devices:
            devices_features_list.append(
                self.get_device_enabled_features(device, force_run)
            )

        return devices_features_list

    def get_all_device_gro_lro_settings(self) -> List[DeviceGroLroSettings]:
        devices_gro_lro_settings = []
        devices = self.get_device_list()
        for device in devices:
            devices_gro_lro_settings.append(self.get_device_gro_lro_settings(device))

        return devices_gro_lro_settings

    def get_all_device_link_settings(self) -> List[DeviceLinkSettings]:
        devices_link_settings_list = []
        devices = self.get_device_list()
        for device in devices:
            devices_link_settings_list.append(self.get_device_link_settings(device))

        return devices_link_settings_list

    def get_all_device_msg_level(self) -> List[DeviceMessageLevel]:
        devices_msg_level_list = []
        devices = self.get_device_list()
        for device in devices:
            devices_msg_level_list.append(self.get_device_msg_level(device))

        return devices_msg_level_list

    def get_all_device_ring_buffer_settings(self) -> List[DeviceRingBufferSettings]:
        devices_ring_buffer_settings_list = []
        devices = self.get_device_list()
        for device in devices:
            devices_ring_buffer_settings_list.append(
                self.get_device_ring_buffer_settings(device)
            )
        return devices_ring_buffer_settings_list

    def get_all_device_rss_hash_key(self) -> List[DeviceRssHashKey]:
        devices_rss_hash_keys = []
        devices = self.get_device_list()
        for device in devices:
            devices_rss_hash_keys.append(self.get_device_rss_hash_key(device))

        return devices_rss_hash_keys

    def get_all_device_rx_hash_level(self, protocol: str) -> List[DeviceRxHashLevel]:
        devices_rx_hash_level = []
        devices = self.get_device_list()
        for device in devices:
            devices_rx_hash_level.append(
                self.get_device_rx_hash_level(device, protocol)
            )

        return devices_rx_hash_level

    def get_all_device_statistics(self) -> List[DeviceStatistics]:
        devices_statistics = []
        devices = self.get_device_list()
        for device in devices:
            devices_statistics.append(
                self.get_device_statistics(device, force_run=True)
            )

        return devices_statistics

    def get_all_device_firmware_version(self) -> Dict[str, str]:
        devices_firmware_versions: Dict[str, str] = {}
        devices = self.get_device_list()
        for device in devices:
            devices_firmware_versions[device] = self.get_device_firmware_version(
                device, force_run=True
            )

        return devices_firmware_versions

    def _get_or_create_device_setting(self, interface: str) -> DeviceSettings:
        settings = self._device_settings_map.get(interface, None)
        if settings is None:
            settings = DeviceSettings(interface)
            self._device_settings_map[interface] = settings
        return settings

    def feature_from_device_info(self, device_feature_raw: str) -> List[str]:
        matched_features_info = DeviceFeatures._feature_info_pattern.search(
            device_feature_raw
        )
        if not matched_features_info:
            raise LisaException("Cannot get features settings info")

        enabled_features: List[str] = []
        for row in matched_features_info.group("value").splitlines():
            feature_info = DeviceFeatures._feature_settings_pattern.match(row)
            if not feature_info:
                raise LisaException(
                    "Could not get feature setting for device"
                    " in the defined pattern."
                )
            if "on" in feature_info.group("value"):
                enabled_features.append(feature_info.group("name"))

        return enabled_features


class EthtoolFreebsd(Ethtool):
    # options=8051b<RXCSUM,TXCSUM,VLAN_MTU,VLAN_HWTAGGING,TSO4,LRO,LINKSTATE>
    _interface_features_pattern = re.compile(
        r"options=.+<(?P<features>.*)>(?:.|\n)*ether"
    )

    _get_bsd_to_linux_features_map = {
        "RXCSUM": "rx-checksumming",
        "TXCSUM": "tx-checksumming",
        "VLAN_MTU": "vlan-mtu",
        "VLAN_HWTAGGING": "vlan-hw-tag-offload",
        "TSO4": "tcp-segmentation-offload",
        "LRO": "large-receive-offload",
        "LINKSTATE": "link-state",
    }

    @property
    def command(self) -> str:
        return ""

    @property
    def can_install(self) -> bool:
        return False

    def _check_exists(self) -> bool:
        return True

    def get_device_list(self, force_run: bool = False) -> Set[str]:
        devices = self.node.tools[Ip].get_interface_list()

        # remove non netvsc devices
        # netvsc device name begin with hn
        devices = [device for device in devices if device.startswith("hn")]
        return set(devices)

    def get_device_enabled_features(
        self, interface: str, force_run: bool = False
    ) -> DeviceFeatures:
        interface_info = self.node.tools[Ip].run(interface).stdout
        # Example output:
        # options=8051b<RXCSUM,TXCSUM,VLAN_MTU,VLAN_HWTAGGING,TSO4,LRO,LINKSTATE>
        # The features are separated by comma and enclosed by "<>"
        features_pattern = find_group_in_lines(
            interface_info, self._interface_features_pattern, False
        )["features"].split(",")

        features = []
        for feature in features_pattern:
            if feature in self._get_bsd_to_linux_features_map:
                features.append(self._get_bsd_to_linux_features_map[feature])
        device_features = DeviceFeatures(interface, features)

        return device_features

    def get_device_statistics(
        self, interface: str, force_run: bool = False
    ) -> DeviceStatistics:
        device = self._get_or_create_device_setting(interface)
        if not force_run and device.device_statistics:
            return device.device_statistics

        # Example Matches
        # hn0
        # mce0
        # da0
        match = re.match(r"^(\w+)(\d+)$", interface)
        if not match:
            raise LisaException(f"Invalid interface name: {interface}")
        device_name = match.group(1)
        number = match.group(2)
        result = self.run(
            f"sysctl dev.{device_name}.{number}", force_run=True, shell=True
        )
        if (result.exit_code != 0) and (
            "Operation not supported" in result.stdout
            or "no stats available" in result.stdout
        ):
            raise UnsupportedOperationException(
                f"Stats retrieval for {interface} operation not supported."
            )
        result.assert_exit_code(message=f"Couldn't get device {interface} statistics.")

        device.device_statistics = DeviceStatistics(interface, result.stdout, True)
        return device.device_statistics

    def _get_or_create_device_setting(self, interface: str) -> DeviceSettings:
        settings = self._device_settings_map.get(interface, None)
        if settings is None:
            settings = DeviceSettings(interface)
            self._device_settings_map[interface] = settings
        return settings
