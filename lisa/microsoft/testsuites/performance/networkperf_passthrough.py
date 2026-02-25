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
from lisa.tools import Kill, Sysctl
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

        # Reboot only the guest VM before configuration.
        # Libvirt sometimes re-uses nodes; boot into a fresh state so the
        # passthrough NIC comes up cleanly. Do NOT reboot the baremetal host.
        cast(RemoteNode, node).reboot()

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

        # Reboot only the guest VM before configuration.
        # Libvirt sometimes re-uses nodes; boot into a fresh state so the
        # passthrough NIC comes up cleanly. Do NOT reboot the baremetal host.
        cast(RemoteNode, node).reboot()

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

        # Reboot only the guest VM before configuration.
        # Libvirt sometimes re-uses nodes; boot into a fresh state so the
        # passthrough NIC comes up cleanly. Do NOT reboot the baremetal host.
        cast(RemoteNode, node).reboot()

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

        # Reboot only the guest VM before configuration.
        # Libvirt sometimes re-uses nodes; boot into a fresh state so the
        # passthrough NIC comes up cleanly. Do NOT reboot the baremetal host.
        cast(RemoteNode, node).reboot()

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

        # Reboot only the guest VM before configuration.
        # Libvirt sometimes re-uses nodes; boot into a fresh state so the
        # passthrough NIC comes up cleanly. Do NOT reboot the baremetal host.
        cast(RemoteNode, node).reboot()

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

        # Reboot only the guest VM before configuration.
        # Libvirt sometimes re-uses nodes; boot into a fresh state so the
        # passthrough NIC comes up cleanly. Do NOT reboot the baremetal host.
        cast(RemoteNode, node).reboot()

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

        def _wrap_aa_unconfined(cmd: str) -> str:
            """Wrap *cmd* so it runs under the AppArmor 'unconfined' profile
            when aa-exec is available; fall back to plain cmd otherwise.

            The if/then/else/fi must be inside a sh -c '...' so that
            'timeout' receives a single executable (sh) rather than the
            bare word 'if', which is a shell built-in and would cause:
              sh: Syntax error: "then" unexpected
            timeout is still placed *outside* this wrapper so it controls
            the full process lifetime regardless of confinement.
            """
            return (
                "sh -c '"
                "if command -v aa-exec >/dev/null 2>&1; then "
                f"aa-exec -p unconfined -- {cmd}; "
                f"else {cmd}; "
                "fi'"
            )

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
        # Identify the passthrough NIC inside the guest without relying on
        # the host-side BDF (QEMU assigns a guest-local BDF that differs).
        #
        # Strategy:
        #   1. Find the SSH management interface via 'ip route get <mgmt_ip>'.
        #   2. Enumerate all non-loopback interfaces that have a PCI backing
        #      (/sys/class/net/<if>/device must exist) in one shell pass.
        #   3. Exclude the management interface; prefer non-virtio-pci drivers
        #      (virtio = emulated mgmt/data NIC, non-virtio = passthrough NIC).
        #   4. Once the interface is identified, look up its guest BDF via
        #      readlink and use canonical sysfs to confirm the mapping.
        # Use the stable SSH target address — NOT internal_address, which gets
        # overwritten with the passthrough IP later in this function.
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

        # One-shot loop: emit "<iface> <driver> <carrier>" for every
        # PCI-backed interface.
        # carrier==1 means link is up; we prefer those candidates.
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

        # Tuples of (carrier_up, iface) — non-virtio preferred, link-up preferred.
        # Virtio drivers (virtio_net, virtio-pci, …) are the emulated mgmt/data
        # NICs; anything else is a passthrough candidate.
        pt_candidates: List[Tuple[bool, str]] = []
        virtio_fallback: List[Tuple[bool, str]] = []
        for _line in iface_info_raw.splitlines():
            _parts = _line.split()
            if not _parts:
                continue
            _iface = _parts[0]
            _drv = _parts[1] if len(_parts) > 1 else ""
            _carrier_up = (_parts[2] == "1") if len(_parts) > 2 else False
            if _iface == mgmt_iface or _iface == "lo":
                continue
            if _drv.startswith("virtio"):
                virtio_fallback.append((_carrier_up, _iface))
            else:
                pt_candidates.append((_carrier_up, _iface))

        # Fall back to virtio interfaces if no non-virtio candidate found.
        # Sort so link-up (carrier=True) interfaces come first.
        if not pt_candidates:
            pt_candidates = virtio_fallback
        pt_candidates.sort(key=lambda t: (not t[0], t[1]))

        if not pt_candidates:
            raise LisaException(
                f"No passthrough NIC found in guest. "
                f"Management iface: {mgmt_iface!r}, "
                f"Enumerated (iface driver carrier): {iface_info_raw!r}"
            )
        interface_name = pt_candidates[0][1]

        # Confirm via canonical sysfs: get the guest BDF and verify net/ entry
        _bdf_raw = node.execute(
            cmd=f"readlink -f /sys/class/net/{interface_name}/device 2>/dev/null"
            " | xargs basename 2>/dev/null || true",
            sudo=False,
            shell=True,
        ).stdout.strip()
        if _bdf_raw:
            _sysfs_check = node.execute(
                cmd=f"ls /sys/bus/pci/devices/{_bdf_raw}/net/ 2>/dev/null || true",
                sudo=False,
                shell=True,
            ).stdout.strip()
            node.log.debug(
                f"[passthrough-nic] guest BDF={_bdf_raw!r} "
                f"net/={_sysfs_check!r} selected iface={interface_name!r}"
            )

        node.log.info(f"[passthrough-nic] GUEST iface={interface_name!r}")
        if host_node is not None and host_nic_name:
            host_node.log.info(
                f"[passthrough-nic] HOST nic={host_nic_name!r}"
                f" (host BDF={device_bdf!r})"
            )

        # Bring the interface up before configuring it
        node.execute(
            cmd=f"ip link set {interface_name} up",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Failed to bring up interface {interface_name}"
            ),
        )

        # Wait for carrier (link up) — some NICs take time to negotiate.
        # 60 s is used because VFs occasionally report carrier late on some
        # host driver combinations.
        carrier_result = node.execute(
            cmd=f"timeout 60 sh -c 'until cat /sys/class/net/{interface_name}/carrier"
            f" 2>/dev/null | grep -q 1; do sleep 1; done'",
            sudo=True,
            shell=True,
        )
        if carrier_result.exit_code == 124:
            # Carrier not up after 60 s — physical link is down.
            # DHCP will never succeed without a link; fail fast with diagnostics.
            _nc_ethtool = node.execute(
                cmd=f"ethtool {interface_name} 2>/dev/null || true",
                sudo=True,
                shell=True,
            ).stdout.strip()
            _nc_ip_link = node.execute(
                cmd=f"ip -d link show {interface_name}",
                sudo=True,
                shell=True,
            ).stdout.strip()
            _nc_dmesg = node.execute(
                cmd="dmesg -T 2>/dev/null"
                f" | grep -E 'i40e|ixgbe|mlx|vfio|{interface_name}|link|carrier'"
                " | tail -n 50 || true",
                sudo=True,
                shell=True,
            ).stdout.strip()
            raise LisaException(
                f"Interface {interface_name} NO-CARRIER after 60 s. "
                f"Physical link is not up — DHCP would fail. Failing fast.\n"
                f"ethtool {interface_name}:\n{_nc_ethtool}\n"
                f"ip -d link show:\n{_nc_ip_link}\n"
                f"dmesg (NIC/carrier):\n{_nc_dmesg}"
            )
        elif carrier_result.exit_code != 0:
            raise LisaException(
                f"Failed to check carrier on {interface_name}: "
                f"exit code {carrier_result.exit_code}"
            )

        # Bounded DHCP: kill any stale dhclient, release old lease, then renew
        # with a hard timeout so we never hang for 600 s waiting for a server.

        # Flush stale address/route state from previous runs so dhclient
        # starts from a clean slate (avoids duplicate-IP / route conflicts).
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
        # Use deterministic pid and lease file paths so:
        #   - kill can target by pidfile (no stale process ambiguity)
        #   - dhclient -r releases the exact lease we acquired
        #   - lease file is readable after the run for diagnostics
        dhcp_pid_file = f"/run/dhclient-{interface_name}.pid"
        dhcp_lease_file = f"/var/lib/dhcp/dhclient-{interface_name}.leases"
        # Two hook scripts, both in /usr/local/bin (noexec-safe, AppArmor-
        # accessible; /run can be mounted noexec on some images).
        #
        # dhcp_bypass_script: pure noop (exit 0).  Used only for the probe
        #   run so we can test the base DHCP/ARP path without executing any
        #   hook at all.
        #
        # dhcp_config_script: minimal "configure IP only" hook.  Used for the
        #   real dhclient run.  It applies ip-addr to the passthrough NIC but
        #   does NOT add a default route — the stock dhclient-script would
        #   add a default route via the passthrough GW and displace the
        #   existing default route used by the management SSH session (ens4),
        #   which breaks the SSH connection and causes a 15-minute hang.
        dhcp_bypass_script = "/usr/local/bin/lisa-dhclient-noop"
        dhcp_config_script = "/usr/local/bin/lisa-dhclient-config"

        # Ensure both the lease directory and the script directory exist.
        # /usr/local/bin can be absent on minimal images; /var/lib/dhcp path
        # varies by distro but is the most common location.
        node.execute("mkdir -p /usr/local/bin /var/lib/dhcp", sudo=True, shell=True)

        # Noop script — just exit 0 so every hook reason is a no-op.
        node.execute(
            "printf '#!/bin/sh\\nexit 0\\n'"
            f" | tee '{dhcp_bypass_script}' >/dev/null"
            f" && chmod 0755 '{dhcp_bypass_script}'"
            f" && chown root:root '{dhcp_bypass_script}'",
            sudo=True,
            shell=True,
        )

        # Minimal config script — applies ip addr, NO default route, NO
        # resolv.conf, NO NM notification.  This is exactly what we need
        # for the passthrough NIC: get an IP assigned without touching the
        # routing table's default entry.
        #
        # ISC dhclient does NOT set new_prefix_length / old_prefix_length.
        # It provides new_subnet_mask / old_subnet_mask (e.g. "255.255.254.0").
        # We compute the CIDR prefix length with a portable sh bit-count loop.
        # Using unset IFS (instead of IFS=' ') avoids a literal single-quote
        # inside the printf '...' wrapper.
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
            f" | tee '{dhcp_config_script}' >/dev/null"
            f" && chmod 0755 '{dhcp_config_script}'"
            f" && chown root:root '{dhcp_config_script}'",
            sudo=True,
            shell=True,
        )

        # Sanity-check both scripts: execute them directly so we catch noexec
        # mounts or permission issues immediately.
        node.execute(f"'{dhcp_bypass_script}'", sudo=True, shell=True)
        node.execute(f"'{dhcp_config_script}'", sudo=True, shell=True)

        # ── Suppress competing DHCP managers for the duration ─────────────
        # NetworkManager and systemd-networkd both react to carrier-up events
        # and can race dhclient for port 68, corrupt the lease, or apply their
        # own routes while we're doing DHCP.  Stop them briefly; restore after
        # in a try/finally so the node is never left with managers stopped if
        # an exception fires mid-way.
        _nm_was_active = (
            node.execute(
                "systemctl is-active NetworkManager 2>/dev/null || true",
                sudo=True,
                shell=True,
            ).stdout.strip()
            == "active"
        )
        # Only stop systemd-networkd if it is both active AND currently
        # managing the passthrough interface.  If the interface is already
        # "unmanaged", stopping networkd would disrupt management networking
        # for zero gain (and could drop the SSH session on some images).
        _nd_systemd_active = (
            node.execute(
                "systemctl is-active systemd-networkd 2>/dev/null || true",
                sudo=True,
                shell=True,
            ).stdout.strip()
            == "active"
        )
        _nd_iface_managed = _nd_systemd_active and (
            "unmanaged"
            not in node.execute(
                f"networkctl status {interface_name} 2>/dev/null || true",
                sudo=True,
                shell=True,
            ).stdout
        )
        _nd_was_active = _nd_iface_managed
        if _nm_was_active:
            node.execute(
                "systemctl stop NetworkManager 2>/dev/null || true",
                sudo=True,
                shell=True,
            )
        if _nd_was_active:
            node.execute(
                "systemctl stop systemd-networkd 2>/dev/null || true",
                sudo=True,
                shell=True,
            )
        try:
            # Cleanup order: release first (best-effort, frees DHCP server
            # binding), then kill any survivors.
            # Kill order: SIGTERM → 1 s grace → SIGKILL.
            node.execute(
                f"dhclient -r -pf {dhcp_pid_file} -lf {dhcp_lease_file}"
                f" {interface_name} 2>/dev/null || true",
                sudo=True,
                shell=True,
            )
            node.execute(
                # Guard with -s to skip empty/garbage pidfiles.
                f"if [ -s {dhcp_pid_file} ]; then"
                f'  kill "$(cat {dhcp_pid_file})" 2>/dev/null || true; fi'
                f"; sleep 1"
                f"; if [ -s {dhcp_pid_file} ]; then"
                f'  kill -9 "$(cat {dhcp_pid_file})" 2>/dev/null || true; fi'
                f"; rm -f {dhcp_pid_file}"
                f"; pkill -f 'dhclient.*{interface_name}' 2>/dev/null || true",
                sudo=True,
                shell=True,
            )

            # ── Script-bypass probe ────────────────────────────────────────
            # Run dhclient with -sf pointing to our noop script (skips all
            # enter/exit hooks: route injection, resolv.conf, etc.).
            # Success → base DHCP/ARP path is fine; hooks were not exercised.
            # If this probe succeeds but the normal run hangs → hang is in hooks.
            # If this probe also hangs → hang is in ARP/kernel/netlink, not hooks.
            # aa-exec -p unconfined: run dhclient outside its AppArmor profile to
            # avoid policy interactions (netlink, helper scripts, resolvconf, etc.)
            # that can cause hangs under confinement.
            # Falls back to plain dhclient on images without aa-exec (non-Ubuntu).
            # timeout wraps the whole aa-exec invocation so it controls the full
            # process lifetime; SIGTERM at 25 s, SIGKILL 2 s later.
            probe_cmd = (
                f"dhclient -v -1 -4"
                f" -sf {dhcp_bypass_script}"
                f" -pf {dhcp_pid_file} -lf {dhcp_lease_file}"
                f" {interface_name}"
            )
            probe_result = node.execute(
                f"timeout -k 2s 25s {_wrap_aa_unconfined(probe_cmd)}",
                sudo=True,
                shell=True,
                timeout=30,
            )
            if probe_result.exit_code in (124, 137):
                # 124 = SIGTERM timeout; 137 = SIGKILL (timeout -k sent it)
                node.log.warning(
                    f"dhclient probe timed out on {interface_name}"
                    f" (exit {probe_result.exit_code})"
                )
            elif probe_result.exit_code != 0:
                node.log.warning(
                    f"dhclient probe failed (exit {probe_result.exit_code})"
                    f" on {interface_name}"
                )
            # Kill any probe residual before the real run.
            node.execute(
                f"if [ -s {dhcp_pid_file} ]; then"
                f'  kill -9 "$(cat {dhcp_pid_file})" 2>/dev/null || true; fi'
                f"; rm -f {dhcp_pid_file}",
                sudo=True,
                shell=True,
            )
            node.execute(
                f"ip addr flush dev {interface_name} 2>/dev/null || true",
                sudo=True,
                shell=True,
            )

            # ── Normal dhclient run ────────────────────────────────────────
            # Use -sf {dhcp_config_script} instead of the default
            # dhclient-script.  The default script adds a default route via
            # the passthrough GW (displacing ens4's default route and killing
            # the SSH session) and rewrites resolv.conf.  Our minimal script
            # only does ip addr, which is all the test needs.
            # aa-exec: avoid AppArmor policy interactions on Ubuntu.
            # timeout: SIGTERM at 30 s, SIGKILL 2 s later.
            dhcp_cmd = (
                f"dhclient -v -1 -4"
                f" -sf {dhcp_config_script}"
                f" -pf {dhcp_pid_file} -lf {dhcp_lease_file}"
                f" {interface_name}"
            )
            dhcp_result = node.execute(
                f"timeout -k 2s 30s {_wrap_aa_unconfined(dhcp_cmd)}",
                sudo=True,
                shell=True,
                timeout=45,
            )
            if dhcp_result.exit_code in (124, 137):
                # Timed out — capture in-flight diagnostics while the process
                # may still be in a hook or kernel/netlink call.
                _pid = node.execute(
                    f"cat {dhcp_pid_file} 2>/dev/null || true",
                    sudo=True,
                    shell=True,
                ).stdout.strip()
                _wchan = node.execute(
                    f"cat /proc/{_pid}/wchan 2>/dev/null || true" if _pid else "true",
                    sudo=True,
                    shell=True,
                ).stdout.strip()
                _stack = node.execute(
                    f"cat /proc/{_pid}/stack 2>/dev/null || true" if _pid else "true",
                    sudo=True,
                    shell=True,
                ).stdout.strip()
                _timeout_ps = node.execute(
                    "ps -ef | grep [d]hclient || true", sudo=True, shell=True
                ).stdout
                _timeout_ss = node.execute(
                    "ss -uapn 2>/dev/null | grep ':68' || true",
                    sudo=True,
                    shell=True,
                ).stdout
                _iface_addr = node.execute(
                    f"ip -4 addr show dev {interface_name} 2>/dev/null || true",
                    sudo=True,
                    shell=True,
                ).stdout
                _iface_route = node.execute(
                    f"ip -4 route show dev {interface_name} 2>/dev/null || true",
                    sudo=True,
                    shell=True,
                ).stdout
                _ip_rules = node.execute(
                    "ip rule show 2>/dev/null || true",
                    sudo=True,
                    shell=True,
                ).stdout
                node.log.warning(
                    f"[dhclient-debug] dhclient timed out"
                    f" (exit {dhcp_result.exit_code}) on {interface_name}.\n"
                    f"dhclient output (first 800 chars):\n"
                    f"{dhcp_result.stdout[:800]}\n"
                    f"pid={_pid!r}  wchan={_wchan!r}\n"
                    f"kernel stack:\n{_stack}\n"
                    f"ps (dhclient):\n{_timeout_ps}\n"
                    f"ss port 68:\n{_timeout_ss}\n"
                    f"ip addr {interface_name}:\n{_iface_addr}\n"
                    f"ip route {interface_name}:\n{_iface_route}\n"
                    f"ip rules:\n{_ip_rules}"
                )
        finally:
            # ── Restore suppressed managers ────────────────────────────────
            # Runs even if dhclient raises or the test assertion fires above.
            if _nd_was_active:
                node.execute(
                    "systemctl start systemd-networkd 2>/dev/null || true",
                    sudo=True,
                    shell=True,
                )
            if _nm_was_active:
                node.execute(
                    "systemctl start NetworkManager 2>/dev/null || true",
                    sudo=True,
                    shell=True,
                )

        if dhcp_result.exit_code != 0:
            # Gather as much NIC/routing state as possible to diagnose the failure.
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
            fail_routes = node.execute("ip -4 route", sudo=True, shell=True).stdout
            fail_rules = node.execute("ip -4 rule", sudo=True, shell=True).stdout
            fail_rp = node.execute(
                f"sysctl net.ipv4.conf.{interface_name}.rp_filter"
                " net.ipv4.conf.all.rp_filter 2>/dev/null || true",
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
                fail_h_routes = host_node.execute(
                    "ip -4 route show default", sudo=True, shell=True
                ).stdout
                fail_h_rules = host_node.execute(
                    "ip -4 rule", sudo=True, shell=True
                ).stdout
                _rp_iface = (
                    f" net.ipv4.conf.{host_nic_name}.rp_filter" if host_nic_name else ""
                )
                fail_h_rp = host_node.execute(
                    f"sysctl net.ipv4.conf.all.rp_filter{_rp_iface}"
                    " 2>/dev/null || true",
                    sudo=True,
                    shell=True,
                ).stdout
                fail_host_info = (
                    f"--- HOST ip -d link show ---\n{fail_h_link}\n"
                    f"--- HOST bridge vlan show ---\n{fail_h_bridge}\n"
                    f"--- HOST ip route show default ---\n{fail_h_routes}\n"
                    f"--- HOST ip rule ---\n{fail_h_rules}\n"
                    f"--- HOST rp_filter ---\n{fail_h_rp}\n"
                )
            raise LisaException(
                f"DHCP lease failed on interface {interface_name} "
                f"(dhclient exit code {dhcp_result.exit_code}).\n"
                f"dhclient output:\n{dhcp_result.stdout}\n"
                f"--- ip -d link show ---\n{fail_link}\n"
                f"--- ip -4 addr show ---\n{fail_addr}\n"
                f"--- ip -s link show (stats) ---\n{fail_stats}\n"
                f"--- ip -4 route ---\n{fail_routes}\n"
                f"--- ip rule ---\n{fail_rules}\n"
                f"--- rp_filter ---\n{fail_rp}\n"
                f"--- ethtool ---\n{fail_ethtool}\n"
                f"--- ethtool -S (counters) ---\n{fail_ethtool_s}\n"
                f"{fail_host_info}"
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
