# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import io
import ipaddress
import os
import shlex
import tempfile
import time
from pathlib import Path, PurePath
from typing import Any, List, Optional, Type, cast

import pycdlib
import uuid
import yaml

from lisa import constants, schema, search_space
from lisa.feature import Features
from lisa.node import Node, RemoteNode
from lisa.tools import Dnsmasq, Ip, Kill, Ls, Mkdir, Modprobe, OpenVmm
from lisa.tools.openvmm import OpenVmmLaunchConfig
from lisa.util import LisaException, get_public_key_data
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
OPENVMM_DHCP_SERVER_PORT = 67


def _get_tap_host_interface_name(network: OpenVmmNetworkSchema) -> str:
    return network.bridge_name or network.tap_name


def _countspace_to_int(value: search_space.CountSpace) -> int:
    chosen = search_space.choose_value_countspace(value, value)
    assert isinstance(chosen, int), f"expected int countspace, got {type(chosen)}"
    return chosen


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
            dvd_disk_paths=(
                [node_context.cloud_init_file_path]
                if node_context.cloud_init_file_path
                else []
            ),
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
            sudo=runbook.network.mode == OPENVMM_NETWORK_MODE_TAP,
        )
        self._ensure_process_running(node_context)
        log.debug(
            f"Launched OpenVMM VM '{node_context.vm_name}' with pid "
            f"{node_context.process_id}"
        )

    def create_node_cloud_init_iso(self, node: "OpenVmmGuestNode") -> None:
        runbook = cast(OpenVmmGuestNodeSchema, node.runbook)
        node_context = get_node_context(node)

        user: dict[str, Any] = {
            "name": runbook.username,
            "shell": "/bin/bash",
            "sudo": ["ALL=(ALL) NOPASSWD:ALL"],
            "groups": ["sudo"],
        }
        if runbook.private_key_file:
            user["ssh_authorized_keys"] = [
                get_public_key_data(runbook.private_key_file)
            ]

        user_data: dict[str, Any] = {"users": ["default", user]}
        if runbook.username == "root":
            user_data["disable_root"] = False
        if runbook.password:
            user["lock_passwd"] = False
            user["plain_text_passwd"] = runbook.password
            user_data["ssh_pwauth"] = True

        for extra_user_data in node_context.extra_cloud_init_user_data:
            for key, value in extra_user_data.items():
                existing_value = user_data.get(key)
                if not existing_value:
                    user_data[key] = value
                elif isinstance(existing_value, dict) and isinstance(value, dict):
                    existing_value.update(value)
                elif isinstance(existing_value, list) and isinstance(value, list):
                    existing_value.extend(value)
                else:
                    user_data[key] = value

        meta_data = {
            "instance-id": f"{node_context.vm_name}-{uuid.uuid4().hex}",
            "local-hostname": node_context.vm_name,
        }

        user_data_string = "#cloud-config\n" + yaml.safe_dump(user_data)
        meta_data_string = yaml.safe_dump(meta_data)

        tmp_dir = tempfile.TemporaryDirectory()
        try:
            iso_path = os.path.join(tmp_dir.name, "cloud-init.iso")
            self._create_iso(
                iso_path,
                [("/user-data", user_data_string), ("/meta-data", meta_data_string)],
            )
            self.host_node.shell.copy(
                Path(iso_path), PurePath(node_context.cloud_init_file_path)
            )
        finally:
            tmp_dir.cleanup()

    def _create_iso(self, file_path: str, files: List[tuple[str, str]]) -> None:
        iso = pycdlib.PyCdlib()
        iso.new(joliet=3, vol_ident="cidata")

        for index, (path, contents) in enumerate(files):
            contents_data = contents.encode()
            iso.add_fp(
                io.BytesIO(contents_data),
                len(contents_data),
                f"/{index}.;1",
                joliet_path=path,
            )

        iso.write(file_path)
        iso.close()

    def _prepare_tap_network(
        self, network: OpenVmmNetworkSchema, node_context: Any
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
                    f"user {shlex.quote(username)}"
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
        else:
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
            self._ensure_tap_dhcp_input_allowed(host_interface_name, node_context)
            lease_file = f"/var/run/qemu-dnsmasq-{host_interface_name}.leases"
            host.execute(f"cp /dev/null {lease_file}", shell=True, sudo=True)
            host.tools[Dnsmasq].start(host_interface_name, tap_gateway, dhcp_range)
            node_context.tap_dnsmasq_pid_file = (
                f"/var/run/qemu-dnsmasq-{host_interface_name}.pid"
            )
            node_context.tap_dnsmasq_lease_file = lease_file

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

    def _ensure_tap_dhcp_input_allowed(
        self, host_interface_name: str, node_context: Any
    ) -> None:
        iptables_exists = self.host_node.execute(
            "command -v iptables >/dev/null 2>&1",
            shell=True,
            sudo=True,
            no_info_log=True,
            no_error_log=True,
            expected_exit_code=None,
        )
        if iptables_exists.exit_code != 0:
            return

        rule = (
            f"INPUT -i {shlex.quote(host_interface_name)} -p udp -m udp "
            f"--dport {OPENVMM_DHCP_SERVER_PORT} -j ACCEPT"
        )
        check_result = self.host_node.execute(
            f"iptables -C {rule}",
            shell=True,
            sudo=True,
            no_info_log=True,
            no_error_log=True,
            expected_exit_code=None,
        )
        if check_result.exit_code == 0:
            return

        self.host_node.execute(
            f"iptables -I {rule}",
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "failed to allow DHCP traffic to the OpenVMM host interface"
            ),
        )
        node_context.tap_dhcp_input_rule_added = True

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
            public_address = network.connection_address or self._get_host_public_address()
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
                "OpenVMM guest SSH port did not become reachable"
            ) from identifier_error

    def _resolve_guest_address(
        self,
        node_context: Any,
        network: OpenVmmNetworkSchema,
        log: Logger,
    ) -> str:
        if network.mode == OPENVMM_NETWORK_MODE_NONE:
            return ""

        if network.address_mode == OPENVMM_ADDRESS_MODE_STATIC:
            if not network.guest_address:
                raise LisaException(
                    "guest_address is required when address_mode is 'static'"
                )
            return network.guest_address
        if network.mode != OPENVMM_NETWORK_MODE_TAP:
            raise LisaException(
                "address discovery is supported only for tap networking"
            )

        return self._get_tap_guest_address(node_context, network, log)

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
        self._wait_for_tap_lease(node_context, guest_address, log)
        return guest_address

    def _wait_for_tap_lease(
        self,
        node_context: Any,
        guest_address: str,
        log: Logger,
        timeout: int = OPENVMM_IP_DISCOVERY_TIMEOUT,
    ) -> None:
        lease_file = node_context.tap_dnsmasq_lease_file
        if not lease_file:
            raise LisaException(
                "OpenVMM TAP DHCP lease tracking is not configured"
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
            if guest_address in result.stdout.strip():
                log.debug(
                    f"confirmed OpenVMM guest DHCP lease '{guest_address}' in {lease_file}"
                )
                return
            if not self._is_process_running(node_context.process_id):
                raise LisaException(
                    "OpenVMM process exited before the guest acquired the expected DHCP lease"
                )
            time.sleep(1)

        raise LisaException(
            f"OpenVMM guest did not acquire the expected DHCP lease '{guest_address}'"
        )

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
                f"{shlex.quote(host_interface)} -o {shlex.quote(forwarding_interface)} -j ACCEPT || "
                "iptables -I FORWARD -i "
                f"{shlex.quote(host_interface)} -o {shlex.quote(forwarding_interface)} -j ACCEPT"
            ),
            (
                "iptables -C FORWARD -i "
                f"{shlex.quote(forwarding_interface)} -o {shlex.quote(host_interface)} "
                "-m state --state RELATED,ESTABLISHED -j ACCEPT || "
                "iptables -I FORWARD -i "
                f"{shlex.quote(forwarding_interface)} -o {shlex.quote(host_interface)} "
                "-m state --state RELATED,ESTABLISHED -j ACCEPT"
            ),
            (
                "iptables -C FORWARD -i "
                f"{shlex.quote(forwarding_interface)} -o {shlex.quote(host_interface)} "
                f"-p tcp -d {guest_address} --dport {guest_port} -j ACCEPT || "
                "iptables -I FORWARD -i "
                f"{shlex.quote(forwarding_interface)} -o {shlex.quote(host_interface)} "
                f"-p tcp -d {guest_address} --dport {guest_port} -j ACCEPT"
            ),
            (
                "iptables -t nat -C POSTROUTING -s "
                f"{shlex.quote(str(host_network))} -o {shlex.quote(forwarding_interface)} -j MASQUERADE || "
                "iptables -t nat -I POSTROUTING -s "
                f"{shlex.quote(str(host_network))} -o {shlex.quote(forwarding_interface)} -j MASQUERADE"
            ),
            (
                "iptables -t nat -C PREROUTING -p tcp --dport "
                f"{forwarded_port} -j DNAT --to-destination {guest_address}:{guest_port} || "
                "iptables -t nat -I PREROUTING -p tcp --dport "
                f"{forwarded_port} -j DNAT --to-destination {guest_address}:{guest_port}"
            ),
            (
                "iptables -t nat -C OUTPUT -p tcp --dport "
                f"{forwarded_port} -j DNAT --to-destination {guest_address}:{guest_port} || "
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
                f"{shlex.quote(host_interface)} -o {shlex.quote(forwarding_interface)} -j ACCEPT || true"
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
                f"{forwarded_port} -j DNAT --to-destination {guest_address}:{guest_port} || true"
            ),
            (
                "iptables -t nat -D OUTPUT -p tcp --dport "
                f"{forwarded_port} -j DNAT --to-destination {guest_address}:{guest_port} || true"
            ),
            (
                "iptables -t nat -D POSTROUTING -s "
                f"{shlex.quote(str(host_network))} -o {shlex.quote(forwarding_interface)} -j MASQUERADE || true"
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

    def _ensure_process_running(self, node_context: Any, grace_period: int = 2) -> None:
        if grace_period > 0:
            time.sleep(grace_period)

        if self._is_process_running(node_context.process_id):
            return

        raise LisaException(
            "OpenVMM process exited immediately after launch. "
            f"Check {node_context.launcher_log_file_path} on the host for details."
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

        if node_context.tap_dhcp_input_rule_added:
            host_interface_name = _get_tap_host_interface_name(network)
            self.host_node.execute(
                (
                    "iptables -D INPUT -i "
                    f"{shlex.quote(host_interface_name)} -p udp -m udp "
                    f"--dport {OPENVMM_DHCP_SERVER_PORT} -j ACCEPT || true"
                ),
                shell=True,
                sudo=True,
                expected_exit_code=0,
            )
            node_context.tap_dhcp_input_rule_added = False

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

        if runbook.cloud_init:
            node_context.cloud_init_file_path = str(working_path / "cloud-init.iso")

            extra_user_data = runbook.cloud_init.extra_user_data
            if extra_user_data:
                if isinstance(extra_user_data, str):
                    extra_user_data = [extra_user_data]

                for relative_file_path in extra_user_data:
                    if not relative_file_path:
                        continue

                    file_path = constants.RUNBOOK_PATH.joinpath(relative_file_path)
                    with open(file_path, "r") as file:
                        node_context.extra_cloud_init_user_data.append(
                            yaml.safe_load(file)
                        )

            self._openvmm_controller.create_node_cloud_init_iso(self)

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
