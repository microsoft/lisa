# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

import re
from typing import Dict, List, Optional, Type, cast

from assertpy import assert_that

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.tools import Cat
from lisa.tools.start_configuration import StartConfiguration
from lisa.tools.whoami import Whoami
from lisa.util import LisaException, find_patterns_in_lines


class IpInfo:
    def __init__(self, nic_name: str, mac_addr: str, ip_addr: str):
        self.nic_name = nic_name
        self.mac_addr = mac_addr
        self.ip_addr = ip_addr


class Ip(Tool):
    # 00:0d:3a:c5:13:6f
    __mac_address_pattern = re.compile(
        "[0-9a-f]{2}([-:]?)[0-9a-f]{2}(\\1[0-9a-f]{2}){4}$", re.M
    )
    __ip_details_pattern = re.compile(
        r"(\d+: \w+:[\w\W]*?)(?=\d+: \w+:|\Z)", re.MULTILINE
    )
    """
    1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000  # noqa: E501
        link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
        inet 127.0.0.1/8 scope host lo
        valid_lft forever preferred_lft forever
        inet6 ::1/128 scope host
        valid_lft forever preferred_lft forever
    3: eth1: <BROADCAST,MULTICAST> mtu 1500 qdisc noop state DOWN group default qlen 1000  # noqa: E501
        link/ether 00:15:5d:33:ff:0b brd ff:ff:ff:ff:ff:ff
    3: eth1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state ...
        UP group default qlen 1000
        link/ether 00:22:48:79:69:b4 brd ff:ff:ff:ff:ff:ff
        inet 10.0.1.4/24 brd 10.0.1.255 scope global eth1
        valid_lft forever preferred_lft forever
        inet6 fe80::222:48ff:fe79:69b4/64 scope link
        valid_lft forever preferred_lft forever
    4: enP13530s1: <BROADCAST,MULTICAST,SLAVE,UP,LOWER_UP> mtu 1500 ...
        qdisc mq master eth0 state UP group default qlen 1000
        link/ether 00:22:48:79:6c:c2 brd ff:ff:ff:ff:ff:ff
    6: ib0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 2044 qdisc mq state UP ...
        link/infiniband 00:00:09:27:fe:80:00:00:00:00:00:00:00:15:5d:...
        inet 172.16.1.118/16 brd 172.16.255.255 scope global ib0
            valid_lft forever preferred_lft forever
        inet6 fe80::215:5dff:fd33:ff7f/64 scope link
            valid_lft forever preferred_lft forever
    5: ibP257s429327: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 2044 qdisc mq state UP group default qlen 256  # noqa: E501
        link/infiniband 00:00:01:49:fe:80:00:00:00:00:00:00:00:15:5d:ff:fd:33:ff:17 brd  # noqa: E501
        00:ff:ff:ff:ff:12:40:1b:80:0a:00:00:00:00:00:00:ff:ff:ff:ff
        altname ibP257p0s0
        inet 172.16.1.14/16 scope global ibP257s429327
        valid_lft forever preferred_lft forever
        inet6 fe80::215:5dff:fd33:ff17/64 scope link
        valid_lft forever preferred_lft forever
    """
    __ip_addr_show_regex = re.compile(
        (
            r"\d+: (?P<name>\w+): \<.+\> .+\n\s+link\/(?:ether|infiniband|loopback)"
            r" (?P<mac>[0-9a-z:]+)( .+\n(?:(?:.+\n\s+|.*)altname \w+))?"
            r"(.*(?:\s+inet (?P<ip_addr>[\d.]+)\/.*\n))?"
        )
    )
    # capturing from ip route show
    # ex:
    #    default via 10.57.0.1 dev eth0 proto dhcp src 10.57.0.4 metric 100
    __dev_regex = re.compile(
        r"default via\s+"  # looking for default route
        r"[0-9a-fA-F]{1,3}\."  # identify ip address
        r"[0-9a-fA-F]{1,3}\."
        r"[0-9a-fA-F]{1,3}\."
        r"[0-9a-fA-F]{1,3}"
        r"\s+dev\s+"  # looking for the device for the default route
        r"([a-zA-Z0-9]+)"  # capture device
    )
    # -br flag gives easily parsible output
    # ex:
    # eth0             UP             00:15:5d:ff:20:68 ...
    __ip_br_show_regex = re.compile(
        r"(?P<name>\w+)\s+(?P<status>\w+)\s+(?P<mac>[0-9a-z:]+)\s+(?P<flags>\<.+\>)"
    )

    @property
    def command(self) -> str:
        return "ip"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("iproute2")
        return self._check_exists()

    @classmethod
    def _freebsd_tool(cls) -> Optional[Type[Tool]]:
        return IpFreebsd

    def _set_device_status(
        self, nic_name: str, status: str, persist: bool = False
    ) -> None:
        self.node.execute(
            f"ip link set {nic_name} {status}",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Could not set {nic_name} to '{status}'"
            ),
        )
        if persist:
            self.node.tools[StartConfiguration].add_command(
                f"ip link set {nic_name} {status}"
            )

    def _get_matched_dict(self, result: str) -> Dict[str, str]:
        matched = self.__ip_addr_show_regex.match(result)
        assert matched is not None, f"Could not parse result: {result}"
        return {
            "name": matched.group("name"),
            "mac": matched.group("mac"),
            "ip_addr": matched.group("ip_addr"),
        }

    def is_device_up(self, nic_name: str) -> bool:
        device_info = self.node.execute(
            f"ip -br link show {nic_name}",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"ip show could not get info for device {nic_name}"
            ),
        ).stdout
        matched = self.__ip_br_show_regex.match(device_info)
        assert matched is not None, f"Could not parse result: {device_info}"
        return matched.group("status") == "UP"

    def up(self, nic_name: str, persist: bool = False) -> None:
        self._set_device_status(nic_name, "up", persist=persist)

    def down(self, nic_name: str, persist: bool = False) -> None:
        self._set_device_status(nic_name, "down", persist=persist)

    def addr_flush(self, nic_name: str) -> None:
        self.node.execute(
            f"ip addr flush dev {nic_name}",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Could not flush address for device {nic_name}"
            ),
        )

    def add_ipv4_address(self, nic_name: str, ip: str, persist: bool = True) -> None:
        self.run(
            f"addr add {ip} dev {nic_name}",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Could not add address to device {nic_name}"
            ),
        )
        if persist:
            self.node.tools[StartConfiguration].add_command(
                f"ip addr add {ip} dev {nic_name}"
            )

    def restart_device(
        self,
        nic_name: str,
        run_dhclient: bool = False,
        default_route: str = "",
    ) -> None:
        cmd = f"ip link set dev {nic_name} down;ip link set dev {nic_name} up "
        dhclient_exist = self.node.execute("which dhclient", shell=True, sudo=True)
        if dhclient_exist.exit_code == 0:
            if run_dhclient:
                # if no ip address
                # firstly kill dhclient if it is running
                # then run dhclient to get ip address
                cmd += (
                    f' && (ip addr show {nic_name} | grep "inet ") || '
                    "(pidof dhclient && kill $(pidof dhclient) && "
                    f"dhclient -r {nic_name}; dhclient {nic_name})"
                )
            if default_route:
                # need add wait 1 second, for some distro, e.g.
                # redhat rhel 7-lvm 7.8.2021051701
                # the ip route will be back after nic down and up for a while
                cmd += " && sleep 1 "
                # if no default route, add it back
                cmd += " && (ip route show | grep default ||"
                cmd += f" ip route add {default_route})"
        self.node.execute(
            cmd,
            shell=True,
            sudo=True,
            nohup=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"fail to restart [down then up] the nic {nic_name}"
            ),
        )

    def get_mtu(self, nic_name: str) -> int:
        cat = self.node.tools[Cat]
        return int(cat.read(f"/sys/class/net/{nic_name}/mtu", force_run=True))

    def set_mtu(self, nic_name: str, mtu: int) -> None:
        self.run(f"link set dev {nic_name} mtu {mtu}", force_run=True, sudo=True)
        new_mtu = self.get_mtu(nic_name=nic_name)
        assert_that(new_mtu).described_as("set mtu failed").is_equal_to(mtu)

    def nic_exists(self, nic_name: str) -> bool:
        result = self.run(f"link show {nic_name}", force_run=True, sudo=True)
        return not (
            (result.stderr and "not exist" in result.stderr)
            or (result.stdout and "not exist" in result.stdout)
        )

    def get_mac(self, nic_name: str) -> str:
        result = self.run(f"addr show {nic_name}", force_run=True, sudo=True)
        matched = self._get_matched_dict(result.stdout)
        assert "mac" in matched, f"not find mac address for nic {nic_name}"
        return matched["mac"]

    def get_info(self, nic_name: Optional[str] = None) -> List[IpInfo]:
        command = "addr show"
        if nic_name:
            command += f" {nic_name}"
        result = self.run(
            command,
            shell=True,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Could not run {command} on node {self.node.name}"
            ),
        )
        raw_list = re.finditer(self.__ip_details_pattern, result.stdout)
        found_nics: List[IpInfo] = []
        for ip_raw in raw_list:
            matched = self._get_matched_dict(ip_raw.group())
            found_nics.append(
                IpInfo(
                    nic_name=matched["name"],
                    mac_addr=matched["mac"],
                    ip_addr=matched["ip_addr"],
                )
            )
        return found_nics

    def setup_bridge(self, name: str, ip: str) -> None:
        if self.nic_exists(name):
            self._log.debug(f"Bridge {name} already exists")
            return

        # create bridge
        self.run(
            f"link add {name} type bridge",
            force_run=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"Could not create bridge {name}",
        )
        self.add_ipv4_address(name, ip)
        self.up(name)

    def set_bridge_configuration(self, name: str, key: str, value: str) -> None:
        self.run(
            f"link set dev {name} type bridge {key} {value}",
            force_run=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Could not set bridge {name} configuation: {key} {value}"
            ),
        )
        self.restart_device(name)

    def delete_interface(self, name: str) -> None:
        # check if the interface exists
        if not self.nic_exists(name):
            self._log.debug(f"Interface {name} does not exist")
            return

        # delete interface
        self.down(name)
        self.run(
            f"link delete {name}",
            force_run=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"Could not delete interface {name}",
        )

    def set_master(self, child_interface: str, master_interface: str) -> None:
        self.run(
            f"link set dev {child_interface} master {master_interface}",
            force_run=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Could not set bridge {master_interface} as master for"
                f" {child_interface}"
            ),
        )

    def setup_tap(self, name: str, bridge: str) -> None:
        if self.nic_exists(name):
            self._log.debug(f"Tap {name} already exists")
            return

        # create tap
        user = self.node.tools[Whoami].run().stdout.strip()
        self.run(
            f"tuntap add {name} mode tap user {user} multi_queue",
            force_run=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"Could not create tap {name}",
        )

        # add tap to bridge
        self.set_master(name, bridge)

        # start interface
        self.up(name)

    def get_ip_address(self, nic_name: str) -> str:
        log.info("Received NIC Name:", nic_name)
        result = self.run(f"addr show {nic_name}", force_run=True, sudo=True)
        matched = self._get_matched_dict(result.stdout)
        assert "ip_addr" in matched, f"not find ip address for nic {nic_name}"
        return matched["ip_addr"]

    def get_default_route_info(self) -> tuple[str, str]:
        result = self.run("route", force_run=True, sudo=True)
        result.assert_exit_code()
        assert_that(result.stdout).is_not_empty()
        dev_match = self.__dev_regex.search(result.stdout)
        if not dev_match or not dev_match.groups():
            raise LisaException(
                "Could not locate default network interface"
                f" in output:\n{result.stdout}"
            )
        assert_that(dev_match.groups()).is_length(1)
        return dev_match.group(1), dev_match.group()

    def add_route_to(self, dest: str, via: str, dev: str) -> None:
        # Add a route to a specific destination (prefix or ip addr)
        # via an IP and a specific interface.
        # useful for l3fwd test where we send traffic to an NVA-like
        # router/forwarder
        self.run(
            f"route add {dest} via {via} dev {dev}",
            sudo=True,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Could not add ip route to {dest} via {via} through dev {dev}"
            ),
        )

    def remove_all_routes_for_device(self, device: str) -> None:
        # get any routes going through a specific nic and remove them.
        log.info(f"Removing all routes for device {device}")
        all_routes = self.run(
            "route",
            force_run=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "ip route del: could not fetch routes with ip route"
            ),
        ).stdout.splitlines()
        delete_routes = []
        for route in all_routes:
            if f"dev {device}" in route:
                delete_routes.append(route)
        if len(delete_routes) == 0:
            self._log.warn(
                f"Ip tool found no routes for {device}"
                " during remove_all_routes_for_device!"
            )
        for route in delete_routes:
            self.run(
                f"route del {route}",
                sudo=True,
                force_run=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=f"Could not delete route: {route}",
            )

    def route_exists(self, prefix: str, dev: str = "") -> bool:
        # get any routes going through a specific nic and remove them.
        all_routes = self.run(
            "route",
            force_run=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "ip route del: could not fetch routes with ip route"
            ),
        ).stdout.splitlines()
        found_routes = []
        for route in all_routes:
            if route.startswith(prefix) and (not dev or f"dev {dev}" in route):
                found_routes.append(route)
        if found_routes:
            log_routes = "\n".join(found_routes)
            self._log.debug(f"found routes: {log_routes}")
        return len(found_routes) > 0

    def get_interface_list(self) -> list[str]:
        raise NotImplementedError()


class IpFreebsd(Ip):
    # ether 00:22:48:ba:0a:39
    __mac_address_pattern = re.compile(
        r"ether\s+(?P<mac>(?:[0-9A-Fa-f]{2}[:-]){5}(?:[0-9A-Fa-f]{2}))"
    )

    # inet 172.20.0.7
    __ip_address_pattern = re.compile(
        r"inet\s+(?P<ip_addr>(?:[0-9]{1,3}\.){3}[0-9]{1,3})"
    )

    @property
    def command(self) -> str:
        return "ifconfig"

    def get_interface_list(self) -> list[str]:
        output = self.run(
            "-l",
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to get interface list",
        )
        return output.stdout.split()

    def get_mac(self, nic_name: str) -> str:
        output = self.run(
            nic_name,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to get mac address",
        ).stdout
        matched = find_patterns_in_lines(output, [self.__mac_address_pattern])
        assert_that(matched).described_as("could not find mac address").is_length(1)
        return str(matched[0][0])

    def get_ip_address(self, nic_name: str) -> str:
        output = self.run(
            nic_name,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to get ip address",
        ).stdout
        matched = find_patterns_in_lines(output, [self.__ip_address_pattern])
        assert_that(matched[0]).described_as("could not find ip address").is_length(1)
        return str(matched[0][0])

    def down(self, nic_name: str, persist: bool = False) -> None:
        self.run(
            f"{nic_name} down",
            force_run=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(f"Could not set {nic_name} to down"),
        )

    def up(self, nic_name: str, persist: bool = False) -> None:
        self.run(
            f"{nic_name} up",
            force_run=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(f"Could not set {nic_name} to up"),
        )
