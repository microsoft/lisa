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
        nodes[0].log.warning("Waiting for VM to fully boot before crash test...")
        time.sleep(30)  # Give console logging time to start
        
        # PROACTIVE CONSOLE LOGGER HEALTH CHECK
        nodes[0].log.warning("=== PROACTIVE CONSOLE LOGGER HEALTH CHECK ===")
        try:
            from lisa.sut_orchestrator.libvirt.context import get_node_context
            node_context = get_node_context(nodes[0])
            console_logger = node_context.console_logger
            
            if console_logger and hasattr(console_logger, '_stream_completed'):
                is_completed = console_logger._stream_completed.is_set()
                nodes[0].log.warning(f"Pre-crash console logger status - stream completed: {is_completed}")
                
                if is_completed:
                    nodes[0].log.error("Console logger stream already completed before crash test!")
                    nodes[0].log.error("This explains why console logging isn't working properly")
                    nodes[0].log.error("Console logging failure occurred during boot or early operation")
                else:
                    nodes[0].log.info("Console logger appears healthy before crash test")
                    
                    # Check console log file health
                    console_log_path = node_context.console_log_file_path
                    import os
                    if os.path.exists(console_log_path):
                        stat_info = os.stat(console_log_path)
                        import datetime
                        age_seconds = (datetime.datetime.now().timestamp() - stat_info.st_mtime)
                        nodes[0].log.info(f"Console log file: {stat_info.st_size} bytes, {age_seconds:.1f}s old")
                        
                        if age_seconds > 60:  # More than 1 minute old
                            nodes[0].log.warning(f"Console log file is getting stale ({age_seconds:.1f}s) - logging may be slowing down")
                        elif stat_info.st_size < 50:
                            nodes[0].log.warning(f"Console log file is very small ({stat_info.st_size} bytes) - may not be capturing properly")
                        else:
                            nodes[0].log.info("Console log file appears healthy")
            else:
                nodes[0].log.error("Console logger not available or missing stream completion check")
                
        except Exception as health_check_error:
            nodes[0].log.warning(f"Console logger health check failed: {health_check_error}")
        
        # Pre-crash system state capture
        nodes[0].log.debug("=== PRE-CRASH SYSTEM STATE CAPTURE ===")
        try:
            pre_crash_uptime = nodes[0].execute("uptime", shell=True)
            nodes[0].log.info(f"Pre-crash uptime: {pre_crash_uptime.stdout.strip()}")
            
            pre_crash_load = nodes[0].execute("cat /proc/loadavg", shell=True)
            nodes[0].log.debug(f"Pre-crash load: {pre_crash_load.stdout.strip()}")
            
            pre_crash_memory = nodes[0].execute("free -m", shell=True)
            nodes[0].log.debug(f"Pre-crash memory: {pre_crash_memory.stdout.strip()}")
            
        except Exception as pre_state_error:
            nodes[0].log.warning(f"Failed to capture pre-crash state: {pre_state_error}")
        
        # Crash the system for testing - enhanced crash methods
        nodes[0].log.warning("=== INITIATING SYSTEM CRASH FOR CRASH DETECTION TESTING ===")
        
        # Enhanced crash preparation
        nodes[0].log.debug("Preparing system for crash testing...")
        
        try:
            # 1. Check and enable all necessary crash mechanisms
            nodes[0].log.debug("Step 1: Enable crash mechanisms...")
            
            # Enable SysRq with all functions
            nodes[0].execute("echo 1 > /proc/sys/kernel/sysrq", sudo=True, shell=True)
            sysrq_status = nodes[0].execute("cat /proc/sys/kernel/sysrq", shell=True)
            nodes[0].log.debug(f"SysRq status: {sysrq_status.stdout.strip()}")
            
            # Enable panic on oops
            nodes[0].execute("echo 1 > /proc/sys/kernel/panic_on_oops", sudo=True, shell=True)
            panic_oops_status = nodes[0].execute("cat /proc/sys/kernel/panic_on_oops", shell=True)
            nodes[0].log.debug(f"Panic on oops: {panic_oops_status.stdout.strip()}")
            
            # Set panic timeout to ensure reboot (0 = no auto reboot, 1 = reboot after 1 sec)
            nodes[0].execute("echo 10 > /proc/sys/kernel/panic", sudo=True, shell=True)
            panic_timeout = nodes[0].execute("cat /proc/sys/kernel/panic", shell=True)
            nodes[0].log.debug(f"Panic timeout: {panic_timeout.stdout.strip()}")
            
            # 2. Prepare crash detection logging and force console output
            nodes[0].log.debug("Step 2: Prepare logging systems...")
            
            # Force kernel to log more verbosely
            nodes[0].execute("echo 7 > /proc/sys/kernel/printk", sudo=True, shell=True)
            printk_level = nodes[0].execute("cat /proc/sys/kernel/printk", shell=True)
            nodes[0].log.debug(f"Kernel printk level: {printk_level.stdout.strip()}")
            
            # Force console output and disable console blanking
            nodes[0].execute("setterm -blank 0 -powerdown 0 2>/dev/null || true", sudo=True, shell=True)
            nodes[0].execute("echo 0 > /sys/class/vtconsole/vtcon1/bind 2>/dev/null || true", sudo=True, shell=True)
            
            # Enable all kernel debugging and ensure console output
            nodes[0].execute("echo 1 > /proc/sys/kernel/printk_ratelimit_burst", sudo=True, shell=True)
            nodes[0].execute("echo 0 > /proc/sys/kernel/printk_ratelimit", sudo=True, shell=True)
            
            # Force immediate console flush
            nodes[0].execute("dmesg --console-level=7 2>/dev/null || true", sudo=True, shell=True)
            
            # Send test message to console to verify logging
            nodes[0].execute("echo 'LISA_CRASH_TEST_START' > /dev/console 2>/dev/null || echo 'LISA_CRASH_TEST_START' > /dev/kmsg || true", sudo=True, shell=True)
            
            # Sync filesystems before crash
            nodes[0].execute("sync", sudo=True, shell=True)
            nodes[0].log.debug("Filesystems synced and console logging configured")
            
        except Exception as prep_error:
            nodes[0].log.warning(f"Crash preparation failed (continuing anyway): {prep_error}")
        
        # Enhanced crash methods with better success detection
        crash_methods = [
            # Method 1: Direct kernel panic trigger (most reliable)
            {
                "name": "direct_panic", 
                "cmd": "echo 1 > /proc/sys/kernel/panic && sleep 1",
                "timeout": 5,
                "description": "Direct kernel panic trigger"
            },
            # Method 2: SysRq crash trigger
            {
                "name": "sysrq_crash", 
                "cmd": "echo c > /proc/sysrq-trigger",
                "timeout": 5,
                "description": "SysRq crash trigger"
            },
            # Method 3: SysRq with sync first  
            {
                "name": "sysrq_sync_crash", 
                "cmd": "echo s > /proc/sysrq-trigger && sleep 1 && echo c > /proc/sysrq-trigger",
                "timeout": 10,
                "description": "SysRq sync then crash"
            },
            # Method 4: Kernel module crash (if possible)
            {
                "name": "module_crash",
                "cmd": "echo 'BUG()' > /proc/breakme 2>/dev/null || echo 1 > /proc/sys/kernel/panic",
                "timeout": 5,
                "description": "Kernel module crash or fallback panic"
            },
            # Method 5: Memory corruption attempt
            {
                "name": "memory_corruption",
                "cmd": "dd if=/dev/urandom of=/dev/mem bs=1 count=1 seek=1000000 2>/dev/null || echo c > /proc/sysrq-trigger",
                "timeout": 10,
                "description": "Memory corruption or SysRq fallback"
            }
        ]
        
        # Try each crash method with comprehensive monitoring
        crash_successful = False
        for i, method in enumerate(crash_methods):
            if crash_successful:
                break
                
            nodes[0].log.warning(f"=== Crash Method {i+1}/{len(crash_methods)}: {method['name']} ===")
            nodes[0].log.debug(f"Description: {method['description']}")
            nodes[0].log.debug(f"Command: {method['cmd']}")
            
            try:
                # Pre-method check
                try:
                    pre_method_check = nodes[0].execute("echo 'pre_method_alive'", shell=True, timeout=3)
                    nodes[0].log.debug(f"Pre-method system state: {pre_method_check.stdout}")
                except Exception as pre_check_error:
                    nodes[0].log.warning(f"Pre-method check failed: {pre_check_error}")
                    # If we can't even do a basic echo, system might already be crashed
                    crash_successful = True
                    break
                
                # Execute crash command with timeout
                nodes[0].log.debug(f"Executing crash command with {method['timeout']}s timeout...")
                try:
                    result = nodes[0].execute(method['cmd'], sudo=True, shell=True, timeout=method['timeout'])
                    nodes[0].log.debug(f"Crash command completed: exit_code={result.exit_code}, stdout='{result.stdout}', stderr='{result.stderr}'")
                    
                    # If command completed without exception, system might not have crashed yet
                    if result.exit_code == 0:
                        nodes[0].log.warning(f"Method {method['name']} completed successfully - unexpected for crash command")
                        # Wait a bit to see if delayed crash occurs
                        time.sleep(5)
                        
                        # Try post-crash connectivity test
                        try:
                            post_test = nodes[0].execute("echo 'post_crash_test'", shell=True, timeout=5)
                            if "post_crash_test" in post_test.stdout:
                                nodes[0].log.warning(f"System still responsive after {method['name']}")
                            else:
                                nodes[0].log.info(f"System response abnormal after {method['name']} - possible crash")
                                crash_successful = True
                        except Exception as post_error:
                            nodes[0].log.info(f"System unresponsive after {method['name']} - crash likely successful: {post_error}")
                            crash_successful = True
                    else:
                        nodes[0].log.warning(f"Method {method['name']} failed with exit code {result.exit_code}")
                
                except Exception as cmd_error:
                    # Exception during crash command is actually expected and indicates success
                    nodes[0].log.info(f"Method {method['name']} triggered exception (EXPECTED): {type(cmd_error).__name__}: {cmd_error}")
                    
                    # Different types of exceptions indicate different levels of crash success
                    error_str = str(cmd_error).lower()
                    if any(keyword in error_str for keyword in ["timeout", "connection", "ssh", "unreachable", "broken pipe"]):
                        nodes[0].log.info(f"Method {method['name']} caused connectivity loss - crash successful!")
                        crash_successful = True
                    else:
                        nodes[0].log.warning(f"Method {method['name']} failed with unexpected error: {cmd_error}")
                
            except Exception as method_error:
                nodes[0].log.info(f"Method {method['name']} caused system-level error - likely successful crash: {method_error}")
                crash_successful = True
            
            # If this method succeeded, no need to try others
            if crash_successful:
                nodes[0].log.info(f"SUCCESS: Method {method['name']} successfully crashed the system!")
                break
            else:
                nodes[0].log.warning(f"Method {method['name']} did not appear to crash the system, trying next method...")
                # Small delay between methods
                time.sleep(2)
        
        # Post-crash analysis and waiting
        if crash_successful:
            nodes[0].log.info("=== SYSTEM CRASH DETECTED - WAITING FOR FULL CRASH CYCLE ===")
            
            # Wait for crash to fully complete and system to potentially restart
            nodes[0].log.info("Waiting for crash to complete and system to potentially restart...")
            time.sleep(60)  # Extended wait for full crash cycle
            
            # Attempt reconnection after crash
            nodes[0].log.info("Attempting to reconnect after crash...")
            reconnection_successful = False
            for reconnect_attempt in range(10):  # More reconnection attempts
                try:
                    wait_time = 10 + (reconnect_attempt * 5)  # Progressive backoff
                    time.sleep(wait_time)
                    
                    # Try to reconnect and get basic system info
                    reconnect_result = nodes[0].execute("echo 'reconnected' && uptime", shell=True, timeout=30)
                    nodes[0].log.info(f"Reconnection attempt {reconnect_attempt + 1} successful!")
                    nodes[0].log.info(f"Post-crash system state: {reconnect_result.stdout}")
                    reconnection_successful = True
                    break
                    
                except Exception as reconnect_error:
                    nodes[0].log.debug(f"Reconnection attempt {reconnect_attempt + 1} failed: {reconnect_error}")
                    
                    # If it's the last attempt, log it as a warning
                    if reconnect_attempt == 9:
                        nodes[0].log.warning("Failed to reconnect after 10 attempts - system may not have restarted or may be permanently crashed")
                        
            if not reconnection_successful:
                nodes[0].log.error("Could not reconnect to system after crash - this may indicate:")
                nodes[0].log.error("1. System crashed and did not restart automatically")
                nodes[0].log.error("2. System is in an unrecoverable state")
                nodes[0].log.error("3. Network connectivity issues")
                
        else:
            nodes[0].log.error("=== CRASH METHODS FAILED ===")
            nodes[0].log.error("All crash methods completed without successfully crashing the system!")
            nodes[0].log.error("This indicates:")
            nodes[0].log.error("1. SysRq may be disabled or filtered by the hypervisor")
            nodes[0].log.error("2. Kernel has strong crash protections enabled")
            nodes[0].log.error("3. Commands are not executing with sufficient privileges")
            nodes[0].log.error("4. System is running in a protected/hardened environment")
            
            # Try one final emergency method
            nodes[0].log.warning("Attempting final emergency crash method...")
            try:
                # More aggressive crash attempts
                emergency_methods = [
                    "echo 'kernel.panic=1' > /proc/sys/kernel/panic && echo c > /proc/sysrq-trigger",
                    "killall -9 init && echo c > /proc/sysrq-trigger", 
                    "echo b > /proc/sysrq-trigger",  # Immediate reboot
                ]
                
                for emergency_cmd in emergency_methods:
                    try:
                        nodes[0].log.debug(f"Emergency method: {emergency_cmd}")
                        result = nodes[0].execute(emergency_cmd, sudo=True, shell=True, timeout=5)
                        nodes[0].log.debug(f"Emergency result: {result}")
                        time.sleep(5)  # Wait to see if it takes effect
                    except Exception as emergency_error:
                        nodes[0].log.info(f"Emergency method triggered exception: {emergency_error}")
                        crash_successful = True
                        break
                        
            except Exception as final_error:
                nodes[0].log.info(f"Final emergency crash method triggered exception: {final_error}")
                crash_successful = True
        
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
                    nodes[0].log.error(f"Failed to start stress job: {deployment_error}")
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
        Check for kernel panics using multiple detection methods.
        This is a comprehensive crash detection system that checks:
        1. Serial console logs for panic patterns
        2. SSH connectivity status 
        3. System uptime changes
        4. Alternative log sources (journalctl, dmesg, syslog)
        5. LibVirt console log files directly
        """
        for node in nodes:
            crash_detected = False
            crash_evidence = []
            
            try:
                # Method 1: Check SSH connectivity first (fastest indicator)
                nodes[0].log.debug("=== Crash Detection Method 1: SSH Connectivity Test ===")
                try:
                    # Simple connectivity test with short timeout
                    connectivity_result = node.execute("echo 'ssh_alive'", shell=True, timeout=5)
                    nodes[0].log.debug(f"SSH connectivity test: {connectivity_result.stdout}")
                    if "ssh_alive" not in connectivity_result.stdout:
                        crash_evidence.append("SSH response malformed")
                        crash_detected = True
                except Exception as ssh_error:
                    nodes[0].log.warning(f"SSH connectivity failed: {ssh_error}")
                    if any(keyword in str(ssh_error).lower() for keyword in ["connection", "timeout", "session not active", "ssh", "unreachable"]):
                        crash_evidence.append(f"SSH failure: {ssh_error}")
                        crash_detected = True
                
                # Method 2: Check system state indicators
                if not crash_detected:
                    nodes[0].log.debug("=== Crash Detection Method 2: System State Analysis ===")
                    try:
                        # Check uptime for recent reboot
                        uptime_result = node.execute("uptime", shell=True, timeout=10)
                        nodes[0].log.debug(f"System uptime: {uptime_result.stdout}")
                        
                        # Parse uptime - if very recent, it suggests reboot
                        uptime_str = uptime_result.stdout.strip()
                        if ("min" in uptime_str and not "hour" in uptime_str and not "day" in uptime_str):
                            # Extract minutes and check if less than 5 minutes
                            import re
                            min_match = re.search(r'(\d+)\s+min', uptime_str)
                            if min_match and int(min_match.group(1)) < 5:
                                crash_evidence.append(f"Recent reboot detected: {uptime_str}")
                                crash_detected = True
                                nodes[0].log.warning(f"System rebooted recently: {uptime_str}")
                        
                        # Check memory info for OOM killer activity
                        oom_check = node.execute("dmesg | grep -i 'killed process\\|out of memory' | tail -5", shell=True, timeout=5)
                        if oom_check.stdout and len(oom_check.stdout.strip()) > 0:
                            crash_evidence.append(f"OOM activity: {oom_check.stdout}")
                            nodes[0].log.warning(f"OOM killer activity detected: {oom_check.stdout}")
                        
                    except Exception as state_error:
                        nodes[0].log.warning(f"System state check failed (possible crash): {state_error}")
                        if any(keyword in str(state_error).lower() for keyword in ["connection", "timeout", "session"]):
                            crash_evidence.append(f"System state check failure: {state_error}")
                            crash_detected = True
                
                # Method 3: Check kernel logs for panic patterns
                if not crash_detected:
                    nodes[0].log.debug("=== Crash Detection Method 3: Kernel Log Analysis ===")
                    try:
                        # Check dmesg for kernel panics and oops
                        dmesg_result = node.execute("dmesg | tail -50", shell=True, timeout=10)
                        kernel_indicators = ["kernel panic", "oops:", "bug:", "call trace:", "rip:", "segfault", "general protection", "unable to handle"]
                        
                        dmesg_content = dmesg_result.stdout.lower()
                        found_kernel_issues = [indicator for indicator in kernel_indicators if indicator in dmesg_content]
                        
                        if found_kernel_issues:
                            crash_evidence.append(f"Kernel issues in dmesg: {found_kernel_issues}")
                            crash_detected = True
                            nodes[0].log.warning(f"Kernel issues detected in dmesg: {found_kernel_issues}")
                        
                        # Check journalctl for system crashes
                        journal_result = node.execute("journalctl -p err --since='5 minutes ago' --no-pager | tail -20", shell=True, timeout=10)
                        if journal_result.stdout and len(journal_result.stdout.strip()) > 0:
                            journal_content = journal_result.stdout.lower()
                            journal_issues = [indicator for indicator in kernel_indicators if indicator in journal_content]
                            if journal_issues:
                                crash_evidence.append(f"System errors in journal: {journal_issues}")
                                crash_detected = True
                                nodes[0].log.warning(f"System errors in journal: {journal_issues}")
                        
                    except Exception as log_error:
                        nodes[0].log.warning(f"Kernel log analysis failed (possible crash): {log_error}")
                        if any(keyword in str(log_error).lower() for keyword in ["connection", "timeout", "session"]):
                            crash_evidence.append(f"Kernel log check failure: {log_error}")
                            crash_detected = True
                
                # Method 4: Serial Console Analysis (enhanced with console logging recovery)
                nodes[0].log.debug("=== Crash Detection Method 4: Serial Console Analysis ===")
                
                # FIRST: Try direct LibVirt console capture (bypass broken logger)
                direct_console_content = ""
                try:
                    nodes[0].log.debug("Attempting direct LibVirt console capture...")
                    from lisa.sut_orchestrator.libvirt.context import get_node_context
                    node_context = get_node_context(node)
                    domain = node_context.domain
                    
                    if domain:
                        # Try to read console directly from LibVirt
                        try:
                            import libvirt
                            
                            # Create a new stream for direct console reading
                            console_stream = domain.connect().newStream(0)  # Blocking stream for one-time read
                            
                            # Open console with safe flags
                            domain.openConsole(None, console_stream, libvirt.VIR_DOMAIN_CONSOLE_SAFE)
                            
                            # Try to read data from the stream
                            nodes[0].log.debug("Reading direct console data...")
                            console_data = b""
                            try:
                                # Read in chunks with timeout
                                for _ in range(10):  # Try up to 10 times
                                    try:
                                        chunk = console_stream.recv(1024)
                                        if chunk and len(chunk) > 0:
                                            console_data += chunk
                                        else:
                                            break
                                    except:
                                        break
                                
                                direct_console_content = console_data.decode('utf-8', errors='ignore')
                                nodes[0].log.warning(f"Direct console capture successful: {len(direct_console_content)} chars")
                                
                                if len(direct_console_content) > 0:
                                    nodes[0].log.debug(f"Direct console content: {direct_console_content[-500:] if len(direct_console_content) > 500 else direct_console_content}")
                                    
                                    # Check for crash patterns in direct console
                                    crash_patterns = ["kernel panic", "oops:", "bug:", "call trace:", "rip:", "segfault", "general protection fault"]
                                    direct_content_lower = direct_console_content.lower()
                                    direct_crash_issues = [pattern for pattern in crash_patterns if pattern in direct_content_lower]
                                    
                                    if direct_crash_issues:
                                        crash_evidence.append(f"Direct console patterns: {direct_crash_issues}")
                                        crash_detected = True
                                        nodes[0].log.warning(f"Crash patterns found in direct console: {direct_crash_issues}")
                                
                            finally:
                                # Always close the stream
                                try:
                                    console_stream.finish()
                                except:
                                    try:
                                        console_stream.abort()
                                    except:
                                        pass
                                        
                        except Exception as direct_console_error:
                            nodes[0].log.debug(f"Direct console capture failed: {direct_console_error}")
                
                except Exception as direct_capture_error:
                    nodes[0].log.debug(f"Direct LibVirt console capture failed: {direct_capture_error}")
                
                try:
                    # Add delay for crash to be logged
                    import time
                    time.sleep(10)  # Give console logging time to capture crash
                    
                    # Force refresh of console log
                    if hasattr(node.features[SerialConsole], 'invalidate_cache'):
                        node.features[SerialConsole].invalidate_cache()
                    
                    # Get console log with force refresh
                    serial_content = node.features[SerialConsole].get_console_log(saved_path=None, force_run=True)
                    nodes[0].log.debug(f"Serial console log length: {len(serial_content)}")
                    
                    if len(serial_content) > 200:  # Substantial content
                        # Look for crash patterns in serial log
                        crash_patterns = ["kernel panic", "oops:", "bug:", "call trace:", "rip:", "segfault", "general protection fault", "unable to handle kernel"]
                        serial_content_lower = serial_content.lower()
                        found_serial_issues = [pattern for pattern in crash_patterns if pattern in serial_content_lower]
                        
                        if found_serial_issues:
                            crash_evidence.append(f"Serial console patterns: {found_serial_issues}")
                            crash_detected = True
                            nodes[0].log.warning(f"Crash patterns found in serial console: {found_serial_issues}")
                        
                        # Also check for repeated login prompts (suggesting reboot loop)
                        login_count = serial_content_lower.count("login:")
                        if login_count > 2:  # Multiple login prompts suggest reboots
                            crash_evidence.append(f"Multiple login prompts detected: {login_count}")
                            nodes[0].log.warning(f"Multiple login prompts suggest system reboots: {login_count}")
                    else:
                        nodes[0].log.warning(f"Serial console log too short: {len(serial_content)} bytes")
                        # Short console log after crash attempt might indicate logging issues
                        if len(serial_content) < 100:
                            crash_evidence.append("Serial console log suspiciously short")
                    
                    # Try direct LibVirt console log access if available
                    try:
                        from lisa.sut_orchestrator.libvirt.context import get_node_context
                        node_context = get_node_context(node)
                        console_log_path = node_context.console_log_file_path
                        
                        import os
                        if os.path.exists(console_log_path):
                            with open(console_log_path, 'r', encoding='utf-8', errors='ignore') as f:
                                direct_log = f.read()
                            
                            nodes[0].log.debug(f"Direct LibVirt log length: {len(direct_log)}")
                            
                            # ENHANCED CONSOLE LOGGING DIAGNOSTICS
                            stat_info = os.stat(console_log_path)
                            import datetime
                            age_seconds = (datetime.datetime.now().timestamp() - stat_info.st_mtime)
                            
                            nodes[0].log.warning(f"=== CONSOLE LOGGING DIAGNOSTICS ===")
                            nodes[0].log.warning(f"Console log file: {console_log_path}")
                            nodes[0].log.warning(f"File size: {stat_info.st_size} bytes")
                            nodes[0].log.warning(f"File age: {age_seconds:.1f} seconds")
                            nodes[0].log.warning(f"Direct log length: {len(direct_log)}")
                            nodes[0].log.warning(f"SerialConsole API length: {len(serial_content)}")
                            
                            # Show recent content for diagnosis
                            if len(direct_log) > 0:
                                recent_content = direct_log[-300:] if len(direct_log) > 300 else direct_log
                                nodes[0].log.debug(f"Recent console content: {repr(recent_content)}")
                                
                                # Check if we're getting kernel messages at all
                                kernel_indicators = ["kernel:", "dmesg:", "[", "]", "systemd", "systemctl", "getty", "login:", "ubuntu"]
                                has_kernel_activity = any(indicator in direct_log.lower() for indicator in kernel_indicators)
                                nodes[0].log.warning(f"Console shows kernel/system activity: {has_kernel_activity}")
                                
                                if not has_kernel_activity and len(direct_log) < 200:
                                    nodes[0].log.error("=== CONSOLE LOGGING ISSUE DETECTED ===")
                                    nodes[0].log.error("Console log contains minimal content and no kernel messages!")
                                    nodes[0].log.error("This suggests:")
                                    nodes[0].log.error("1. Console logging stopped after initial boot")
                                    nodes[0].log.error("2. Kernel console output is not being redirected to serial console") 
                                    nodes[0].log.error("3. LibVirt console stream is not capturing runtime messages")
                                    nodes[0].log.error("4. The kernel may not be configured to output to the console device")
                                    nodes[0].log.error("")
                                    nodes[0].log.error("=== POTENTIAL FIXES FOR CONSOLE LOGGING ===")
                                    nodes[0].log.error("1. Add kernel parameters: console=ttyS0 console=tty0")
                                    nodes[0].log.error("2. Add kernel parameters: earlyprintk=serial")
                                    nodes[0].log.error("3. Add kernel parameters: ignore_loglevel")
                                    nodes[0].log.error("4. Check if systemd is redirecting console output")
                                    nodes[0].log.error("5. Verify LibVirt console device configuration")
                                    crash_evidence.append("Console logging appears broken - no kernel messages")
                                elif len(direct_log) < 100:
                                    nodes[0].log.warning("Console log is very short - may indicate early boot failure or logging issue")
                                    crash_evidence.append("Console log suspiciously short")
                            
                            # Check direct log for crash patterns
                            if len(direct_log) > 0:
                                crash_patterns = ["kernel panic", "oops:", "bug:", "call trace:", "rip:", "segfault", "general protection fault", "unable to handle kernel"]
                                direct_log_lower = direct_log.lower()
                                direct_issues = [pattern for pattern in crash_patterns if pattern in direct_log_lower]
                                if direct_issues:
                                    crash_evidence.append(f"Direct LibVirt log patterns: {direct_issues}")
                                    crash_detected = True
                                    nodes[0].log.warning(f"Crash patterns found in direct LibVirt log: {direct_issues}")
                            
                            # Check file age - if very old, logging might be broken
                            if age_seconds > 300:  # More than 5 minutes old
                                nodes[0].log.warning(f"Console log file is stale ({age_seconds:.1f}s old) - console logging may have stopped!")
                                crash_evidence.append(f"Console log file stale: {age_seconds:.1f}s old")
                                
                                # Try to diagnose why console logging stopped
                                nodes[0].log.error("=== INVESTIGATING STALE CONSOLE LOG ===")
                                try:
                                    # Check if LibVirt domain is still running
                                    node_context = get_node_context(node)
                                    domain = node_context.domain
                                    if domain:
                                        domain_state = domain.state()
                                        nodes[0].log.warning(f"LibVirt domain state: {domain_state}")
                                        
                                        # Domain state meanings:
                                        # 1 = VIR_DOMAIN_RUNNING
                                        # 3 = VIR_DOMAIN_PAUSED  
                                        # 4 = VIR_DOMAIN_CRASHED
                                        # 5 = VIR_DOMAIN_SHUTOFF
                                        if domain_state[0] == 1:  # VIR_DOMAIN_RUNNING
                                            nodes[0].log.error("LibVirt domain is RUNNING but console log is stale!")
                                            nodes[0].log.error("This indicates a console logging configuration issue!")
                                            crash_evidence.append("LibVirt domain running but console log stale")
                                        elif domain_state[0] in [4, 5]:  # VIR_DOMAIN_CRASHED, VIR_DOMAIN_SHUTOFF
                                            nodes[0].log.warning(f"LibVirt domain state indicates crash/shutdown: {domain_state}")
                                            crash_evidence.append(f"LibVirt domain crash/shutdown state: {domain_state}")
                                            crash_detected = True
                                        elif domain_state[0] == 3:  # VIR_DOMAIN_PAUSED
                                            nodes[0].log.warning("LibVirt domain is PAUSED - may indicate system hang")
                                            crash_evidence.append("LibVirt domain paused")
                                            crash_detected = True
                                            
                                        # Check console logger status
                                        console_logger = node_context.console_logger
                                        if console_logger:
                                            nodes[0].log.debug("Console logger object exists")
                                            # Try to determine if console logger is still active
                                            if hasattr(console_logger, '_stream_completed'):
                                                is_completed = console_logger._stream_completed.is_set()
                                                nodes[0].log.warning(f"Console logger stream completed: {is_completed}")
                                                if is_completed:
                                                    nodes[0].log.error("Console logger stream has completed - this explains why logging stopped!")
                                                    nodes[0].log.error("Attempting to restart console logger...")
                                                    crash_evidence.append("Console logger stream completed")
                                                    
                                                    # ATTEMPT TO RESTART CONSOLE LOGGER
                                                    try:
                                                        nodes[0].log.warning("=== ATTEMPTING CONSOLE LOGGER RECOVERY ===")
                                                        
                                                        # Import required modules
                                                        from lisa.sut_orchestrator.libvirt.console_logger import QemuConsoleLogger
                                                        import os
                                                        
                                                        # Create new console log file path with timestamp
                                                        import datetime
                                                        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                                                        original_log_path = node_context.console_log_file_path
                                                        recovery_log_path = f"{original_log_path}.recovery_{timestamp}"
                                                        
                                                        nodes[0].log.warning(f"Creating recovery console log: {recovery_log_path}")
                                                        
                                                        # Close the old logger if possible
                                                        try:
                                                            console_logger.close(abort=True)
                                                            nodes[0].log.debug("Old console logger closed")
                                                        except Exception as close_error:
                                                            nodes[0].log.debug(f"Failed to close old logger: {close_error}")
                                                        
                                                        # Create new console logger
                                                        new_console_logger = QemuConsoleLogger()
                                                        
                                                        # Attach to the domain with new log file
                                                        domain = node_context.domain
                                                        if domain:
                                                            new_console_logger.attach(domain, recovery_log_path)
                                                            node_context.console_logger = new_console_logger
                                                            nodes[0].log.warning("Console logger successfully restarted!")
                                                            
                                                            # Wait a bit for new logger to capture data
                                                            import time
                                                            time.sleep(5)
                                                            
                                                            # Check if new logger is working
                                                            if os.path.exists(recovery_log_path):
                                                                stat_info = os.stat(recovery_log_path)
                                                                if stat_info.st_size > 0:
                                                                    nodes[0].log.warning(f"Recovery console log is working! Size: {stat_info.st_size} bytes")
                                                                    
                                                                    # Try to read recovery log for crash patterns
                                                                    with open(recovery_log_path, 'r', encoding='utf-8', errors='ignore') as f:
                                                                        recovery_content = f.read()
                                                                    
                                                                    if len(recovery_content) > 0:
                                                                        nodes[0].log.debug(f"Recovery log content: {recovery_content}")
                                                                        
                                                                        # Check for crash patterns in recovery log
                                                                        crash_patterns = ["kernel panic", "oops:", "bug:", "call trace:", "rip:", "segfault"]
                                                                        recovery_content_lower = recovery_content.lower()
                                                                        recovery_issues = [pattern for pattern in crash_patterns if pattern in recovery_content_lower]
                                                                        
                                                                        if recovery_issues:
                                                                            crash_evidence.append(f"Recovery console log patterns: {recovery_issues}")
                                                                            crash_detected = True
                                                                            nodes[0].log.warning(f"Crash patterns found in recovery console log: {recovery_issues}")
                                                                else:
                                                                    nodes[0].log.warning("Recovery console log is empty")
                                                            else:
                                                                nodes[0].log.warning("Recovery console log file not created")
                                                        else:
                                                            nodes[0].log.error("LibVirt domain is None - cannot restart console logger")
                                                            
                                                    except Exception as recovery_error:
                                                        nodes[0].log.error(f"Console logger recovery failed: {recovery_error}")
                                                        nodes[0].log.error("This suggests a fundamental issue with LibVirt console streams")
                                                        crash_evidence.append(f"Console logger recovery failed: {recovery_error}")
                                        else:
                                            nodes[0].log.error("Console logger object is None!")
                                            crash_evidence.append("Console logger missing")
                                            
                                except Exception as domain_error:
                                    nodes[0].log.debug(f"Failed to check LibVirt domain state: {domain_error}")
                        else:
                            nodes[0].log.error(f"Console log file doesn't exist: {console_log_path}")
                            crash_evidence.append("Console log file missing")
                        
                    except Exception as libvirt_error:
                        nodes[0].log.debug(f"Direct LibVirt log access failed: {libvirt_error}")
                
                except Exception as serial_error:
                    nodes[0].log.warning(f"Serial console analysis failed: {serial_error}")
                    # If serial console analysis fails completely, it might indicate system crash
                    crash_evidence.append(f"Serial console analysis failure: {serial_error}")
                
                # Method 5: LibVirt Domain State Analysis (console-independent)
                if not crash_detected:
                    nodes[0].log.debug("=== Crash Detection Method 5: LibVirt Domain State Analysis ===")
                    try:
                        from lisa.sut_orchestrator.libvirt.context import get_node_context
                        node_context = get_node_context(node)
                        domain = node_context.domain
                        
                        if domain:
                            # Get current domain state
                            domain_state = domain.state()
                            nodes[0].log.debug(f"LibVirt domain state: {domain_state}")
                            
                            # Domain state analysis
                            state_code = domain_state[0]
                            reason_code = domain_state[1] if len(domain_state) > 1 else 0
                            
                            if state_code == 4:  # VIR_DOMAIN_CRASHED
                                crash_evidence.append(f"LibVirt domain crashed (state={state_code}, reason={reason_code})")
                                crash_detected = True
                                nodes[0].log.error(f"LibVirt reports domain CRASHED: {domain_state}")
                            elif state_code == 5:  # VIR_DOMAIN_SHUTOFF
                                crash_evidence.append(f"LibVirt domain shutoff (state={state_code}, reason={reason_code})")
                                crash_detected = True
                                nodes[0].log.warning(f"LibVirt reports domain SHUTOFF: {domain_state}")
                            elif state_code == 3:  # VIR_DOMAIN_PAUSED
                                crash_evidence.append(f"LibVirt domain paused (state={state_code}, reason={reason_code})")
                                crash_detected = True
                                nodes[0].log.warning(f"LibVirt reports domain PAUSED: {domain_state}")
                            elif state_code == 1:  # VIR_DOMAIN_RUNNING
                                nodes[0].log.debug("LibVirt domain is running - checking for other crash indicators")
                            else:
                                nodes[0].log.warning(f"Unknown LibVirt domain state: {domain_state}")
                                crash_evidence.append(f"LibVirt domain unknown state: {domain_state}")
                        else:
                            nodes[0].log.error("LibVirt domain object is None!")
                            crash_evidence.append("LibVirt domain missing")
                            crash_detected = True
                            
                    except Exception as domain_analysis_error:
                        nodes[0].log.warning(f"LibVirt domain state analysis failed: {domain_analysis_error}")
                        # If we can't check domain state, it might indicate system issues
                        crash_evidence.append(f"LibVirt domain analysis failure: {domain_analysis_error}")
                
                # Method 6: Use built-in SerialConsole.check_panic (fallback)
                # Method 6: Use built-in SerialConsole.check_panic (fallback)
                if not crash_detected:
                    nodes[0].log.debug("=== Crash Detection Method 6: Built-in Panic Check (Fallback) ===")
                    try:
                        # Use the built-in panic detection with force refresh
                        node.features[SerialConsole].check_panic(saved_path=None, stage="stress_test_panic_check", force_run=True)
                        nodes[0].log.debug("Built-in panic check passed - no panic detected")
                    except KernelPanicException as builtin_panic:
                        nodes[0].log.warning(f"Built-in panic check detected crash: {builtin_panic}")
                        crash_evidence.append(f"Built-in panic detection: {builtin_panic.panics}")
                        crash_detected = True
                        # Re-raise this exception as it's already properly formatted
                        raise builtin_panic
                    except Exception as builtin_error:
                        nodes[0].log.warning(f"Built-in panic check failed: {builtin_error}")
                        # If built-in check fails, it might be due to system crash
                        crash_evidence.append(f"Built-in panic check failure: {builtin_error}")
                
                # If any crash evidence was found, raise KernelPanicException
                if crash_detected and crash_evidence:
                    nodes[0].log.error(f"CRASH DETECTED on node {node.name}")
                    nodes[0].log.error(f"Evidence found: {crash_evidence}")
                    
                    # Create comprehensive crash message
                    crash_message = f"Crash detected on {node.name} with evidence: {'; '.join(crash_evidence)}"
                    
                    # Ensure we have a TestResult for reporting
                    if test_result is None:
                        from lisa.testsuite import TestResult
                        test_result = TestResult(id_=f"crash_detection_{test_case_name}")
                    
                    # Send crash test results
                    send_sub_test_result_message(
                        test_result=test_result,
                        test_case_name=f"CRASH_{test_case_name}_{node.name}",
                        test_status=TestStatus.FAILED,
                        test_message=crash_message,
                    )
                    
                    # Raise KernelPanicException with proper parameters
                    from lisa.util import KernelPanicException
                    raise KernelPanicException(
                        stage="comprehensive_crash_detection",
                        panics=crash_evidence,
                        source="multi_method_analysis"
                    )
                else:
                    nodes[0].log.info(f"No crash evidence found on node {node.name}")
                
            except KernelPanicException:
                # Re-raise KernelPanicException as-is
                raise
            except Exception as check_error:
                nodes[0].log.error(f"Crash detection failed with unexpected error: {check_error}")
                # If crash detection itself fails completely, it might indicate system instability
                if test_result:
                    send_sub_test_result_message(
                        test_result=test_result,
                        test_case_name=f"CRASH_DETECTION_ERROR_{test_case_name}_{node.name}",
                        test_status=TestStatus.FAILED,
                        test_message=f"Crash detection system failure: {check_error}",
                    )
                raise

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
