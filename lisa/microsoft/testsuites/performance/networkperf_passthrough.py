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
from lisa.tools import Kill, Sysctl, TcpDump
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

        # Reboot the nodes before configuration. Libvirt sometimes re-uses the nodes.
        # Boot into a fresh state so that the passthrough NIC comes up cleanly.
        cast(RemoteNode, node).reboot()
        server.reboot(time_out=1200)

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

        # Reboot the nodes before configuration. Libvirt sometimes re-uses the nodes.
        # Boot into a fresh state so that the passthrough NIC comes up cleanly.
        cast(RemoteNode, node).reboot()
        server.reboot(time_out=1200)

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

        # Reboot the nodes before configuration. Libvirt sometimes re-uses the nodes.
        # Boot into a fresh state so that the passthrough NIC comes up cleanly.
        cast(RemoteNode, node).reboot()
        server.reboot(time_out=1200)

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

        # Reboot the nodes before configuration. Libvirt sometimes re-uses the nodes.
        # Boot into a fresh state so that the passthrough NIC comes up cleanly.
        cast(RemoteNode, node).reboot()
        server.reboot(time_out=1200)

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

        # Reboot the nodes before configuration. Libvirt sometimes re-uses the nodes.
        # Boot into a fresh state so that the passthrough NIC comes up cleanly.
        cast(RemoteNode, node).reboot()
        server.reboot(time_out=1200)

        client, client_nic_name = self._configure_passthrough_nic_for_node(
            node, log_path, host_node=server
        )

        perf_ntttcp(
            test_result=result,
            client=client,
            server=server,
            server_nic_name=self._get_host_nic_name(server),
            client_nic_name=client_nic_name,
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

        # Reboot the nodes before configuration. Libvirt sometimes re-uses the nodes.
        # Boot into a fresh state so that the passthrough NIC comes up cleanly.
        cast(RemoteNode, node).reboot()
        server.reboot(time_out=1200)

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

        # Reboot the nodes before configuration. Libvirt sometimes re-uses the nodes.
        # Boot into a fresh state so that the passthrough NIC comes up cleanly.
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

        # Reboot the nodes before configuration. Libvirt sometimes re-uses the nodes.
        # Boot into a fresh state so that the passthrough NIC comes up cleanly.
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

        # Reboot the nodes before configuration. Libvirt sometimes re-uses the nodes.
        # Boot into a fresh state so that the passthrough NIC comes up cleanly.
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

        # Reboot the nodes before configuration. Libvirt sometimes re-uses the nodes.
        # Boot into a fresh state so that the passthrough NIC comes up cleanly.
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

        # Reboot the nodes before configuration. Libvirt sometimes re-uses the nodes.
        # Boot into a fresh state so that the passthrough NIC comes up cleanly.
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

        # Reboot the nodes before configuration. Libvirt sometimes re-uses the nodes.
        # Boot into a fresh state so that the passthrough NIC comes up cleanly.
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
        """Normalise a PCI address component to zero-padded lowercase hex.

        Accepts "0x19", "0X019", "19", "0019" – all become "19" (width=2)
        or "0019" (width=4 for the domain).
        """
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

        # Use passthrough_devices from context as the source of truth
        passthrough_dev = ctx.passthrough_devices[0]
        if not passthrough_dev.device_list:
            raise LisaException("passthrough_devices[0].device_list is empty")
        device_addr_obj = passthrough_dev.device_list[0]
        # Normalise each component to canonical zero-padded lowercase hex so
        # the path matches exactly what the kernel exposes under /sys/bus/pci/,
        # regardless of whether the runbook wrote "0x0000", "0000", or "0".
        domain = self._norm_hex(device_addr_obj.domain or "0000", 4)
        bus = self._norm_hex(device_addr_obj.bus, 2)
        slot = self._norm_hex(device_addr_obj.slot, 2)
        function = self._norm_hex(device_addr_obj.function, 1)
        device_bdf = f"{domain}:{bus}:{slot}.{function}"

        # If a host node is provided, look up which NIC maps to this BDF on the
        # host. After VFIO passthrough the driver is unbound so net/ may be
        # absent; fall back to capturing on 'any' in that case.
        host_nic_name = ""
        if host_node is not None:
            _h = host_node.execute(
                f"ls /sys/bus/pci/devices/{device_bdf}/net/ 2>/dev/null"
                " | head -1 || true",
                sudo=True,
                shell=True,
            ).stdout.strip()
            host_nic_name = _h.split()[0] if _h.split() else ""
        err_msg: str = f"Can't find interface from PCI address: {device_bdf}"
        interface_name = (
            node.execute(
                cmd=f"ls /sys/bus/pci/devices/{device_bdf}/net/",
                sudo=True,
                shell=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=err_msg,
            )
            .stdout.strip()
            .split()[0]
        )
        assert (
            interface_name
        ), f"No interface found at /sys/bus/pci/devices/{device_bdf}/net/"

        # Bring the interface up before configuring it
        node.execute(
            cmd=f"ip link set {interface_name} up",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Failed to bring up interface {interface_name}"
            ),
        )

        # Wait for carrier (link up) - some NICs take time to negotiate
        # Exit code 124 = timeout (no carrier), which is acceptable if DHCP works anyway
        carrier_result = node.execute(
            cmd=f"timeout 30 sh -c 'until cat /sys/class/net/{interface_name}/carrier"
            f" 2>/dev/null | grep -q 1; do sleep 1; done'",
            sudo=True,
            shell=True,
        )
        if carrier_result.exit_code == 124:
            node.log.warning(
                f"Interface {interface_name} carrier not detected after 30s. "
                f"Proceeding with DHCP anyway - may fail if no physical link."
            )
        elif carrier_result.exit_code != 0:
            raise LisaException(
                f"Failed to check carrier on {interface_name}: "
                f"exit code {carrier_result.exit_code}"
            )

        # Bounded DHCP: kill any stale dhclient, release old lease, then renew
        # with a hard timeout so we never hang for 600 s waiting for a server.

        # Debug: capture routing state before DHCP to detect management-NIC disruption
        mgmt_ip = cast(RemoteNode, node).connection_info.get(
            constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS, ""
        )
        pre_routes = node.execute("ip -4 route show", sudo=True, shell=True).stdout
        pre_rules = node.execute("ip -4 rule show", sudo=True, shell=True).stdout
        pre_ssh = node.execute(
            "ss -tnp | grep ':22' || true", sudo=True, shell=True
        ).stdout
        pre_mgmt_route = (
            node.execute(
                f"ip route get {mgmt_ip} 2>/dev/null || true",
                sudo=True,
                shell=True,
            ).stdout
            if mgmt_ip
            else ""
        )

        # Debug: check for conflicting dhclient/NM processes on this interface
        conflicting_procs = node.execute(
            "ps aux | grep -E 'dhclient|NetworkManager|systemd-networkd'"
            " | grep -v grep || true",
            sudo=True,
            shell=True,
        ).stdout
        pid_files = node.execute(
            "ls -l /run/dhclient*.pid /var/run/dhclient*.pid 2>/dev/null || true",
            sudo=True,
            shell=True,
        ).stdout
        nm_status = node.execute(
            "nmcli dev status 2>/dev/null || true", sudo=True, shell=True
        ).stdout
        networkctl_status = node.execute(
            f"networkctl status {interface_name} 2>/dev/null || true",
            sudo=True,
            shell=True,
        ).stdout
        link_detail = node.execute(
            f"ip -d link show {interface_name}", sudo=True, shell=True
        ).stdout
        # Debug: capture interface IP and lease state before dhclient -r (release)
        pre_release_addr = node.execute(
            f"ip -4 addr show dev {interface_name}", sudo=True, shell=True
        ).stdout
        pre_release_routes = node.execute(
            f"ip -4 route show dev {interface_name}", sudo=True, shell=True
        ).stdout
        dhclient_procs_intf = node.execute(
            f"pgrep -a dhclient | grep {interface_name} || true",
            sudo=True,
            shell=True,
        ).stdout
        lease_info = node.execute(
            f"grep -nE 'interface \"{interface_name}\"|fixed-address|lease'"
            f" /var/lib/dhcp/dhclient*.leases 2>/dev/null | tail -n 60 || true",
            sudo=True,
            shell=True,
        ).stdout

        # Guest VLAN / offload / kernel ring-buffer state
        ethtool_k = node.execute(
            f"ethtool -k {interface_name} 2>/dev/null"
            " | egrep -i 'rx-vlan|tx-vlan|gro|gso|lro|tso' || true",
            sudo=True,
            shell=True,
        ).stdout
        bridge_vlan = node.execute(
            "bridge vlan show 2>/dev/null || true", sudo=True, shell=True
        ).stdout
        dmesg_out = node.execute(
            "dmesg -T 2>/dev/null"
            " | egrep -i 'i40e|ixgbe|mlx|vfio|pci|net|link|firmware'"
            " | tail -n 200 || true",
            sudo=True,
            shell=True,
        ).stdout

        # Host-side NIC / VLAN state (if host is accessible)
        host_pre_info = ""
        if host_node is not None:
            h_link = host_node.execute(
                f"ip -d link show {host_nic_name}"
                if host_nic_name
                else "ip -d link show",
                sudo=True,
                shell=True,
            ).stdout
            h_bridge_vlan = host_node.execute(
                "bridge vlan show 2>/dev/null || true", sudo=True, shell=True
            ).stdout
            host_pre_info = (
                f"[dhclient-debug] HOST NIC state"
                f" (bdf={device_bdf}, nic={host_nic_name or 'any'}):\n"
                f"  link detail: {h_link.strip()}\n"
                f"  bridge vlan:\n{h_bridge_vlan}"
            )
            node.log.debug(host_pre_info)

        node.log.debug(
            f"[dhclient-debug] PRE-DHCP on {interface_name}:\n"
            f"  mgmt_ip={mgmt_ip}\n"
            f"  route get mgmt: {pre_mgmt_route.strip()}\n"
            f"  routes:\n{pre_routes}\n"
            f"  rules:\n{pre_rules}\n"
            f"  sshd bindings: {pre_ssh.strip()}\n"
            f"  link detail: {link_detail.strip()}\n"
            f"  ethtool -k (offloads): {ethtool_k.strip()}\n"
            f"  bridge vlan:\n{bridge_vlan}\n"
            f"  dmesg (NIC-related):\n{dmesg_out}\n"
            f"  --- pre-release state (before dhclient -r) ---\n"
            f"  addr on {interface_name}: {pre_release_addr.strip()}\n"
            f"  routes on {interface_name}: {pre_release_routes.strip()}\n"
            f"  dhclient procs for {interface_name}: {dhclient_procs_intf.strip()}\n"
            f"  lease info:\n{lease_info}\n"
            f"  --- conflict checks ---\n"
            f"  dhclient/NM procs:\n{conflicting_procs}\n"
            f"  pid files: {pid_files.strip()}\n"
            f"  nmcli dev status:\n{nm_status}\n"
            f"  networkctl {interface_name}:\n{networkctl_status}"
        )

        # Guest tcpdump: captures DHCP DISCOVER/OFFER as seen by the VM.
        # This tells us whether DISCOVER reaches the network and OFFER comes back.
        tcpdump_pcap = "dhclient_dhcp_debug.pcap"
        tcpdump_proc = node.tools[TcpDump].dump_async(
            nic_name=interface_name,
            expression="port 67 or port 68",
            packet_filename=tcpdump_pcap,
        )

        # Host tcpdump: captures the same DHCP exchange on the physical NIC.
        # Comparing guest vs host capture reveals where packets are lost:
        #   guest DISCOVER but no host DISCOVER → VF/VFIO path broken
        #   both DISCOVER, no OFFER anywhere   → switch/VLAN/DHCP server issue
        #   OFFER on host but not guest         → VF RX filtering or tagging issue
        host_tcpdump_pcap = "host_dhclient_dhcp_debug.pcap"
        host_tcpdump_proc = None
        if host_node is not None:
            host_tcpdump_iface = host_nic_name or "any"
            host_tcpdump_proc = host_node.tools[TcpDump].dump_async(
                nic_name=host_tcpdump_iface,
                expression="port 67 or port 68",
                packet_filename=host_tcpdump_pcap,
            )

        node.execute(
            f"pkill -f 'dhclient.*{interface_name}' || true",
            sudo=True,
            shell=True,
        )
        node.execute(
            f"dhclient -r {interface_name} || true",
            sudo=True,
            shell=True,
        )
        dhcp_result = node.execute(
            # Outer shell timeout guarantees an exit code even if dhclient
            # ignores -timeout or hangs on a different code path.
            f"timeout 30 dhclient -v -1 -timeout 15 {interface_name}",
            sudo=True,
            shell=True,
            timeout=45,
        )

        # Stop tcpdump and read back the capture in verbose text form
        tcpdump_proc.kill()
        tcpdump_path = node.tools[TcpDump].get_tool_path() / tcpdump_pcap
        tcpdump_out = (
            node.tools[TcpDump]
            .run(
                f"-vvv -n -r {tcpdump_path}",
                sudo=True,
                force_run=True,
                shell=True,
            )
            .stdout
        )
        node.log.debug(
            f"[dhclient-debug] tcpdump DHCP traffic on {interface_name}:\n"
            f"{tcpdump_out[:4000]}"
        )
        node.log.info(
            f"[dhclient-debug] tcpdump DHCP traffic on {interface_name}"
            f" (first 10 lines):\n" + "\n".join(tcpdump_out.splitlines()[:10])
        )
        # Copy the pcap back to the local artifact directory so it is always
        # available after the run, whether DHCP succeeded or failed.
        try:
            local_pcap = log_path / f"{node.name}_{tcpdump_pcap}"
            node.shell.copy_back(tcpdump_path, local_pcap)
            node.log.debug(f"[dhclient-debug] pcap saved locally to {local_pcap}")
        except Exception as copy_err:
            node.log.warning(
                f"[dhclient-debug] Could not copy pcap back to {log_path}: {copy_err}"
            )

        # Stop host tcpdump, read back and copy to local artifacts
        host_tcpdump_out = ""
        if host_tcpdump_proc is not None and host_node is not None:
            host_tcpdump_proc.kill()
            host_tcpdump_path = (
                host_node.tools[TcpDump].get_tool_path() / host_tcpdump_pcap
            )
            host_tcpdump_out = (
                host_node.tools[TcpDump]
                .run(
                    f"-vvv -n -r {host_tcpdump_path}",
                    sudo=True,
                    force_run=True,
                    shell=True,
                )
                .stdout
            )
            node.log.debug(
                f"[dhclient-debug] HOST tcpdump DHCP traffic"
                f" ({host_nic_name or 'any'}):\n{host_tcpdump_out[:4000]}"
            )
            node.log.info(
                f"[dhclient-debug] HOST tcpdump DHCP traffic"
                f" ({host_nic_name or 'any'}) (first 10 lines):\n"
                + "\n".join(host_tcpdump_out.splitlines()[:10])
            )
            try:
                local_host_pcap = log_path / f"{node.name}_host_{host_tcpdump_pcap}"
                host_node.shell.copy_back(host_tcpdump_path, local_host_pcap)
                node.log.debug(
                    f"[dhclient-debug] host pcap saved locally to {local_host_pcap}"
                )
            except Exception as hcopy_err:
                node.log.warning(
                    f"[dhclient-debug] Could not copy host pcap: {hcopy_err}"
                )
        if "DHCPOFFER" not in tcpdump_out and "OFFER" not in tcpdump_out:
            node.log.warning(
                f"[dhclient-debug] No DHCPOFFER seen on GUEST {interface_name}. "
                "DHCP server may be unreachable (no VLAN, blocked port, "
                "no DHCP service on this network)."
            )
        if (
            host_tcpdump_out
            and "DHCPOFFER" not in host_tcpdump_out
            and "OFFER" not in host_tcpdump_out
        ):
            node.log.warning(
                "[dhclient-debug] No DHCPOFFER seen on HOST side either. "
                "DHCP server not responding to this network segment."
            )
        elif (
            host_tcpdump_out
            and ("DHCPDISCOVER" in host_tcpdump_out or "DISCOVER" in host_tcpdump_out)
            and "DHCPOFFER" not in tcpdump_out
            and "OFFER" not in tcpdump_out
        ):
            node.log.warning(
                "[dhclient-debug] DISCOVER seen on HOST but no OFFER on GUEST. "
                "Possible VF RX filtering or VLAN tagging mismatch on the VF path."
            )

        if dhcp_result.exit_code != 0:
            # Gather as much NIC state as possible to diagnose why DHCP failed.
            fail_link = node.execute(
                f"ip -d link show {interface_name}", sudo=True, shell=True
            ).stdout
            fail_addr = node.execute(
                f"ip -4 addr show {interface_name}", sudo=True, shell=True
            ).stdout
            fail_stats = node.execute(
                f"ip -s link show {interface_name}", sudo=True, shell=True
            ).stdout
            fail_ethtool = node.execute(
                f"ethtool {interface_name} 2>/dev/null || true",
                sudo=True,
                shell=True,
            ).stdout
            fail_ethtool_s = node.execute(
                f"ethtool -S {interface_name} 2>/dev/null || true",
                sudo=True,
                shell=True,
            ).stdout
            fail_host_info = ""
            if host_node is not None:
                fail_h_link = host_node.execute(
                    f"ip -d link show {host_nic_name}"
                    if host_nic_name
                    else "ip -d link show",
                    sudo=True,
                    shell=True,
                ).stdout
                fail_h_bridge = host_node.execute(
                    "bridge vlan show 2>/dev/null || true", sudo=True, shell=True
                ).stdout
                fail_host_info = (
                    f"--- HOST ip -d link show ---\n{fail_h_link}\n"
                    f"--- HOST bridge vlan show ---\n{fail_h_bridge}\n"
                    f"--- HOST tcpdump capture ---\n{host_tcpdump_out[:4000]}\n"
                )
            raise LisaException(
                f"DHCP lease failed on interface {interface_name} "
                f"(dhclient exit code {dhcp_result.exit_code}).\n"
                f"dhclient output:\n{dhcp_result.stdout}\n"
                f"--- ip -d link show ---\n{fail_link}\n"
                f"--- ip -4 addr show ---\n{fail_addr}\n"
                f"--- ip -s link show (stats) ---\n{fail_stats}\n"
                f"--- ethtool ---\n{fail_ethtool}\n"
                f"--- ethtool -S (counters) ---\n{fail_ethtool_s}\n"
                f"--- tcpdump DHCP capture (guest) ---\n{tcpdump_out[:4000]}\n"
                f"{fail_host_info}"
            )
        # Debug: capture routing state after DHCP to detect if default route flipped
        post_routes = node.execute("ip -4 route show", sudo=True, shell=True).stdout
        post_mgmt_route = (
            node.execute(
                f"ip route get {mgmt_ip} 2>/dev/null || true",
                sudo=True,
                shell=True,
            ).stdout
            if mgmt_ip
            else ""
        )
        node.log.debug(
            f"[dhclient-debug] POST-DHCP on {interface_name}:\n"
            f"  route get mgmt: {post_mgmt_route.strip()}\n"
            f"  routes:\n{post_routes}"
        )
        if pre_routes != post_routes:
            node.log.warning(
                f"[dhclient-debug] Routing table changed after dhclient on "
                f"{interface_name}! This may disrupt management connectivity.\n"
                f"  BEFORE:\n{pre_routes}\n"
                f"  AFTER:\n{post_routes}"
            )

        # Wait for the IP address to appear. dhclient may return before the
        # kernel has fully processed the DHCP ACK (especially with
        # systemd-networkd interactions), so poll for up to 10 seconds.
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

        # Get the interface ip
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
        # Track baremetal host for cleanup
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

        # root [ /home/cloud ]# ip route show | grep 10.195.88.216 | grep default
        # default via 10.195.88.1 dev eth1 proto dhcp src 10.195.88.216 metric 1024
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

        # Combine environment nodes and baremetal host nodes for cleanup
        all_nodes = list(environment.nodes.list())
        if self._baremetal_hosts:
            all_nodes.extend(self._baremetal_hosts)

        # use these cleanup functions
        def do_process_cleanup(process: str, node: Node) -> None:
            # Kill the process on the specific node
            kill = node.tools[Kill]
            kill.by_name(process, ignore_not_exist=True)

        def do_sysctl_cleanup(node: Node) -> None:
            node.tools[Sysctl].reset()

        # to run parallel cleanup of processes on all nodes
        cleanup_tasks: List[Callable[[], None]] = []
        for process in ["lagscope", "netperf", "netserver", "ntttcp", "iperf3"]:
            for node in all_nodes:
                cleanup_tasks.append(partial(do_process_cleanup, process, node))

        run_in_parallel(cleanup_tasks)
        run_in_parallel([partial(do_sysctl_cleanup, x) for x in all_nodes])

        # Clear the baremetal hosts list after cleanup
        self._baremetal_hosts.clear()
