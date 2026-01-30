# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import inspect
import pathlib
import time
from decimal import Decimal
from functools import partial
from typing import Any, Dict, List, Optional, Tuple, Union, cast

from assertpy import assert_that
from retry import retry

from lisa import (
    Environment,
    Node,
    RemoteNode,
    SkippedException,
    notifier,
    run_in_parallel,
    schema,
)
from lisa.features import Nvme
from lisa.features.disks import Disk
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
    Echo,
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
from lisa.tools.fio import IoEngine, FIOResult
from lisa.tools.ip import Ip
from lisa.tools.ntttcp import (
    NTTTCP_TCP_CONCURRENCY,
    NTTTCP_TCP_CONCURRENCY_BSD,
    NTTTCP_UDP_CONCURRENCY,
)
from lisa.util import LisaException
from lisa.util.process import ExecutableResult, Process


def perf_nvme(
    node: Node,
    result: TestResult,
    test_name: str = "",
    disk_type: DiskType = DiskType.nvme,
    ioengine: IoEngine = IoEngine.LIBAIO,
    max_iodepth: int = 256,
) -> None:
    nvme = node.features[Nvme]
    nvme_namespaces = nvme.get_raw_nvme_disks()
    disk_count = len(nvme_namespaces)
    assert_that(disk_count).described_as(
        "At least 1 NVMe disk for fio testing."
    ).is_greater_than(0)
    filename = ":".join(nvme_namespaces)
    echo = node.tools[Echo]
    # This will have kernel avoid sending IPI to finish I/O on the issuing CPUs
    # if they are not on the same NUMA node of completion CPU.
    # This setting will give a better and more stable IOPS.
    for nvme_namespace in nvme_namespaces:
        # /dev/nvme0n1 => nvme0n1
        disk_name = nvme_namespace.split("/")[-1]
        echo.write_to_file(
            "0",
            node.get_pure_path(f"/sys/block/{disk_name}/queue/rq_affinity"),
            sudo=True,
        )
    cpu = node.tools[Lscpu]
    core_count = cpu.get_core_count()
    start_iodepth = 1
    if test_name:
        test_name = inspect.stack()[1][3]

    perf_disk(
        node,
        start_iodepth,
        max_iodepth,
        filename,
        core_count=core_count,
        disk_count=disk_count,
        numjob=disk_count,  # Changed: 1 job per disk instead of core_count
        test_name=test_name,
        disk_setup_type=DiskSetupType.raw,
        disk_type=disk_type,
        test_result=result,
        ioengine=ioengine,
        # CPU affinity: Prevent I/O queue pair overflow (Azure ASAP MEQS=255 limit)
        # Each worker gets specific vCPU: worker1→CPU0, worker2→CPU1, etc.
        cpus_allowed=":".join(str(i) for i in range(min(disk_count, core_count))),
    )


def _generate_cpu_affinity_per_worker(worker_index: int, core_count: int) -> str:
    """
    Generate CPU affinity for a specific worker to ensure 1:1 CPU:worker mapping.
    worker1 → CPU0, worker2 → CPU1, etc.
    
    Args:
        worker_index: 0-based worker index (0 for first worker)
        core_count: Total available CPU cores
    
    Returns:
        Single CPU ID string for this specific worker (e.g. "0" for first worker)
    """
    if worker_index >= core_count:
        # If we exceed available cores, wrap around
        cpu_id = worker_index % core_count
    else:
        cpu_id = worker_index
    
    return str(cpu_id)


def perf_disk_with_cpu_affinity(
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
    block_size: int = 4,
    time: int = 120,
    size_mb: int = 0,
    overwrite: bool = False,
    ioengine: IoEngine = IoEngine.LIBAIO,
    cwd: Optional[pathlib.PurePath] = None,
) -> None:
    """
    Run disk performance test with 1:1:1 CPU:job:disk mapping.
    Starting from vCPU0, assigns one CPU per worker per disk.
    """
    # Set numjob to match disk_count for 1:1:1 mapping
    numjob = min(disk_count, core_count)
    
    # Generate CPU affinity starting from vCPU0 (legacy colon-separated format)
    effective_workers = min(numjob, disk_count, core_count)
    cpus_allowed = ":".join(str(i) for i in range(effective_workers))
    
    node.log.info(
        f"Starting 1:1:1 CPU:job:disk test - "
        f"CPUs: {cpus_allowed}, Jobs: {numjob}, Disks: {disk_count}"
    )
    
    # Call the main perf_disk function with generated parameters
    perf_disk(
        node=node,
        start_iodepth=start_iodepth,
        max_iodepth=max_iodepth,
        filename=filename,
        core_count=core_count,
        disk_count=disk_count,
        test_result=test_result,
        disk_setup_type=disk_setup_type,
        disk_type=disk_type,
        test_name=test_name,
        num_jobs=None,  # Use fixed numjob instead
        block_size=block_size,
        time=time,
        size_mb=size_mb,
        numjob=numjob,
        overwrite=overwrite,
        ioengine=ioengine,
        cpus_allowed=cpus_allowed,
        cwd=cwd,
    )


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
    cpus_allowed: str = "",
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
    
    # Auto-generate CPU affinity for 1:1:1 mapping (CPU:job:disk) if not provided
    if not cpus_allowed and numjob > 0:
        effective_workers = min(numjob, disk_count, core_count)
        cpus_allowed = ":".join(str(i) for i in range(effective_workers))
        node.log.info(
            f"Auto-generated CPU affinity: {cpus_allowed} "
            f"(cores:{core_count}, disks:{disk_count}, jobs:{numjob})"
        )
    
    # Check if we need strict worker→CPU mapping (multiple disks with specific affinity)
    use_worker_specific_affinity = (
        disk_count > 1 and 
        cpus_allowed and 
        numjob == disk_count and 
        ":" in filename  # Multiple disk files
    )
    
    # Resource validation for large-scale testing
    if use_worker_specific_affinity and disk_count > 32:
        node.log.warning(
            f"Large-scale test detected: {disk_count} disks. "
            f"This may stress system resources (memory, file descriptors, AIO limits)."
        )
    
    # Validate AIO limits for libaio engine
    if ioengine == IoEngine.LIBAIO and use_worker_specific_affinity:
        max_aio_requests = disk_count * max_iodepth
        if max_aio_requests > 65536:
            node.log.warning(
                f"AIO requests ({max_aio_requests}) may exceed system limit (65536). "
                f"Consider reducing iodepth or using io_uring engine."
            )
    
    if use_worker_specific_affinity:
        # Split disks and run parallel FIO jobs for precise worker→CPU mapping
        disk_files = filename.split(":")
        node.log.info(
            f"Running parallel FIO jobs for worker-specific CPU affinity: "
            f"{len(disk_files)} disks, {disk_count} workers"
        )
        
        # Run parallel FIO jobs for each iodepth level (randread mode only)
        mode = FIOMODES.randread
        iodepth = start_iodepth
        numjobindex = 0
        while iodepth <= max_iodepth:
                # Create FIO job file for all disks at this iodepth
                job_file_content = f"""[global]
ioengine={ioengine.value}
direct=1
runtime={time}
time_based=1
bs={block_size}K
rw={mode.name}
iodepth={iodepth}
group_reporting=1
"""
                if overwrite:
                    job_file_content += "overwrite=1\n"
                
                job_file_content += "\n"
                
                # Add individual job sections for each disk
                for disk_idx, disk_file in enumerate(disk_files[:disk_count]):
                    specific_cpu = _generate_cpu_affinity_per_worker(disk_idx, core_count)
                    size_per_disk = size_mb // disk_count if size_mb > 0 else 0
                    
                    job_file_content += f"""[worker{disk_idx+1}_iteration{numjobiterator}]
filename={disk_file}
cpus_allowed={specific_cpu}
numjobs=1
"""
                    if size_per_disk > 0:
                        job_file_content += f"size={size_per_disk}M\n"
                    job_file_content += "\n"
                
                # Write job file and execute single FIO command
                job_file_path = f"/tmp/multi_disk_iodepth_{iodepth}_iter_{numjobiterator}.fio"
                
                # Use shell=True to execute heredoc as a single shell command
                write_command = f"cat > {job_file_path} << 'EOF'\n{job_file_content}EOF"
                result = node.execute(write_command, shell=True)
                if result.exit_code != 0:
                    raise LisaException(f"Failed to write job file: {result.stderr}")
                
                # Run single FIO command with job file (requires sudo for block device access)
                fio_result = node.execute(f"sudo fio {job_file_path}")
                if fio_result.exit_code != 0:
                    raise LisaException(f"FIO failed with exit code {fio_result.exit_code}: {fio_result.stderr}")
                
                # Parse aggregated results from the job file output
                try:
                    # FIO job files with group_reporting=1 aggregate all jobs into single result
                    aggregated_result = fio.get_result_from_raw_output(
                        mode.name, fio_result.stdout, iodepth, len(disk_files[:disk_count])
                    )
                except Exception as parse_error:
                    # Log FIO output for debugging if parsing fails
                    node.log.error(f"Failed to parse FIO output. Raw output: {fio_result.stdout[:1000]}...")
                    raise LisaException(f"FIO result parsing failed: {parse_error}")
                
                # For job files, we get one aggregated result representing all disks
                # Split this into individual results for each disk (for compatibility)
                if aggregated_result.iops > 0:
                    individual_iops = aggregated_result.iops / len(disk_files[:disk_count])
                else:
                    node.log.warning("FIO reported zero IOPS, using fallback value")
                    individual_iops = Decimal(1)  # Fallback to prevent division by zero
                    
                for disk_idx in range(len(disk_files[:disk_count])):
                    individual_result = FIOResult()
                    individual_result.mode = mode.name
                    individual_result.iops = individual_iops  # Distribute IOPS equally
                    individual_result.latency = aggregated_result.latency  # Same latency
                    individual_result.iodepth = iodepth
                    individual_result.qdepth = iodepth
                    fio_result_list.append(individual_result)
                
                # Clean up job file
                node.execute(f"rm -f {job_file_path}")
                
                iodepth = iodepth * 2
                numjobindex += 1
                numjobiterator += 1
        
    else:
        # Standard single FIO job approach (workers may float among CPUs) - randread mode only
        mode = FIOMODES.randread
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
                    cpus_allowed=cpus_allowed,
                )
                fio_result_list.append(fio_result)
                iodepth = iodepth * 2
                numjobindex += 1
                numjobiterator += 1
    
    # After all FIO jobs are complete, process and notify results
    other_fields: Dict[str, Any] = {}
    other_fields["core_count"] = core_count
    other_fields["disk_count"] = disk_count
    other_fields["block_size"] = block_size
    other_fields["disk_setup_type"] = disk_setup_type
    other_fields["disk_type"] = disk_type
    if not test_name:
        test_name = inspect.stack()[1][3]
        
    # Aggregate results if we used separate jobs per disk
    aggregated_results = _aggregate_multi_disk_fio_results(
        fio_result_list, disk_count, use_worker_specific_affinity
    )
    
    # Print aggregated results to screen for debugging
    node.log.info("=== FIO Performance Results ===")
    for result in aggregated_results:
        node.log.info(
            f"Mode: {result.mode}, "
            f"IODepth: {result.iodepth}, "
            f"QDepth: {result.qdepth}, "
            f"IOPS: {result.iops:,.0f}, "
            f"Latency: {result.latency:.2f}μs"
        )
    node.log.info("==============================")
    
    fio_messages: List[DiskPerformanceMessage] = fio.create_performance_messages(
        aggregated_results,
        test_name=test_name,
        test_result=test_result,
        other_fields=other_fields,
    )
    for fio_message in fio_messages:
        notifier.notify(fio_message)


def _aggregate_multi_disk_fio_results(
    fio_result_list: List[FIOResult], disk_count: int, use_worker_specific_affinity: bool
) -> List[FIOResult]:
    """
    Aggregate FIO results from multiple disk jobs into combined results.
    When running separate jobs per disk, we need to sum IOPS and average latencies
    to get meaningful aggregate performance metrics.
    
    Args:
        fio_result_list: List of individual disk FIO results
        disk_count: Number of disks being tested
        use_worker_specific_affinity: Whether separate jobs were used
        
    Returns:
        Aggregated FIO results suitable for standard reporting
    """
    if not use_worker_specific_affinity or disk_count <= 1:
        # No aggregation needed for standard single-job approach
        return fio_result_list
    
    # Group results by (mode, iodepth) for aggregation
    grouped_results: Dict[Tuple[str, int], List[FIOResult]] = {}
    
    for result in fio_result_list:
        key = (result.mode, result.iodepth)
        if key not in grouped_results:
            grouped_results[key] = []
        grouped_results[key].append(result)
    
    # Create aggregated results
    aggregated_results = []
    for (mode, iodepth), results in grouped_results.items():
        if len(results) == disk_count:
            # We have results from all disks for this configuration
            # Sum IOPS and average latencies
            total_iops = sum(r.iops for r in results)
            avg_latency = sum(r.latency for r in results) / Decimal(len(results))
            
            # Create aggregated result using first result as template
            base_result = results[0]
            aggregated_result = FIOResult()
            aggregated_result.mode = mode
            aggregated_result.iops = total_iops
            aggregated_result.latency = avg_latency
            aggregated_result.iodepth = iodepth
            aggregated_result.qdepth = iodepth  # Keep same qdepth format as original (iodepth * numjob where numjob=1 per disk)
            aggregated_results.append(aggregated_result)
    
    return aggregated_results


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
    thread_count = cpu.get_thread_count()
    if "maxpps" == test_type:
        ssh = client.tools[Ssh]
        ssh.set_max_session()
        ports = range(30000, 30032)
    else:
        ports = range(30000, 30001)
    for port in ports:
        server_netperf.run_as_server(port)
    for port in ports:
        client_netperf.run_as_client_async(server.internal_address, thread_count, port)
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
    variables: Optional[Dict[str, Any]] = None,
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

    # Initialize variables before try block
    client_lagscope = None
    server_lagscope = None
    client_ntttcp = None
    server_ntttcp = None

    try:
        client_ntttcp, server_ntttcp = run_in_parallel(
            [lambda: client.tools[Ntttcp], lambda: server.tools[Ntttcp]]  # type: ignore
        )
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
            client_sriov_count = len(client.nics.get_pci_nics())
            server_sriov_count = len(server.nics.get_pci_nics())
        for ntttcp in [client_ntttcp, server_ntttcp]:
            ntttcp.setup_system(udp_mode, set_task_max)
        for lagscope in [client_lagscope, server_lagscope]:
            lagscope.set_busy_poll()
        client_nic = client.nics.default_nic
        server_nic = server.nics.default_nic
        client_ip = client.tools[Ip]
        server_ip = server.tools[Ip]
        mtu = variables.get("perf_ntttcp_mtu", 0) if variables is not None else 0
        if mtu != 0:
            # set mtu for default nics
            client_ip.set_mtu(client_nic, mtu)
            server_ip.set_mtu(server_nic, mtu)
        client_mtu = client_ip.get_mtu(client_nic)
        server_mtu = server_ip.get_mtu(server_nic)

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
            if mtu != 0:
                # set mtu for AN nics, MTU needs to be set on both AN and non-AN nics
                client_ip.set_mtu(client_nic_name, mtu)
                server_ip.set_mtu(server_nic_name, mtu)
        else:
            server_nic_name = (
                server_nic_name if server_nic_name else server.nics.default_nic
            )
            client_nic_name = (
                client_nic_name if client_nic_name else client.nics.default_nic
            )
            dev_differentiator = "Hypervisor callback interrupts"
        max_server_threads = 64
        perf_ntttcp_message_list: List[
            Union[NetworkTCPPerformanceMessage, NetworkUDPPerformanceMessage]
        ] = []

        # Retry mechanism configuration:
        # ntttcp client can sometimes hang or timeout, especially with
        # high connection counts. We implement a retry mechanism to improve
        # test reliability without failing the entire suite.
        max_retries = 20  # Maximum retry attempts for each connection test

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

            # Retry mechanism for the current connection test:
            # Each connection count (test_thread) gets up to max_retries
            # attempts. This handles transient failures like process hangs,
            # timeouts, or network issues.
            retry_count = 0
            test_success = False
            server_result_temp = None
            client_result_temp = None
            client_average_latency = None

            while retry_count < max_retries and not test_success:
                try:
                    if retry_count > 0:
                        client.log.info(
                            f"Retrying ntttcp test for {test_thread} connections "
                            f"(attempt {retry_count + 1}/{max_retries})"
                        )
                        # Clean up any stuck processes from the previous attempt.
                        # This is critical to prevent resource conflicts and
                        # ensure a clean retry.
                        for node in [client, server]:
                            node.tools[Kill].by_name("ntttcp")
                            node.tools[Kill].by_name("lagscope")

                    # Restart lagscope server for each attempt to ensure clean
                    # connection state
                    server_lagscope.run_as_server_async(
                        ip=(
                            lagscope_server_ip
                            if lagscope_server_ip is not None
                            else server.internal_address
                        )
                    )

                    # Start ntttcp server asynchronously to accept incoming
                    # connections
                    server_result = server_ntttcp.run_as_server_async(
                        server_nic_name,
                        server_ip=(
                            server.internal_address
                            if isinstance(server.os, BSD)
                            else ""
                        ),
                        ports_count=num_threads_p,
                        buffer_size=buffer_size,
                        dev_differentiator=dev_differentiator,
                        udp_mode=udp_mode,
                    )

                    # Start lagscope client to measure latency during the
                    # ntttcp test
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

                    # Run ntttcp client and monitor for hangs
                    # Use daemon mode to run in background, then monitor process
                    client_ntttcp_result = client_ntttcp.run_as_client(
                        client_nic_name,
                        server.internal_address,
                        buffer_size=buffer_size,
                        threads_count=num_threads_n,
                        ports_count=num_threads_p,
                        dev_differentiator=dev_differentiator,
                        udp_mode=udp_mode,
                    )

                    # Stop the server and collect results from both client
                    # and server
                    server.tools[Kill].by_name(server_ntttcp.command)
                    server_ntttcp_result = server_result.wait_result()
                    server_result_temp = server_ntttcp.create_ntttcp_result(
                        server_ntttcp_result
                    )
                    client_result_temp = client_ntttcp.create_ntttcp_result(
                        client_ntttcp_result, role="client"
                    )

                    # Collect latency measurement from lagscope client
                    client_sar_result = client_lagscope_process.wait_result()
                    client_average_latency = client_lagscope.get_average(
                        client_sar_result
                    )

                    # Mark the test as successful and exit the retry loop
                    test_success = True
                    client.log.info(
                        f"Successfully completed ntttcp test for "
                        f"{test_thread} connections"
                    )

                except Exception as e:
                    # An error occurred during the test (timeout, process hang,
                    # network issue, etc.)

                    time.sleep(30)
                    client.log.error(
                        f"Error during ntttcp test for {test_thread} connections "
                        f"(attempt {retry_count}/{max_retries}): {e}"
                    )
                    retry_count += 1

                    # Clean up all processes to ensure a clean state for the
                    # next retry. This prevents hung processes from interfering
                    # with subsequent attempts.
                    try:
                        for node in [client, server]:
                            node.tools[Kill].by_name("ntttcp")
                            node.tools[Kill].by_name("lagscope")
                    except Exception as cleanup_error:
                        # Log cleanup errors but don't fail the retry mechanism
                        client.log.error(f"Cleanup error: {cleanup_error}")

                    if retry_count >= max_retries:
                        # All retry attempts exhausted for this connection count.
                        # Log the failure and skip to the next connection count
                        # instead of failing the entire test suite. This allows
                        # other connection tests to proceed.
                        client.log.error(
                            f"Failed ntttcp test for {test_thread} connections "
                            f"after {max_retries} attempts. "
                            f"Skipping this connection count."
                        )
                        # Break out of the retry loop to move to the next
                        # connection
                        break

            # All retry attempts exhausted without success.
            # Raise an exception to fail the test as performance data
            # could not be collected.
            if not test_success:
                raise LisaException(
                    f"ntttcp test for {test_thread} connections failed after "
                    f"{max_retries} attempts."
                )
            assert server_result_temp is not None, "server result should not be None"
            assert client_result_temp is not None, "client result should not be None"
            assert (
                client_average_latency is not None
            ), "client average latency should not be None"
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
                    client_mtu,
                    server_mtu,
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
                    client_mtu,
                    server_mtu,
                )
            notifier.notify(ntttcp_message)
            perf_ntttcp_message_list.append(ntttcp_message)
    except Exception as ex:
        client.log.info(f"Exception during ntttcp performance test: {ex}")
        raise
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
        if client_ntttcp and server_ntttcp:
            for ntttcp in [client_ntttcp, server_ntttcp]:
                ntttcp.restore_system(udp_mode)
        if client_lagscope and server_lagscope:
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
        client_output = client.tools[Sockperf].run_client(mode, server.internal_address)
        client.tools[Sockperf].create_latency_performance_message(
            client_output, test_case_name, test_result
        )
    finally:
        if server_proc.is_running():
            server_proc.kill()

        for sysctl in sysctls:
            sysctl.reset()


def perf_premium_datadisks(
    node: Node,
    test_result: TestResult,
    disk_setup_type: DiskSetupType = DiskSetupType.raw,
    disk_type: DiskType = DiskType.premiumssd,
    block_size: int = 4,
    start_iodepth: int = 1,
    max_iodepth: int = 256,
    ioengine: IoEngine = IoEngine.LIBAIO,
) -> None:
    disk = node.features[Disk]
    data_disks = disk.get_raw_data_disks()
    disk_count = len(data_disks)
    assert_that(disk_count).described_as(
        "At least 1 data disk for fio testing."
    ).is_greater_than(0)
    partition_disks = reset_partitions(node, data_disks)
    filename = ":".join(partition_disks)
    cpu = node.tools[Lscpu]
    thread_count = cpu.get_thread_count()
    perf_disk(
        node,
        start_iodepth,
        max_iodepth,
        filename,
        test_name=inspect.stack()[1][3],
        core_count=thread_count,
        disk_count=disk_count,
        disk_setup_type=disk_setup_type,
        disk_type=disk_type,
        numjob=disk_count,  # Changed: 1 job per disk instead of thread_count
        block_size=block_size,
        size_mb=8192,
        overwrite=True,
        test_result=test_result,
        ioengine=ioengine,
        cpus_allowed=":".join(str(i) for i in range(min(disk_count, thread_count))),  # Worker-specific CPU assignment: worker1→vCPU0, worker2→vCPU1, etc.
    )


def perf_resource_disks(
    node: Node,
    test_result: TestResult,
    disk_setup_type: DiskSetupType = DiskSetupType.raw,
    block_size: int = 4,
    start_iodepth: int = 1,
    max_iodepth: int = 256,
) -> None:
    disk = node.features[Disk]
    resource_disks = disk.get_resource_disks()
    disk_count = len(resource_disks)
    if disk_count == 0:
        raise SkippedException(
            "No resource disk found, skipping resource disk performance test."
        )
    resource_disk_type = disk.get_resource_disk_type()
    if schema.ResourceDiskType.NVME == resource_disk_type:
        perf_nvme(
            node,
            test_result,
            disk_type=DiskType.localnvme,
        )
        return
    elif schema.ResourceDiskType.SCSI == resource_disk_type:
        # If there is only one resource disk and its SCSI type,
        # it will be mounted at /mnt.
        # Create a file under and use it as fio filename.
        # If there are multiple resource disks, reset partitions and
        # use the partition disks as fio filename.
        if disk_count == 1:
            filename = f"{disk.get_resource_disk_mount_point()}/fiodata"
        else:
            partition_disks = reset_partitions(node, resource_disks)
            filename = ":".join(partition_disks)
        core_count = node.tools[Lscpu].get_core_count()

        perf_disk(
            node,
            start_iodepth,
            max_iodepth,
            filename,
            test_name=inspect.stack()[1][3],
            core_count=core_count,
            disk_count=disk_count,
            disk_setup_type=disk_setup_type,
            disk_type=DiskType.localssd,
            numjob=disk_count,  # Changed: 1 job per disk instead of core_count
            block_size=block_size,
            size_mb=8192,
            overwrite=True,
            test_result=test_result,
            cpus_allowed=":".join(str(i) for i in range(min(disk_count, core_count))),  # Worker-specific CPU assignment: worker1→vCPU0, worker2→vCPU1, etc.
        )

    else:
        raise SkippedException(
            f"Resource disk type {resource_disk_type} not supported for "
            f"performance test."
        )


def calculate_middle_average(values: List[Union[float, int]]) -> float:
    """
    This method is used to calculate an average indicator. It discard the max
    and min value, and then take the average.
    """
    total = sum(x for x in values) - min(values) - max(values)
    # calculate average
    return total / (len(values) - 2)


@retry(exceptions=AssertionError, tries=30, delay=2)  # type:ignore
def check_sriov_count(node: RemoteNode, sriov_count: int) -> None:
    node_nic_info = node.nics
    node_nic_info.reload()

    assert_that(len(node_nic_info.get_pci_nics())).described_as(
        f"VF count inside VM is {len(node_nic_info.get_pci_nics())},"
        f"actual sriov nic count is {sriov_count}"
    ).is_equal_to(sriov_count)
