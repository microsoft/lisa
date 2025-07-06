# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import Path, PurePath
from typing import Any, Dict, List, cast

from lisa import Environment, RemoteNode, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.features import SerialConsole
from lisa.messages import TestStatus, send_sub_test_result_message
from lisa.testsuite import TestResult
from lisa.tools import StressNg
from lisa.util import SkippedException
from lisa.util.logger import Logger  # Add this import
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
        log: Logger,  # Add this parameter
        variables: Dict[str, Any],
        environment: Environment,
        result: TestResult,
    ) -> None:
        log.info("Starting stress_ng_jobfile test case")
        log.debug(f"Looking for variable: '{self.CONFIG_VARIABLE}'")
        log.debug(f"Available variables: {list(variables.keys())}")
        
        if self.CONFIG_VARIABLE in variables:
            jobs = variables[self.CONFIG_VARIABLE]
            log.info(f"Found {self.CONFIG_VARIABLE}: '{jobs}' (type: {type(jobs)})")
            
            # Convert single string to list for uniform processing
            if isinstance(jobs, str):
                log.debug(f"Converting string to list: '{jobs}' -> ['{jobs}']")
                jobs = [jobs]
            elif isinstance(jobs, list):
                log.debug(f"Jobs is already a list with {len(jobs)} items: {jobs}")
            else:
                log.warning(f"Unexpected type for jobs: {type(jobs)}, value: {jobs}")
                jobs = [str(jobs)]  # Convert to string and then to list
            
            log.info(f"Final jobs list: {jobs} (length: {len(jobs)})")
            
            for i, job_file in enumerate(jobs):
                log.info(f"Processing job file {i+1}/{len(jobs)}: '{job_file}'")
                try:
                    self._run_stress_ng_job(job_file, environment, result, log)
                    log.info(f"Successfully completed job file: '{job_file}'")
                except Exception as e:
                    log.error(f"Failed to run job file '{job_file}': {e}")
                    raise
        else:
            log.error(f"Variable '{self.CONFIG_VARIABLE}' not found in variables")
            log.error(f"Available variables: {variables}")
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
        log: Logger,  # Add this parameter
    ) -> None:
        log.info(f"Starting _run_stress_ng_job with job_file: '{job_file}'")
        
        nodes = [cast(RemoteNode, node) for node in environment.nodes.list()]
        log.debug(f"Found {len(nodes)} nodes: {[node.name for node in nodes]}")
        
        procs: List[Process] = []
        job_file_name = Path(job_file).name
        log.debug(f"Job file name: '{job_file_name}'")
        
        test_status = TestStatus.QUEUED
        test_msg = ""
        
        try:
            for i, node in enumerate(nodes):
                log.debug(f"Processing node {i+1}/{len(nodes)}: {node.name}")
                
                remote_working_dir = node.working_path / "stress_ng_jobs"
                log.debug(f"Remote working directory: {remote_working_dir}")
                
                node.shell.mkdir(remote_working_dir, exist_ok=True)
                log.debug(f"Created directory: {remote_working_dir}")
                
                job_file_dest = remote_working_dir / job_file_name
                log.debug(f"Destination path: {job_file_dest}")
                
                log.info(f"Copying '{job_file}' -> '{job_file_dest}'")
                node.shell.copy(PurePath(job_file), job_file_dest)
                log.info(f"Copy completed successfully")
                
                log.info(f"Launching stress-ng job: {job_file_dest}")
                proc = node.tools[StressNg].launch_job_async(str(job_file_dest))
                procs.append(proc)
                log.debug(f"Process launched, PID: {proc.id if hasattr(proc, 'id') else 'unknown'}")
            
            log.info(f"Waiting for {len(procs)} processes to complete")
            for i, proc in enumerate(procs):
                log.debug(f"Waiting for process {i+1}/{len(procs)}")
                result = proc.wait_result(expected_exit_code=0)
                log.debug(f"Process {i+1} completed with exit code: {result.exit_code}")
                if result.stdout:
                    log.debug(f"Process {i+1} stdout: {result.stdout[:500]}...")  # First 500 chars
                if result.stderr:
                    log.debug(f"Process {i+1} stderr: {result.stderr[:500]}...")  # First 500 chars
            
            test_status = TestStatus.PASSED
            log.info(f"All stress-ng processes completed successfully")
            
        except Exception as e:
            test_status = TestStatus.FAILED
            test_msg = repr(e)
            log.error(f"Error during stress-ng job execution: {e}")
            log.exception("Full exception details:")
            
        finally:
            log.info(f"Sending test result: status={test_status}, message='{test_msg}'")
            send_sub_test_result_message(
                test_result=test_result,
                test_case_name=job_file_name,
                test_status=test_status,
                test_message=test_msg,
            )
            log.debug("Checking for kernel panics")
            self._check_panic(nodes)
            log.info(f"Completed _run_stress_ng_job for '{job_file}'")

    def _check_panic(self, nodes: List[RemoteNode]) -> None:
        for node in nodes:
            node.features[SerialConsole].check_panic(saved_path=None, force_run=True)
