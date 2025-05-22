# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from functools import partial
from typing import Any, Dict, Tuple, cast

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
from lisa.sut_orchestrator.libvirt.context import get_node_context
from lisa.testsuite import TestResult
from lisa.tools import Dhclient, Lspci, Sysctl
from lisa.tools.iperf3 import (
    IPERF_TCP_BUFFER_LENGTHS,
    IPERF_TCP_CONCURRENCY,
    IPERF_UDP_BUFFER_LENGTHS,
    IPERF_UDP_CONCURRENCY,
)
from lisa.util import (
    SkippedException,
    constants,
    find_group_in_lines,
    find_groups_in_lines,
)
from lisa.util.logger import get_logger
from lisa.util.parallel import run_in_parallel
from microsoft.testsuites.performance.common import (
    cleanup_process,
    perf_iperf,
    perf_ntttcp,
    perf_tcp_pps,
)


@TestSuiteMetadata(
    area="network passthrough",
    category="performance",
    description="""
    This test suite is to validate linux network performance
    for various NIC passthrough scenarios.
    """,
)
class NetworkPerformace(TestSuite):
    TIMEOUT = 12000
    PPS_TIMEOUT = 3000

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
            )
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
        This test case uses ntttcp to test sriov tcp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=1,
                memory_mb=search_space.IntRange(min=8192),
            )
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
        This test case uses ntttcp to test sriov tcp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=2,
                memory_mb=search_space.IntRange(min=8192),
            )
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
        This test case uses ntttcp to test sriov tcp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=2,
                memory_mb=search_space.IntRange(min=8192),
            )
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
        ctx = get_node_context(node)
        if not ctx.passthrough_devices:
            raise SkippedException("No passthrough devices found for node")

        # Configure the nw interface on guest
        node.tools[Dhclient].run(
            force_run=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="dhclient run failed",
        )

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

        # Get the interface name
        err_msg: str = "Can't find interface from PCI address"
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
        assert passthrough_nic_ip, "Can not find interface IP"

        test_node = cast(RemoteNode, node)
        test_node.internal_address = passthrough_nic_ip

        return test_node, interface_name

    def _get_host_as_server(self, variables: Dict[str, Any]) -> RemoteNode:
        ip = variables.get("baremetal_host_ip", "")
        username = variables.get("baremetal_host_username", "")
        passwd = variables.get("baremetal_host_password", "")

        if not (ip and username and passwd):
            raise SkippedException("Server-Node details are not provided")

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
        )
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

        # use these cleanup functions
        def do_process_cleanup(process: str) -> None:
            cleanup_process(environment, process)

        def do_sysctl_cleanup(node: Node) -> None:
            node.tools[Sysctl].reset()

        # to run parallel cleanup of processes and sysctl settings
        run_in_parallel(
            [
                partial(do_process_cleanup, x)
                for x in [
                    "lagscope",
                    "netperf",
                    "netserver",
                    "ntttcp",
                    "iperf3",
                ]
            ]
        )
        run_in_parallel(
            [partial(do_sysctl_cleanup, x) for x in environment.nodes.list()]
        )
