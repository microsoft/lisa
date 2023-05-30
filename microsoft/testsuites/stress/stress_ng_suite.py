# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import Path, PurePath
from typing import Any, Dict, List, cast

from lisa import (
    Environment,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    notifier,
)
from lisa.features import SerialConsole
from lisa.messages import SubTestMessage, TestStatus, create_test_result_message
from lisa.testsuite import TestResult
from lisa.tools import StressNg
from lisa.util import SkippedException
from lisa.util.process import Process


@TestSuiteMetadata(
    area="stress-ng",
    category="stress",
    description="""
    A suite for running the various classes of stressors provided
    by stress-ng.
    """,
)
class StressNgTestSuite(TestSuite):
    TIME_OUT = 3600
    CONFIG_VARIABLE = "stress_ng_jobs"

    @TestCaseMetadata(
        description="""
        Runs a stress-ng jobfile. The path to the jobfile must be specified using a
        runbook variable named "stress_ng_jobs". For more info about jobfiles refer:
        https://manpages.ubuntu.com/manpages/jammy/man1/stress-ng.1.html
        """,
        priority=4,
    )
    def stress_ng_jobfile(
        self,
        variables: Dict[str, Any],
        environment: Environment,
        result: TestResult,
    ) -> None:
        if self.CONFIG_VARIABLE in variables:
            jobs = variables[self.CONFIG_VARIABLE]
            for job_file in jobs:
                self._run_stress_ng_job(job_file, environment, result)
        else:
            raise SkippedException("No jobfile provided for stress-ng")

    @TestCaseMetadata(
        description="Runs stress-ng's 'cpu' class stressors for 60s each.",
        priority=4,
    )
    def stress_ng_cpu_stressors(
        self,
        environment: Environment,
    ) -> None:
        self._run_stressor_class(environment, "cpu")

    @TestCaseMetadata(
        description="Runs stress-ng's 'memory' class stressors for 60s each.",
        priority=4,
    )
    def stress_ng_memory_stressors(
        self,
        environment: Environment,
    ) -> None:
        self._run_stressor_class(environment, "memory")

    @TestCaseMetadata(
        description="Runs stress-ng's 'vm' class stressors for 60s each.",
        priority=4,
    )
    def stress_ng_vm_stressors(
        self,
        environment: Environment,
    ) -> None:
        self._run_stressor_class(environment, "vm")

    @TestCaseMetadata(
        description="Runs stress-ng's 'io' class stressors for 60s each.",
        priority=4,
    )
    def stress_ng_io_stressors(
        self,
        environment: Environment,
    ) -> None:
        self._run_stressor_class(environment, "io")

    @TestCaseMetadata(
        description="Runs stress-ng's 'network' class stressors for 60s each.",
        priority=4,
    )
    def stress_ng_network_stressors(
        self,
        environment: Environment,
    ) -> None:
        self._run_stressor_class(environment, "network")

    def _run_stressor_class(self, environment: Environment, class_name: str) -> None:
        nodes = [cast(RemoteNode, node) for node in environment.nodes.list()]
        procs: List[Process] = []
        try:
            for node in nodes:
                procs.append(node.tools[StressNg].launch_class_async(class_name))
            for proc in procs:
                proc.wait_result(timeout=self.TIME_OUT, expected_exit_code=0)
        except Exception as e:
            self._check_panic(nodes)
            raise e

    def _run_stress_ng_job(
        self,
        job_file: str,
        environment: Environment,
        test_result: TestResult,
    ) -> None:
        nodes = [cast(RemoteNode, node) for node in environment.nodes.list()]
        procs: List[Process] = []
        job_file_name = Path(job_file).name
        test_status = TestStatus.QUEUED
        test_msg = ""
        try:
            for node in nodes:
                remote_working_dir = node.working_path / "stress_ng_jobs"
                node.shell.mkdir(remote_working_dir, exist_ok=True)
                job_file_dest = remote_working_dir / job_file_name
                node.shell.copy(PurePath(job_file), job_file_dest)
                procs.append(node.tools[StressNg].launch_job_async(str(job_file_dest)))
            for proc in procs:
                proc.wait_result(expected_exit_code=0)
            test_status = TestStatus.PASSED
        except Exception as e:
            test_status = TestStatus.FAILED
            test_msg = repr(e)
        finally:
            self._send_subtest_msg(
                test_result,
                environment,
                job_file_name,
                test_status,
                test_msg,
            )
            self._check_panic(nodes)

    def _check_panic(self, nodes: List[RemoteNode]) -> None:
        for node in nodes:
            node.features[SerialConsole].check_panic(saved_path=None, force_run=True)

    def _send_subtest_msg(
        self,
        test_result: TestResult,
        environment: Environment,
        test_name: str,
        test_status: TestStatus,
        test_msg: str = "",
    ) -> None:
        subtest_msg = create_test_result_message(
            SubTestMessage,
            test_result,
            environment,
            test_name,
            test_status,
        )

        notifier.notify(subtest_msg)
