# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
#from time import sleep
import time ,inspect
from pathlib import PurePath, PurePosixPath
from typing_extensions import runtime
from typing import Dict, Any, cast
from unittest import result
from assertpy import assert_that
from lisa.messages import SubTestMessage, TestStatus, create_test_result_message

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    notifier,
    TestSuiteMetadata,
    simple_requirement,
    Environment
)
from lisa.features import acc, Synthetic
from lisa.messages import DiskSetupType, DiskType
from lisa.operating_system import Debian
from lisa.testsuite import TestResult
from lisa.tools import Echo, Lscpu, StressNg
from lisa.util.perf_timer import create_timer
from microsoft.testsuites.performance.common import (
    perf_disk,
    perf_ntttcp,
    reset_partitions,
    reset_raid,
    stop_raid,
)
from functools import partial
from lisa.util.parallel import T_RESULT, TaskManager, run_in_parallel_async

@TestSuiteMetadata(
    area="ACC_longhaul",
    category="performance",
    description="""
    This test suite is to validate ACC longhaul disk performance of Linux VM using fio tool.
    """,
)
class ACCPerformance(TestSuite):
    TIME_OUT = 150000
    MEASUREMENT_COUNT = 30#00
    MEASUREMENT_INTERVAL = 10
    IOSTAT_OUTPUT_PATH = "/home/lisatest/log_disk.txt"
    MEMSTAT_OUTPUT_PATH = "/home/lisatest/log_mem.txt"
    NETSTAT_OUTPUT_PATH = "/home/lisatest/log_netwk.txt"
    CPUSTAT_OUTPUT_PATH = "/home/lisatest/log_cpu.txt"


    def parallel_callback(result: T_RESULT, int: result) -> None:
        print("")

    def monitor_disk_throughput(self, node: Node, environment: Environment) -> None:
        # wait for 10 minutes
        timeout = self.MEASUREMENT_COUNT * self.MEASUREMENT_INTERVAL
        try:
            result = node.execute("apt-get install -y sysstat", sudo=True, shell=True)
        except:
            print("Unable to install sysstat")
        iostat_command = f"iostat -p sda1 -dx {self.MEASUREMENT_INTERVAL} {self.MEASUREMENT_COUNT} > {self.IOSTAT_OUTPUT_PATH}" 
        try:
            result = node.execute(iostat_command, sudo=True, shell=True,timeout=1000)
        except:
            print("`n`n!!! Unable to store iostat logs !!")

        timer = create_timer()
        while timeout > timer.elapsed(False):
            result = node.execute(f"iostat -p sda1 -dx {self.MEASUREMENT_INTERVAL} {self.MEASUREMENT_COUNT}")
            subtest_message = create_test_result_message(
                message_type=SubTestMessage,
                id=1,
                test_case_name="ACC_Longhaul_Disk",
                test_message=result.stdout,
                environment=environment
            )
            notifier.notify(subtest_message)
            if result.exit_code == 1:
                break
            time.sleep(5)
        if timeout < timer.elapsed():
            print(f"timeout {timeout} greater than elapsed {timer.elapsed()}")

    def monitor_memory_throughput(self, node: Node, environment: Environment) -> None:
        timeout = self.MEASUREMENT_COUNT * self.MEASUREMENT_INTERVAL
        try:
            result = node.execute("apt-get install -y sysstat", sudo=True, shell=True)
        except:
            print("Unable to install sysstat")
        memstat_command = f"sar -r {self.MEASUREMENT_INTERVAL} {self.MEASUREMENT_COUNT} > {self.MEMSTAT_OUTPUT_PATH}" 
        try:
            result = node.execute(memstat_command, sudo=True, shell=True,timeout=1000)
        except:
            print("`n`n!!! Unable to store iostat logs !!")

        timer = create_timer()
        while timeout > timer.elapsed(False):
            result = node.execute(f"sar -r {self.MEASUREMENT_INTERVAL} {self.MEASUREMENT_COUNT}")
            subtest_message = create_test_result_message(
                message_type=SubTestMessage,
                id=1,
                test_case_name="ACC_Longhaul_Memory",
                test_message=result.stdout,
                environment=environment
            )
            notifier.notify(subtest_message)
            if result.exit_code == 1:
                break
            time.sleep(5)
        if timeout < timer.elapsed():
            print(f"timeout {timeout} greater than elapsed {timer.elapsed()}")

    def monitor_network_throughput(self, node: Node, environment: Environment) -> None:

        timeout = self.MEASUREMENT_COUNT * self.MEASUREMENT_INTERVAL
        try:
            result = node.execute("apt-get install -y sysstat", sudo=True, shell=True)
        except:
            print("Unable to install sysstat")
        netstat_command = f"sar -n DEV {self.MEASUREMENT_INTERVAL} {self.MEASUREMENT_COUNT} > {self.NETSTAT_OUTPUT_PATH}" 
        try:
            result = node.execute(netstat_command, sudo=True, shell=True,timeout=1000)
        except:
            print("`n`n!!! Unable to store iostat logs !!")

        timer = create_timer()
        while timeout > timer.elapsed(False):
            result = node.execute(f"sar -n DEV {self.MEASUREMENT_INTERVAL} {self.MEASUREMENT_COUNT}")
            subtest_message = create_test_result_message(
                message_type=SubTestMessage,
                id=1,
                test_case_name="ACC_Longhaul_Network",
                test_message=result.stdout,
                environment=environment
            )
            notifier.notify(subtest_message)
            if result.exit_code == 1:
                break
            time.sleep(5)
        if timeout < timer.elapsed():
            print(f"timeout {timeout} greater than elapsed {timer.elapsed()}")

    def monitor_cpu_utilization(self, node: Node, environment: Environment) -> None:
        timeout = self.MEASUREMENT_COUNT * self.MEASUREMENT_INTERVAL
        try:
            result = node.execute("apt-get install -y sysstat", sudo=True, shell=True)
        except:
            print("Unable to install sysstat")
        cpustat_command = f" sar -u " #{self.MEASUREMENT_INTERVAL} {self.MEASUREMENT_COUNT} > {self.CPUSTAT_OUTPUT_PATH}
        try:
            process = self.node.execute(cpustat_command, shell=True, sudo=True)
            result = node.execute(cpustat_command, sudo=True, shell=True,timeout=15000)
        except:
            print("`n`n!!! Unable to store cpustat logs !!")

        timer = create_timer()
        while timeout > timer.elapsed(False):
            result = node.execute(f"sar -u 1 10",timeout=timeout) #{self.MEASUREMENT_INTERVAL} {self.MEASUREMENT_COUNT}
            subtest_message = create_test_result_message(
                message_type=SubTestMessage,
                id=1,
                test_case_name="ACC_Longhaul_CPU",
                test_message=result.stdout,
                environment=environment
            )
            notifier.notify(subtest_message)
            if result.exit_code == 1:
                break
            time.sleep(5)
        if timeout < timer.elapsed():
            print(f"timeout {timeout} greater than elapsed {timer.elapsed()}")

    @TestCaseMetadata(
        description="""
        This test case uses fio to test ACC longhaul disk performance.
        """,
        priority=3,
        timeout=TIME_OUT,
        requirement=simple_requirement(
            supported_features=[acc.ACC],
        ),
    )
    def longhaul_diskperf(
        self,
        node: Node,
        log:Logger,
        log_path: str,
        result: TestResult,
        environment: Environment,
        variables:Dict[str, Any]

    ) -> None:
        
        block_size = 4 
        cpu = node.tools[Lscpu]
        core_count = cpu.get_core_count()
        start_iodepth = 1
        max_iodepth=2
        timeout = self.MEASUREMENT_INTERVAL * self.MEASUREMENT_COUNT
        perf_disk_partial = partial(
            perf_disk,
            node=node,
            start_iodepth=start_iodepth,
            max_iodepth=max_iodepth,
            filename="/dev/sda1",
            core_count=core_count,
            disk_count=1,
            disk_setup_type=DiskSetupType.raid0,
            disk_type=DiskType.premiumssd,
            numjob=core_count,
            block_size=block_size,
            size_mb=8192,
            overwrite=True,
            test_result=result,
            time=timeout,
        )

        monitor_disk_partial = partial(self.monitor_disk_throughput, node, environment )
        task_manager = run_in_parallel_async([perf_disk_partial ,monitor_disk_partial], self.parallel_callback, log)

        task_manager.wait_worker()
        node.shell.copy_back(
            PurePosixPath(self.IOSTAT_OUTPUT_PATH), PurePath(log_path) / "iostat-output.txt"
        )

    @TestCaseMetadata(
        description="""
        This test case uses stress-ng to test ACC longhaul memory performance.
        """,
        priority=3,
        timeout=TIME_OUT,
        requirement=simple_requirement(
            supported_features=[acc.ACC],
        ),
    )
    def longhaul_memperf(
        self,
        node: Node,
        log:Logger,
        log_path: str,
        result: TestResult,
        environment: Environment,
        variables:Dict[str, Any]

    ) -> None:
        
        #node = cast(RemoteNode, environment.nodes[0])
        #is_distro_supported(node)
        stress_ng_tool = node.tools[StressNg]
        timeout = self.MEASUREMENT_INTERVAL * self.MEASUREMENT_COUNT
        perf_mem_partial = partial(
            stress_ng_tool.launch,
            #node,
            num_workers=16,
            vm_bytes="100%",
            timeout_in_seconds=timeout,
        )

        monitor_mem_partial = partial(self.monitor_memory_throughput, node, environment )
        task_manager = run_in_parallel_async([perf_mem_partial ,monitor_mem_partial], self.parallel_callback, log)

        task_manager.wait_worker()
        node.shell.copy_back(
            PurePosixPath(self.MEMSTAT_OUTPUT_PATH), PurePath(log_path) / "memstat-output.txt"
        )

    @TestCaseMetadata(
        description="""
        This test case uses ntttcp to test ACC longhaul network performance.
        """,
        priority=3,
        timeout=TIME_OUT,
        requirement=simple_requirement(
            supported_features=[acc.ACC],
            min_count=2,
            network_interface=Synthetic(),
        ),
    )
    def longhaul_netperf(
        self,
        node: Node,
        log:Logger,
        log_path: str,
        result: TestResult,
        environment: Environment,
        variables:Dict[str, Any]

    ) -> None:
        
        #node = cast(RemoteNode, environment.nodes[0])
        #is_distro_supported(node)
        timeout = self.MEASUREMENT_COUNT * self.MEASUREMENT_INTERVAL
        perf_ntttcp_partial = partial(
            perf_ntttcp,
            #node,
            test_result=result,
            udp_mode=False,
            connections=[1],
            runtime_in_seconds=timeout,
            test_case_name=inspect.stack()[2].function,
        )

        monitor_netwk_partial = partial(self.monitor_network_throughput, node, environment )
        task_manager = run_in_parallel_async([perf_ntttcp_partial ,monitor_netwk_partial], self.parallel_callback, log)

        task_manager.wait_worker()
        node[0].shell.copy_back(
            PurePosixPath(self.NETSTAT_OUTPUT_PATH), PurePath(log_path) / "netstat-output.txt"
        )

    @TestCaseMetadata(
        description="""
        This test case uses stress-ng to test ACC longhaul CPU performance.
        """,
        priority=3,
        timeout=TIME_OUT,
        requirement=simple_requirement(
            supported_features=[acc.ACC],
        ),
    )
    def longhaul_cpuperf(
        self,
        node: Node,
        log:Logger,
        log_path: str,
        result: TestResult,
        environment: Environment,
        variables:Dict[str, Any]

    ) -> None:
        
        stress_ng_tool = node.tools[StressNg]
        timeout = self.MEASUREMENT_INTERVAL * self.MEASUREMENT_COUNT
        print("!!!!! timeout:")
        print(timeout)
        lscpu = node.tools[Lscpu]
        perf_cpu_partial = partial(
            stress_ng_tool.launch_cpu,
            num_cores=lscpu.get_core_count(),
            timeout_in_seconds=timeout,
        )

        monitor_cpu_partial = partial(self.monitor_cpu_utilization, node, environment )
        task_manager = run_in_parallel_async([perf_cpu_partial ,monitor_cpu_partial], self.parallel_callback, log)

        task_manager.wait_worker()
        try:
            node.shell.copy_back(
                PurePosixPath(self.CPUSTAT_OUTPUT_PATH), PurePath(log_path) / "cpustat-output.txt"
            )
        except:
            print("!!!!FAiled to copy")
