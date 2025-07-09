# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import Path, PurePath
from typing import Any, Dict, List, cast
import yaml
import logging

from lisa import Environment, RemoteNode, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.features import SerialConsole
from lisa.messages import TestStatus, send_sub_test_result_message
from lisa.testsuite import TestResult
from lisa.tools import StressNg
from lisa.util import SkippedException
from lisa.util.logger import Logger
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
        log: Logger,
        variables: Dict[str, Any],
        environment: Environment,
        result: TestResult,
    ) -> None:
        if self.CONFIG_VARIABLE in variables:
            jobs = variables[self.CONFIG_VARIABLE]

            # Handle different input formats: string, comma-separated string, or list
            if isinstance(jobs, str):
                # Split on comma and strip whitespace from each job
                jobs = [job.strip() for job in jobs.split(',')]
            elif isinstance(jobs, list):
                # Already a list, keep as is
                log.debug(f"Job list provided as list type with {len(jobs)} job(s)")
                pass
            else:
                # Convert other types to string and then split
                jobs = [job.strip() for job in str(jobs).split(',')]

            for job_file in jobs:
                try:
                    self._run_stress_ng_job(job_file, environment, result, log)
                except Exception as e:
                    log.error(f"Failed to run job file '{job_file}': {e}")
                    raise
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
        log: Logger,
    ) -> None:
        """
        Execute a stress-ng job file on all nodes in the environment.

        Args:
            job_file: Path to the stress-ng job file
            environment: Test environment containing target nodes
            test_result: Test result object for reporting
            log: Logger instance for detailed logging
        """

        nodes = [cast(RemoteNode, node) for node in environment.nodes.list()]
        stress_processes: List[Process] = []
        job_file_name = Path(job_file).name

        execution_status = TestStatus.QUEUED
        execution_summary = ""

        try:
            self._deploy_and_launch_stress_jobs(
                nodes, job_file, job_file_name, stress_processes, log
            )

            execution_status, execution_summary = self._monitor_stress_execution(
                stress_processes, nodes, log, job_file_name
            )

        except Exception as execution_error:
            execution_status = TestStatus.FAILED
            execution_summary = (
                f"Error : {type(execution_error).__name__}: " f"{str(execution_error)}"
            )
            self._check_panic(nodes)
            raise execution_error

        finally:
            self._report_test_results(
                test_result, job_file_name, execution_status, execution_summary
            )

    def _deploy_and_launch_stress_jobs(
        self,
        nodes: List[RemoteNode],
        job_file: str,
        job_file_name: str,
        stress_processes: List[Process],
        log: Logger,
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
                log.debug(f"Processing node {node_index + 1}/{len(nodes)}: {node.name}")

                # Create dedicated workspace for stress-ng jobs
                remote_workspace = node.working_path / "stress_ng_jobs"
                node.shell.mkdir(remote_workspace, exist_ok=True)

                # Deploy job file to remote node
                remote_job_file = remote_workspace / job_file_name
                node.shell.copy(PurePath(job_file), remote_job_file)

                # Launch stress-ng with the job file
                stress_process = node.tools[StressNg].launch_job_async(
                    str(remote_job_file),
                    yaml=True,
                )
                stress_processes.append(stress_process)

            except Exception as deployment_error:
                log.error(
                    f"Failed to start stress job on node {node_index + 1}: "
                    f"{deployment_error}"
                )
                if getattr(node, "log", None):
                    node.log.error(f"Failed to start stress job: {deployment_error}")
                raise deployment_error

    def _monitor_stress_execution(
        self,
        stress_processes: List[Process],
        nodes: List[RemoteNode],
        log: Logger,
        job_file_name: str,
    ) -> tuple[TestStatus, str]:
        """
        Monitor stress-ng execution and capture stress-ng info output.

        Returns:
            Tuple of (TestStatus, stress_ng_info_output)
        """

        failed_nodes = 0
        node_outputs = []
        exceptions_to_raise = []

        # Wait for all processes and capture their output
        for i, process in enumerate(stress_processes):
            node_name = nodes[i].name if i < len(nodes) else f"node-{i + 1}"
            try:
                result = process.wait_result(
                    timeout=self.TIME_OUT, expected_exit_code=0
                )
                log.info(f"{node_name} completed successfully")

                # Process YAML output if applicable
                node_output = self._process_yaml_output(
                    nodes[i], job_file_name, log
                )

                node_outputs.append(node_output)

            except Exception as e:
                failed_nodes += 1
                error_output = f"=== {node_name} ===\nERROR: {str(e)}"
                node_outputs.append(error_output)
                log.error(f"{node_name} failed: {e}")
                # Store the exception to re-raise after collecting all outputs
                exceptions_to_raise.append(e)

        # Combine all node outputs, including node names for clarity
        execution_summary = f"Job: {job_file_name}\n\n"
        for i, node_output in enumerate(node_outputs):
            node_name = nodes[i].name if i < len(nodes) else f"node-{i + 1}"
            execution_summary += f"=== {node_name} ===\n{node_output}\n\n"

        # If any processes failed, re-raise the first exception to fail the test
        if exceptions_to_raise:
            log.error(
                f"Stress-ng job failed on {failed_nodes} node(s). "
                f"Re-raising first exception to fail the test case."
            )
            raise exceptions_to_raise[0]

        # Return status and stress-ng info output
        overall_status = TestStatus.PASSED if failed_nodes == 0 else TestStatus.FAILED
        return overall_status, execution_summary

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

    def _check_panic(self, nodes: List[RemoteNode]) -> None:
        for node in nodes:
            node.features[SerialConsole].check_panic(saved_path=None, force_run=True)

    def _process_yaml_output(
        self,
        node: RemoteNode,
        job_file_name: str,
        log: Logger,
    ) -> str:
        """
        Process YAML output file if it exists and return its content as a string.

        Args:
            node: The remote node where the job was executed
            job_file_name: Name of the job file (used to derive YAML filename)
            log: Logger instance

        Returns:
            YAML content string or an empty string if not found or error occurs
        """
        # Suppress YAML library warnings
        logging.getLogger("YamlManager").setLevel(logging.WARNING)
        
        node_output = ""
        try:
            # Determine YAML file name based on job file name
            job_stem = Path(job_file_name).stem
            yaml_filename = f"{job_stem}.yaml"

            # Check if YAML file exists in the working directory
            yaml_file_path = node.working_path / yaml_filename
            log.debug(f"Looking for YAML file at: {yaml_file_path}")

            if node.shell.exists(yaml_file_path):
                log.debug(f"Found YAML output file: {yaml_file_path}")
                
                # Read YAML file content using cat command
                result = node.execute(f"cat '{yaml_file_path}'", shell=True)
                yaml_content = result.stdout.strip()
                
                if yaml_content:
                    # Print raw YAML content for debugging
                    log.info(f"Raw YAML file content:\n{yaml_content}")

                    # Try to parse YAML content and extract specific elements
                    try:
                        parsed_yaml = yaml.safe_load(yaml_content)
                        if parsed_yaml is None:
                            log.warning("YAML file parsed as None (empty or invalid)")
                            node_output = f"=== YAML Results ===\nYAML file is empty or invalid"
                        elif isinstance(parsed_yaml, dict):
                            if parsed_yaml:  # Check if dict is not empty
                                # Extract only system-info and times sections
                                filtered_data = {}
                                
                                # Look for system-info element
                                if 'system-info' in parsed_yaml:
                                    filtered_data['system-info'] = parsed_yaml['system-info']
                                
                                # Look for times element
                                if 'times' in parsed_yaml:
                                    filtered_data['times'] = parsed_yaml['times']
                                
                                if filtered_data:
                                    key_values = []
                                    for k, v in filtered_data.items():
                                        key_values.append(f"{k}:")
                                        if isinstance(v, dict):
                                            for sub_k, sub_v in v.items():
                                                key_values.append(f"  {sub_k}: {sub_v}")
                                        else:
                                            key_values.append(f"  {v}")
                                    node_output = key_values
                                else:
                                    node_output = f"=== YAML Results ===\nNo system-info or times sections found"
                            else:
                                node_output = f"=== YAML Results ===\nYAML contains empty dictionary"
                        elif isinstance(parsed_yaml, list):
                            # Handle list case - look for items containing system-info or times
                            filtered_items = []
                            for item in parsed_yaml:
                                if isinstance(item, dict):
                                    if 'system-info' in item or 'times' in item:
                                        filtered_items.append(item)
                            
                            if filtered_items:
                                list_items = []
                                for i, item in enumerate(filtered_items):
                                    list_items.append(f"[{i}]:")
                                    if isinstance(item, dict):
                                        for k, v in item.items():
                                            if k in ['system-info', 'times']:
                                                list_items.append(f"  {k}:")
                                                if isinstance(v, dict):
                                                    for sub_k, sub_v in v.items():
                                                        list_items.append(f"    {sub_k}: {sub_v}")
                                                else:
                                                    list_items.append(f"    {v}")
                                node_output = f"=== YAML Results (Filtered List) ===\n" + "\n".join(list_items)
                            else:
                                node_output = f"=== YAML Results ===\nNo system-info or times sections found in list"
                        else:
                            node_output = f"=== YAML Results ===\n{str(parsed_yaml)}"
                    except yaml.YAMLError as yaml_error:
                        log.warning(f"Failed to parse YAML content: {yaml_error}")
                        node_output = f"=== YAML Results (Raw - Parse Error) ===\n{yaml_content}"
                    except Exception as parse_error:
                        log.warning(f"Unexpected error parsing YAML: {parse_error}")
                        node_output = f"=== YAML Results (Raw - Unexpected Error) ===\n{yaml_content}"
                else:
                    log.debug(f"YAML file {yaml_file_path} is empty")
                    node_output = "=== YAML Results ===\nYAML file is empty"
                
            else:
                log.debug(f"YAML file not found at: {yaml_file_path}")
                node_output = "=== YAML Results ===\nNo YAML output file found"

        except Exception as e:
            log.warning(f"Could not process YAML output: {e}")
            node_output = f"=== YAML Processing Error ===\n{str(e)}"

        return node_output
