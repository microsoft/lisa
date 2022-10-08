# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from time import sleep
import time
from pathlib import PurePath, PurePosixPath
from typing_extensions import runtime
from typing import Dict, Any
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
from lisa.features import acc
from lisa.messages import DiskSetupType, DiskType
from lisa.operating_system import Debian
from lisa.testsuite import TestResult
from lisa.tools import Echo, Lscpu
from lisa.util.perf_timer import create_timer
from microsoft.testsuites.performance.common import (
    perf_disk,
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
    TIME_OUT = 15000
    IOSTAT_OUTPUT_PATH = "/home/lisatest/log.txt"


    def parallel_callback(result: T_RESULT, int: result) -> None:
        print("")

    def monitor_disk_throughput(self, node: Node, environment: Environment) -> None:
        # wait for 10 minutes
        timeout = 60
        try:
            result = node.execute("apt-get install -y sysstat", sudo=True, shell=True)
        except:
            print("Unable to install sysstat")
        iostat_command = f"iostat -p sda1 -dx 5 2 > {self.IOSTAT_OUTPUT_PATH}" 
        try:
            result = node.execute(iostat_command, sudo=True, shell=True,timeout=1000)
        except:
            print("`n`n!!! Unable to store iostat logs !!")

        timer = create_timer()
        while timeout > timer.elapsed(False):
            result = node.execute(f"iostat -p sda1 -dx")
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
            time=100000,
        )

        monitor_disk_partial = partial(self.monitor_disk_throughput, node, environment )
        task_manager = run_in_parallel_async([perf_disk_partial ,monitor_disk_partial], self.parallel_callback, log)

        task_manager.wait_worker()
        node.shell.copy_back(
            PurePosixPath(self.IOSTAT_OUTPUT_PATH), PurePath(log_path) / "iostat-output.txt"
        )
