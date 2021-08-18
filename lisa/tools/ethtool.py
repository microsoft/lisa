import re
from typing import Any, Dict, List, Optional, Set, cast

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.util import LisaException, UnsupportedOperationException

from .find import Find
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

    def __init__(self, interface: str, device_feature_raw: str) -> None:
        self._parse_feature_info(interface, device_feature_raw)

    def _parse_feature_info(self, interface: str, raw_str: str) -> None:
        matched_features_info = self._feature_info_pattern.search(raw_str)
        if not matched_features_info:
            raise LisaException(f"Cannot get {interface} features settings info")

        self.device_name = interface
        self.enabled_features = []
        for row in matched_features_info.group("value").splitlines():
            feature_info = self._feature_settings_pattern.match(row)
            if not feature_info:
                raise LisaException(
                    f"Could not get feature setting for device {interface}"
                    " in the defined pattern."
                )
            if "on" in feature_info.group("value"):
                self.enabled_features.append(feature_info.group("name"))


class DeviceLinkSettings:
    # ethtool device link settings info is in format -
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
    _link_settings_info_pattern = re.compile(
        r"Settings for (?P<interface>[\w]*):[\s]*(?P<value>.*?)$", re.DOTALL
    )
    _link_settings_pattern = re.compile(
        r"^[ \t]*(?P<name>.*):[ \t]*(?P<value>.*?)?$", re.MULTILINE
    )

    def __init__(self, interface: str, device_link_settings_raw: str) -> None:
        self._parse_link_settings_info(interface, device_link_settings_raw)

    def _parse_link_settings_info(self, interface: str, raw_str: str) -> None:
        matched_link_settings_info = self._link_settings_info_pattern.search(raw_str)
        if not matched_link_settings_info:
            raise LisaException(f"Cannot get {interface} link settings info")

        self.device_name = interface
        self.link_settings: Dict[str, str] = {}

        for row in matched_link_settings_info.group("value").splitlines():
            link_setting_info = self._link_settings_pattern.match(row)
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
        r"^RSS hash key:[\s+](?P<value>.*?)?$", re.MULTILINE
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
        print(f"protocol {protocol}, protocol_hash_map {self.protocol_hash_map}")


class DeviceSettings:
    def __init__(
        self,
        interface: str,
    ) -> None:
        self.interface = interface
        self.device_channel: Optional[DeviceChannel] = None
        self.device_features: Optional[DeviceFeatures] = None
        self.device_link_settings: Optional[DeviceLinkSettings] = None
        self.device_ringbuffer_settings: Optional[DeviceRingBufferSettings] = None
        self.device_gro_lro_settings: Optional[DeviceGroLroSettings] = None
        self.device_rss_hash_key: Optional[DeviceRssHashKey] = None
        self.device_rx_hash_level: Optional[DeviceRxHashLevel] = None


class Ethtool(Tool):
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

    def _set_device(
        self,
        name: str,
        device_channels: Optional[DeviceChannel] = None,
        device_features: Optional[DeviceFeatures] = None,
        device_link_settings: Optional[DeviceLinkSettings] = None,
        device_ringbuffer_settings: Optional[DeviceRingBufferSettings] = None,
        device_gro_lro_settings: Optional[DeviceGroLroSettings] = None,
        device_rss_hash_key: Optional[DeviceRssHashKey] = None,
        device_rx_hash_level: Optional[DeviceRxHashLevel] = None,
    ) -> None:
        device = self._device_settings_map.get(name, None)
        if device is None:
            device = DeviceSettings(name)

        self._device_settings_map[name] = device

        if device_channels:
            device.device_channel = device_channels
        if device_features:
            device.device_features = device_features
        if device_link_settings:
            device.device_link_settings = device_link_settings
        if device_ringbuffer_settings:
            device.device_ringbuffer_settings = device_ringbuffer_settings
        if device_gro_lro_settings:
            device.device_gro_lro_settings = device_gro_lro_settings
        if device_rss_hash_key:
            device.device_rss_hash_key = device_rss_hash_key
        if device_rx_hash_level:
            device.device_rx_hash_level = device_rx_hash_level

    def get_device_driver(self, interface: str) -> str:
        _device_driver_pattern = re.compile(
            r"^[\s]*driver:(?P<value>.*?)?$", re.MULTILINE
        )

        cmd_result = self.run(f"-i {interface}")
        cmd_result.assert_exit_code(
            message=f"Could not find the driver information for {interface}"
        )
        driver_info = re.search(_device_driver_pattern, cmd_result.stdout)
        if not driver_info:
            raise LisaException(f"No driver information found for device {interface}")

        return driver_info.group("value")

    def get_device_list(self, force: bool = False) -> Set[str]:
        if (not force) and self._device_set:
            return self._device_set

        find_tool = self.node.tools[Find]
        netdirs = find_tool.find_files(
            self.node.get_pure_path("/sys/devices"),
            name_pattern="net",
            path_pattern="*vmbus*",
            ignore_case=True,
        )
        for netdir in netdirs:
            if not netdir:
                continue
            cmd_result = self.node.execute(f"ls {netdir}")
            cmd_result.assert_exit_code(message="Could not find the network device.")

            # add only the network devices with netvsc driver
            driver = self.get_device_driver(cmd_result.stdout)
            if "hv_netvsc" in driver:
                self._device_set.add(cmd_result.stdout)

        if not self._device_set:
            raise LisaException("Did not find any synthetic network interface.")

        return self._device_set

    def get_device_channels_info(
        self, interface: str, force: bool = False
    ) -> DeviceChannel:
        if not force:
            device = self._device_settings_map.get(interface, None)
            if device and device.device_channel:
                return device.device_channel

        result = self.run(f"-l {interface}", force_run=force)
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
        vcpu_count = lscpu.get_core_count(force_run=True)
        if vcpu_count < device_channel_info.max_channels:
            device_channel_info.max_channels = vcpu_count

        self._set_device(interface, device_channels=device_channel_info)

        return device_channel_info

    def change_device_channels_info(
        self,
        interface: str,
        channel_count: int,
    ) -> DeviceChannel:
        change_result = self.run(
            f"-L {interface} combined {channel_count}", sudo=True, force_run=True
        )
        change_result.assert_exit_code(
            message=f" Couldn't change device {interface} channels count."
        )

        return self.get_device_channels_info(interface, force=True)

    def get_device_enabled_features(
        self, interface: str, force: bool = False
    ) -> DeviceFeatures:
        if not force:
            device = self._device_settings_map.get(interface, None)
            if device and device.device_features:
                return device.device_features

        result = self.run(f"-k {interface}", force_run=force)
        result.assert_exit_code()

        device_feature = DeviceFeatures(interface, result.stdout)
        self._set_device(interface, device_features=device_feature)

        return device_feature

    def get_device_gro_lro_settings(
        self, interface: str, force: bool = False
    ) -> DeviceGroLroSettings:
        if not force:
            device = self._device_settings_map.get(interface, None)
            if device and device.device_gro_lro_settings:
                return device.device_gro_lro_settings

        result = self.run(f"-k {interface}", force_run=force)
        result.assert_exit_code()

        device_gro_lro_settings = DeviceGroLroSettings(interface, result.stdout)
        self._set_device(interface, device_gro_lro_settings=device_gro_lro_settings)

        return device_gro_lro_settings

    def change_device_gro_lro_settings(
        self, interface: str, gro_setting: bool, lro_setting: bool
    ) -> DeviceGroLroSettings:
        gro = "on" if gro_setting else "off"
        lro = "on" if lro_setting else "off"
        change_result = self.run(
            f"-K {interface} gro {gro} lro {lro}",
            sudo=True,
            force_run=True,
        )
        change_result.assert_exit_code(
            message=f" Couldn't change device {interface} GRO LRO settings."
        )

        return self.get_device_gro_lro_settings(interface, force=True)

    def get_device_link_settings(self, interface: str) -> DeviceLinkSettings:
        device = self._device_settings_map.get(interface, None)
        if device and device.device_link_settings:
            return device.device_link_settings

        result = self.run(interface)
        result.assert_exit_code()

        device_link_settings = DeviceLinkSettings(interface, result.stdout)
        self._set_device(interface, device_link_settings=device_link_settings)

        return device_link_settings

    def get_device_ring_buffer_settings(
        self, interface: str, force: bool = False
    ) -> DeviceRingBufferSettings:
        if not force:
            device = self._device_settings_map.get(interface, None)
            if device and device.device_ringbuffer_settings:
                return device.device_ringbuffer_settings

        result = self.run(f"-g {interface}", force_run=force)
        if (result.exit_code != 0) and ("Operation not supported" in result.stdout):
            raise UnsupportedOperationException(
                f"ethtool -g {interface} operation not supported."
            )
        result.assert_exit_code(
            message=f"Couldn't get device {interface} ring buffer settings."
        )

        device_ring_buffer_settings = DeviceRingBufferSettings(interface, result.stdout)
        self._set_device(
            interface, device_ringbuffer_settings=device_ring_buffer_settings
        )

        return device_ring_buffer_settings

    def change_device_ring_buffer_settings(
        self, interface: str, rx: int, tx: int
    ) -> DeviceRingBufferSettings:
        change_result = self.run(
            f"-G {interface} rx {rx} tx {tx}", sudo=True, force_run=True
        )
        change_result.assert_exit_code(
            message=f" Couldn't change device {interface} ring buffer settings."
        )

        return self.get_device_ring_buffer_settings(interface, force=True)

    def get_device_rss_hash_key(
        self, interface: str, force: bool = False
    ) -> DeviceRssHashKey:
        if not force:
            device = self._device_settings_map.get(interface, None)
            if device and device.device_rss_hash_key:
                return device.device_rss_hash_key

        result = self.run(f"-x {interface}", force_run=force)
        if (result.exit_code != 0) and ("Operation not supported" in result.stdout):
            raise UnsupportedOperationException(
                f"ethtool -x {interface} operation not supported."
            )
        result.assert_exit_code(
            message=f"Couldn't get device {interface} ring buffer settings."
        )
        device_rss_hash_key = DeviceRssHashKey(interface, result.stdout)
        self._set_device(interface, device_rss_hash_key=device_rss_hash_key)

        return device_rss_hash_key

    def change_device_rss_hash_key(
        self, interface: str, hash_key: str
    ) -> DeviceRssHashKey:
        result = self.run(f"-X {interface} hkey {hash_key}", sudo=True, force_run=True)
        if (result.exit_code != 0) and ("Operation not supported" in result.stdout):
            raise UnsupportedOperationException(
                f"Changing RSS hash key with 'ethtool -X {interface}' not supported."
            )
        result.assert_exit_code(
            message=f" Couldn't change device {interface} hash key."
        )

        return self.get_device_rss_hash_key(interface, force=True)

    def get_device_rx_hash_level(
        self, interface: str, protocol: str, force: bool = False
    ) -> DeviceRxHashLevel:
        if not force:
            device = self._device_settings_map.get(interface, None)
            if (
                device
                and device.device_rx_hash_level
                and (protocol in device.device_rx_hash_level.protocol_hash_map.keys())
            ):
                return device.device_rx_hash_level

        result = self.run(f"-n {interface} rx-flow-hash {protocol}", force_run=force)
        if (result.exit_code != 0) and ("Operation not supported" in result.stdout):
            raise UnsupportedOperationException(
                f"ethtool -n {interface} operation not supported."
            )
        result.assert_exit_code(
            message=f"Couldn't get device {interface} RX flow hash level for"
            f" protocol {protocol}."
        )

        device = self._device_settings_map.get(interface, None)
        if device and device.device_rx_hash_level:
            device.device_rx_hash_level._parse_rx_hash_level(
                interface, protocol, result.stdout
            )
            device_rx_hash_level = device.device_rx_hash_level
        else:
            device_rx_hash_level = DeviceRxHashLevel(interface, protocol, result.stdout)
        self._set_device(interface, device_rx_hash_level=device_rx_hash_level)

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
            force_run=True,
        )
        if (result.exit_code != 0) and ("Operation not supported" in result.stdout):
            raise UnsupportedOperationException(
                f"ethtool -N {interface} rx-flow-hash {protocol} {param}"
                " operation not supported."
            )
        result.assert_exit_code(
            message=f" Couldn't change device {interface} hash level for {protocol}."
        )

        return self.get_device_rx_hash_level(interface, protocol, force=True)

    def get_all_device_channels_info(self) -> List[DeviceChannel]:
        devices_channel_list = []
        devices = self.get_device_list()
        for device in devices:
            devices_channel_list.append(self.get_device_channels_info(device))

        return devices_channel_list

    def get_all_device_enabled_features(self) -> List[DeviceFeatures]:
        devices_features_list = []
        devices = self.get_device_list()
        for device in devices:
            devices_features_list.append(self.get_device_enabled_features(device))

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
