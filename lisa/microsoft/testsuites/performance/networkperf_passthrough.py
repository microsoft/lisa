# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from functools import partial
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, cast

from microsoft.testsuites.performance.common import (
    perf_iperf,
    perf_ntttcp,
    perf_tcp_pps,
)

from lisa import (
    Logger,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    node_requirement,
    schema,
    search_space,
    simple_requirement,
)
from lisa.environment import Environment, Node
from lisa.operating_system import Windows
from lisa.sut_orchestrator import CLOUD_HYPERVISOR
from lisa.testsuite import TestResult
from lisa.tools import Dhclient, Kill, PowerShell, Sysctl
from lisa.tools.iperf3 import (
    IPERF_TCP_BUFFER_LENGTHS,
    IPERF_TCP_CONCURRENCY,
    IPERF_UDP_BUFFER_LENGTHS,
    IPERF_UDP_CONCURRENCY,
)
from lisa.util import (
    LisaException,
    SkippedException,
    constants,
    find_group_in_lines,
    find_groups_in_lines,
)
from lisa.util.logger import get_logger
from lisa.util.parallel import run_in_parallel


@TestSuiteMetadata(
    area="network passthrough",
    category="performance",
    description="""
    This test suite is to validate linux network performance
    for various NIC passthrough scenarios.
    """,
    requirement=simple_requirement(
        supported_platform_type=[CLOUD_HYPERVISOR],
        unsupported_os=[Windows],
    ),
)
class NetworkPerformance(TestSuite):
    # Timeout values:
    # TIMEOUT: 12000s (3.3 hrs) - accounts for test execution + network setup overhead
    # PPS_TIMEOUT: 3000s (50 min) - shorter for PPS tests which are less intensive
    TIMEOUT = 12000
    PPS_TIMEOUT = 3000

    # Track baremetal host nodes for cleanup
    _baremetal_hosts: list[RemoteNode] = []

    # Network device passthrough tests between host and guest
    @TestCaseMetadata(
        description="""
        This test case uses iperf3 to test passthrough tcp network throughput.
        Run iperf server on physical server and client on VM
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=1,
            supported_platform_type=[CLOUD_HYPERVISOR],
            unsupported_os=[Windows],
        ),
    )
    def perf_tcp_iperf_passthrough_host_guest(
        self,
        node: Node,
        result: TestResult,
        log_path: Path,
        variables: Dict[str, Any],
    ) -> None:
        server = self._get_host_as_server(variables)

        client, _ = self._configure_passthrough_nic_for_node(
            node, log_path, host_node=server
        )

        perf_iperf(
            test_result=result,
            connections=IPERF_TCP_CONCURRENCY,
            buffer_length_list=IPERF_TCP_BUFFER_LENGTHS,
            server=server,
            client=client,
            run_with_internal_address=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses iperf3 to test passthrough udp network throughput.
        Run iperf server on physical host and client on vm with udp mode
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=1,
            supported_platform_type=[CLOUD_HYPERVISOR],
            unsupported_os=[Windows],
        ),
    )
    def perf_udp_iperf_passthrough_host_guest(
        self,
        node: Node,
        result: TestResult,
        log_path: Path,
        variables: Dict[str, Any],
    ) -> None:
        server = self._get_host_as_server(variables)

        client, _ = self._configure_passthrough_nic_for_node(
            node, log_path, host_node=server
        )

        perf_iperf(
            test_result=result,
            connections=IPERF_UDP_CONCURRENCY,
            buffer_length_list=IPERF_UDP_BUFFER_LENGTHS,
            server=server,
            client=client,
            udp_mode=True,
            run_with_internal_address=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses sar to test passthrough network PPS (Packets Per Second)
        when running netperf with single port. Test will consider VM as
        client node and physical host as server node.
        """,
        priority=3,
        timeout=PPS_TIMEOUT,
        requirement=simple_requirement(
            min_count=1,
            supported_platform_type=[CLOUD_HYPERVISOR],
            unsupported_os=[Windows],
        ),
    )
    def perf_tcp_single_pps_passthrough_host_guest(
        self,
        result: TestResult,
        node: Node,
        log_path: Path,
        variables: Dict[str, Any],
    ) -> None:
        server = self._get_host_as_server(variables)

        client, _ = self._configure_passthrough_nic_for_node(
            node, log_path, host_node=server
        )

        perf_tcp_pps(
            test_result=result,
            test_type="singlepps",
            server=server,
            client=client,
            use_internal_address=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses sar to test passthrough network PPS (Packets Per Second)
        when running netperf with multiple ports. Run netperf client on VM
        and server on physical host.
        """,
        priority=3,
        timeout=PPS_TIMEOUT,
        requirement=simple_requirement(
            min_count=1,
            supported_platform_type=[CLOUD_HYPERVISOR],
            unsupported_os=[Windows],
        ),
    )
    def perf_tcp_max_pps_passthrough_host_guest(
        self,
        result: TestResult,
        node: Node,
        log_path: Path,
        variables: Dict[str, Any],
    ) -> None:
        server = self._get_host_as_server(variables)

        client, _ = self._configure_passthrough_nic_for_node(
            node, log_path, host_node=server
        )

        perf_tcp_pps(
            test_result=result,
            test_type="maxpps",
            server=server,
            client=client,
            use_internal_address=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test tcp network throughput.
        We will run nttcp server of physical host and client on VM
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=1,
                memory_mb=search_space.IntRange(min=8192),
            ),
            supported_platform_type=[CLOUD_HYPERVISOR],
        ),
    )
    def perf_tcp_ntttcp_passthrough_host_guest(
        self,
        result: TestResult,
        node: Node,
        log_path: Path,
        variables: Dict[str, Any],
    ) -> None:
        server = self._get_host_as_server(variables)

        # Reboot guest first to avoid stale passthrough NIC state after device attach.
        node.reboot()

        client, client_nic_name = self._configure_passthrough_nic_for_node(
            node, log_path, host_node=server
        )

        perf_ntttcp(
            test_result=result,
            client=client,
            server=server,
            server_nic_name=self._get_host_nic_name(server),
            client_nic_name=client_nic_name,
            skip_server_task_max=True,  # host: TasksMax reboot clears NIC DHCP state
        )

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test passthrough udp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=1,
                memory_mb=search_space.IntRange(min=8192),
            ),
            supported_platform_type=[CLOUD_HYPERVISOR],
        ),
    )
    def perf_udp_1k_ntttcp_passthrough_host_guest(
        self,
        result: TestResult,
        node: Node,
        log_path: Path,
        variables: Dict[str, Any],
    ) -> None:
        server = self._get_host_as_server(variables)

        client, client_nic_name = self._configure_passthrough_nic_for_node(
            node, log_path, host_node=server
        )

        perf_ntttcp(
            test_result=result,
            client=client,
            server=server,
            server_nic_name=self._get_host_nic_name(server),
            client_nic_name=client_nic_name,
            udp_mode=True,
            skip_server_task_max=True,  # host: TasksMax reboot clears NIC DHCP state
        )

    # Network device passthrough tests between 2 guests
    @TestCaseMetadata(
        description="""
        This test case uses iperf3 to test passthrough tcp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            supported_platform_type=[CLOUD_HYPERVISOR],
            unsupported_os=[Windows],
        ),
    )
    def perf_tcp_iperf_passthrough_two_guest(
        self, result: TestResult, log_path: Path
    ) -> None:
        # Run iperf server on VM and client on another VM
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        server_node = cast(RemoteNode, environment.nodes[1])

        # Reboot both guests first to avoid stale passthrough NIC state.
        client_node.reboot()
        server_node.reboot()

        client, _ = self._configure_passthrough_nic_for_node(client_node, log_path)
        server, _ = self._configure_passthrough_nic_for_node(server_node, log_path)

        perf_iperf(
            test_result=result,
            connections=IPERF_TCP_CONCURRENCY,
            buffer_length_list=IPERF_TCP_BUFFER_LENGTHS,
            server=server,
            client=client,
            run_with_internal_address=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses iperf3 to test passthrough udp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            supported_platform_type=[CLOUD_HYPERVISOR],
            unsupported_os=[Windows],
        ),
    )
    def perf_udp_iperf_passthrough_two_guest(
        self, result: TestResult, log_path: Path
    ) -> None:
        # Run iperf server on VM and client on another VM
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        server_node = cast(RemoteNode, environment.nodes[1])

        # Reboot both nodes; Libvirt may reuse them, boot into fresh state.
        client_node.reboot()
        server_node.reboot()

        client, _ = self._configure_passthrough_nic_for_node(client_node, log_path)
        server, _ = self._configure_passthrough_nic_for_node(server_node, log_path)

        perf_iperf(
            test_result=result,
            connections=IPERF_UDP_CONCURRENCY,
            buffer_length_list=IPERF_UDP_BUFFER_LENGTHS,
            server=server,
            client=client,
            udp_mode=True,
            run_with_internal_address=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses sar to test passthrough network PPS (Packets Per Second)
        when running netperf with single port. Test will consider VM as
        server node and host as client node.
        """,
        priority=3,
        timeout=PPS_TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            supported_platform_type=[CLOUD_HYPERVISOR],
            unsupported_os=[Windows],
        ),
    )
    def perf_tcp_single_pps_passthrough_two_guest(
        self, result: TestResult, log_path: Path
    ) -> None:
        # Run netperf server on VM and client on another VM
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        server_node = cast(RemoteNode, environment.nodes[1])

        # Reboot both nodes; Libvirt may reuse them, boot into fresh state.
        client_node.reboot()
        server_node.reboot()

        client, _ = self._configure_passthrough_nic_for_node(client_node, log_path)
        server, _ = self._configure_passthrough_nic_for_node(server_node, log_path)

        perf_tcp_pps(
            test_result=result,
            test_type="singlepps",
            server=server,
            client=client,
            use_internal_address=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses sar to test passthrough network PPS (Packets Per Second)
        when running netperf with multiple ports. Test will consider VM as
        server node and host as client node.
        """,
        priority=3,
        timeout=PPS_TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            supported_platform_type=[CLOUD_HYPERVISOR],
            unsupported_os=[Windows],
        ),
    )
    def perf_tcp_max_pps_passthrough_two_guest(
        self, result: TestResult, log_path: Path
    ) -> None:
        # Run netperf server on VM and client on another VM
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        server_node = cast(RemoteNode, environment.nodes[1])

        # Reboot both nodes; Libvirt may reuse them, boot into fresh state.
        client_node.reboot()
        server_node.reboot()

        client, _ = self._configure_passthrough_nic_for_node(client_node, log_path)
        server, _ = self._configure_passthrough_nic_for_node(server_node, log_path)

        perf_tcp_pps(
            test_result=result,
            test_type="maxpps",
            server=server,
            client=client,
            use_internal_address=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test passthrough tcp network throughput
        between two guest VMs.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=2,
                memory_mb=search_space.IntRange(min=8192),
            ),
            supported_platform_type=[CLOUD_HYPERVISOR],
        ),
    )
    def perf_tcp_ntttcp_passthrough_two_guest(
        self, result: TestResult, log_path: Path
    ) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        server_node = cast(RemoteNode, environment.nodes[1])

        # Reboot both nodes; Libvirt may reuse them, boot into fresh state.
        client_node.reboot()
        server_node.reboot()

        client, client_nic_name = self._configure_passthrough_nic_for_node(
            client_node, log_path
        )
        server, server_nic_name = self._configure_passthrough_nic_for_node(
            server_node, log_path
        )

        perf_ntttcp(
            test_result=result,
            client=client,
            server=server,
            server_nic_name=server_nic_name,
            client_nic_name=client_nic_name,
        )

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test passthrough udp network throughput
        between two guest VMs.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=2,
                memory_mb=search_space.IntRange(min=8192),
            ),
            supported_platform_type=[CLOUD_HYPERVISOR],
        ),
    )
    def perf_udp_1k_ntttcp_passthrough_two_guest(
        self, result: TestResult, log_path: Path
    ) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        server_node = cast(RemoteNode, environment.nodes[1])

        # Reboot both nodes; Libvirt may reuse them, boot into fresh state.
        client_node.reboot()
        server_node.reboot()

        client, client_nic_name = self._configure_passthrough_nic_for_node(
            client_node, log_path
        )
        server, server_nic_name = self._configure_passthrough_nic_for_node(
            server_node, log_path
        )

        perf_ntttcp(
            test_result=result,
            client=client,
            server=server,
            server_nic_name=server_nic_name,
            client_nic_name=client_nic_name,
            udp_mode=True,
        )

    @staticmethod
    def _norm_hex(value: str, width: int) -> str:
        """Zero-pad lowercase hex PCI component; strips leading '0x'."""
        return value.lower().replace("0x", "").zfill(width)

    def _configure_passthrough_nic_for_node(
        self,
        node: Node,
        log_path: Path,
        host_node: Optional[RemoteNode] = None,
    ) -> Tuple[RemoteNode, str]:
        from lisa.sut_orchestrator.libvirt.context import get_node_context

        ctx = get_node_context(node)
        if not ctx.passthrough_devices:
            raise SkippedException("No passthrough devices found for node")

        passthrough_dev = ctx.passthrough_devices[0]
        if not passthrough_dev.device_list:
            raise LisaException("passthrough_devices[0].device_list is empty")
        device_addr_obj = passthrough_dev.device_list[0]
        domain = self._norm_hex(device_addr_obj.domain or "0000", 4)
        bus = self._norm_hex(device_addr_obj.bus, 2)
        slot = self._norm_hex(device_addr_obj.slot, 2)
        function = self._norm_hex(device_addr_obj.function, 1)
        device_bdf = f"{domain}:{bus}:{slot}.{function}"

        host_nic_name = ""
        if host_node is not None:
            _h = host_node.execute(
                f"ls /sys/bus/pci/devices/{device_bdf}/net/ 2>/dev/null"
                " | head -1 || true",
                sudo=True,
                shell=True,
            ).stdout.strip()
            _parts = _h.split()
            host_nic_name = _parts[0] if _parts else ""

        # Exclude management interface from passthrough NIC selection.
        mgmt_ip_ssh = cast(RemoteNode, node).connection_info[
            constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS
        ]
        mgmt_iface_raw = node.execute(
            cmd=f"ip -4 route get {mgmt_ip_ssh} 2>/dev/null || true",
            sudo=True,
            shell=True,
        ).stdout.strip()
        _m = re.search(r"\bdev\s+(\S+)", mgmt_iface_raw)
        mgmt_iface = _m.group(1) if _m else ""

        # Enumerate PCI-backed interfaces as: "<iface> <driver> <carrier>".
        iface_info_raw = node.execute(
            cmd=(
                "for iface in /sys/class/net/*/; do "
                "iface=$(basename $iface); "
                "[ -e /sys/class/net/$iface/device ] || continue; "
                "drv=$(basename "
                "$(readlink /sys/class/net/$iface/device/driver 2>/dev/null) "
                "2>/dev/null); "
                "carrier=$(cat /sys/class/net/$iface/carrier 2>/dev/null "
                "|| echo 0); "
                'echo "$iface $drv $carrier"; '
                "done"
            ),
            sudo=False,
            shell=True,
        ).stdout.strip()

        interface_name = self._find_guest_passthrough_iface(
            node, mgmt_iface, iface_info_raw
        )

        node.log.debug(f"[passthrough-nic] GUEST iface={interface_name!r}")
        if host_node is not None and host_nic_name:
            host_node.log.debug(
                f"[passthrough-nic] HOST nic={host_nic_name!r} BDF={device_bdf!r}"
            )

        node.execute(
            cmd=f"ip link set {interface_name} up",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Failed to bring up interface {interface_name}"
            ),
        )

        self._wait_for_carrier(node, interface_name)

        # Flush stale address/route state from prior runs.
        node.execute(
            f"ip addr flush dev {interface_name} 2>/dev/null || true",
            sudo=True,
            shell=True,
        )
        node.execute(
            f"ip route flush dev {interface_name} 2>/dev/null || true",
            sudo=True,
            shell=True,
        )

        dhcp_result = self._run_dhcp_on_iface(node, interface_name)
        if dhcp_result.exit_code != 0:
            self._raise_dhcp_failure(
                node, interface_name, dhcp_result, host_node, host_nic_name
            )

        # Wait briefly for IP address assignment.
        node.execute(
            cmd=(
                f"for i in $(seq 1 10); do "
                f"ip -4 -o addr show dev {interface_name} "
                f"| grep -q 'inet ' && break; "
                f"sleep 1; done"
            ),
            sudo=True,
            shell=True,
        )

        err_msg = f"Failed to get interface details for: {interface_name}"
        interface_details = node.execute(
            cmd=f"ip addr show {interface_name}",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=err_msg,
        ).stdout
        ip_regex = re.compile(r"\binet (?P<INTERFACE_IP>\d+\.\d+\.\d+\.\d+)/\d+\b")
        interface_ip = find_group_in_lines(
            lines=interface_details,
            pattern=ip_regex,
            single_line=False,
        )
        passthrough_nic_ip = interface_ip.get("INTERFACE_IP", "")
        if not passthrough_nic_ip:
            raise LisaException(
                f"Failed to get IP for passthrough interface '{interface_name}'. "
                f"Interface details: {interface_details[:200]}"
            )

        test_node = cast(RemoteNode, node)
        test_node.internal_address = passthrough_nic_ip

        return test_node, interface_name

    def _find_guest_passthrough_iface(
        self,
        node: Node,
        mgmt_iface: str,
        iface_info_raw: str,
    ) -> str:
        """Select passthrough NIC, preferring non-virtio and carrier-up links."""
        pt_candidates: List[Tuple[bool, str]] = []
        virtio_fallback: List[Tuple[bool, str]] = []
        for _line in iface_info_raw.splitlines():
            _parts = _line.split()
            if not _parts:
                continue
            _iface = _parts[0]
            _drv = _parts[1] if len(_parts) > 1 else ""
            _carrier_up = (_parts[2] == "1") if len(_parts) > 2 else False
            if _iface in (mgmt_iface, "lo"):
                continue
            if _drv.startswith("virtio"):
                virtio_fallback.append((_carrier_up, _iface))
            else:
                pt_candidates.append((_carrier_up, _iface))

        # Fall back to virtio, then prefer link-up interfaces.
        if not pt_candidates:
            pt_candidates = virtio_fallback
        pt_candidates.sort(key=lambda t: (not t[0], t[1]))

        if not pt_candidates:
            raise LisaException(
                f"No passthrough NIC found in guest. "
                f"Management iface: {mgmt_iface!r}, "
                f"Enumerated (iface driver carrier): {iface_info_raw!r}"
            )
        return pt_candidates[0][1]

    def _wait_for_carrier(self, node: Node, interface_name: str) -> None:
        """Wait up to 60 s for link carrier; raise with diagnostics on failure."""
        carrier_result = node.execute(
            cmd=(
                f"timeout 60 sh -c 'until cat /sys/class/net/{interface_name}/carrier"
                f" 2>/dev/null | grep -q 1; do sleep 1; done'"
            ),
            sudo=True,
            shell=True,
        )
        if carrier_result.exit_code == 124:
            _nc_diag = node.execute(
                cmd=(
                    f"echo '--- ethtool ---';"
                    f" ethtool {interface_name} 2>/dev/null || true;"
                    f" echo '--- ip -d link ---';"
                    f" ip -d link show {interface_name} 2>/dev/null || true;"
                    f" echo '--- dmesg ---';"
                    f" dmesg -T 2>/dev/null"
                    f" | grep -E 'no carrier|carrier loss|"
                    f"link up|link down|vfio|{interface_name}'"
                    f" | tail -n 20 || true"
                ),
                sudo=True,
                shell=True,
            ).stdout.strip()
            raise LisaException(
                f"Interface {interface_name} NO-CARRIER after 60 s. "
                f"Physical link is not up — DHCP would fail. Failing fast.\n"
                f"{_nc_diag}"
            )
        elif carrier_result.exit_code != 0:
            raise LisaException(
                f"Failed to check carrier on {interface_name}: "
                f"exit code {carrier_result.exit_code}"
            )

    def _install_dhclient_scripts(
        self,
        node: Node,
        config_script: str,
    ) -> None:
        """Install minimal dhclient hook script for interface IP config."""
        node.execute("mkdir -p /usr/local/bin /var/lib/dhcp", sudo=True, shell=True)
        node.execute(
            f"printf '#!/bin/sh\\n"
            f"pfx=0\\n"
            f"IFS=.\\n"
            f'case "$reason" in\\n'
            f'  BOUND|RENEW|REBIND|REBOOT) _mask="$new_subnet_mask" ;;\\n'
            f'  *)                          _mask="$old_subnet_mask" ;;\\n'
            f"esac\\n"
            f"for _o in $_mask; do\\n"
            f"  case $_o in\\n"
            f"    255) pfx=$((pfx+8)) ;;\\n"
            f"    254) pfx=$((pfx+7)) ;;\\n"
            f"    252) pfx=$((pfx+6)) ;;\\n"
            f"    248) pfx=$((pfx+5)) ;;\\n"
            f"    240) pfx=$((pfx+4)) ;;\\n"
            f"    224) pfx=$((pfx+3)) ;;\\n"
            f"    192) pfx=$((pfx+2)) ;;\\n"
            f"    128) pfx=$((pfx+1)) ;;\\n"
            f"  esac\\n"
            f"done\\n"
            f"unset IFS\\n"
            f'case "$reason" in\\n'
            f"  BOUND|RENEW|REBIND|REBOOT)\\n"
            f'    ip addr replace "${{new_ip_address}}/$pfx"'
            f' dev "$interface" 2>/dev/null || true\\n'
            f"    ;;\\n"
            f"  EXPIRE|FAIL|RELEASE|STOP)\\n"
            f'    ip addr del "${{old_ip_address}}/$pfx"'
            f' dev "$interface" 2>/dev/null || true\\n'
            f"    ;;\\n"
            f"esac\\n"
            f"exit 0\\n'"
            f" | tee '{config_script}' >/dev/null"
            f" && chmod 0755 '{config_script}'"
            f" && chown root:root '{config_script}'",
            sudo=True,
            shell=True,
        )
        # Run script once to catch noexec mount issues early.
        node.execute(f"'{config_script}'", sudo=True, shell=True)

    def _run_dhcp_on_iface(self, node: Node, interface_name: str) -> Any:
        """Run dhclient with safety guards and return its result."""
        # Probe which DHCP client is available via the Dhclient tool.
        # Our custom -sf hook is dhclient-specific; skip on images with only dhcpcd.
        dhclient_tool = node.tools[Dhclient]
        if dhclient_tool.command != "dhclient":
            raise SkippedException(
                f"Passthrough NIC DHCP requires dhclient; "
                f"found '{dhclient_tool.command}' which is not supported."
            )
        dhcp_pid = f"/run/dhclient-{interface_name}.pid"
        dhcp_lease = f"/var/lib/dhcp/dhclient-{interface_name}.leases"
        config_script = "/usr/local/bin/lisa-dhclient-config"

        def _wrap_aa(cmd: str) -> str:
            """Run cmd under AppArmor 'unconfined' when aa-exec is available."""
            return (
                "sh -c '"
                "if command -v aa-exec >/dev/null 2>&1; then "
                f"aa-exec -p unconfined -- {cmd}; "
                f"else {cmd}; "
                "fi'"
            )

        self._install_dhclient_scripts(node, config_script)

        # Isolate only the target interface from competing DHCP managers.
        # NM: mark this interface unmanaged instead of stopping the service.
        _nm_active = (
            node.execute(
                "systemctl is-active NetworkManager 2>/dev/null || true",
                sudo=True,
                shell=True,
            ).stdout.strip()
            == "active"
        )
        _nm_was_managed = _nm_active and (
            node.execute(
                f"nmcli -g GENERAL.NM-MANAGED device show {interface_name}"
                " 2>/dev/null || true",
                sudo=True,
                shell=True,
            )
            .stdout.strip()
            .lower()
            == "yes"
        )
        if _nm_was_managed:
            node.execute(
                f"nmcli device set {interface_name} managed no" " 2>/dev/null || true",
                sudo=True,
                shell=True,
            )
        # systemd-networkd: write a per-interface drop-in that marks it
        # unmanaged, then reload (no service stop needed).
        _nd_dropin = f"/etc/systemd/network/90-{interface_name}-unmanaged.network"
        _nd_was_managed = (
            node.execute(
                "systemctl is-active systemd-networkd 2>/dev/null || true",
                sudo=True,
                shell=True,
            ).stdout.strip()
            == "active"
        ) and (
            "unmanaged"
            not in node.execute(
                f"networkctl status {interface_name} 2>/dev/null || true",
                sudo=True,
                shell=True,
            ).stdout
        )
        if _nd_was_managed:
            node.execute(
                f"printf '[Match]\\nName={interface_name}\\n\\n"
                f"[Link]\\nUnmanaged=yes\\n' > {_nd_dropin}"
                "; networkctl reload 2>/dev/null || true",
                sudo=True,
                shell=True,
            )
        try:
            # Release stale lease and kill leftover dhclient processes.
            node.execute(
                f"dhclient -r -pf {dhcp_pid} -lf {dhcp_lease}"
                f" {interface_name} 2>/dev/null || true",
                sudo=True,
                shell=True,
            )
            node.execute(
                f"if [ -s {dhcp_pid} ]; then"
                f'  kill "$(cat {dhcp_pid})" 2>/dev/null || true; fi'
                f"; sleep 1"
                f"; if [ -s {dhcp_pid} ]; then"
                f'  kill -9 "$(cat {dhcp_pid})" 2>/dev/null || true; fi'
                f"; rm -f {dhcp_pid}"
                f"; pkill -f 'dhclient.*{interface_name}' 2>/dev/null || true",
                sudo=True,
                shell=True,
            )
            node.execute(
                f"ip addr flush dev {interface_name} 2>/dev/null || true",
                sudo=True,
                shell=True,
            )
            # Real dhclient run with minimal config hook.
            dhcp_cmd = (
                f"dhclient -v -1 -4 -sf {config_script}"
                f" -pf {dhcp_pid} -lf {dhcp_lease} {interface_name}"
            )
            dhcp_result = node.execute(
                f"timeout -k 2s 30s {_wrap_aa(dhcp_cmd)}",
                sudo=True,
                shell=True,
                timeout=45,
            )
        finally:
            if _nd_was_managed:
                node.execute(
                    f"rm -f {_nd_dropin}" "; networkctl reload 2>/dev/null || true",
                    sudo=True,
                    shell=True,
                )
            if _nm_was_managed:
                node.execute(
                    f"nmcli device set {interface_name} managed yes"
                    " 2>/dev/null || true",
                    sudo=True,
                    shell=True,
                )
        return dhcp_result

    def _raise_dhcp_failure(
        self,
        node: Node,
        interface_name: str,
        dhcp_result: Any,
        host_node: Optional[RemoteNode],
        host_nic_name: str,
    ) -> None:
        """Gather diagnostics and raise LisaException for a DHCP failure."""
        fail_link = node.execute(
            f"ip -d link show {interface_name}", sudo=True, shell=True
        ).stdout
        fail_addr = node.execute(
            f"ip -4 addr show {interface_name}", sudo=True, shell=True
        ).stdout
        fail_routes = node.execute("ip -4 route", sudo=True, shell=True).stdout
        fail_rp = node.execute(
            f"sysctl net.ipv4.conf.{interface_name}.rp_filter"
            " net.ipv4.conf.all.rp_filter 2>/dev/null || true",
            sudo=True,
            shell=True,
        ).stdout
        fail_host_info = ""
        if host_node is not None:
            _iface_arg = host_nic_name or ""
            _rp_iface = (
                f" net.ipv4.conf.{host_nic_name}.rp_filter" if host_nic_name else ""
            )
            _h = host_node.execute(
                f"echo '--- HOST ip link ---';"
                f" ip -d link show {_iface_arg} 2>/dev/null || ip -d link show;"
                f" echo '--- HOST ip route default ---';"
                f" ip -4 route show default;"
                f" echo '--- HOST rp_filter ---';"
                f" sysctl net.ipv4.conf.all.rp_filter{_rp_iface} 2>/dev/null || true",
                sudo=True,
                shell=True,
            ).stdout
            fail_host_info = f"--- HOST diagnostics ---\n{_h}\n"
        raise LisaException(
            f"DHCP lease failed on interface {interface_name} "
            f"(dhclient exit code {dhcp_result.exit_code}).\n"
            f"dhclient output:\n{dhcp_result.stdout}\n"
            f"--- ip -d link show ---\n{fail_link}\n"
            f"--- ip -4 addr show ---\n{fail_addr}\n"
            f"--- ip -4 route ---\n{fail_routes}\n"
            f"--- rp_filter ---\n{fail_rp}\n"
            f"{fail_host_info}"
        )

    def _get_host_as_server(self, variables: Dict[str, Any]) -> RemoteNode:
        ip = variables.get("baremetal_host_ip", "")
        username = variables.get("baremetal_host_username", "")
        passwd = variables.get("baremetal_host_password", "")
        private_key = variables.get("baremetal_host_private_key_file", "")

        if not (ip and username and (passwd or private_key)):
            raise SkippedException(
                "Server-Node details are not provided. Required: "
                "baremetal_host_ip, baremetal_host_username, and either "
                "baremetal_host_password or baremetal_host_private_key_file"
            )

        server = RemoteNode(
            runbook=schema.Node(name="baremetal-host"),
            index=-1,
            logger_name="baremetal-host",
            parent_logger=get_logger("baremetal-host-platform"),
        )
        server.set_connection_info(
            address=ip,
            public_address=ip,
            public_port=22,
            username=username,
            password=passwd,
            private_key_file=private_key,
        )
        server.internal_address = ip

        server.initialize()

        if isinstance(server.os, Windows):
            server.close()
            server.cleanup()
            raise SkippedException(
                "Host/guest passthrough performance tests require a Linux "
                "baremetal host; Windows baremetal hosts are not supported."
            )

        # Track baremetal host for cleanup.
        if server not in self._baremetal_hosts:
            self._baremetal_hosts.append(server)
        return server

    def _get_host_nic_name(self, node: RemoteNode) -> str:
        ip = node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS]
        command = "ip route show"
        routes = node.execute(
            cmd=command,
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Can not get IP route",
        ).stdout

        regex_pattern = re.compile(
            r"^default.*?dev\s+(?P<interface>\S+).*?src\s+(?P<ip>\d+\.\d+\.\d+\.\d+)\s"
        )
        matches = find_groups_in_lines(
            lines=routes,
            pattern=regex_pattern,
            single_line=True,
        )
        interface_name: str = ""
        for match in matches:
            match_ip = match.get("ip", "").strip()
            if match_ip == ip:
                interface_name = match.get("interface", "")
                break
        assert interface_name, f"Can't get {ip} interface name from: {routes}"
        return interface_name

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")

        # Include baremetal hosts in cleanup.
        all_nodes = list(environment.nodes.list())
        if self._baremetal_hosts:
            all_nodes.extend(self._baremetal_hosts)

        def do_process_cleanup(process: str, node: Node) -> None:
            try:
                if isinstance(node.os, Windows):
                    escaped_process = process.replace("'", "''")
                    node.tools[PowerShell].run_cmdlet(
                        cmdlet=(
                            f"$p = Get-Process -Name '{escaped_process}' "
                            "-ErrorAction SilentlyContinue; "
                            "if ($p) { $p | Stop-Process -Force "
                            "-ErrorAction SilentlyContinue }"
                        ),
                        fail_on_error=False,
                    )
                    return

                kill = node.tools[Kill]
                kill.by_name(process, ignore_not_exist=True)
            except LisaException as identifier_error:
                log.debug(
                    f"Skipping Kill tool-based cleanup for '{process}' on "
                    f"node '{node.name}': {identifier_error}"
                )
                if isinstance(node.os, Windows):
                    return

                node.execute(
                    cmd=(
                        f"pids=$(pidof {process} 2>/dev/null || true); "
                        '[ -z "$pids" ] || kill -9 $pids || true'
                    ),
                    shell=True,
                    sudo=True,
                )

        def do_sysctl_cleanup(node: Node) -> None:
            if isinstance(node.os, Windows):
                return

            try:
                node.tools[Sysctl].reset()
            except LisaException as sysctl_error:
                log.debug(
                    f"Skipping sysctl cleanup on node '{node.name}': {sysctl_error}"
                )

        cleanup_tasks: List[Callable[[], None]] = []
        for process in ["lagscope", "netperf", "netserver", "ntttcp", "iperf3"]:
            for node in all_nodes:
                cleanup_tasks.append(partial(do_process_cleanup, process, node))

        run_in_parallel(cleanup_tasks)
        run_in_parallel([partial(do_sysctl_cleanup, x) for x in all_nodes])

        # Clear the baremetal hosts list after cleanup
        self._baremetal_hosts.clear()
