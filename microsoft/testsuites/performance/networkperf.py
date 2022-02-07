# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import inspect
from typing import Any, Dict, List, Optional, cast

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
from lisa.tools import Iperf3, Lagscope, Lscpu, Netperf, Ntttcp, Sar, Ssh, Sysctl
from lisa.tools.iperf3 import (
    IPERF_TCP_BUFFER_LENGTHS,
    IPERF_TCP_CONCURRENCY,
    IPERF_UDP_BUFFER_LENGTHS,
    IPERF_UDP_CONCURRENCY,
)
from lisa.tools.ntttcp import NTTTCP_TCP_CONCURRENCY, NTTTCP_UDP_CONCURRENCY
from lisa.util.process import ExecutableResult, Process
from microsoft.testsuites.network.common import stop_firewall
from microsoft.testsuites.performance.common import (
    cleanup_process,
    get_nic_datapath,
    restore_sysctl_setting,
    set_systemd_tasks_max,
)


@TestSuiteMetadata(
    area="network",
    category="performance",
    description="""
    This test suite is to validate linux network performance.
    """,
)
class NetworkPerformace(TestSuite):
    TIMEOUT = 12000

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
        self.perf_tcp_latency(environment)

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
        self.perf_tcp_latency(environment)

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
        self.perf_tcp_pps(environment, "singlepps")

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
        self.perf_tcp_pps(environment, "singlepps")

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
        self.perf_tcp_pps(environment, "maxpps")

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
        self.perf_tcp_pps(environment, "maxpps")

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test synthetic tcp network throughput for
         128 connections.
        """,
        priority=2,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_tcp_ntttcp_128_connections_synthetic(
        self, log: Logger, environment: Environment
    ) -> None:
        self.perf_ntttcp(log, environment, connections=[128])

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test synthetic tcp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_tcp_ntttcp_synthetic(self, log: Logger, environment: Environment) -> None:
        self.perf_ntttcp(log, environment)

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test sriov tcp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_tcp_ntttcp_sriov(self, log: Logger, environment: Environment) -> None:
        self.perf_ntttcp(log, environment)

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test synthetic udp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_udp_1k_ntttcp_synthetic(
        self, log: Logger, environment: Environment
    ) -> None:
        self.perf_ntttcp(log, environment, True)

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test sriov udp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_udp_1k_ntttcp_sriov(self, log: Logger, environment: Environment) -> None:
        self.perf_ntttcp(log, environment, True)

    @TestCaseMetadata(
        description="""
        This test case uses iperf3 to test synthetic tcp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_tcp_iperf_synthetic(self, environment: Environment) -> None:
        self.perf_iperf(
            environment,
            connections=IPERF_TCP_CONCURRENCY,
            buffer_length_list=IPERF_TCP_BUFFER_LENGTHS,
        )

    @TestCaseMetadata(
        description="""
        This test case uses iperf3 to test sriov tcp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_tcp_iperf_sriov(self, environment: Environment) -> None:
        self.perf_iperf(
            environment,
            connections=IPERF_TCP_CONCURRENCY,
            buffer_length_list=IPERF_TCP_BUFFER_LENGTHS,
        )

    @TestCaseMetadata(
        description="""
        This test case uses iperf to test synthetic udp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def perf_udp_iperf_synthetic(self, environment: Environment) -> None:
        self.perf_iperf(
            environment,
            connections=IPERF_UDP_CONCURRENCY,
            buffer_length_list=IPERF_UDP_BUFFER_LENGTHS,
            udp_mode=True,
        )

    @TestCaseMetadata(
        description="""
        This test case uses iperf to test sriov udp network throughput.
        """,
        priority=3,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            min_count=2,
            network_interface=Sriov(),
        ),
    )
    def perf_udp_iperf_sriov(self, environment: Environment) -> None:
        self.perf_iperf(
            environment,
            connections=IPERF_UDP_CONCURRENCY,
            buffer_length_list=IPERF_UDP_BUFFER_LENGTHS,
            udp_mode=True,
        )

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        for process in ["lagscope", "netperf", "netserver", "ntttcp", "iperf3"]:
            cleanup_process(environment, process)

    def perf_tcp_latency(self, environment: Environment) -> None:
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
                client_lagscope.run_as_client(server_ip=server.internal_address),
                environment,
                inspect.stack()[1][3],
            )
            for latency_perf_message in latency_perf_messages:
                notifier.notify(latency_perf_message)
        finally:
            restore_sysctl_setting([client, server], perf_tuning)

    def perf_tcp_pps(self, environment: Environment, test_type: str) -> None:
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
        pps_message = client_sar.create_pps_peformance_messages(
            result, inspect.stack()[1][3], environment, test_type
        )
        notifier.notify(pps_message)

    def perf_ntttcp(
        self,
        log: Logger,
        environment: Environment,
        udp_mode: bool = False,
        connections: Optional[List[int]] = None,
    ) -> None:
        client = cast(RemoteNode, environment.nodes[0])
        server = cast(RemoteNode, environment.nodes[1])
        test_case_name = inspect.stack()[1][3]
        perf_tuning: Dict[str, List[Dict[str, str]]] = {
            client.name: [],
            server.name: [],
        }
        sys_list = [
            {"kernel.pid_max": "122880"},
            {"vm.max_map_count": "655300"},
            {"net.ipv4.ip_local_port_range": "1024 65535"},
        ]
        if connections is None:
            connections = NTTTCP_TCP_CONCURRENCY
            if udp_mode:
                sys_list = [
                    {"net.core.rmem_max": "67108864"},
                    {"net.core.rmem_default": "67108864"},
                    {"net.core.wmem_default": "67108864"},
                    {"net.core.wmem_max": "67108864"},
                ]
                connections = NTTTCP_UDP_CONCURRENCY
        try:
            client_ntttcp = client.tools[Ntttcp]
            server_ntttcp = server.tools[Ntttcp]
            client_lagscope = client.tools[Lagscope]
            server_lagscope = server.tools[Lagscope]
            stop_firewall(environment)
            set_systemd_tasks_max([client, server], log)
            for node in [client, server]:
                sysctl = node.tools[Sysctl]
                for tcp_sys in sys_list:
                    for variable, value in tcp_sys.items():
                        perf_tuning[node.name].append({variable: sysctl.get(variable)})
                        sysctl.write(variable, value)
            data_path = get_nic_datapath(client)
            server_nic_name = server.nics.default_nic
            client_nic_name = client.nics.default_nic
            dev_differentiator = "Hypervisor callback interrupts"
            if NetworkDataPath.Sriov.value == data_path:
                server_nic_name = server.nics.get_lower_nics()[0]
                client_nic_name = client.nics.get_lower_nics()[0]
                dev_differentiator = "mlx"
            server_lagscope.run_as_server(ip=server.internal_address)
            max_server_threads = 64
            perf_ntttcp_message_list: List[Any] = []
            for test_thread in connections:
                if test_thread < max_server_threads:
                    num_threads_p = test_thread
                    num_threads_n = 1
                else:
                    num_threads_p = max_server_threads
                    num_threads_n = int(test_thread / num_threads_p)
                if 1 == num_threads_n and 1 == num_threads_p:
                    buffer_size = int(1048576 / 1024)
                else:
                    buffer_size = int(65536 / 1024)
                if udp_mode:
                    buffer_size = int(1024 / 1024)
                server_result = server_ntttcp.run_as_server_async(
                    server_nic_name,
                    ports_count=num_threads_p,
                    buffer_size=buffer_size,
                    dev_differentiator=dev_differentiator,
                    udp_mode=udp_mode,
                )
                client_lagscope_process = client_lagscope.run_as_client_async(
                    server_ip=server.internal_address,
                    ping_count=0,
                    run_time_seconds=10,
                    print_histogram=False,
                    print_percentile=False,
                    histogram_1st_interval_start_value=0,
                    length_of_histogram_intervals=0,
                    count_of_histogram_intervals=0,
                    dump_csv=False,
                )
                client_ntttcp_result = client_ntttcp.run_as_client(
                    client_nic_name,
                    server.internal_address,
                    buffer_size=buffer_size,
                    threads_count=num_threads_n,
                    ports_count=num_threads_p,
                    dev_differentiator=dev_differentiator,
                    udp_mode=udp_mode,
                )
                server_ntttcp_result = server_result.wait_result()
                server_result_temp = server_ntttcp.create_ntttcp_result(
                    server_ntttcp_result
                )
                client_result_temp = client_ntttcp.create_ntttcp_result(
                    client_ntttcp_result, role="client"
                )
                client_sar_result = client_lagscope_process.wait_result()
                client_average_latency = client_lagscope.get_average(client_sar_result)
                if udp_mode:
                    perf_ntttcp_message_list.append(
                        client_ntttcp.create_ntttcp_udp_performance_message(
                            server_result_temp,
                            client_result_temp,
                            str(test_thread),
                            buffer_size,
                            environment,
                            test_case_name,
                        )
                    )
                else:
                    perf_ntttcp_message_list.append(
                        client_ntttcp.create_ntttcp_tcp_performance_message(
                            server_result_temp,
                            client_result_temp,
                            client_average_latency,
                            str(test_thread),
                            buffer_size,
                            environment,
                            test_case_name,
                        )
                    )
            for ntttcp_message in perf_ntttcp_message_list:
                notifier.notify(ntttcp_message)
        finally:
            restore_sysctl_setting([client, server], perf_tuning)

    def perf_iperf(
        self,
        environment: Environment,
        connections: List[int],
        buffer_length_list: List[int],
        udp_mode: bool = False,
    ) -> None:
        client = cast(RemoteNode, environment.nodes[0])
        server = cast(RemoteNode, environment.nodes[1])
        client_iperf3 = client.tools[Iperf3]
        server_iperf3 = server.tools[Iperf3]
        test_case_name = inspect.stack()[1][3]
        iperf3_messages_list: List[Any] = []
        if udp_mode:
            for node in [client, server]:
                ssh = node.tools[Ssh]
                ssh.set_max_session()
                node.close()
        for buffer_length in buffer_length_list:
            for connection in connections:
                server_iperf3_process_list: List[Process] = []
                client_iperf3_process_list: List[Process] = []
                client_result_list: List[ExecutableResult] = []
                server_result_list: List[ExecutableResult] = []
                if connection < 64:
                    num_threads_p = connection
                    num_threads_n = 1
                else:
                    num_threads_p = 64
                    num_threads_n = int(connection / 64)
                server_start_port = 750
                current_server_port = server_start_port
                current_server_iperf_instances = 0
                while current_server_iperf_instances < num_threads_n:
                    current_server_iperf_instances += 1
                    server_iperf3_process_list.append(
                        server_iperf3.run_as_server_async(
                            current_server_port, "g", 10, True, True, False
                        )
                    )
                    current_server_port += 1
                client_start_port = 750
                current_client_port = client_start_port
                current_client_iperf_instances = 0
                while current_client_iperf_instances < num_threads_n:
                    current_client_iperf_instances += 1
                    client_iperf3_process_list.append(
                        client_iperf3.run_as_client_async(
                            server.internal_address,
                            output_json=True,
                            report_periodic=1,
                            report_unit="g",
                            port=current_client_port,
                            buffer_length=buffer_length,
                            run_time_seconds=10,
                            parallel_number=num_threads_p,
                            ip_version="4",
                            udp_mode=udp_mode,
                        )
                    )
                    current_client_port += 1
                for client_iperf3_process in client_iperf3_process_list:
                    client_result_list.append(client_iperf3_process.wait_result())
                for server_iperf3_process in server_iperf3_process_list:
                    server_result_list.append(server_iperf3_process.wait_result())
                if udp_mode:
                    iperf3_messages_list.append(
                        client_iperf3.create_iperf_udp_performance_message(
                            server_result_list,
                            client_result_list,
                            buffer_length,
                            connection,
                            environment,
                            test_case_name,
                        )
                    )
                else:
                    iperf3_messages_list.append(
                        client_iperf3.create_iperf_tcp_performance_message(
                            server_result_list[0].stdout,
                            client_result_list[0].stdout,
                            buffer_length,
                            environment,
                            test_case_name,
                        )
                    )
        for iperf3_message in iperf3_messages_list:
            notifier.notify(iperf3_message)
