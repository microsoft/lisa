# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from functools import partial
from typing import Any, Callable, Dict, List, Tuple, cast

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
from lisa.tools import Dhclient, Kill, Lspci, Sysctl
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
        variables: Dict[str, Any],
    ) -> None:
        server = self._get_host_as_server(variables)
        client, _ = self._configure_passthrough_nic_for_node(node)

        # Reboot the nodes. Libvirt sometime re-use the nodes.
        # Try to run the test on fresh state of the nodes
        client.reboot()
        server.reboot(time_out=1200)

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
        variables: Dict[str, Any],
    ) -> None:
        server = self._get_host_as_server(variables)
        client, _ = self._configure_passthrough_nic_for_node(node)

        # Reboot the nodes. Libvirt sometime re-use the nodes.
        # Try to run the test on fresh state of the nodes
        client.reboot()
        server.reboot(time_out=1200)

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
        variables: Dict[str, Any],
    ) -> None:
        server = self._get_host_as_server(variables)
        client, _ = self._configure_passthrough_nic_for_node(node)

        # Reboot the nodes. Libvirt sometime re-use the nodes.
        # Try to run the test on fresh state of the nodes
        client.reboot()
        server.reboot(time_out=1200)

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
        variables: Dict[str, Any],
    ) -> None:
        server = self._get_host_as_server(variables)
        client, _ = self._configure_passthrough_nic_for_node(node)

        # Reboot the nodes. Libvirt sometime re-use the nodes.
        # Try to run the test on fresh state of the nodes
        client.reboot()
        server.reboot(time_out=1200)

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
        variables: Dict[str, Any],
    ) -> None:
        client, client_nic_name = self._configure_passthrough_nic_for_node(node)
        server = self._get_host_as_server(variables)

        # Reboot the nodes. Libvirt sometime re-use the nodes.
        # Try to run the test on fresh state of the nodes
        client.reboot()
        server.reboot(time_out=1200)

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
        variables: Dict[str, Any],
    ) -> None:
        client, client_nic_name = self._configure_passthrough_nic_for_node(node)
        server = self._get_host_as_server(variables)

        # Reboot the nodes. Libvirt sometime re-use the nodes.
        # Try to run the test on fresh state of the nodes
        client.reboot()
        server.reboot(time_out=1200)

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
    def perf_tcp_iperf_passthrough_two_guest(self, result: TestResult) -> None:
        # Run iperf server on VM and client on another VM
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        client, _ = self._configure_passthrough_nic_for_node(client_node)
        server_node = cast(RemoteNode, environment.nodes[1])
        server, _ = self._configure_passthrough_nic_for_node(server_node)

        # Reboot the nodes. Libvirt sometime re-use the nodes.
        # Try to run the test on fresh state of the nodes
        client.reboot()
        server.reboot()

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
    def perf_udp_iperf_passthrough_two_guest(self, result: TestResult) -> None:
        # Run iperf server on VM and client on another VM
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        client, _ = self._configure_passthrough_nic_for_node(client_node)
        server_node = cast(RemoteNode, environment.nodes[1])
        server, _ = self._configure_passthrough_nic_for_node(server_node)

        # Reboot the nodes. Libvirt sometime re-use the nodes.
        # Try to run the test on fresh state of the nodes
        client.reboot()
        server.reboot()

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
    def perf_tcp_single_pps_passthrough_two_guest(self, result: TestResult) -> None:
        # Run netperf server on VM and client on another VM
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        client, _ = self._configure_passthrough_nic_for_node(client_node)
        server_node = cast(RemoteNode, environment.nodes[1])
        server, _ = self._configure_passthrough_nic_for_node(server_node)

        # Reboot the nodes. Libvirt sometime re-use the nodes.
        # Try to run the test on fresh state of the nodes
        client.reboot()
        server.reboot()

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
    def perf_tcp_max_pps_passthrough_two_guest(self, result: TestResult) -> None:
        # Run netperf server on VM and client on another VM
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        client, _ = self._configure_passthrough_nic_for_node(client_node)
        server_node = cast(RemoteNode, environment.nodes[1])
        server, _ = self._configure_passthrough_nic_for_node(server_node)

        # Reboot the nodes. Libvirt sometime re-use the nodes.
        # Try to run the test on fresh state of the nodes
        client.reboot()
        server.reboot()

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
    def perf_tcp_ntttcp_passthrough_two_guest(self, result: TestResult) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        client, client_nic_name = self._configure_passthrough_nic_for_node(client_node)
        server_node = cast(RemoteNode, environment.nodes[1])
        server, server_nic_name = self._configure_passthrough_nic_for_node(server_node)

        # Reboot the nodes. Libvirt sometime re-use the nodes.
        # Try to run the test on fresh state of the nodes
        client.reboot()
        server.reboot()

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
    def perf_udp_1k_ntttcp_passthrough_two_guest(self, result: TestResult) -> None:
        environment = result.environment
        assert environment, "fail to get environment from testresult"

        client_node = cast(RemoteNode, environment.nodes[0])
        client, client_nic_name = self._configure_passthrough_nic_for_node(client_node)
        server_node = cast(RemoteNode, environment.nodes[1])
        server, server_nic_name = self._configure_passthrough_nic_for_node(server_node)

        # Reboot the nodes. Libvirt sometime re-use the nodes.
        # Try to run the test on fresh state of the nodes
        client.reboot()
        server.reboot()

        perf_ntttcp(
            test_result=result,
            client=client,
            server=server,
            server_nic_name=server_nic_name,
            client_nic_name=client_nic_name,
            udp_mode=True,
        )

    def _configure_passthrough_nic_for_node(
        self,
        node: Node,
    ) -> Tuple[RemoteNode, str]:
        from lisa.sut_orchestrator.libvirt.context import get_node_context

        ctx = get_node_context(node)
        if not ctx.passthrough_devices:
            raise SkippedException("No passthrough devices found for node")

        lspci = node.tools[Lspci]
        pci_devices = lspci.get_devices_by_type(
            constants.DEVICE_TYPE_SRIOV, force_run=True
        )
        device_addr = None

        # Get the first non-virtio device
        for device in pci_devices:
            kernel_driver = lspci.get_used_module(device.slot)
            if kernel_driver != "virtio-pci":
                device_addr = device.slot
                break

        if device_addr is None:
            raise LisaException(
                f"No non-virtio passthrough device found. "
                f"Available devices: {[d.slot for d in pci_devices]}"
            )

        # Get the interface name
        err_msg: str = f"Can't find interface from PCI address: {device_addr}"
        device_path = node.execute(
            cmd=(
                "find /sys/class/net/*/device/subsystem/devices"
                f" -name '*{device_addr}*'"
            ),
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=err_msg,
        ).stdout

        pattern = re.compile(r"/sys/class/net/(?P<INTERFACE_NAME>\w+)/device")
        interface_name_raw = find_group_in_lines(
            pattern=pattern,
            lines=device_path,
        )
        interface_name = interface_name_raw.get("INTERFACE_NAME", "")
        assert interface_name, "Can not find interface name"

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

        # Configure the nw interface on guest with dhclient for the specific interface
        node.tools[Dhclient].renew(interface_name)

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
