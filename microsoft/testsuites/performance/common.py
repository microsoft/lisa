# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import inspect
import pathlib
from functools import partial
from typing import Any, Dict, List, Optional, Union, cast

from assertpy import assert_that
from retry import retry

from lisa import (
    Environment,
    Node,
    RemoteNode,
    SkippedException,
    notifier,
    run_in_parallel,
)
from lisa.messages import (
    DiskPerformanceMessage,
    DiskSetupType,
    DiskType,
    NetworkLatencyPerformanceMessage,
    NetworkTCPPerformanceMessage,
    NetworkUDPPerformanceMessage,
)
from lisa.operating_system import BSD, Ubuntu
from lisa.schema import NetworkDataPath
from lisa.testsuite import TestResult
from lisa.tools import (
    FIOMODES,
    Fdisk,
    Fio,
    FIOResult,
    Iperf3,
    Kill,
    Lagscope,
    Lscpu,
    Mdadm,
    Netperf,
    Ntttcp,
    Sar,
    Sockperf,
    Ssh,
    Sysctl,
)
from lisa.tools.fio import IoEngine
from lisa.tools.ntttcp import (
    NTTTCP_TCP_CONCURRENCY,
    NTTTCP_TCP_CONCURRENCY_BSD,
    NTTTCP_UDP_CONCURRENCY,
)
from lisa.util import LisaException
from lisa.util.process import ExecutableResult, Process


def perf_disk(
    node: Node,
    start_iodepth: int,
    max_iodepth: int,
    filename: str,
    core_count: int,
    disk_count: int,
    test_result: TestResult,
    disk_setup_type: DiskSetupType = DiskSetupType.unknown,
    disk_type: DiskType = DiskType.unknown,
    test_name: str = "",
    num_jobs: Optional[List[int]] = None,
    block_size: int = 4,
    time: int = 120,
    size_mb: int = 0,
    numjob: int = 0,
    overwrite: bool = False,
    ioengine: IoEngine = IoEngine.LIBAIO,
    cwd: Optional[pathlib.PurePath] = None,
) -> None:
    fio_result_list: List[FIOResult] = []
    fio = node.tools[Fio]
    numjobiterator = 0
    # In fio test with ioengine == 'libaio',
    # numjob*max_iodepth (aio-nr) should always be less than aio-max-nr.
    # The default value of aio-max-nr is 65536.
    # As max_iodepth is 256, numjob which is equal to 'nproc' should not exceed 256.
    # /proc/sys/fs/aio-nr is the number of events currently active.
    # /proc/sys/fs/aio-max-nr is the maximum number of events that can be queued.
    # If aio-nr reaches aio-max-nr the io performance will drop and io_setup will
    # fail with EAGAIN.
    # read: https://www.kernel.org/doc/Documentation/sysctl/fs.txt
    # So we set numjob to 256 if numjob is larger than 256.
    # This limitation is only needed for 'libaio' ioengine but not for 'io_uring'.
    if ioengine == IoEngine.LIBAIO:
        numjob = min(numjob, 256)
    for mode in FIOMODES:
        iodepth = start_iodepth
        numjobindex = 0
        while iodepth <= max_iodepth:
            if num_jobs:
                numjob = num_jobs[numjobindex]
            fio_result = fio.launch(
                name=f"iteration{numjobiterator}",
                filename=filename,
                mode=mode.name,
                time=time,
                size_gb=size_mb,
                block_size=f"{block_size}K",
                iodepth=iodepth,
                overwrite=overwrite,
                numjob=numjob,
                cwd=cwd,
                ioengine=ioengine,
            )
            fio_result_list.append(fio_result)
            iodepth = iodepth * 2
            numjobindex += 1
            numjobiterator += 1

    other_fields: Dict[str, Any] = {}
    other_fields["core_count"] = core_count
    other_fields["disk_count"] = disk_count
    other_fields["block_size"] = block_size
    other_fields["disk_setup_type"] = disk_setup_type
    other_fields["disk_type"] = disk_type
    if not test_name:
        test_name = inspect.stack()[1][3]
    fio_messages: List[DiskPerformanceMessage] = fio.create_performance_messages(
        fio_result_list,
        test_name=test_name,
        test_result=test_result,
        other_fields=other_fields,
    )
    for fio_message in fio_messages:
        notifier.notify(fio_message)


def get_nic_datapath(node: Node) -> str:
    data_path: str = ""
    assert (
        node.capability.network_interface
        and node.capability.network_interface.data_path
    ), "nic datapath not available"
    if isinstance(node.capability.network_interface.data_path, NetworkDataPath):
        data_path = node.capability.network_interface.data_path.value
    return data_path


def cleanup_process(environment: Environment, process_name: str) -> None:
    nodes = environment.nodes.list()

    # use cleanup function
    def do_cleanup(node: Node) -> None:
        node.tools[Kill].by_name(process_name)

    # to run parallel cleanup for processes
    run_in_parallel([partial(do_cleanup, node) for node in nodes])


def reset_partitions(
    node: Node,
    disk_names: List[str],
) -> List[str]:
    fdisk = node.tools[Fdisk]
    partition_disks: List[str] = []
    for data_disk in disk_names:
        fdisk.delete_partitions(data_disk)
        partition_disks.append(fdisk.make_partition(data_disk, format_=False))
    return partition_disks


def stop_raid(node: Node) -> None:
    mdadm = node.tools[Mdadm]
    mdadm.stop_raid()


def reset_raid(node: Node, disk_list: List[str]) -> None:
    stop_raid(node)
    mdadm = node.tools[Mdadm]
    mdadm.create_raid(disk_list)


def perf_tcp_latency(test_result: TestResult) -> List[NetworkLatencyPerformanceMessage]:
    environment = test_result.environment
    assert environment, "fail to get environment from testresult"

    client = cast(RemoteNode, environment.nodes[0])
    server = cast(RemoteNode, environment.nodes[1])
    client_lagscope = client.tools[Lagscope]
    server_lagscope = server.tools[Lagscope]
    try:
        for lagscope in [client_lagscope, server_lagscope]:
            lagscope.set_busy_poll()
        server_lagscope.run_as_server_async(ip=server.internal_address)
        latency_perf_messages = client_lagscope.create_latency_performance_messages(
            client_lagscope.run_as_client(server_ip=server.internal_address),
            inspect.stack()[1][3],
            test_result,
        )
    finally:
        for lagscope in [client_lagscope, server_lagscope]:
            lagscope.kill()
            lagscope.restore_busy_poll()

    return latency_perf_messages


def perf_tcp_pps(
    test_result: TestResult,
    test_type: str,
    server: Optional[RemoteNode] = None,
    client: Optional[RemoteNode] = None,
) -> None:
    # Either server and client are set explicitly or we use the first two nodes
    # from the environment. We never combine the two options. We need to specify
    # server and client explicitly for nested VM's which are not part of the
    # `environment` and are created during the test.
    if server is not None or client is not None:
        assert server is not None, "server need to be specified, if client is set"
        assert client is not None, "client need to be specified, if server is set"
    else:
        environment = test_result.environment
        assert environment, "fail to get environment from testresult"
        # set server and client from environment, if not set explicitly
        server = cast(RemoteNode, environment.nodes[1])
        client = cast(RemoteNode, environment.nodes[0])

    client_netperf, server_netperf = run_in_parallel(
        [lambda: client.tools[Netperf], lambda: server.tools[Netperf]]  # type: ignore
    )

    cpu = client.tools[Lscpu]
    core_count = cpu.get_core_count()
    if "maxpps" == test_type:
        ssh = client.tools[Ssh]
        ssh.set_max_session()
        ports = range(30000, 30032)
    else:
        ports = range(30000, 30001)
    for port in ports:
        server_netperf.run_as_server(port)
    for port in ports:
        client_netperf.run_as_client_async(server.internal_address, core_count, port)
    client_sar = client.tools[Sar]
    server_sar = server.tools[Sar]
    server_sar.get_statistics_async()
    result = client_sar.get_statistics()
    pps_message = client_sar.create_pps_performance_messages(
        result, inspect.stack()[1][3], test_type, test_result
    )
    notifier.notify(pps_message)


def perf_ntttcp(  # noqa: C901
    test_result: TestResult,
    server: Optional[RemoteNode] = None,
    client: Optional[RemoteNode] = None,
    udp_mode: bool = False,
    connections: Optional[List[int]] = None,
    test_case_name: str = "",
    lagscope_server_ip: Optional[str] = None,
    server_nic_name: Optional[str] = None,
    client_nic_name: Optional[str] = None,
) -> List[Union[NetworkTCPPerformanceMessage, NetworkUDPPerformanceMessage]]:
    # Either server and client are set explicitly or we use the first two nodes
    # from the environment. We never combine the two options. We need to specify
    # server and client explicitly for nested VM's which are not part of the
    # `environment` and are created during the test.
    if server is not None or client is not None:
        assert server is not None, "server need to be specified, if client is set"
        assert client is not None, "client need to be specified, if server is set"
    else:
        environment = test_result.environment
        assert environment, "fail to get environment from testresult"
        # set server and client from environment, if not set explicitly
        server = cast(RemoteNode, environment.nodes[1])
        client = cast(RemoteNode, environment.nodes[0])

    if not test_case_name:
        # if it's not filled, assume it's called by case directly.
        test_case_name = inspect.stack()[1][3]

    if connections is None:
        if udp_mode:
            connections = NTTTCP_UDP_CONCURRENCY
        else:
            if isinstance(server.os, BSD):
                connections = NTTTCP_TCP_CONCURRENCY_BSD
            else:
                connections = NTTTCP_TCP_CONCURRENCY

    client_ntttcp, server_ntttcp = run_in_parallel(
        [lambda: client.tools[Ntttcp], lambda: server.tools[Ntttcp]]  # type: ignore
    )
    try:
        client_lagscope, server_lagscope = run_in_parallel(
            [
                lambda: client.tools[Lagscope],  # type: ignore
                lambda: server.tools[Lagscope],  # type: ignore
            ]
        )
        # no need to set task max and reboot VM when connection less than 20480
        if max(connections) >= 20480 and not isinstance(server.os, BSD):
            set_task_max = True
        else:
            set_task_max = False
        # collect sriov nic counts before reboot
        if not udp_mode and set_task_max:
            need_reboot = True
        else:
            need_reboot = False
        if need_reboot:
            client_sriov_count = len(client.nics.get_lower_nics())
            server_sriov_count = len(server.nics.get_lower_nics())
        for ntttcp in [client_ntttcp, server_ntttcp]:
            ntttcp.setup_system(udp_mode, set_task_max)
        for lagscope in [client_lagscope, server_lagscope]:
            lagscope.set_busy_poll()
        data_path = get_nic_datapath(client)
        if NetworkDataPath.Sriov.value == data_path:
            if need_reboot:
                # check sriov count not change after reboot
                check_sriov_count(client, client_sriov_count)
                check_sriov_count(server, server_sriov_count)
            server_nic_name = (
                server_nic_name
                if server_nic_name
                else server.nics.get_primary_nic().pci_device_name
            )

            client_nic_name = (
                client_nic_name
                if client_nic_name
                else client.nics.get_primary_nic().pci_device_name
            )
            dev_differentiator = "mlx"
        else:
            server_nic_name = (
                server_nic_name if server_nic_name else server.nics.default_nic
            )
            client_nic_name = (
                client_nic_name if client_nic_name else client.nics.default_nic
            )
            dev_differentiator = "Hypervisor callback interrupts"
        server_lagscope.run_as_server_async(
            ip=lagscope_server_ip
            if lagscope_server_ip is not None
            else server.internal_address
        )
        max_server_threads = 64
        perf_ntttcp_message_list: List[
            Union[NetworkTCPPerformanceMessage, NetworkUDPPerformanceMessage]
        ] = []
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
                server_ip=server.internal_address if isinstance(server.os, BSD) else "",
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
            server.tools[Kill].by_name(server_ntttcp.command)
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
                ntttcp_message: Union[
                    NetworkTCPPerformanceMessage, NetworkUDPPerformanceMessage
                ] = client_ntttcp.create_ntttcp_udp_performance_message(
                    server_result_temp,
                    client_result_temp,
                    str(test_thread),
                    buffer_size,
                    test_case_name,
                    test_result,
                )
            else:
                ntttcp_message = client_ntttcp.create_ntttcp_tcp_performance_message(
                    server_result_temp,
                    client_result_temp,
                    client_average_latency,
                    str(test_thread),
                    buffer_size,
                    test_case_name,
                    test_result,
                )
            notifier.notify(ntttcp_message)
            perf_ntttcp_message_list.append(ntttcp_message)
    finally:
        error_msg = ""
        throw_error = False
        for node in [client, server]:
            if not node.is_connected:
                error_msg += f" VM {node.name} can't be connected, "
                throw_error = True
        if throw_error:
            error_msg += "probably due to VM stuck on reboot stage."
            raise LisaException(error_msg)
        for ntttcp in [client_ntttcp, server_ntttcp]:
            ntttcp.restore_system(udp_mode)
        for lagscope in [client_lagscope, server_lagscope]:
            lagscope.kill()
            lagscope.restore_busy_poll()
    return perf_ntttcp_message_list


def perf_iperf(
    test_result: TestResult,
    connections: List[int],
    buffer_length_list: List[int],
    udp_mode: bool = False,
) -> None:
    environment = test_result.environment
    assert environment, "fail to get environment from testresult"

    client = cast(RemoteNode, environment.nodes[0])
    server = cast(RemoteNode, environment.nodes[1])
    client_iperf3, server_iperf3 = run_in_parallel(
        [lambda: client.tools[Iperf3], lambda: server.tools[Iperf3]]
    )
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
                        test_case_name,
                        test_result,
                    )
                )
            else:
                iperf3_messages_list.append(
                    client_iperf3.create_iperf_tcp_performance_message(
                        server_result_list[0].stdout,
                        client_result_list[0].stdout,
                        buffer_length,
                        connection,
                        test_case_name,
                        test_result,
                    )
                )
    for iperf3_message in iperf3_messages_list:
        notifier.notify(iperf3_message)


def perf_sockperf(
    test_result: TestResult, mode: str, test_case_name: str, set_busy_poll: bool = False
) -> None:
    environment = test_result.environment
    assert environment, "fail to get environment from testresult"

    client = cast(RemoteNode, environment.nodes[0])
    server = cast(RemoteNode, environment.nodes[1])
    sysctls: List[Sysctl] = []
    if isinstance(client.os, Ubuntu) and (client.os.information.version < "18.4.0"):
        raise SkippedException(
            f"Sockperf tests don't support EOL Ubuntu {client.os.information.release}"
        )
    if set_busy_poll:
        sysctls = run_in_parallel(
            [lambda: client.tools[Sysctl], lambda: server.tools[Sysctl]]
        )
        for sysctl in sysctls:
            sysctl.enable_busy_polling("50")

    run_in_parallel([lambda: client.tools[Sockperf], lambda: server.tools[Sockperf]])

    server_proc = server.tools[Sockperf].start_server_async(mode)
    # wait for sockperf to start, fail if it doesn't.
    try:
        server_proc.wait_output(
            "sockperf: Warmup stage",
            timeout=30,
        )
        client_output = client.tools[Sockperf].run_client(
            mode, server.nics.get_primary_nic().ip_addr
        )
        client.tools[Sockperf].create_latency_performance_message(
            client_output, test_case_name, test_result
        )
    finally:
        if server_proc.is_running():
            server_proc.kill()

        for sysctl in sysctls:
            sysctl.reset()


def calculate_middle_average(values: List[Union[float, int]]) -> float:
    """
    This method is used to calculate an average indicator. It discard the max
    and min value, and then take the average.
    """
    total = sum(x for x in values) - min(values) - max(values)
    # calculate average
    return total / (len(values) - 2)


@retry(exceptions=AssertionError, tries=30, delay=2)
def check_sriov_count(node: RemoteNode, sriov_count: int) -> None:
    node_nic_info = node.nics
    node_nic_info.reload()

    assert_that(len(node_nic_info.get_lower_nics())).described_as(
        f"VF count inside VM is {len(node_nic_info.get_lower_nics())},"
        f"actual sriov nic count is {sriov_count}"
    ).is_equal_to(sriov_count)
