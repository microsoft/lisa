# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import logging
from pathlib import Path, PurePath
from typing import Any, Dict, List, Optional, Tuple, cast

import yaml

from lisa import Environment, RemoteNode, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.base_tools import Cat
from lisa.features import SerialConsole
from lisa.messages import TestStatus, send_sub_test_result_message
from lisa.testsuite import TestResult
from lisa.tools import StressNg
from lisa.util import SkippedException, KernelPanicException
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

            # Convert job file configuration to a list if needed
            if not isinstance(jobs, list):
                jobs = [job.strip() for job in str(jobs).split(",")]

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
            # Check for crashes and send test results (no TestResult available)
            self._check_panic(nodes, class_name, None)
            
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
                f"Error: {type(execution_error).__name__}: {str(execution_error)}"
            )
            
            raise execution_error

        finally:
            # Always check for crashes before reporting results, regardless of how we got here
            try:
                self._check_panic(nodes, job_file_name, test_result)
            except Exception as panic_check_error:
                # If panic check fails, log it but don't break the finally block
                log.warning(f"Failed to check for panic: {panic_check_error}")
            
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
        # Wait for VM to fully boot and console logging to be established
        import time
        log.warning("Waiting for VM to fully boot before crash test...")
        time.sleep(30)  # Give console logging time to start
        
        # Check initial console log state
        try:
            initial_serial = nodes[0].features[SerialConsole].get_console_log(saved_path=None, force_run=True)
            log.debug(f"Initial serial log length: {len(initial_serial)}")
            log.debug(f"Initial serial content: {initial_serial[-200:] if len(initial_serial) > 200 else initial_serial}")
        except Exception as e:
            log.warning(f"Failed to get initial serial log: {e}")
        
        # Crash the system for testing
        log.warning("CRASHING SYSTEM NOW for crash detection testing")
        
        # First, enable SysRq if it's disabled
        log.debug("Enabling SysRq...")
        nodes[0].execute("echo 1 > /proc/sys/kernel/sysrq", sudo=True, shell=True)
        
        # Verify SysRq is enabled
        sysrq_status = nodes[0].execute("cat /proc/sys/kernel/sysrq", sudo=True, shell=True)
        log.debug(f"SysRq status: {sysrq_status.stdout}")
        
        # Try multiple crash methods for better reliability
        crash_methods = [
            # Method 1: SysRq crash trigger (immediate)
            "echo c > /proc/sysrq-trigger",
            # Method 2: Force kernel panic with immediate crash
            "echo 1 > /proc/sys/kernel/panic_on_oops && echo c > /proc/sysrq-trigger",
            # Method 3: NULL pointer dereference in kernel space
            "echo 1 > /proc/sys/kernel/panic_on_oops && echo 'int main(){int *p=0; *p=42; return 0;}' > /tmp/crash.c && gcc /tmp/crash.c -o /tmp/crash && /tmp/crash",
            # Method 4: Direct kernel module crash (if available)
            "modprobe dummy 2>/dev/null || echo 'Kernel module crash method not available'",
        ]
        
        # Try each crash method until one works
        crash_successful = False
        for i, crash_cmd in enumerate(crash_methods):
            try:
                log.warning(f"Attempting crash method {i+1}/{len(crash_methods)}: {crash_cmd[:50]}...")
                
                # For method 3 (NULL pointer), prepare the crash program first
                if "crash.c" in crash_cmd:
                    log.debug("Preparing NULL pointer crash program...")
                    # Split the command to execute parts separately for better control
                    nodes[0].execute("echo 1 > /proc/sys/kernel/panic_on_oops", sudo=True, shell=True)
                    nodes[0].execute("echo 'int main(){int *p=0; *p=42; return 0;}' > /tmp/crash.c", sudo=True, shell=True)
                    nodes[0].execute("gcc /tmp/crash.c -o /tmp/crash", sudo=True, shell=True)
                    result = nodes[0].execute("/tmp/crash", sudo=True, shell=True)
                else:
                    # Execute the crash command
                    result = nodes[0].execute(crash_cmd, sudo=True, shell=True)
                
                log.debug(f"Crash method {i+1} result: {result}")
                
                # If we get here without exception, the command completed
                # For crash commands, we expect the connection to drop
                if result.exit_code == 0 and "echo c > /proc/sysrq-trigger" in crash_cmd:
                    log.warning(f"Crash method {i+1} executed successfully")
                    crash_successful = True
                    break
                elif "modprobe" in crash_cmd:
                    log.debug(f"Kernel module method attempted: {result.stdout}")
                    continue  # Try next method
                else:
                    log.info(f"Crash method {i+1} completed, trying next method...")
                    
            except Exception as crash_error:
                log.info(f"Crash method {i+1} triggered exception (expected for crash): {crash_error}")
                crash_successful = True
                break  # Exception likely means the crash worked
        
        if not crash_successful:
            log.warning("All crash methods completed without apparent system crash")
        else:
            log.info("Crash appears to have been triggered successfully")
        
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
    ) -> Tuple[TestStatus, str]:
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
            node_name = nodes[i].name
            try:
                process.wait_result(timeout=self.TIME_OUT, expected_exit_code=0)
                log.info(f"{node_name} completed successfully")

                # Process YAML output if applicable
                node_output = self._process_yaml_output(nodes[i], job_file_name, log)

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
            node_name = nodes[i].name
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

    def _check_panic(self, nodes: List[RemoteNode], test_case_name: str, test_result: Optional[TestResult]) -> None:
        """
        Check for kernel panics, send crash details as test results, and raise.
        """
        for node in nodes:
            try:
                # Add longer delay for crash to be fully logged
                import time
                node.log.info("Waiting for crash to be fully logged to serial console...")
                
                # Check if we can access the console log file directly from LibVirt context
                try:
                    from lisa.sut_orchestrator.libvirt.context import get_node_context
                    node_context = get_node_context(node)
                    console_log_path = node_context.console_log_file_path
                    node.log.debug(f"LibVirt console log file path: {console_log_path}")
                    
                    # Try to read the file directly if it exists
                    import os
                    if os.path.exists(console_log_path):
                        with open(console_log_path, 'r', encoding='utf-8', errors='ignore') as f:
                            direct_content = f.read()
                        node.log.debug(f"Direct console log file size: {len(direct_content)}")
                        if len(direct_content) > 500:
                            node.log.debug(f"Direct console log (last 500 chars): {direct_content[-500:]}")
                        else:
                            node.log.debug(f"Direct console log content: {direct_content}")
                        
                        # Check for common crash indicators in the direct log
                        crash_indicators = ["kernel panic", "Oops:", "BUG:", "Call Trace:", "RIP:", "segfault", "general protection fault"]
                        for indicator in crash_indicators:
                            if indicator.lower() in direct_content.lower():
                                node.log.info(f"FOUND CRASH INDICATOR in direct log: {indicator}")
                                
                    else:
                        node.log.warning(f"Console log file doesn't exist at: {console_log_path}")
                except Exception as direct_read_error:
                    node.log.warning(f"Failed to read console log directly: {direct_read_error}")
                
                # Also check if the VM actually rebooted (indicating a crash)
                try:
                    uptime_result = node.execute("uptime", shell=True)
                    node.log.debug(f"System uptime after crash: {uptime_result.stdout}")
                    
                    # Check for crash evidence in dmesg or /var/log
                    dmesg_result = node.execute("dmesg | tail -50", shell=True)
                    node.log.debug(f"Recent dmesg output: {dmesg_result.stdout}")
                    
                except Exception as system_check_error:
                    node.log.warning(f"Failed to check system state after crash: {system_check_error}")
                    # This might be expected if the system is still recovering from crash
                
                # Try multiple attempts with increasing delays to capture the crash
                max_attempts = 5
                for attempt in range(max_attempts):
                    node.log.debug(f"Attempt {attempt + 1}/{max_attempts} to capture crash log...")
                    
                    # Wait progressively longer for crash to be logged
                    wait_time = 5 + (attempt * 5)  # 5, 10, 15, 20, 25 seconds
                    time.sleep(wait_time)
                    
                    # Force invalidate cache and refresh
                    if hasattr(node.features[SerialConsole], 'invalidate_cache'):
                        node.features[SerialConsole].invalidate_cache()
                    
                    # Get fresh serial log content
                    serial_content = node.features[SerialConsole].get_console_log(saved_path=None, force_run=True)
                    node.log.debug(f"Serial console log content (length: {len(serial_content)}):")
                    
                    # Show more content for debugging
                    if len(serial_content) > 1000:
                        node.log.debug(f"First 500 chars: {serial_content[:500]}")
                        node.log.debug(f"Last 500 chars: {serial_content[-500:]}")
                    else:
                        node.log.debug(f"Full serial log: {serial_content}")
                    
                    # If we have substantial content (more than just login prompt), try to check for panic
                    if len(serial_content) > 200:  # More than just login prompt
                        break
                    else:
                        node.log.warning(f"Serial log too short ({len(serial_content)} chars), retrying...")
                
                node.log.debug("Checking panic in serial log with force_run=True...")
                
                # Now check for panic
                node.features[SerialConsole].check_panic(saved_path=None, force_run=True)
                
                # If we get here, no panic was detected
                node.log.warning("No kernel panic detected in serial console log")
                
            except KernelPanicException as panic_ex:
                # Always log the crash details
                node.log.error(f"CRASH DETECTED on node {node.name}:")
                node.log.error(f"  Stage: {panic_ex.stage}")
                node.log.error(f"  Source: {panic_ex.source}")
                node.log.error(f"  Error codes/phrases: {panic_ex.panics}")
                node.log.error(f"  Full error: {str(panic_ex)}")
                
                # Create detailed crash message
                crash_message = f"""CRASH DETECTED on {node.name}:
Stage: {panic_ex.stage}
Source: {panic_ex.source}
Error codes/phrases: {panic_ex.panics}
Full error: {str(panic_ex)}"""
                
                # Always ensure we have a TestResult for reporting
                if test_result is None:
                    test_result = TestResult(id_=f"crash_detection_{test_case_name}")
                
                # Always send crash test results
                send_sub_test_result_message(
                    test_result=test_result,
                    test_case_name=f"CRASH_{test_case_name}_{node.name}",
                    test_status=TestStatus.FAILED,
                    test_message=crash_message,
                )
                
                # Raise the panic to fail the test
                raise panic_ex

    def _process_yaml_output(
        self,
        node: RemoteNode,
        job_file_name: str,
        log: Logger,
    ) -> str:
        """
        Process YAML output file if it exists and return a concise summary string.
        Only extracts 'system-info' and 'times' sections if present.
        """
        logging.getLogger("YamlManager").setLevel(logging.WARNING)

        job_stem = Path(job_file_name).stem
        yaml_filename = f"{job_stem}.yaml"
        yaml_file_path = node.working_path / yaml_filename

        if not node.shell.exists(yaml_file_path):
            return "No YAML output file found"

        cat = node.tools[Cat]
        yaml_content = cat.read(str(yaml_file_path)).strip()
        if not yaml_content:
            return "YAML file is empty"

        try:
            parsed_yaml = yaml.safe_load(yaml_content)
        except Exception as e:
            log.warning(f"Failed to parse YAML content: {e}")
            return "YAML parse error"

        if not isinstance(parsed_yaml, dict):
            return str(parsed_yaml) if parsed_yaml else "YAML file is empty or invalid"

        output_lines = []
        # Extract system-info, times, and metrics sections if present
        for key in ("metrics", "system-info", "times"):
            if key in parsed_yaml:
                if key == "metrics":
                    # Calculate total bogo-ops from metrics section
                    total_bogo_ops = 0.0
                    if isinstance(parsed_yaml[key], list):
                        for stressor in parsed_yaml[key]:
                            if isinstance(stressor, dict) and "bogo-ops" in stressor:
                                total_bogo_ops += float(stressor["bogo-ops"])
                    output_lines.append(f"Total Bogo-Ops: {total_bogo_ops:.2f}")
                else:
                    # Handle system-info and times sections as before
                    output_lines.append(f"{key}:")
                    value = parsed_yaml[key]
                    if isinstance(value, dict):
                        for sub_k, sub_v in value.items():
                            output_lines.append(f"  {sub_k}: {sub_v}")
                    else:
                        output_lines.append(f"  {value}")
        if not output_lines:
            return "No useful information found in YAML"
        return "\n".join(output_lines)
