# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import ipaddress
import re
import shlex
import time
from abc import ABC, abstractmethod
from pathlib import Path, PurePath
from typing import Any, List, Optional, Type, cast

from lisa import schema, search_space
from lisa.feature import Features
from lisa.node import Node, RemoteNode
from lisa.tools import Dnsmasq, Ip, Kill, Ls, Mkdir, Modprobe, OpenVmm
from lisa.tools.openvmm import OpenVmmLaunchConfig
from lisa.util import LisaException
from lisa.util.logger import Logger
from lisa.util.shell import wait_tcp_port_ready

from .. import OPENVMM
from .context import get_node_context
from .schema import (
    OPENVMM_ADDRESS_MODE_STATIC,
    OPENVMM_NETWORK_MODE_NONE,
    OPENVMM_NETWORK_MODE_TAP,
    OpenVmmGuestNodeSchema,
    OpenVmmNetworkSchema,
)
from .start_stop import StartStop


OPENVMM_CONNECTION_TIMEOUT = 300
OPENVMM_IP_DISCOVERY_TIMEOUT = 300
OPENVMM_LOG_TAIL_LINES = 40


def _get_tap_host_interface_name(network: OpenVmmNetworkSchema) -> str:
    return network.bridge_name or network.tap_name


def _countspace_to_int(value: search_space.CountSpace) -> int:
    chosen = search_space.choose_value_countspace(value, value)
    assert isinstance(chosen, int), f"expected int countspace, got {type(chosen)}"
    return chosen


class GuestIpResolver(ABC):
    @abstractmethod
    def resolve(
        self,
        host: Node,
        node_context: Any,
        network: OpenVmmNetworkSchema,
        log: Logger,
    ) -> str:
        pass


class StaticAddressResolver(GuestIpResolver):
    def resolve(
        self,
        host: Node,
        node_context: Any,
        network: OpenVmmNetworkSchema,
        log: Logger,
    ) -> str:
        if not network.guest_address:
            raise LisaException(
                "guest_address is required when "
                "address_mode is 'static'"
            )
        return network.guest_address


class NeighborTableResolver(GuestIpResolver):
    _IPV4_NEIGHBOR_PATTERN = re.compile(
        r"^(?P<address>\d+\.\d+\.\d+\.\d+)\s+.*\s"
        r"(?P<state>REACHABLE|STALE|DELAY|PROBE|PERMANENT)$"
    )

    def resolve(
        self,
        host: Node,
        node_context: Any,
        network: OpenVmmNetworkSchema,
        log: Logger,
    ) -> str:
        interface_name = _get_tap_host_interface_name(network)
        deadline = time.time() + OPENVMM_IP_DISCOVERY_TIMEOUT
        while time.time() < deadline:
            if not self._tap_interface_exists(host, interface_name):
                time.sleep(1)
                continue

            addresses = self._get_candidate_addresses(host, interface_name)
            if len(addresses) == 1:
                log.debug(
                    f"discovered OpenVMM guest IP '{addresses[0]}' on host "
                    f"interface '{interface_name}'"
                )
                return addresses[0]
            if len(addresses) > 1:
                raise LisaException(
                    "multiple candidate guest addresses were discovered on host "
                    f"interface '{interface_name}': {addresses}. "
                    "Set network.address_mode to 'static' and provide "
                    "guest_address to disambiguate."
                )
            time.sleep(1)

        raise LisaException(
            "failed to discover the OpenVMM guest IP on host interface "
            f"'{interface_name}'. Provide network.guest_address with "
            "address_mode 'static', or use a host-side network setup that "
            "makes the guest address discoverable."
        )

    def _tap_interface_exists(self, host: Node, tap_name: str) -> bool:
        result = host.tools[Ip].run(
            f"link show dev {tap_name}",
            sudo=True,
            force_run=True,
            expected_exit_code=None,
        )
        return result.exit_code == 0

    def _get_candidate_addresses(self, host: Node, tap_name: str) -> List[str]:
        result = host.tools[Ip].run(
            f"-4 neigh show dev {tap_name}",
            sudo=True,
            force_run=True,
            expected_exit_code=None,
        )

        if result.exit_code != 0:
            output = f"{result.stdout}\n{result.stderr}".lower()
            if "cannot find device" in output or "does not exist" in output:
                return []
            raise LisaException(
                f"failed to inspect neighbor table on tap interface {tap_name}. "
                f"stdout: {result.stdout.strip()} stderr: {result.stderr.strip()}"
            )

        addresses: List[str] = []
        for line in result.stdout.splitlines():
            matched = self._IPV4_NEIGHBOR_PATTERN.match(line.strip())
            if matched:
                addresses.append(matched.group("address"))
        return addresses


class OpenVmmController:
    def __init__(self, node: "OpenVmmGuestNode") -> None:
        self._node = node
        assert node.parent, "OpenVMM guest node must have a parent host node"
        self.host_node = node.parent
        self._log = node.log

    @classmethod
    def type_name(cls) -> str:
        return OPENVMM

    @classmethod
    def supported_features(cls) -> List[Type[Any]]:
        return [StartStop]

    def resolve_guest_artifact_path(
        self, source_path: str, is_remote_path: bool, working_path: PurePath
    ) -> str:
        if not source_path:
            return ""

        if is_remote_path or not self.host_node.is_remote:
            return source_path

        source = Path(source_path)
        if not source.exists():
            raise LisaException(f"file does not exist: {source_path}")

        destination = working_path / source.name
        if not self.host_node.tools[Ls].path_exists(str(destination), sudo=True):
            self.host_node.shell.copy(source, destination)
        return str(destination)

    def get_openvmm_tool(self, binary_path: str) -> OpenVmm:
        openvmm = cast(OpenVmm, OpenVmm.create(self.host_node))
        openvmm.initialize()
        requested_path = binary_path or "openvmm"
        openvmm.set_binary_path(requested_path)
        if not openvmm.exists and requested_path != "openvmm":
            self._log.debug(
                f"OpenVMM binary '{requested_path}' was not found; "
                "falling back to 'openvmm' from PATH"
            )
            openvmm.set_binary_path("openvmm")
        return openvmm

    def launch(self, node: "OpenVmmGuestNode", log: Logger) -> None:
        runbook = cast(OpenVmmGuestNodeSchema, node.runbook)
        node_context = get_node_context(node)
        self._prepare_tap_network(runbook.network, node_context)
        launch_config = OpenVmmLaunchConfig(
            uefi_firmware_path=node_context.uefi_firmware_path,
            disk_img_path=node_context.disk_img_path,
            processors=_countspace_to_int(node.capability.core_count),
            memory_mb=_countspace_to_int(node.capability.memory_mb),
            network_mode=runbook.network.mode,
            tap_name=runbook.network.tap_name,
            network_cidr=runbook.network.consomme_cidr,
            serial_mode=runbook.serial.mode,
            serial_path=node_context.console_log_file_path,
            extra_args=runbook.extra_args,
            stdout_path=node_context.launcher_log_file_path,
            stderr_path=node_context.launcher_log_file_path,
        )
        openvmm = self.get_openvmm_tool(runbook.openvmm_binary)
        node_context.command_line = openvmm.build_command(launch_config)
        node_context.process_id = openvmm.launch_vm(
            launch_config,
            cwd=PurePath(node_context.working_path),
        )
        self._ensure_process_running(node_context, runbook.network)
        log.debug(
            f"Launched OpenVMM VM '{node_context.vm_name}' with pid "
            f"{node_context.process_id}"
        )

    def _prepare_tap_network(
        self,
        network: OpenVmmNetworkSchema,
        node_context: Any,
    ) -> None:
        if network.mode != OPENVMM_NETWORK_MODE_TAP:
            return

        tap_name = network.tap_name
        bridge_name = network.bridge_name
        host = self.host_node
        ip_tool = host.tools[Ip]
        host_interface_name = _get_tap_host_interface_name(network)
        tap_gateway, dhcp_range = self._get_tap_network_config(network)

        if bridge_name:
            self._disable_bridge_netfilter()

            if not ip_tool.nic_exists(bridge_name):
                ip_tool.create_virtual_interface(bridge_name, "bridge")
                node_context.tap_bridge_created = True
            host.execute(
                f"ip link set dev {shlex.quote(bridge_name)} type bridge stp_state 0",
                shell=True,
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    f"failed to disable STP on OpenVMM bridge {bridge_name}"
                ),
            )
            host.execute(
                f"ip link set dev {shlex.quote(bridge_name)} type bridge forward_delay 0",
                shell=True,
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    f"failed to set bridge forward delay on {bridge_name}"
                ),
            )
            host.execute(
                (
                    f"ip addr replace {shlex.quote(network.tap_host_cidr)} "
                    f"dev {shlex.quote(bridge_name)}"
                ),
                shell=True,
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    f"failed to configure OpenVMM bridge interface {bridge_name}"
                ),
            )
            ip_tool.up(bridge_name)

        if not ip_tool.nic_exists(tap_name):
            username = host.execute(
                "whoami",
                shell=True,
                no_info_log=True,
                no_error_log=True,
            ).stdout.strip()
            host.execute(
                (
                    f"ip tuntap add {shlex.quote(tap_name)} mode tap "
                    f"user {shlex.quote(username)} multi_queue vnet_hdr"
                ),
                shell=True,
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    f"failed to create OpenVMM tap interface {tap_name}"
                ),
            )
            node_context.tap_created = True

        if bridge_name:
            ip_tool.set_master(tap_name, bridge_name)

        if not bridge_name:
            host.execute(
                (
                    f"ip addr replace {shlex.quote(network.tap_host_cidr)} "
                    f"dev {shlex.quote(tap_name)}"
                ),
                shell=True,
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    f"failed to configure OpenVMM tap interface {tap_name}"
                ),
            )
        ip_tool.up(tap_name)

        if network.address_mode != OPENVMM_ADDRESS_MODE_STATIC:
            lease_file = f"/var/run/qemu-dnsmasq-{host_interface_name}.leases"
            host.execute(f"cp /dev/null {lease_file}", shell=True, sudo=True)
            host.tools[Dnsmasq].start(host_interface_name, tap_gateway, dhcp_range)
            node_context.tap_dnsmasq_pid_file = (
                f"/var/run/qemu-dnsmasq-{host_interface_name}.pid"
            )
            node_context.tap_dnsmasq_lease_file = lease_file

        self._log_tap_network_state(network, node_context)
        if node_context.tap_dnsmasq_pid_file:
            self._log_dnsmasq_state(node_context)

    def _disable_bridge_netfilter(self) -> None:
        host = self.host_node
        modprobe = host.tools[Modprobe]
        if modprobe.module_exists("br_netfilter") and not modprobe.is_module_loaded(
            "br_netfilter", force_run=True
        ):
            modprobe.load("br_netfilter")

        for key in [
            "net.bridge.bridge-nf-call-iptables",
            "net.bridge.bridge-nf-call-arptables",
            "net.bridge.bridge-nf-call-ip6tables",
        ]:
            host.execute(
                f"sysctl -w {shlex.quote(key)}=0 >/dev/null 2>&1 || true",
                shell=True,
                sudo=True,
                expected_exit_code=0,
            )

    def _get_tap_network_config(
        self, network: OpenVmmNetworkSchema
    ) -> tuple[str, str]:
        host_interface = ipaddress.ip_interface(network.tap_host_cidr)
        guest_ip = network.guest_address
        if not guest_ip:
            for address in host_interface.network.hosts():
                if address != host_interface.ip:
                    guest_ip = str(address)
                    break

        if not guest_ip:
            raise LisaException(
                "failed to derive a guest IP for OpenVMM tap networking from "
                f"'{network.tap_host_cidr}'. Provide network.guest_address."
            )

        return str(host_interface.ip), f"{guest_ip},{guest_ip}"

    def configure_connection(self, node: RemoteNode, log: Logger) -> None:
        runbook = cast(OpenVmmGuestNodeSchema, node.runbook)
        network = runbook.network
        node_context = get_node_context(node)

        if network.mode == OPENVMM_NETWORK_MODE_NONE:
            return

        guest_address = self._resolve_guest_address(node_context, network, log)
        node_context.guest_address = guest_address

        address = guest_address
        public_address = network.connection_address or guest_address
        port = network.ssh_port
        public_port = port

        if network.forward_ssh_port:
            self._enable_ssh_forwarding(node_context, guest_address, network)
            public_address = (
                network.connection_address or self._get_host_public_address()
            )
            public_port = network.forwarded_port
            node_context.forwarded_port = network.forwarded_port
            node_context.forwarding_enabled = True

        node.set_connection_info(
            address=address,
            public_address=public_address,
            username=runbook.username,
            password=runbook.password,
            private_key_file=runbook.private_key_file,
            port=port,
            public_port=public_port,
        )
        try:
            wait_tcp_port_ready(
                public_address,
                public_port,
                log=log,
                timeout=OPENVMM_CONNECTION_TIMEOUT,
            )
        except Exception as identifier_error:
            raise LisaException(
                "OpenVMM guest SSH port did not become reachable. "
                f"{self._get_openvmm_failure_context(node_context, runbook.network)}"
            ) from identifier_error

    def _resolve_guest_address(
        self,
        node_context: Any,
        network: OpenVmmNetworkSchema,
        log: Logger,
    ) -> str:
        if network.mode == OPENVMM_NETWORK_MODE_NONE:
            return ""

        resolver: GuestIpResolver
        if network.address_mode == OPENVMM_ADDRESS_MODE_STATIC:
            resolver = StaticAddressResolver()
        elif network.mode == OPENVMM_NETWORK_MODE_TAP:
            return self._get_tap_guest_address(node_context, network, log)
        else:
            raise LisaException(
                "address discovery is supported only for tap networking. "
                "Use address_mode 'static' for other network modes."
            )

        return resolver.resolve(self.host_node, node_context, network, log)

    def _get_tap_guest_address(
        self,
        node_context: Any,
        network: OpenVmmNetworkSchema,
        log: Logger,
    ) -> str:
        _, dhcp_range = self._get_tap_network_config(network)
        guest_address = dhcp_range.split(",", maxsplit=1)[0].strip()
        if not guest_address:
            raise LisaException(
                "failed to derive the OpenVMM guest IP from "
                f"'{network.tap_host_cidr}'"
            )
        self._wait_for_tap_lease(node_context, guest_address, log, network)
        return guest_address

    def _wait_for_tap_lease(
        self,
        node_context: Any,
        guest_address: str,
        log: Logger,
        network: Optional[OpenVmmNetworkSchema] = None,
        timeout: int = OPENVMM_IP_DISCOVERY_TIMEOUT,
    ) -> None:
        lease_file = node_context.tap_dnsmasq_lease_file
        if not lease_file:
            raise LisaException(
                "OpenVMM TAP DHCP lease tracking is not configured. "
                "dnsmasq lease file path was not recorded."
            )

        deadline = time.time() + timeout
        while time.time() < deadline:
            result = self.host_node.execute(
                f"test -f {shlex.quote(lease_file)} && cat {shlex.quote(lease_file)} || true",
                shell=True,
                sudo=True,
                no_info_log=True,
                no_error_log=True,
                expected_exit_code=0,
            )
            lease_contents = result.stdout.strip()
            if guest_address in lease_contents:
                log.debug(
                    f"confirmed OpenVMM guest DHCP lease '{guest_address}' in {lease_file}"
                )
                return
            if not self._is_process_running(node_context.process_id):
                raise LisaException(
                    "OpenVMM process exited before the guest acquired the expected "
                    f"DHCP lease '{guest_address}'. "
                    f"{self._get_openvmm_failure_context(node_context, network)}"
                )
            time.sleep(1)

        raise LisaException(
            "OpenVMM guest did not acquire the expected DHCP lease "
            f"'{guest_address}' on '{lease_file}'. "
            f"{self._get_openvmm_failure_context(node_context, None)}"
        )

    def _get_openvmm_failure_context(
        self,
        node_context: Any,
        network: Optional[OpenVmmNetworkSchema],
    ) -> str:
        details: list[str] = []

        network_state = self._capture_tap_network_state(network)
        if network_state:
            details.append(network_state)

        dnsmasq_state = self._capture_dnsmasq_state(node_context)
        if dnsmasq_state:
            details.append(dnsmasq_state)

        process_state = self._capture_process_state(node_context)
        if process_state:
            details.append(process_state)

        forwarding_state = self._capture_forwarding_state(node_context, network)
        if forwarding_state:
            details.append(forwarding_state)

        if node_context.tap_dnsmasq_lease_file:
            lease_result = self.host_node.execute(
                (
                    f"test -f {shlex.quote(node_context.tap_dnsmasq_lease_file)} && "
                    f"tail -n {OPENVMM_LOG_TAIL_LINES} {shlex.quote(node_context.tap_dnsmasq_lease_file)} || true"
                ),
                shell=True,
                sudo=True,
                no_info_log=True,
                no_error_log=True,
                expected_exit_code=0,
            )
            lease_output = lease_result.stdout.strip()
            details.append(
                "lease tail: " + (lease_output if lease_output else "<empty>")
            )

        for label, path in [
            ("console tail", node_context.console_log_file_path),
            ("launcher tail", node_context.launcher_log_file_path),
        ]:
            if not path:
                continue
            result = self.host_node.execute(
                (
                    f"test -f {shlex.quote(path)} && "
                    f"tail -n {OPENVMM_LOG_TAIL_LINES} {shlex.quote(path)} || true"
                ),
                shell=True,
                sudo=True,
                no_info_log=True,
                no_error_log=True,
                expected_exit_code=0,
            )
            output = result.stdout.strip()
            details.append(f"{label}: " + (output if output else "<empty>"))

        return " | ".join(details)

    def _log_tap_network_state(
        self,
        network: OpenVmmNetworkSchema,
        node_context: Any,
    ) -> None:
        state = self._capture_tap_network_state(network)
        if state:
            self._log.debug(state)

    def _capture_tap_network_state(
        self,
        network: Optional[OpenVmmNetworkSchema],
    ) -> str:
        if not network or network.mode != OPENVMM_NETWORK_MODE_TAP:
            return ""

        host_interface = _get_tap_host_interface_name(network)
        commands = [
            (
                "host interface addr",
                f"ip addr show dev {shlex.quote(host_interface)} 2>/dev/null || true",
            ),
            (
                "host interface link",
                f"ip link show dev {shlex.quote(host_interface)} 2>/dev/null || true",
            ),
            (
                "tap link",
                f"ip link show dev {shlex.quote(network.tap_name)} 2>/dev/null || true",
            ),
        ]
        if network.bridge_name:
            commands.append(
                (
                    "bridge members",
                    f"bridge link show master {shlex.quote(network.bridge_name)} 2>/dev/null || true",
                )
            )

        outputs = self._capture_command_outputs(commands)
        return "tap network state: " + " | ".join(outputs) if outputs else ""

    def _log_dnsmasq_state(self, node_context: Any) -> None:
        state = self._capture_dnsmasq_state(node_context)
        if state:
            self._log.debug(state)

    def _capture_dnsmasq_state(self, node_context: Any) -> str:
        commands: list[tuple[str, str]] = []
        if node_context.tap_dnsmasq_pid_file:
            commands.append(
                (
                    "dnsmasq pid",
                    (
                        f"test -f {shlex.quote(node_context.tap_dnsmasq_pid_file)} && "
                        f"cat {shlex.quote(node_context.tap_dnsmasq_pid_file)} || true"
                    ),
                )
            )
        if node_context.tap_dnsmasq_lease_file:
            commands.append(
                (
                    "dnsmasq lease tail",
                    (
                        f"test -f {shlex.quote(node_context.tap_dnsmasq_lease_file)} && "
                        f"tail -n {OPENVMM_LOG_TAIL_LINES} {shlex.quote(node_context.tap_dnsmasq_lease_file)} || true"
                    ),
                )
            )

        outputs = self._capture_command_outputs(commands)
        return "dnsmasq state: " + " | ".join(outputs) if outputs else ""

    def _capture_process_state(self, node_context: Any) -> str:
        if not node_context.process_id:
            return ""

        process_id = shlex.quote(node_context.process_id)
        commands = [
            (
                "openvmm process status",
                f"ps -p {process_id} -o pid=,ppid=,stat=,etime=,cmd= 2>/dev/null || true",
            ),
        ]
        outputs = self._capture_command_outputs(commands)
        return "process state: " + " | ".join(outputs) if outputs else ""

    def _capture_forwarding_state(
        self,
        node_context: Any,
        network: Optional[OpenVmmNetworkSchema],
    ) -> str:
        if not network or not node_context.forwarded_port:
            return ""

        guest_address = str(node_context.guest_address or "")
        if not guest_address:
            return ""
        match_pattern = shlex.quote(
            f"{node_context.forwarded_port}|{guest_address}"
        )
        commands = [
            (
                "forward filter rules",
                (
                    "iptables -S FORWARD 2>/dev/null | "
                    f"grep -E {match_pattern} || true"
                ),
            ),
            (
                "forward nat rules",
                (
                    "iptables -t nat -S 2>/dev/null | "
                    f"grep -E {match_pattern} || true"
                ),
            ),
        ]
        outputs = self._capture_command_outputs(commands)
        return "forwarding state: " + " | ".join(outputs) if outputs else ""

    def _capture_command_outputs(self, commands: list[tuple[str, str]]) -> list[str]:
        outputs: list[str] = []
        for label, command in commands:
            result = self.host_node.execute(
                command,
                shell=True,
                sudo=True,
                no_info_log=True,
                no_error_log=True,
                expected_exit_code=0,
            )
            output = result.stdout.strip()
            outputs.append(f"{label}: {output if output else '<empty>'}")
        return outputs

    def stop_node(self, node: Node, wait: bool = True) -> None:
        node_context = get_node_context(node)
        self._disable_ssh_forwarding(node)
        if node.is_connected:
            node.execute(
                "shutdown -P now",
                shell=True,
                sudo=True,
                no_info_log=True,
                no_error_log=True,
                expected_exit_code=None,
            )

        if wait and node_context.process_id:
            self._wait_for_process_exit(node_context.process_id)

        if node_context.process_id:
            self.host_node.tools[Kill].by_pid(
                node_context.process_id,
                ignore_not_exist=True,
            )
            node_context.process_id = ""

        self._teardown_tap_network(
            node_context,
            cast(OpenVmmGuestNodeSchema, node.runbook).network,
        )

    def start_node(self, node: "OpenVmmGuestNode", wait: bool = True) -> None:
        self.launch(node, node.log)
        self.configure_connection(node, node.log)

    def restart_node(self, node: "OpenVmmGuestNode", wait: bool = True) -> None:
        self.stop_node(node, wait=wait)
        self.start_node(node, wait=wait)

    def _get_host_public_address(self) -> str:
        if self.host_node.is_remote:
            return cast(RemoteNode, self.host_node).public_address
        return "127.0.0.1"

    def _enable_ssh_forwarding(
        self,
        node_context: Any,
        guest_address: str,
        network: OpenVmmNetworkSchema,
    ) -> None:
        forwarding_interface, _ = self.host_node.tools[Ip].get_default_route_info()
        host_interface = _get_tap_host_interface_name(network)
        host_network = ipaddress.ip_interface(network.tap_host_cidr).network
        guest_address = shlex.quote(guest_address)
        guest_port = network.ssh_port
        forwarded_port = network.forwarded_port
        commands = [
            "sysctl -w net.ipv4.ip_forward=1",
            (
                "iptables -C FORWARD -i "
                f"{shlex.quote(host_interface)} -o {shlex.quote(forwarding_interface)} "
                "-j ACCEPT "
                "|| "
                "iptables -I FORWARD -i "
                f"{shlex.quote(host_interface)} -o {shlex.quote(forwarding_interface)} "
                "-j ACCEPT"
            ),
            (
                "iptables -C FORWARD -i "
                f"{shlex.quote(forwarding_interface)} -o {shlex.quote(host_interface)} "
                "-m state --state RELATED,ESTABLISHED -j ACCEPT "
                "|| "
                "iptables -I FORWARD -i "
                f"{shlex.quote(forwarding_interface)} -o {shlex.quote(host_interface)} "
                "-m state --state RELATED,ESTABLISHED -j ACCEPT"
            ),
            (
                "iptables -C FORWARD -i "
                f"{shlex.quote(forwarding_interface)} -o {shlex.quote(host_interface)} "
                f"-p tcp -d {guest_address} --dport {guest_port} -j ACCEPT "
                "|| "
                "iptables -I FORWARD -i "
                f"{shlex.quote(forwarding_interface)} -o {shlex.quote(host_interface)} "
                f"-p tcp -d {guest_address} --dport {guest_port} -j ACCEPT"
            ),
            (
                "iptables -t nat -C POSTROUTING -s "
                f"{shlex.quote(str(host_network))} -o {shlex.quote(forwarding_interface)} "
                "-j MASQUERADE || "
                "iptables -t nat -I POSTROUTING -s "
                f"{shlex.quote(str(host_network))} -o {shlex.quote(forwarding_interface)} "
                "-j MASQUERADE"
            ),
            (
                "iptables -t nat -C PREROUTING -p tcp --dport "
                f"{forwarded_port} -j DNAT --to-destination {guest_address}:{guest_port} "
                "|| "
                "iptables -t nat -I PREROUTING -p tcp --dport "
                f"{forwarded_port} -j DNAT --to-destination {guest_address}:{guest_port}"
            ),
            (
                "iptables -t nat -C OUTPUT -p tcp --dport "
                f"{forwarded_port} -j DNAT --to-destination {guest_address}:{guest_port} "
                "|| "
                "iptables -t nat -I OUTPUT -p tcp --dport "
                f"{forwarded_port} -j DNAT --to-destination {guest_address}:{guest_port}"
            ),
        ]
        for command in commands:
            self.host_node.execute(
                command,
                shell=True,
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "failed to configure OpenVMM SSH forwarding"
                ),
            )
        node_context.forwarding_interface = forwarding_interface

    def _disable_ssh_forwarding(self, node: Node) -> None:
        node_context = get_node_context(node)
        if not node_context.forwarding_enabled or not node_context.forwarded_port:
            return

        guest_address = shlex.quote(node_context.guest_address)
        guest_port = node_context.ssh_port
        forwarded_port = node_context.forwarded_port
        forwarding_interface = node_context.forwarding_interface
        host_interface = _get_tap_host_interface_name(
            cast(OpenVmmGuestNodeSchema, node.runbook).network
        )
        host_network = ipaddress.ip_interface(
            cast(OpenVmmGuestNodeSchema, node.runbook).network.tap_host_cidr
        ).network
        commands = [
            (
                "iptables -D FORWARD -i "
                f"{shlex.quote(host_interface)} -o {shlex.quote(forwarding_interface)} "
                "-j ACCEPT || true"
            ),
            (
                "iptables -D FORWARD -i "
                f"{shlex.quote(forwarding_interface)} -o {shlex.quote(host_interface)} "
                "-m state --state RELATED,ESTABLISHED -j ACCEPT || true"
            ),
            (
                "iptables -D FORWARD -i "
                f"{shlex.quote(forwarding_interface)} -o {shlex.quote(host_interface)} "
                f"-p tcp -d {guest_address} --dport {guest_port} -j ACCEPT || true"
            ),
            (
                "iptables -t nat -D PREROUTING -p tcp --dport "
                f"{forwarded_port} -j DNAT --to-destination "
                f"{guest_address}:{guest_port} || true"
            ),
            (
                "iptables -t nat -D OUTPUT -p tcp --dport "
                f"{forwarded_port} -j DNAT --to-destination "
                f"{guest_address}:{guest_port} || true"
            ),
            (
                "iptables -t nat -D POSTROUTING -s "
                f"{shlex.quote(str(host_network))} -o {shlex.quote(forwarding_interface)} "
                "-j MASQUERADE || true"
            ),
        ]
        for command in commands:
            self.host_node.execute(
                command,
                shell=True,
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "failed to remove OpenVMM SSH forwarding"
                ),
            )

        node_context.forwarded_port = 0
        node_context.forwarding_enabled = False
        node_context.forwarding_interface = ""

    def _wait_for_process_exit(self, process_id: str, timeout: int = 60) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self._is_process_running(process_id):
                return
            time.sleep(1)

    def _ensure_process_running(
        self,
        node_context: Any,
        network: OpenVmmNetworkSchema,
        grace_period: int = 2,
    ) -> None:
        if grace_period > 0:
            time.sleep(grace_period)

        if self._is_process_running(node_context.process_id):
            return

        raise LisaException(
            "OpenVMM process exited immediately after launch. "
            f"{self._get_openvmm_failure_context(node_context, network)}"
        )

    def _is_process_running(self, process_id: str) -> bool:
        if not process_id:
            return False

        result = self.host_node.execute(
            f"kill -0 {shlex.quote(process_id)}",
            shell=True,
            sudo=True,
            no_info_log=True,
            no_error_log=True,
            expected_exit_code=None,
        )
        return result.exit_code == 0

    def _teardown_tap_network(
        self,
        node_context: Any,
        network: OpenVmmNetworkSchema,
    ) -> None:
        if network.mode != OPENVMM_NETWORK_MODE_TAP:
            return

        if node_context.tap_dnsmasq_pid_file:
            self.host_node.execute(
                (
                    f"test -f {shlex.quote(node_context.tap_dnsmasq_pid_file)} && "
                    f"kill $(cat {shlex.quote(node_context.tap_dnsmasq_pid_file)}) || true"
                ),
                shell=True,
                sudo=True,
                expected_exit_code=0,
            )
            node_context.tap_dnsmasq_pid_file = ""
            node_context.tap_dnsmasq_lease_file = ""

        if node_context.tap_created:
            self.host_node.execute(
                f"ip link delete {shlex.quote(network.tap_name)} || true",
                shell=True,
                sudo=True,
                expected_exit_code=0,
            )
            node_context.tap_created = False

        if node_context.tap_bridge_created and network.bridge_name:
            self.host_node.execute(
                f"ip link delete {shlex.quote(network.bridge_name)} || true",
                shell=True,
                sudo=True,
                expected_exit_code=0,
            )
            node_context.tap_bridge_created = False


class OpenVmmGuestNode(RemoteNode):
    def __init__(
        self,
        runbook: schema.Node,
        index: int,
        logger_name: str,
        is_test_target: bool = True,
        base_part_path: Optional[Path] = None,
        parent_logger: Optional[Logger] = None,
        encoding: str = "utf-8",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            runbook=runbook,
            index=index,
            logger_name=logger_name,
            is_test_target=is_test_target,
            base_part_path=base_part_path,
            parent_logger=parent_logger,
            encoding=encoding,
            **kwargs,
        )
        self._openvmm_controller = OpenVmmController(self)
        self._initialize_capability()
        self.features = Features(self, cast(Any, self._openvmm_controller))

    @classmethod
    def type_name(cls) -> str:
        return OPENVMM

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return OpenVmmGuestNodeSchema

    def cleanup(self) -> None:
        try:
            self._openvmm_controller.stop_node(self, wait=False)
        except Exception as identifier:
            self.log.debug(f"failed to stop OpenVMM guest during cleanup: {identifier}")
        super().cleanup()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._provision()
        super()._initialize(*args, **kwargs)

    def _provision(self) -> None:
        assert self.parent, "OpenVMM guest node must have a parent host node"
        self.parent.initialize()
        runbook = cast(OpenVmmGuestNodeSchema, self.runbook)

        host_node = self.parent
        openvmm = self._openvmm_controller.get_openvmm_tool(runbook.openvmm_binary)
        if not openvmm.exists:
            raise LisaException(
                f"OpenVMM binary not found on host: {runbook.openvmm_binary}. "
                "Use the openvmm_installer transformer before provisioning guests."
            )

        vm_name = f"{self.parent.name or 'host'}-{self.name or f'g{self.index}'}"
        node_context = get_node_context(self)
        node_context.vm_name = vm_name
        node_context.host = host_node

        working_path = PurePath(runbook.lisa_working_dir, vm_name)
        node_context.working_path = str(working_path)
        host_node.tools[Mkdir].create_directory(str(working_path))

        assert runbook.uefi, "UEFI settings should be validated in schema"
        node_context.uefi_firmware_path = (
            self._openvmm_controller.resolve_guest_artifact_path(
                runbook.uefi.firmware_path,
                runbook.uefi.firmware_is_remote_path,
                working_path,
            )
        )

        if runbook.disk_img:
            node_context.disk_img_path = (
                self._openvmm_controller.resolve_guest_artifact_path(
                    runbook.disk_img,
                    runbook.disk_img_is_remote_path,
                    working_path,
                )
            )

        node_context.launcher_log_file_path = str(working_path / "openvmm-launcher.log")
        node_context.console_log_file_path = str(working_path / "openvmm-console.log")
        node_context.ssh_port = runbook.network.ssh_port

        self._openvmm_controller.launch(self, self.log)
        self._openvmm_controller.configure_connection(self, self.log)

    def _initialize_capability(self) -> None:
        if not self.capability.features:
            self.capability.features = search_space.SetSpace[schema.FeatureSettings](
                is_allow_set=True
            )
        if not any(
            feature.type == StartStop.name() for feature in self.capability.features
        ):
            self.capability.features.add(
                schema.FeatureSettings.create(StartStop.name())
            )

    def _openvmm_stop(self, wait: bool = True) -> None:
        self._openvmm_controller.stop_node(self, wait=wait)

    def _openvmm_start(self, wait: bool = True) -> None:
        self._openvmm_controller.start_node(self, wait=wait)

    def _openvmm_restart(self, wait: bool = True) -> None:
        self._openvmm_controller.restart_node(self, wait=wait)
