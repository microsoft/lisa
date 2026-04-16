# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import hashlib
import io
import ipaddress
import os
import shlex
import tempfile
import uuid
from abc import ABC, abstractmethod
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Any, Dict, List, Optional, Type, cast

import yaml

from lisa import constants, schema, search_space
from lisa.feature import Features
from lisa.node import Node, RemoteNode
from lisa.tools import Dnsmasq, Ip, Kill, Mkdir, Modprobe, OpenVmm, Rm
from lisa.tools.openvmm import OpenVmmLaunchConfig
from lisa.util import (
    LisaException,
    LisaTimeoutException,
    check_till_timeout,
    create_timer,
    get_public_key_data,
)
from lisa.util.logger import Logger
from lisa.util.shell import wait_tcp_port_ready

from .. import OPENVMM
from .context import NodeContext, get_host_context, get_node_context
from .schema import (
    OPENVMM_ADDRESS_MODE_STATIC,
    OPENVMM_NETWORK_MODE_TAP,
    OPENVMM_NETWORK_MODE_USER,
    OpenVmmGuestNodeSchema,
    OpenVmmNetworkSchema,
)
from .start_stop import StartStop

# Allow slower guest boot and reconnect paths on loaded L1 hosts.
OPENVMM_CONNECTION_TIMEOUT = 300
# Allow DHCP lease discovery enough time after OpenVMM launch.
OPENVMM_IP_DISCOVERY_TIMEOUT = 300
# Capture enough recent log lines to include the relevant launch or boot failure.
OPENVMM_LOG_TAIL_LINES = 40
OPENVMM_DHCP_SERVER_PORT = 67
OPENVMM_BRIDGE_NETFILTER_KEYS = [
    "net.bridge.bridge-nf-call-iptables",
    "net.bridge.bridge-nf-call-arptables",
    "net.bridge.bridge-nf-call-ip6tables",
]


def _get_tap_host_interface_name(network: OpenVmmNetworkSchema) -> str:
    return network.bridge_name or network.tap_name


def _countspace_to_int(value: search_space.CountSpace) -> int:
    chosen = search_space.choose_value_countspace(value, value)
    if not isinstance(chosen, int):
        raise LisaException(
            f"choose_value_countspace() returned non-int value '{chosen}' "
            f"of type '{type(chosen).__name__}'. Verify the countspace "
            "configuration resolves to a single integer value."
        )
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
                "guest_address is required when address_mode is 'static'"
            )
        return network.guest_address


class OpenVmmController:
    def __init__(self, node: "OpenVmmGuestNode") -> None:
        self._node = node
        host_node = node.parent
        if host_node is None:
            raise LisaException("OpenVMM guest node must have a parent host node")
        self.host_node = host_node
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

        source_id = hashlib.sha256(str(source.resolve()).encode("utf-8")).hexdigest()[
            :8
        ]
        destination = working_path / f"{source.stem}-{source_id}{source.suffix}"
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
            tap_name=getattr(runbook.network, "tap_name", ""),
            network_cidr=runbook.network.consomme_cidr,
            serial_mode=runbook.serial.mode,
            serial_path=node_context.console_log_file_path,
            extra_args=runbook.extra_args,
            stdout_path=node_context.launcher_log_file_path,
            stderr_path=node_context.launcher_stderr_log_file_path,
        )
        openvmm = self.get_openvmm_tool(runbook.openvmm_binary)
        node_context.command_line = openvmm.build_command(launch_config)
        launch_cwd = self.host_node.get_pure_path(node_context.working_path)
        node_context.process_id = openvmm.launch_vm(
            launch_config,
            cwd=launch_cwd,
            sudo=runbook.network.mode == OPENVMM_NETWORK_MODE_TAP,
        )
        self._ensure_process_running(node_context, runbook.network)
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

        user_data: dict[str, Any] = {
            "users": ["default", user],
        }
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
                [
                    ("/user-data", user_data_string),
                    ("/meta-data", meta_data_string),
                ],
            )
            self.host_node.shell.copy(
                Path(iso_path),
                self.host_node.get_pure_path(node_context.cloud_init_file_path),
            )
        finally:
            tmp_dir.cleanup()

    def _create_iso(self, file_path: str, files: List[tuple[str, str]]) -> None:
        import pycdlib

        iso = pycdlib.PyCdlib()
        iso_created = False
        try:
            iso.new(joliet=3, vol_ident="cidata")
            iso_created = True

            for index, (path, contents) in enumerate(files):
                contents_data = contents.encode()
                iso.add_fp(
                    io.BytesIO(contents_data),
                    len(contents_data),
                    f"/{index}.;1",
                    joliet_path=path,
                )

            iso.write(file_path)
        finally:
            if iso_created:
                iso.close()

    def _prepare_tap_network(
        self,
        network: OpenVmmNetworkSchema,
        node_context: NodeContext,
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
            self._disable_bridge_netfilter(node_context)

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
                (
                    "ip link set dev "
                    f"{shlex.quote(bridge_name)} type bridge forward_delay 0"
                ),
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
            whoami_result = host.execute(
                "whoami",
                shell=True,
                no_info_log=True,
                no_error_log=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "failed to determine the host username with 'whoami' before "
                    f"creating OpenVMM tap interface {tap_name}. Verify that "
                    "'whoami' is available and working on the host."
                ),
            )
            username = whoami_result.stdout.strip()
            if not username:
                raise LisaException(
                    "failed to determine the host username before creating "
                    f"OpenVMM tap interface {tap_name}: 'whoami' returned an "
                    "empty username. Verify that the host shell environment is "
                    "configured correctly and that 'whoami' returns a valid user."
                )
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
            self._ensure_tap_dhcp_input_allowed(host_interface_name, node_context)
            pid_file = f"/var/run/qemu-dnsmasq-{host_interface_name}.pid"
            lease_file = f"/var/run/qemu-dnsmasq-{host_interface_name}.leases"
            host.execute(
                (
                    f"test -f {shlex.quote(pid_file)} && "
                    f"kill $(cat {shlex.quote(pid_file)}) || true; "
                    f"rm -f {shlex.quote(pid_file)}; "
                    f"cp /dev/null {shlex.quote(lease_file)}"
                ),
                shell=True,
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "failed to reset OpenVMM dnsmasq state before starting "
                    f"DHCP on interface {host_interface_name}"
                ),
            )
            host.tools[Dnsmasq].start(
                host_interface_name,
                tap_gateway,
                dhcp_range,
                stop_firewall=False,
                kill_existing=False,
                pid_file=pid_file,
                lease_file=lease_file,
            )
            node_context.tap_dnsmasq_pid_file = pid_file
            node_context.tap_dnsmasq_lease_file = lease_file

        self._log_tap_network_state(network, node_context)
        if node_context.tap_dnsmasq_pid_file:
            self._log_dnsmasq_state(node_context)

    def _disable_bridge_netfilter(self, node_context: NodeContext) -> None:
        host = self.host_node
        host_context = get_host_context(host)
        modprobe = host.tools[Modprobe]
        if modprobe.module_exists("br_netfilter") and not modprobe.is_module_loaded(
            "br_netfilter", force_run=True
        ):
            modprobe.load("br_netfilter")

        if host_context.active_bridge_netfilter_count > 0:
            host_context.active_bridge_netfilter_count += 1
            node_context.tap_bridge_netfilter_disabled = True
            return

        original_values = {}
        for key in OPENVMM_BRIDGE_NETFILTER_KEYS:
            value_result = host.execute(
                f"sysctl -n {shlex.quote(key)}",
                shell=True,
                sudo=True,
                no_info_log=True,
                no_error_log=True,
                expected_exit_code=None,
            )
            if value_result.exit_code == 0:
                original_values[key] = value_result.stdout.strip()

        if not original_values:
            return

        host_context.original_bridge_netfilter_values = original_values
        host_context.active_bridge_netfilter_count = 1
        node_context.tap_bridge_netfilter_disabled = True
        try:
            self._set_bridge_netfilter_values(
                {key: "0" for key in original_values},
                failure_message=(
                    "failed to disable bridge netfilter on the OpenVMM host"
                ),
            )
        except Exception:
            try:
                self._set_bridge_netfilter_values(
                    original_values,
                    failure_message=(
                        "failed to roll back bridge netfilter after an OpenVMM "
                        "setup error"
                    ),
                )
            except Exception as cleanup_identifier:
                self._log.debug(
                    "failed to roll back bridge netfilter after setup error: "
                    f"{cleanup_identifier}"
                )
            host_context.original_bridge_netfilter_values = {}
            host_context.active_bridge_netfilter_count = 0
            node_context.tap_bridge_netfilter_disabled = False
            raise

    def _set_bridge_netfilter_values(
        self,
        values: Dict[str, str],
        failure_message: str,
    ) -> None:
        for key, value in values.items():
            self.host_node.execute(
                f"sysctl -w {shlex.quote(f'{key}={value}')}",
                shell=True,
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=failure_message,
            )

    def _ensure_tap_dhcp_input_allowed(
        self, host_interface_name: str, node_context: NodeContext
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

    def _get_tap_network_config(self, network: OpenVmmNetworkSchema) -> tuple[str, str]:
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
            is_ready, error_code = wait_tcp_port_ready(
                public_address,
                public_port,
                log=log,
                timeout=OPENVMM_CONNECTION_TIMEOUT,
            )
        except LisaException as identifier:
            raise LisaException(
                "OpenVMM guest SSH port readiness check failed for "
                f"{public_address}:{public_port}. "
                "Verify the guest is running, port forwarding or network "
                "configuration is correct, the SSH service is listening on the "
                "expected port, and review the OpenVMM guest and host logs for "
                "startup or networking errors. "
                f"{self._get_openvmm_failure_context(node_context, runbook.network)}"
            ) from identifier
        if not is_ready:
            raise LisaException(
                "OpenVMM guest SSH port did not become reachable at "
                f"{public_address}:{public_port} "
                f"(error code: {error_code}). Verify the guest is running, "
                "port forwarding or network configuration is correct, the SSH "
                "service is listening on the expected port, and review the "
                "OpenVMM guest and host logs for startup or networking errors. "
                f"{self._get_openvmm_failure_context(node_context, runbook.network)}"
            )

    def _resolve_guest_address(
        self,
        node_context: Any,
        network: OpenVmmNetworkSchema,
        log: Logger,
    ) -> str:
        if network.mode == OPENVMM_NETWORK_MODE_USER:
            return network.connection_address or self._get_host_public_address()

        if network.address_mode == OPENVMM_ADDRESS_MODE_STATIC:
            return StaticAddressResolver().resolve(
                self.host_node, node_context, network, log
            )
        elif network.mode == OPENVMM_NETWORK_MODE_TAP:
            return self._get_tap_guest_address(node_context, network, log)
        else:
            raise LisaException(
                "address discovery is supported only for tap networking. "
                "Use address_mode 'static' for other network modes."
            )

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

        def _lease_is_ready() -> bool:
            result = self.host_node.execute(
                (
                    f"test -f {shlex.quote(lease_file)} && "
                    f"cat {shlex.quote(lease_file)} || true"
                ),
                shell=True,
                sudo=True,
                no_info_log=True,
                no_error_log=True,
                expected_exit_code=0,
            )
            for lease_line in result.stdout.splitlines():
                lease_fields = lease_line.split()
                if len(lease_fields) >= 3 and lease_fields[2] == guest_address:
                    log.debug(
                        "confirmed OpenVMM guest DHCP lease "
                        f"'{guest_address}' in {lease_file}"
                    )
                    return True
            if not self._is_process_running(node_context.process_id):
                raise LisaException(
                    "OpenVMM process exited before the guest acquired the expected "
                    f"DHCP lease '{guest_address}'. "
                    f"{self._get_openvmm_failure_context(node_context, network)}"
                )
            return False

        try:
            check_till_timeout(
                _lease_is_ready,
                timeout_message=(
                    "wait for OpenVMM guest DHCP lease "
                    f"'{guest_address}' in '{lease_file}'"
                ),
                timeout=timeout,
            )
        except LisaTimeoutException as identifier:
            raise LisaException(
                "OpenVMM guest did not acquire the expected DHCP lease "
                f"'{guest_address}' on '{lease_file}'. "
                f"{self._get_openvmm_failure_context(node_context, None)}"
            ) from identifier

    def _get_openvmm_failure_context(
        self,
        node_context: Any,
        network: Optional[OpenVmmNetworkSchema],
    ) -> str:
        details: list[str] = []

        self._log_tap_network_state(network, node_context, log_commands=True)
        self._log_dnsmasq_state(node_context, log_commands=True)
        self._log_process_state(node_context, log_commands=True)
        self._log_forwarding_state(node_context, network, log_commands=True)

        if node_context.tap_dnsmasq_lease_file:
            lease_result = self.host_node.execute(
                (
                    f"test -f {shlex.quote(node_context.tap_dnsmasq_lease_file)} && "
                    "tail -n "
                    f"{OPENVMM_LOG_TAIL_LINES} "
                    f"{shlex.quote(node_context.tap_dnsmasq_lease_file)} || true"
                ),
                shell=True,
                sudo=True,
                no_info_log=False,
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
                no_info_log=False,
                expected_exit_code=0,
            )
            output = result.stdout.strip()
            details.append(f"{label}: " + (output if output else "<empty>"))

        return " | ".join(details)

    def _log_tap_network_state(
        self,
        network: Optional[OpenVmmNetworkSchema],
        node_context: Any,
        log_commands: bool = False,
    ) -> None:
        if not network or network.mode != OPENVMM_NETWORK_MODE_TAP:
            return

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
                    "bridge link show master "
                    f"{shlex.quote(network.bridge_name)} 2>/dev/null || true",
                )
            )

        self._log_command_outputs(
            "tap network state",
            commands,
            log_commands=log_commands,
        )

    def _log_dnsmasq_state(self, node_context: Any, log_commands: bool = False) -> None:
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
                        "test -f "
                        f"{shlex.quote(node_context.tap_dnsmasq_lease_file)} && "
                        "tail -n "
                        f"{OPENVMM_LOG_TAIL_LINES} "
                        f"{shlex.quote(node_context.tap_dnsmasq_lease_file)} || true"
                    ),
                )
            )

        self._log_command_outputs(
            "dnsmasq state",
            commands,
            log_commands=log_commands,
        )

    def _log_process_state(self, node_context: Any, log_commands: bool = False) -> None:
        if not node_context.process_id:
            return

        process_id = shlex.quote(node_context.process_id)
        commands = [
            (
                "openvmm process status",
                "ps -p "
                f"{process_id} -o pid=,ppid=,stat=,etime=,cmd= 2>/dev/null || true",
            ),
        ]
        self._log_command_outputs(
            "process state",
            commands,
            log_commands=log_commands,
        )

    def _log_forwarding_state(
        self,
        node_context: Any,
        network: Optional[OpenVmmNetworkSchema],
        log_commands: bool = False,
    ) -> None:
        if not network or not node_context.forwarded_port:
            return

        guest_address = str(node_context.guest_address or "")
        if not guest_address:
            return
        match_pattern = shlex.quote(f"{node_context.forwarded_port}|{guest_address}")
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
        self._log_command_outputs(
            "forwarding state",
            commands,
            log_commands=log_commands,
        )

    def _log_command_outputs(
        self,
        section: str,
        commands: list[tuple[str, str]],
        log_commands: bool = False,
    ) -> None:
        outputs: list[str] = []
        for label, command in commands:
            try:
                result = self.host_node.execute(
                    command,
                    shell=True,
                    sudo=True,
                    no_info_log=not log_commands,
                    no_error_log=not log_commands,
                    expected_exit_code=None,
                )
                if not log_commands:
                    output = result.stdout.strip()
                    outputs.append(f"{label}: {output if output else '<empty>'}")
            except LisaException as identifier:
                outputs.append(f"{label}: <unavailable: {identifier}>")

        if outputs:
            self._log.debug(f"{section}: {' | '.join(outputs)}")

    def stop_node(self, node: Node, wait: bool = True) -> None:
        node_context = get_node_context(node)
        wait_failure: Optional[LisaException] = None
        process_id = node_context.process_id
        if node.is_connected:
            node.execute(
                "shutdown -P now",
                shell=True,
                sudo=True,
                no_info_log=True,
                no_error_log=True,
                expected_exit_code=None,
            )

        if wait and process_id:
            try:
                self._wait_for_process_exit(process_id)
            except LisaException as identifier:
                wait_failure = identifier

        if process_id:
            self.host_node.tools[Kill].by_pid(
                process_id,
                ignore_not_exist=True,
            )
            node_context.process_id = ""

        self._disable_ssh_forwarding(node)
        self._teardown_tap_network(
            node_context,
            cast(OpenVmmGuestNodeSchema, node.runbook).network,
        )

        if wait_failure:
            self._log.info(
                f"{wait_failure} Forcing OpenVMM process '{process_id}' to stop."
            )

    def start_node(self, node: "OpenVmmGuestNode", wait: bool = True) -> None:
        runbook = cast(OpenVmmGuestNodeSchema, node.runbook)
        if runbook.cloud_init:
            self.create_node_cloud_init_iso(node)
        self.launch(node, node.log)
        if wait:
            self.configure_connection(node, node.log)

    def restart_node(self, node: "OpenVmmGuestNode", wait: bool = True) -> None:
        self.stop_node(node, wait=wait)
        self.start_node(node, wait=wait)

    def cleanup_node_artifacts(self, node: "OpenVmmGuestNode") -> None:
        node_context = get_node_context(node)
        if not node_context.working_path:
            return

        runbook = cast(OpenVmmGuestNodeSchema, node.runbook)
        base_working_path = self.host_node.get_pure_path(runbook.lisa_working_dir)
        working_path = self.host_node.get_pure_path(node_context.working_path)
        if working_path == base_working_path:
            raise LisaException(
                "refusing to delete the OpenVMM base working directory "
                f"'{working_path}'."
            )

        try:
            relative_working_path = working_path.relative_to(base_working_path)
        except ValueError as identifier:
            raise LisaException(
                "refusing to delete OpenVMM working path outside the configured "
                f"base directory. Working path: '{working_path}'. Base path: "
                f"'{base_working_path}'."
            ) from identifier

        if not relative_working_path.parts or any(
            part in {"", ".", ".."} for part in relative_working_path.parts
        ):
            raise LisaException(
                "refusing to delete unsafe OpenVMM working path "
                f"'{working_path}'. Verify the guest and host names do not "
                "contain path traversal segments."
            )

        self.host_node.tools[Rm].remove_directory(str(working_path), sudo=True)
        node_context.working_path = ""
        node_context.uefi_firmware_path = ""
        node_context.disk_img_path = ""
        node_context.cloud_init_file_path = ""
        node_context.console_log_file_path = ""
        node_context.launcher_log_file_path = ""

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
        host_context = get_host_context(self.host_node)
        forwarding_interface, _ = self.host_node.tools[Ip].get_default_route_info()
        host_interface = _get_tap_host_interface_name(network)
        host_network = ipaddress.ip_interface(network.tap_host_cidr).network
        guest_address = shlex.quote(guest_address)
        guest_port = network.ssh_port
        forwarded_port = network.forwarded_port

        if host_context.active_forwarding_count == 0:
            ip_forward_result = self.host_node.execute(
                "sysctl -n net.ipv4.ip_forward",
                shell=True,
                sudo=True,
                no_info_log=True,
                no_error_log=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "failed to read current host ip_forward state for OpenVMM "
                    "SSH forwarding"
                ),
            )
            original_ip_forward_value = ip_forward_result.stdout.strip()
            if original_ip_forward_value not in ["0", "1"]:
                raise LisaException(
                    "failed to parse current host ip_forward state for "
                    "OpenVMM SSH forwarding. "
                    f"stdout: {ip_forward_result.stdout.strip() or '<empty>'}. "
                    f"stderr: {ip_forward_result.stderr.strip() or '<empty>'}"
                )
            host_context.original_ip_forward_value = original_ip_forward_value

        host_context.active_forwarding_count += 1
        node_context.forwarding_interface = forwarding_interface
        node_context.forwarded_port = forwarded_port
        node_context.forwarding_enabled = True

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
                f"{shlex.quote(str(host_network))} "
                f"-o {shlex.quote(forwarding_interface)} "
                "-j MASQUERADE || "
                "iptables -t nat -I POSTROUTING -s "
                f"{shlex.quote(str(host_network))} "
                f"-o {shlex.quote(forwarding_interface)} "
                "-j MASQUERADE"
            ),
            (
                "iptables -t nat -C PREROUTING -p tcp --dport "
                f"{forwarded_port} -j DNAT --to-destination "
                f"{guest_address}:{guest_port} "
                "|| "
                "iptables -t nat -I PREROUTING -p tcp --dport "
                f"{forwarded_port} -j DNAT --to-destination "
                f"{guest_address}:{guest_port}"
            ),
            (
                "iptables -t nat -C OUTPUT -p tcp --dport "
                f"{forwarded_port} -j DNAT --to-destination "
                f"{guest_address}:{guest_port} "
                "|| "
                "iptables -t nat -I OUTPUT -p tcp --dport "
                f"{forwarded_port} -j DNAT --to-destination "
                f"{guest_address}:{guest_port}"
            ),
        ]
        try:
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
        except Exception:
            try:
                self._disable_ssh_forwarding_context(node_context, network)
            except Exception as cleanup_identifier:
                self._log.debug(
                    "failed to roll back OpenVMM SSH forwarding after setup "
                    f"error: {cleanup_identifier}"
                )
            raise

    def _disable_ssh_forwarding(self, node: Node) -> None:
        node_context = get_node_context(node)
        self._disable_ssh_forwarding_context(
            node_context,
            cast(OpenVmmGuestNodeSchema, node.runbook).network,
        )

    def _disable_ssh_forwarding_context(
        self,
        node_context: Any,
        network: OpenVmmNetworkSchema,
    ) -> None:
        if (
            not node_context.forwarding_enabled
            and not node_context.forwarded_port
            and not node_context.forwarding_interface
        ):
            return

        host_context = get_host_context(self.host_node)
        guest_address = shlex.quote(node_context.guest_address)
        guest_port = node_context.ssh_port
        forwarded_port = node_context.forwarded_port
        forwarding_interface = node_context.forwarding_interface
        host_interface = _get_tap_host_interface_name(network)
        host_network = ipaddress.ip_interface(network.tap_host_cidr).network
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
                f"{shlex.quote(str(host_network))} "
                f"-o {shlex.quote(forwarding_interface)} "
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

        if node_context.forwarding_enabled and host_context.active_forwarding_count > 0:
            host_context.active_forwarding_count -= 1

        if (
            host_context.active_forwarding_count == 0
            and host_context.original_ip_forward_value
        ):
            self.host_node.execute(
                "sysctl -w net.ipv4.ip_forward="
                f"{shlex.quote(host_context.original_ip_forward_value)}",
                shell=True,
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "failed to restore host ip_forward state after OpenVMM "
                    "SSH forwarding"
                ),
            )
            host_context.original_ip_forward_value = ""

        node_context.forwarded_port = 0
        node_context.forwarding_enabled = False
        node_context.forwarding_interface = ""

    def _wait_for_process_exit(self, process_id: str, timeout: int = 60) -> None:
        try:
            check_till_timeout(
                lambda: not self._is_process_running(process_id),
                timeout_message=(f"wait for OpenVMM process '{process_id}' to exit"),
                timeout=timeout,
            )
        except LisaTimeoutException as identifier:
            raise LisaException(
                f"OpenVMM process '{process_id}' did not exit within {timeout} "
                "seconds. Check the host process state and guest shutdown logs "
                "for details."
            ) from identifier

    def _ensure_process_running(
        self,
        node_context: Any,
        network: OpenVmmNetworkSchema,
        grace_period_seconds: int = 2,
    ) -> None:
        timeout = max(grace_period_seconds + 1, 1)
        grace_timer = create_timer()

        def _process_survived_grace_period() -> bool:
            if not self._is_process_running(node_context.process_id):
                raise LisaException(
                    "OpenVMM process exited immediately after launch. "
                    f"{self._get_openvmm_failure_context(node_context, network)}"
                )
            return grace_timer.elapsed(False) >= grace_period_seconds

        check_till_timeout(
            _process_survived_grace_period,
            timeout_message=(
                f"wait for OpenVMM process '{node_context.process_id}' to "
                "remain running after launch"
            ),
            timeout=timeout,
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
                    "kill $(cat "
                    f"{shlex.quote(node_context.tap_dnsmasq_pid_file)}) || true"
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

        if node_context.tap_bridge_netfilter_disabled:
            host_context = get_host_context(self.host_node)
            if host_context.active_bridge_netfilter_count > 0:
                host_context.active_bridge_netfilter_count -= 1

            if (
                host_context.active_bridge_netfilter_count == 0
                and host_context.original_bridge_netfilter_values
            ):
                self._set_bridge_netfilter_values(
                    host_context.original_bridge_netfilter_values,
                    failure_message=(
                        "failed to restore bridge netfilter state on the "
                        "OpenVMM host"
                    ),
                )
                host_context.original_bridge_netfilter_values = {}

            node_context.tap_bridge_netfilter_disabled = False


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
        try:
            self._openvmm_controller.cleanup_node_artifacts(self)
        except Exception as identifier:
            self.log.debug(
                f"failed to clean OpenVMM guest artifacts during cleanup: {identifier}"
            )
        super().cleanup()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._provision()
        super()._initialize(*args, **kwargs)

    def _provision(self) -> None:
        host_node = self.parent
        if host_node is None:
            raise LisaException("OpenVMM guest node must have a parent host node")

        host_node.initialize()
        runbook = cast(OpenVmmGuestNodeSchema, self.runbook)

        openvmm = self._openvmm_controller.get_openvmm_tool(runbook.openvmm_binary)
        if not openvmm.exists:
            raise LisaException(
                f"OpenVMM binary not found on host: {runbook.openvmm_binary}. "
                "Use the openvmm_installer transformer before provisioning guests."
            )

        vm_name = f"{host_node.name or 'host'}-{self.name or f'g{self.index}'}"
        node_context = get_node_context(self)
        node_context.vm_name = vm_name
        node_context.host = host_node

        base_working_path = host_node.get_pure_path(runbook.lisa_working_dir)
        working_path = base_working_path / vm_name
        node_context.working_path = str(working_path)
        host_node.tools[Mkdir].create_directory(str(working_path))

        if runbook.uefi is None:
            raise LisaException("UEFI settings must be defined for OpenVMM guests")
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

            self._load_extra_cloud_init_user_data(
                runbook.cloud_init.extra_user_data,
                node_context,
            )

            self._openvmm_controller.create_node_cloud_init_iso(self)

        node_context.launcher_log_file_path = str(working_path / "openvmm-launcher.log")
        node_context.launcher_stderr_log_file_path = str(
            working_path / "openvmm-launcher.stderr.log"
        )
        node_context.console_log_file_path = str(working_path / "openvmm-console.log")
        node_context.ssh_port = runbook.network.ssh_port

        self._openvmm_controller.launch(self, self.log)
        self._openvmm_controller.configure_connection(self, self.log)

    def _resolve_extra_user_data_file(self, relative_file_path: str) -> Path:
        root_path = constants.RUNBOOK_PATH.resolve().absolute()
        posix_path = PurePosixPath(relative_file_path)
        windows_path = PureWindowsPath(relative_file_path)

        if (
            posix_path.is_absolute()
            or windows_path.is_absolute()
            or windows_path.drive
            or windows_path.root
        ):
            raise LisaException(
                "cloud-init extra_user_data file path must be relative to the "
                f"runbook directory: '{relative_file_path}'"
            )

        file_path = root_path.joinpath(relative_file_path).resolve()
        try:
            file_path.relative_to(root_path)
        except ValueError as identifier:
            raise LisaException(
                "cloud-init extra_user_data file path "
                f"'{relative_file_path}' escapes the runbook directory "
                f"'{root_path}'. Use a relative path under the runbook directory."
            ) from identifier

        return file_path

    def _load_extra_cloud_init_user_data(
        self,
        extra_user_data: Optional[Any],
        node_context: Any,
    ) -> None:
        if not extra_user_data:
            return

        if isinstance(extra_user_data, str):
            extra_user_data = [extra_user_data]

        for relative_file_path in extra_user_data:
            if not relative_file_path:
                continue

            file_path = self._resolve_extra_user_data_file(relative_file_path)
            try:
                with open(file_path, "r", encoding="utf-8") as file:
                    file_content = file.read()
            except OSError as identifier:
                raise LisaException(
                    "failed to read cloud-init extra_user_data file "
                    f"'{relative_file_path}' resolved to '{file_path}'. "
                    "Verify the file exists under the runbook directory and is "
                    "readable."
                ) from identifier

            try:
                loaded_user_data = yaml.safe_load(file_content)
            except yaml.YAMLError as identifier:
                raise LisaException(
                    "failed to parse cloud-init extra_user_data file "
                    f"'{file_path}'. Verify the file contains valid YAML "
                    "mapping content that cloud-init can merge. "
                    f"Parse error: {identifier}"
                ) from identifier

            if not isinstance(loaded_user_data, dict):
                raise LisaException(
                    "invalid cloud-init extra_user_data file "
                    f"'{file_path}': expected a YAML mapping/dictionary, but got "
                    f"{type(loaded_user_data).__name__}. Update the file to "
                    "contain key/value pairs that cloud-init can merge."
                )

            node_context.extra_cloud_init_user_data.append(loaded_user_data)

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
