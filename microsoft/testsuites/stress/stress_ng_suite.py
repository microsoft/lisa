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
        log: Logger,  # Added logger parameter
    ) -> None:
        """
        Execute a stress-ng job file on all nodes in the environment.
        
        Args:
            job_file: Path to the stress-ng job file
            environment: Test environment containing target nodes
            test_result: Test result object for reporting
            log: Logger instance for detailed logging
        """
        log.info(f"Starting _run_stress_ng_job with job_file: '{job_file}'")
        
        nodes = [cast(RemoteNode, node) for node in environment.nodes.list()]
        log.debug(f"Found {len(nodes)} nodes: {[node.name for node in nodes]}")
        
        stress_processes: List[Process] = []
        job_file_name = Path(job_file).name
        log.debug(f"Job file name: '{job_file_name}'")
        
        execution_status = TestStatus.QUEUED
        execution_summary = ""
        node_outputs: List[str] = []
        
        try:
            # Phase 1: Deploy job files and launch stress tests
            log.info("Phase 1: Deploying job files and launching stress tests")
            self._deploy_and_launch_stress_jobs(
                nodes, job_file, job_file_name, stress_processes, log
            )
            
            # Phase 2: Monitor execution and collect results
            log.info("Phase 2: Monitoring execution and collecting results")
            node_outputs = self._monitor_stress_execution(stress_processes, nodes, log)
            
            execution_status = TestStatus.PASSED
            execution_summary = self._format_success_summary(node_outputs, job_file_name)
            log.info(f"All stress-ng processes completed successfully for '{job_file_name}'")
            
        except Exception as execution_error:
            execution_status = TestStatus.FAILED
            execution_summary = self._format_failure_summary(
                execution_error, node_outputs, job_file_name
            )
            log.error(f"Error during stress-ng job execution: {execution_error}")
            log.exception("Full exception details:")
            
        finally:
            log.info("Phase 3: Reporting results and verifying system stability")
            self._report_test_results(
                test_result, job_file_name, execution_status, execution_summary
            )
            self._verify_system_stability(nodes, log)
            log.info(f"Completed _run_stress_ng_job for '{job_file}'")

    def _deploy_and_launch_stress_jobs(
        self,
        nodes: List[RemoteNode],
        job_file: str,
        job_file_name: str,
        stress_processes: List[Process],
        log: Logger,  # Added logger parameter
    ) -> None:
        """
        Deploy job files to nodes and launch stress-ng processes.
        
        Args:
            nodes: List of target nodes
            job_file: Local path to job file
            job_file_name: Name of the job file
            stress_processes: List to store launched processes
            log: Logger instance for detailed logging
        """
        for node_index, node in enumerate(nodes):
            try:
                log.debug(f"Processing node {node_index+1}/{len(nodes)}: {node.name}")
                
                # Create dedicated workspace for stress-ng jobs
                remote_workspace = node.working_path / "stress_ng_jobs"
                log.debug(f"Remote working directory: {remote_workspace}")
                
                node.shell.mkdir(remote_workspace, exist_ok=True)
                log.debug(f"Created directory: {remote_workspace}")
                
                # Deploy job file to remote node
                remote_job_file = remote_workspace / job_file_name
                log.debug(f"Destination path: {remote_job_file}")
                
                log.info(f"Copying '{job_file}' -> '{remote_job_file}'")
                node.shell.copy(PurePath(job_file), remote_job_file)
                log.info(f"Copy completed successfully")
                
                # Launch stress-ng with the job file
                log.info(f"Launching stress-ng job: {remote_job_file}")
                stress_process = node.tools[StressNg].launch_job_async(str(remote_job_file))
                stress_processes.append(stress_process)
                
                log.debug(f"Process launched, PID: {stress_process.id if hasattr(stress_process, 'id') else 'unknown'}")
                node.log.info(
                    f"Stress job '{job_file_name}' launched on node {node_index + 1}"
                )
                
            except Exception as deployment_error:
                log.error(
                    f"Failed to deploy stress job on node {node_index + 1}: "
                    f"{deployment_error}"
                )
                node.log.error(
                    f"Failed to deploy stress job on node {node_index + 1}: "
                    f"{deployment_error}"
                )
                raise

    def _monitor_stress_execution(
        self, 
        stress_processes: List[Process], 
        nodes: List[RemoteNode],
        log: Logger,  # Added logger parameter
    ) -> List[str]:
        """
        Monitor stress-ng process execution and collect output.
        
        Args:
            stress_processes: List of stress-ng processes to monitor
            nodes: List of nodes for logging context
            log: Logger instance for detailed logging
            
        Returns:
            List of formatted output strings from each node
        """
        node_outputs = []
        
        log.info(f"Waiting for {len(stress_processes)} processes to complete")
        
        for process_index, stress_process in enumerate(stress_processes):
            try:
                log.debug(f"Waiting for process {process_index+1}/{len(stress_processes)}")
                execution_result = stress_process.wait_result(
                    timeout=self.TIME_OUT, 
                    expected_exit_code=0
                )
                
                log.debug(f"Process {process_index+1} completed with exit code: {execution_result.exit_code}")
                if execution_result.stdout:
                    log.debug(f"Process {process_index+1} stdout: {execution_result.stdout[:500]}...")
                if execution_result.stderr:
                    log.debug(f"Process {process_index+1} stderr: {execution_result.stderr[:500]}...")
                
                # Capture and format process output
                formatted_output = self._format_node_output(
                    process_index + 1, execution_result
                )
                node_outputs.append(formatted_output)
                
                nodes[process_index].log.info(
                    f"Stress execution completed successfully on node {process_index + 1}"
                )
                
            except Exception as execution_error:
                error_output = f"Node {process_index + 1} - Execution Failed:\n{execution_error}"
                node_outputs.append(error_output)
                
                log.error(f"Stress execution failed on node {process_index + 1}: {execution_error}")
                nodes[process_index].log.error(
                    f"Stress execution failed on node {process_index + 1}: "
                    f"{execution_error}"
                )
                raise
    
        return node_outputs

    def _format_node_output(self, node_number: int, execution_result) -> str:
        """
        Format the output from a stress-ng execution for reporting.
        
        Args:
            node_number: Sequential number of the node
            execution_result: Process execution result object
            
        Returns:
            Formatted output string
        """
        output_sections = [f"=== Node {node_number} Stress Results ==="]
        
        if execution_result.stdout:
            output_sections.extend([
                "STDOUT:",
                execution_result.stdout.strip(),
                ""
            ])
        
        if execution_result.stderr:
            output_sections.extend([
                "STDERR:",
                execution_result.stderr.strip(),
                ""
            ])
        
        # Add execution metadata
        output_sections.extend([
            f"Exit Code: {execution_result.exit_code}",
            f"Execution Time: {getattr(execution_result, 'elapsed', 'Unknown')}",
            "=" * 50
        ])
        
        return "\n".join(output_sections)

    def _format_success_summary(self, node_outputs: List[str], job_file_name: str) -> str:
        """
        Format a comprehensive summary for successful stress test execution.
        
        Args:
            node_outputs: List of output strings from all nodes
            job_file_name: Name of the executed job file
            
        Returns:
            Formatted success summary
        """
        summary_header = [
            f"Stress-ng job '{job_file_name}' executed successfully",
            f"Nodes processed: {len(node_outputs)}",
            f"Timestamp: {TestStatus.PASSED.name}",
            "=" * 60
        ]
        
        return "\n".join(summary_header + node_outputs)

    def _format_failure_summary(
        self, 
        execution_error: Exception, 
        node_outputs: List[str], 
        job_file_name: str
    ) -> str:
        """
        Format a comprehensive summary for failed stress test execution.
        
        Args:
            execution_error: The exception that caused the failure
            node_outputs: List of output strings from nodes (may be partial)
            job_file_name: Name of the executed job file
            
        Returns:
            Formatted failure summary
        """
        failure_header = [
            f"Stress-ng job '{job_file_name}' execution failed",
            f"Error: {type(execution_error).__name__}: {str(execution_error)}",
            f"Nodes with output: {len(node_outputs)}",
            "=" * 60
        ]
        
        if node_outputs:
            failure_header.extend(["", "Partial execution results:"])
            return "\n".join(failure_header + node_outputs)
        else:
            failure_header.append("No execution output captured")
            return "\n".join(failure_header)

    def _report_test_results(
        self,
        test_result: TestResult,
        job_file_name: str,
        execution_status: TestStatus,
        execution_summary: str,
    ) -> None:
        """
        Report the stress test results through LISA's messaging system.
        
        Args:
            test_result: Test result object for reporting
            job_file_name: Name of the executed job file
            execution_status: Final test status (PASSED/FAILED)
            execution_summary: Comprehensive execution summary
        """
        send_sub_test_result_message(
            test_result=test_result,
            test_case_name=job_file_name,
            test_status=execution_status,
            test_message=execution_summary,
        )

    def _verify_system_stability(self, nodes: List[RemoteNode], log: Logger) -> None:
        """
        Verify system stability after stress testing by checking for kernel panics.
        
        Args:
            nodes: List of nodes to check for stability issues
            log: Logger instance for detailed logging
        """
        log.debug("Checking for kernel panics")
        
        for node_index, node in enumerate(nodes):
            try:
                node.features[SerialConsole].check_panic(
                    saved_path=None, force_run=True
                )
                log.debug(f"System stability verified on node {node_index + 1}")
                node.log.debug(f"System stability verified on node {node_index + 1}")
                
            except Exception as stability_error:
                log.warning(
                    f"Stability check failed on node {node_index + 1}: "
                    f"{stability_error}"
                )
                node.log.warning(
                    f"Stability check failed on node {node_index + 1}: "
                    f"{stability_error}"
                )
