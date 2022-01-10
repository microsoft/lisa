# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Any, Dict, List, cast

from lisa import (
    Logger,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    notifier,
    simple_requirement,
)
from lisa.environment import Environment
from lisa.features import Sriov, Synthetic
from lisa.schema import NetworkDataPath
from lisa.tools import Lagscope, Lscpu, Netperf, Sar, Ssh, Sysctl
from lisa.util import dict_to_fields
from microsoft.testsuites.network.common import stop_firewall
from microsoft.testsuites.performance.common import cleanup_process


@TestSuiteMetadata(
    area="network",
    category="performance",
    description="""
    This test suite is to validate linux network performance.
    """,
)
class NetworkPerformace(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case uses lagscope to test synthetic network latency.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_tcp_latency_synthetic(self, environment: Environment) -> None:
        self.perf_tcp_latency(environment, "perf_tcp_latency_synthetic")

    @TestCaseMetadata(
        description="""
        This test case uses lagscope to test sriov network latency.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_tcp_latency_sriov(self, environment: Environment) -> None:
        self.perf_tcp_latency(environment, "perf_tcp_latency_sriov")

    @TestCaseMetadata(
        description="""
        This test case uses sar to test synthetic network PPS (Packets Per Second)
         when running netperf with single port.
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_tcp_single_pps_synthetic(self, environment: Environment) -> None:
        self.perf_tcp_pps(environment, "perf_tcp_single_pps_synthetic", "singlepps")

    @TestCaseMetadata(
        description="""
        This test case uses sar to test sriov network PPS (Packets Per Second)
         when running netperf with single port.
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_tcp_single_pps_sriov(self, environment: Environment) -> None:
        self.perf_tcp_pps(environment, "perf_tcp_single_pps_sriov", "singlepps")

    @TestCaseMetadata(
        description="""
        This test case uses sar to test synthetic network PPS (Packets Per Second)
         when running netperf with multiple ports.
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_tcp_max_pps_synthetic(self, environment: Environment) -> None:
        self.perf_tcp_pps(environment, "perf_tcp_max_pps_synthetic", "maxpps")

    @TestCaseMetadata(
        description="""
        This test case uses sar to test sriov network PPS (Packets Per Second)
         when running netperf with multiple ports.
        """,
        priority=3,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_tcp_max_pps_sriov(self, environment: Environment) -> None:
        self.perf_tcp_pps(environment, "perf_tcp_max_pps_sriov", "maxpps")

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        for process in ["lagscope", "netperf", "netserver"]:
            cleanup_process(environment, process)

    def perf_tcp_latency(self, environment: Environment, test_case_name: str) -> None:
        client = cast(RemoteNode, environment.nodes[0])
        server = cast(RemoteNode, environment.nodes[1])
        perf_tuning: Dict[str, List[Dict[str, str]]] = {
            client.name: [],
            server.name: [],
        }
        # Busy polling helps reduce latency in the network receive path by allowing
        #  socket layer code to poll the receive queue of a network device, and
        #  disabling network interrupts. This removes delays caused by the interrupt
        #  and the resultant context switch.
        #  However, it also increases CPU utilization.
        #  Busy polling also prevents the CPU from sleeping, which can incur
        #  additional power consumption.
        sys_list = ["net.core.busy_poll", "net.core.busy_read"]
        try:
            client_lagscope = client.tools[Lagscope]
            server_lagscope = server.tools[Lagscope]
            for node in [client, server]:
                sysctl = node.tools[Sysctl]
                # store the original value before updating
                for variable in sys_list:
                    perf_tuning[node.name].append({variable: sysctl.get(variable)})
                    sysctl.write(variable, "50")
            stop_firewall(environment)
            server_lagscope.run_as_server(ip=server.internal_address)
            latency_perf_messages = client_lagscope.create_latency_peformance_messages(
                client_lagscope.run_as_client(server_ip=server.internal_address)
            )
            data_path: str = ""
            assert (
                client.capability.network_interface
                and client.capability.network_interface.data_path
            )
            if isinstance(
                client.capability.network_interface.data_path, NetworkDataPath
            ):
                data_path = client.capability.network_interface.data_path.value
            information: Dict[str, str] = environment.get_information()
            for latency_perf_message in latency_perf_messages:
                latency_perf_message = dict_to_fields(information, latency_perf_message)
                latency_perf_message.test_case_name = test_case_name
                latency_perf_message.data_path = data_path
                notifier.notify(latency_perf_message)
        finally:
            for node in [client, server]:
                sysctl = node.tools[Sysctl]
                for variable_list in perf_tuning[node.name]:
                    # restore back to the original value after testing
                    for variable, value in variable_list.items():
                        sysctl.write(variable, value)

    def perf_tcp_pps(
        self, environment: Environment, test_case_name: str, test_type: str
    ) -> None:
        client = cast(RemoteNode, environment.nodes[0])
        server = cast(RemoteNode, environment.nodes[1])
        client_netperf = client.tools[Netperf]
        server_netperf = server.tools[Netperf]
        stop_firewall(environment)
        cpu = client.tools[Lscpu]
        core_count = cpu.get_core_count()
        if "maxpps" == test_type:
            ssh = client.tools[Ssh]
            ssh.set_max_session()
            client.close()
            ports = range(30000, 30032)
        else:
            ports = range(30000, 30001)
        for port in ports:
            server_netperf.run_as_server(port)
        for port in ports:
            client_netperf.run_as_client_async(
                server.internal_address, core_count, port
            )
        client_sar = client.tools[Sar]
        server_sar = server.tools[Sar]
        server_sar.get_statistics_async()
        result = client_sar.get_statistics()
        pps_message = client_sar.create_pps_peformance_messages(result)
        pps_message.test_type = test_type
        data_path: str = ""
        assert (
            client.capability.network_interface
            and client.capability.network_interface.data_path
        )
        if isinstance(client.capability.network_interface.data_path, NetworkDataPath):
            data_path = client.capability.network_interface.data_path.value
        information: Dict[str, str] = environment.get_information()
        pps_message = dict_to_fields(information, pps_message)
        pps_message.test_execution_tag = test_case_name
        pps_message.data_path = data_path
        notifier.notify(pps_message)
