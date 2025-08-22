# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


import os
import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from assertpy import assert_that
from retry import retry

from lisa.tools import Cat, Ip, KernelConfig, Ls, Lspci, Modprobe, Tee
from lisa.util import InitializableMixin, LisaException, constants, find_groups_in_lines

if TYPE_CHECKING:
    from lisa import Node


class NicInfo:
    # Class for info about an single nic/pci device pair.
    # Devices using AN on azure typically have an network interface (NIC).
    # paired with a PCI device that
    # enables the passthrough to the physical NIC.

    # If AN is not enabled then there will not be a pci device.
    # In this case, NicInfo will have lower = ""

    def __init__(
        self,
        name: str,
        lower: str = "",
        pci_slot: str = "",
        lower_module_name: str = "",
        driver_sysfs_path: Optional[PurePosixPath] = None,
    ) -> None:
        self.name = name
        self.lower = lower
        self.mac_addr = ""
        self.ip_addr = ""
        self.pci_slot = pci_slot
        self.dev_uuid = ""
        self.module_name = ""
        if driver_sysfs_path is None:
            self.driver_sysfs_path = PurePosixPath("")
        else:
            self.driver_sysfs_path = driver_sysfs_path
        self.lower_module_name = lower_module_name

    def __str__(self) -> str:
        return (
            "NicInfo:\n"
            f"name: {self.name}\n"
            f"pci_slot: {self.pci_slot}\n"
            f"ip_addr: {self.ip_addr}\n"
            f"mac_addr: {self.mac_addr}\n"
        )

    @property
    def is_pci_module_enabled(self) -> bool:
        # nic with paired pci device
        if len(self.lower) > 0:
            return True
        else:
            # pci device without paired nic
            if self.is_pci_device:
                # pci device without accelerated network module
                if self.module_name == "hv_netvsc":
                    return False
                else:
                    # pci device with accelerated network module
                    return True
            else:
                # no pci devices
                return False

    @property
    def is_pci_device(self) -> bool:
        return len(self.pci_slot) > 0

    @property
    def pci_device_name(self) -> str:
        if self.is_pci_device:
            return self.lower if self.lower else self.name
        return ""


class Nics(InitializableMixin):
    # Class for all of the nics on a node. Contains multiple NodeNic classes.
    # Init identifies nic/pci paired devices and the pci slot info for the pci device.

    # ex:
    # /sys/class/net/eth0/lower_enP13530s1 -> ../../../ (continued next line)
    # ad379351-34da-4568-93a3-03878ae8eee8/pci34da:00/34da:00:02.0/net/enP13530s1
    __nic_pci_device_regex = re.compile(
        (
            r"/sys/class/net/"
            r"([a-zA-Z0-9_\-]+)"  # network interface GROUP1
            r"/lower_([a-zA-Z0-9_\-]+)"  # pci interface GROUP2
            r"/device -> ../../../"  # link to devices guid
            r"([a-zA-Z0-9]{4}:[a-zA-Z0-9]{2}:[a-zA-Z0-9]{2}.[a-zA-Z0-9])"  # bus info
        )
    )

    # /sys/class/net/enP35158p0s2/device -> ../../../8956:00:02.0
    __nic_vf_slot_regex = re.compile(
        (
            r"/sys/class/net/"
            r"([a-zA-Z0-9_\-]+)"  # pci interface name
            r"/device -> ../../../"  # link to devices guid
            r"([a-zA-Z0-9]{4}:[a-zA-Z0-9]{2}:[a-zA-Z0-9]{2}.[a-zA-Z0-9])"  # bus info
        )
    )

    _file_not_exist = re.compile(r"No such file or directory", re.MULTILINE)

    # ConnectX-3 uses mlx4_core
    # mlx4_en and mlx4_ib depends on mlx4_core
    #  need remove mlx4_en and mlx4_ib firstly
    #  otherwise will see modules is in used issue
    # ConnectX-4/ConnectX-5 uses mlx5_core
    # mlx5_ib depends on mlx5_core, need remove mlx5_ib firstly
    @dataclass
    class ModuleInformation:
        drivers: List[str]
        config: str

    _device_module_map = {
        "mlx5_core": ModuleInformation(["mlx5_ib"], "CONFIG_MLX5_CORE"),
        "mlx4_core": ModuleInformation(["mlx4_en", "mlx4_ib"], "CONFIG_MLX4_CORE"),
        "mana": ModuleInformation(
            ["mana", "mana_en", "mana_ib"], "CONFIG_MICROSOFT_MANA"
        ),
    }

    def __init__(self, node: "Node"):
        super().__init__()
        self._node = node
        self.nics: Dict[str, NicInfo] = OrderedDict()

    def __str__(self) -> str:
        _str = ""
        for nic in self.nics:
            _str += f"{self.nics[nic]}"
        return _str

    def __len__(self) -> int:
        return len(self.nics)

    def append(self, next_node: NicInfo) -> None:
        self.nics[next_node.name] = next_node

    def is_empty(self) -> bool:
        return len(self.nics) == 0

    def get_unpaired_devices(self) -> List[str]:
        return [x.name for x in self.nics.values() if not x.lower]

    def get_lower_nics(self) -> List[str]:
        return [x.lower for x in self.nics.values() if x.lower]

    def is_pci_module_enabled(self) -> bool:
        return any(
            [
                x
                for x in self.nics.values()
                if x.is_pci_device and x.is_pci_module_enabled
            ]
        )

    def get_used_modules(self, exclude_module_name: List[str]) -> List[str]:
        used_module_list = list(
            set(
                [
                    x.lower_module_name or x.module_name
                    for x in self.nics.values()
                    if (x.module_name or x.lower_module_name)
                ]
            )
        )
        for item in list(set(exclude_module_name)):
            if item in used_module_list:
                used_module_list.remove(item)
        return used_module_list

    def get_device_slots(self) -> List[str]:
        return [x.pci_slot for x in self.nics.values() if x.pci_slot]

    def _get_nics_driver(self) -> None:
        for nic in [x.name for x in self.nics.values()]:
            self.get_nic_driver(nic)

    # update the current nic driver in the NicInfo instance
    # grabs the driver short name and the driver sysfs path
    def get_nic_driver(self, nic_name: str) -> str:
        # get the current driver for the nic from the node
        # sysfs provides a link to the driver entry at device/driver
        nic = self.get_nic(nic_name)
        cmd = f"readlink -f /sys/class/net/{nic_name}/device/driver"
        # ex return value:
        # /sys/bus/vmbus/drivers/hv_netvsc
        found_link = self._node.execute(cmd, expected_exit_code=0).stdout
        assert_that(found_link).described_as(
            f"sysfs check for NIC device {nic_name} driver returned no output"
        ).is_not_equal_to("")
        nic.driver_sysfs_path = PurePosixPath(found_link)
        driver_name = nic.driver_sysfs_path.name
        assert_that(driver_name).described_as(
            f"sysfs entry contained no filename for device driver: {found_link}"
        ).is_not_equal_to("")
        nic.module_name = driver_name
        return driver_name

    def get_nic(self, nic_name: str) -> NicInfo:
        return self.nics[nic_name]

    def get_nic_names(self) -> List[str]:
        return list(self.nics.keys())

    def get_primary_nic(self) -> NicInfo:
        return self.get_nic_by_index(0)

    def get_secondary_nic(self) -> NicInfo:
        # get a nic which isn't servicing the SSH connection with lisa.
        # will assert if none is present.
        return self.get_nic_by_index(1)

    def get_nic_by_index(self, index: int = -1) -> NicInfo:
        # get nic by index, default is -1 to give a non-primary nic
        # when there are more than one nic on the system
        number_of_nics = len(self.get_nic_names())
        assert_that(number_of_nics).is_greater_than(0)
        try:
            nic_name = self.get_nic_names()[index]
        except IndexError:
            raise LisaException(
                f"Attempted get_nic_names()[{index}], only "
                f"{number_of_nics} nics are registered in node.nics. "
                f"Had network interfaces: {self.get_nic_names()}"
            )

        try:
            nic = self.nics[nic_name]
        except KeyError:
            raise LisaException(
                f"NicInfo for interface {nic_name} not found! "
                f"Had network interfaces: {self.get_nic_names()}"
            )
        return nic

    def unbind(self, nic: NicInfo) -> None:
        # unbind nic from current driver and return the old sysfs path
        tee = self._node.tools[Tee]
        ip = self._node.tools[Ip]
        # if sysfs path is not set, fetch the current driver
        if not nic.driver_sysfs_path:
            self.get_nic_driver(nic.name)
        # if the device is active, set to down before unbind
        if ip.nic_exists(nic.name):
            ip.down(nic.name)
        unbind_path = nic.driver_sysfs_path.joinpath("unbind")
        tee.write_to_file(nic.dev_uuid, unbind_path, sudo=True)

    def bind(self, nic: NicInfo, driver_module_path: str) -> None:
        tee = self._node.tools[Tee]
        nic.driver_sysfs_path = PurePosixPath(driver_module_path)
        bind_path = nic.driver_sysfs_path.joinpath("bind")
        tee.write_to_file(
            nic.dev_uuid,
            self._node.get_pure_path(f"{str(bind_path)}"),
            sudo=True,
        )
        nic.module_name = nic.driver_sysfs_path.name

    def load_nics_info(self, nic_name: Optional[str] = None) -> None:
        ip = self._node.tools[Ip]
        nics_info = ip.get_info(nic_name=nic_name)
        found_nics = []
        for nic_info in nics_info:
            nic_name = nic_info.nic_name
            mac = nic_info.mac_addr
            ip_addr = nic_info.ip_addr
            self._node.log.debug(f"Found nic info: {nic_name} {mac} {ip_addr}")
            if nic_name in self.get_nic_names():
                nic_entry = self.nics[nic_name]
                nic_entry.ip_addr = ip_addr
                nic_entry.mac_addr = mac
                found_nics.append(nic_name)

        if not nic_name:
            assert_that(sorted(found_nics)).described_as(
                f"Could not locate nic info for all nics. "
                f"Nic set was {self.nics.keys()} and only found info for {found_nics}"
            ).is_equal_to(sorted(self.nics.keys()))

    def reload(self) -> None:
        self.nics.clear()
        self._initialize()

    @retry(tries=15, delay=3, backoff=1.15)  # type: ignore
    def check_pci_enabled(self, pci_enabled: bool) -> None:
        self.reload()
        if pci_enabled:
            assert_that(len(self.get_device_slots())).described_as(
                "Could not identify any pci devices on the test node."
            ).is_not_zero()
            if self.is_pci_module_enabled():
                assert_that(pci_enabled).described_as(
                    "AN enablement and pci device are inconsistent"
                ).is_equal_to(any(self.get_lower_nics()))
        else:
            assert_that(self.get_device_slots()).described_as(
                "pci devices still on the test node."
            ).is_empty()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._node.log.debug("loading nic information...")
        self._nic_names = self._get_nic_names()
        self._load_nics()
        self._get_nics_driver()
        self.load_nics_info()
        self._get_nic_uuids()
        self._get_default_nic()

    def _get_nic_names(self) -> List[str]:
        # identify all of the nics on the device, excluding tunnels and loopbacks etc.
        all_nics = self._node.execute(
            "ls /sys/class/net/",
            shell=True,
            sudo=True,
        ).stdout.split()
        virtual_nics = self._node.execute(
            "ls /sys/devices/virtual/net",
            shell=True,
            sudo=True,
        ).stdout.split()

        # remove virtual nics from the list
        non_virtual_nics = [x for x in all_nics if x not in virtual_nics]

        # verify if the nics names are not empty
        assert_that(non_virtual_nics).described_as(
            "nic name could not be found"
        ).is_not_empty()
        return non_virtual_nics

    def _get_nic_uuid(self, nic_name: str) -> str:
        full_dev_path = self._node.execute(f"readlink /sys/class/net/{nic_name}/device")
        uuid = os.path.basename(full_dev_path.stdout.strip())
        self._node.log.debug(f"{nic_name} UUID:{uuid}")
        return uuid

    def _get_nic_uuids(self) -> None:
        for nic_name in self.nics.keys():
            self.nics[nic_name].dev_uuid = self._get_nic_uuid(nic_name)

    def _load_nics(self) -> None:
        # Identify which nics are slaved to master devices.
        # This should be really simple with /usr/bin/ip but experience shows
        # the tool isn't super consistent across distros in this regard

        # use sysfs to gather synthetic/pci nic pairings and pci slot info
        nic_info_fetch_cmd = "ls -la /sys/class/net/*/lower*/device"
        self._node.log.debug(f"Gathering NIC information on {self._node.name}.")
        lspci = self._node.tools[Lspci]
        result = self._node.execute(
            nic_info_fetch_cmd,
            shell=True,
        )
        if result.exit_code != 0:
            nic_info_fetch_cmd = "ls -la /sys/class/net/*/device"
            result = self._node.execute(
                nic_info_fetch_cmd,
                shell=True,
                expected_exit_code=0,
                expected_exit_code_failure_message="Could not grab NIC device info.",
            )

        for line in result.stdout.splitlines():
            sriov_match = self.__nic_pci_device_regex.search(line)
            if sriov_match:
                nic_name, lower, pci_slot = sriov_match.groups()
                used_module = lspci.get_used_module(pci_slot)
                self.append(
                    NicInfo(
                        name=nic_name,
                        lower=lower,
                        pci_slot=pci_slot,
                        lower_module_name=used_module,
                    )
                )

            sriov_match = self.__nic_vf_slot_regex.search(line)
            if sriov_match:
                lower, pci_slot = sriov_match.groups()
                ip = self._node.tools[Ip]
                pci_nic_mac = ip.get_mac(lower)
                for nic_name in [x for x in self._nic_names if x != lower]:
                    synthetic_nic_mac = ip.get_mac(nic_name)
                    if synthetic_nic_mac == pci_nic_mac:
                        used_module = lspci.get_used_module(pci_slot)
                        self.append(
                            NicInfo(
                                name=nic_name,
                                lower=lower,
                                pci_slot=pci_slot,
                                lower_module_name=used_module,
                            )
                        )
                        break

        # Collects NIC info for any unpaired NICS
        for nic_name in [
            x
            for x in self._nic_names
            if x not in self.nics.keys() and x not in self.get_lower_nics()
        ]:
            nic_info = NicInfo(name=nic_name)
            self.append(nic_info)

        assert_that(len(self)).described_as(
            "During Lisa nic info initialization, Nics class could not "
            f"find any nics attached to {self._node.name}."
        ).is_greater_than(0)

        # handle situation when there is no mana driver, but have mana pci devices
        if self.is_mana_device_present() and not self.is_mana_driver_enabled():
            pci_devices = lspci.get_devices_by_type(
                constants.DEVICE_TYPE_SRIOV, force_run=True
            )
            for pci_device in pci_devices:
                for nic in self.get_unpaired_devices():
                    self.nics[nic].pci_slot = pci_device.slot
                break

    def is_mana_device_present(self) -> bool:
        lspci = self._node.tools[Lspci]
        pci_devices = lspci.get_devices_by_type(
            constants.DEVICE_TYPE_SRIOV, force_run=True
        )
        all_mana_devices = False
        for pci_device in pci_devices:
            if (
                "Device 00ba" in pci_device.device_info
                and pci_device.vendor == "Microsoft Corporation"
            ):
                all_mana_devices = True
                break
            else:
                all_mana_devices = False
        return all_mana_devices

    def is_mana_driver_enabled(self) -> bool:
        return self._node.tools[KernelConfig].is_enabled("CONFIG_MICROSOFT_MANA")

    def _get_default_nic(self) -> None:
        self.default_nic: str = ""
        self.default_nic_route: str = ""
        self.default_nic, self.default_nic_route = self._node.tools[
            Ip
        ].get_default_route_info()
        assert_that(self.default_nic in self._nic_names).described_as(
            (
                f"ERROR: NIC name found as default {self.default_nic} "
                f"was not in original list of nics {repr(self._nic_names)}."
            )
        ).is_true()

    def is_module_reloadable(self, module_name: str) -> bool:
        return self._node.tools[KernelConfig].is_built_as_module(
            self._device_module_map[module_name].config
        )

    def unload_module(self, module_name: str) -> List[str]:
        modprobe = self._node.tools[Modprobe]
        module_list = self._device_module_map[module_name].drivers
        modprobe.remove(module_list)
        return module_list

    def load_module(self, module_name: str) -> str:
        modprobe = self._node.tools[Modprobe]
        modprobe.load(module_name)
        return module_name

    def module_exists(self, module_name: str) -> bool:
        modprobe = self._node.tools[Modprobe]
        return modprobe.module_exists(module_name)

    def get_packets(self, nic_name: str, name: str = "tx_packets") -> int:
        if not self.packet_path_exist(nic_name, name):
            self.reload()
        cat = self._node.tools[Cat]
        return int(
            cat.read(f"/sys/class/net/{nic_name}/statistics/{name}", force_run=True)
        )

    def packet_path_exist(self, nic_name: str, name: str = "tx_packets") -> bool:
        ls = self._node.tools[Ls]
        return ls.path_exists(f"/sys/class/net/{nic_name}/statistics/{name}", sudo=True)


class NicsBSD(Nics):
    # hn0
    # hn1
    _nic_vf_index_regex = re.compile(r"hn(?P<index>\d+)")

    # default            172.20.0.1         UGS         hn0
    _default_nic_regex = re.compile(
        r"default\s+(?P<ip_addr>\d+\.\d+\.\d+\.\d+)\s+UGS\s+(?P<nic_name>\w+)"
    )

    def _get_nic_names(self) -> List[str]:
        # identify all of the nics on the device
        return self._node.tools[Ip].get_interface_list()

    def _load_nics(self) -> None:
        # Get list of mac addresses for nics excluding loopback and netvsc
        mac_address_map = {}
        ip_tool = self._node.tools[Ip]
        for nic_name in [
            x
            for x in self._nic_names
            if not x.startswith("lo") and not x.startswith("hn")
        ]:
            mac_address_map[ip_tool.get_mac(nic_name)] = nic_name

        netvsc_nics = [x for x in self._nic_names if x.startswith("hn")]
        for nic_name in netvsc_nics:
            # check if there is a paired SRIOV nic
            mac = self._node.tools[Ip].get_mac(nic_name)

            # check for paired SRIOV nics
            lower = ""
            module = ""
            pci_slot = ""
            if mac in mac_address_map.keys():
                lower = mac_address_map[mac]

                # get index of the nic
                nic_index = find_groups_in_lines(nic_name, self._nic_vf_index_regex)[0][
                    "index"
                ]

                # get info about its pci slot and mlx module version
                slot_regex = re.compile(
                    rf"mlx(?P<index>\d+)_core{nic_index}@(?P<pci_slot>.*):\s+"
                )
                module_slot_info = self._node.execute("pciconf -l", sudo=True).stdout
                matched = find_groups_in_lines(module_slot_info, slot_regex)[0]
                module_version = matched["index"]
                pci_slot = matched["pci_slot"]

                # set the module name
                module = f"mlx{module_version}_core"

            self.append(
                NicInfo(
                    name=nic_name,
                    lower=lower,
                    lower_module_name=module,
                    pci_slot=pci_slot,
                )
            )

        assert_that(len(self)).described_as(
            "During Lisa nic info initialization, Nics class could not "
            f"find any nics attached to {self._node.name}."
        ).is_greater_than(0)

    def _get_nics_driver(self) -> None:
        # This function is not needed for FreeBSD
        # We get the driver name in the _load_nics function
        pass

    def load_nics_info(self, nic_name: Optional[str] = None) -> None:
        ip_tool = self._node.tools[Ip]
        if nic_name:
            nic_names = [nic_name]
        else:
            nic_names = self.get_nic_names()
        nics = [self.nics[nic_name] for nic_name in nic_names]
        for nic in nics:
            try:
                nic.ip_addr = ip_tool.get_ip_address(nic.name)
            except AssertionError:
                # handle case where nic is not configured correctly
                nic.ip_addr = ""
            nic.mac_addr = ip_tool.get_mac(nic.name)

    def _get_nic_uuids(self) -> None:
        # This information is presently not needed for FreeBSD tests
        pass

    def _get_default_nic(self) -> None:
        # This information is presently not needed for FreeBSD tests
        output = self._node.execute("netstat -4rn", sudo=True).stdout
        matched = find_groups_in_lines(output, self._default_nic_regex)[0]
        self.default_nic = matched["nic_name"]

    def _get_tx_packets(self, nic_name: str) -> int:
        output = self._node.execute(
            f"netstat -I {nic_name} -n -b | awk '{{print $9}}'",
            sudo=True,
            shell=True,
        ).stdout
        entries = output.splitlines()
        assert_that(
            entries[0], f"Could not find tx_packets for {nic_name}"
        ).is_equal_to("Opkts")
        return int(entries[1])

    def _get_rx_packets(self, nic_name: str) -> int:
        output = self._node.execute(
            f"netstat -I {nic_name} -n -b | awk '{{print $5}}'",
            sudo=True,
            shell=True,
        ).stdout
        entries = output.splitlines()
        assert_that(
            entries[0], f"Could not find rx_packets for {nic_name}"
        ).is_equal_to("Ipkts")
        return int(entries[1])

    def get_packets(self, nic_name: str, name: str = "tx_packets") -> int:
        if name == "tx_packets":
            return self._get_tx_packets(nic_name)
        elif name == "rx_packets":
            return self._get_rx_packets(nic_name)
        else:
            raise LisaException(f"Unknown packet type {name}")
