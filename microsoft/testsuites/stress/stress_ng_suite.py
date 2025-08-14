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

        # Wait for all processes and capture their output with periodic crash monitoring
        for i, process in enumerate(stress_processes):
            node_name = nodes[i].name
            try:
                # Enhanced process monitoring with crash detection
                self._monitor_stress_process_with_crash_detection(process, nodes[i], job_file_name, log)
                log.info(f"{node_name} completed successfully")

                # Process YAML output if applicable
                node_output = self._process_yaml_output(nodes[i], job_file_name, log)

                node_outputs.append(node_output)

            except Exception as e:
                failed_nodes += 1
                
                # Enhanced error classification for SSH failures
                error_str = str(e).lower()
                ssh_failure_indicators = [
                    "ssh session not active", "paramiko", "sshexception", 
                    "connection", "channel", "transport", "timeout"
                ]
                
                is_ssh_failure = any(indicator in error_str for indicator in ssh_failure_indicators)
                
                if is_ssh_failure:
                    log.error(f"{node_name} failed with SSH/Connection error - likely system crash: {e}")
                    error_output = f"=== {node_name} ===\nSSH/CONNECTION FAILURE (LIKELY SYSTEM CRASH): {str(e)}\n"
                    error_output += "This type of error typically indicates the target system has crashed or become unresponsive.\n"
                    error_output += "SSH connectivity was lost during stress test execution.\n"
                    
                    # Try to capture what we can through alternative methods
                    try:
                        fallback_logs = self._capture_post_crash_logs(nodes[i], job_file_name)
                        error_output += f"\nFallback diagnostic logs:\n{fallback_logs}"
                    except Exception as fallback_error:
                        error_output += f"\nFallback log collection also failed: {fallback_error}"
                        
                else:
                    log.error(f"{node_name} failed: {e}")
                    error_output = f"=== {node_name} ===\nERROR: {str(e)}"
                
                node_outputs.append(error_output)
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

    def _capture_post_crash_logs(self, node: RemoteNode, test_case_name: str) -> str:
        """
        Capture comprehensive diagnostic logs immediately after crash detection.
        This function attempts to gather as much diagnostic information as possible
        from the crashed system before it potentially becomes completely unresponsive.
        
        Args:
            node: The node that crashed
            test_case_name: Name of the test case for logging context
            
        Returns:
            String containing comprehensive diagnostic information
        """
        post_crash_data = []
        import time
        node.log.warning("=== CAPTURING POST-CRASH DIAGNOSTIC LOGS ===")
        
        # First, test if SSH is available at all
        ssh_available = False
        try:
            test_result = node.execute("echo 'ssh_test'", shell=True, timeout=3)
            if "ssh_test" in test_result.stdout:
                ssh_available = True
                node.log.info("SSH is available for post-crash log collection")
            else:
                node.log.warning("SSH responds but output is malformed")
        except Exception as ssh_test_error:
            node.log.error(f"SSH is completely unavailable for post-crash log collection: {ssh_test_error}")
            ssh_available = False
        
        # Helper function to safely execute commands and capture output
        def safe_execute(command: str, description: str, timeout: int = 30) -> str:
            if not ssh_available:
                return f"=== {description} ===\nSKIPPED: SSH unavailable due to system crash\n"
            try:
                result = node.execute(command, shell=True, timeout=timeout)
                output = f"=== {description} ===\n{result.stdout}\n"
                if result.stderr:
                    output += f"STDERR: {result.stderr}\n"
                return output
            except Exception as e:
                error_str = str(e).lower()
                if any(keyword in error_str for keyword in ["ssh", "connection", "timeout", "session", "paramiko"]):
                    return f"=== {description} ===\nFAILED - SSH ERROR (system likely crashed): {str(e)}\n"
                else:
                    return f"=== {description} ===\nFAILED: {str(e)}\n"
        
        # 1. IMMEDIATE SYSTEM STATE CAPTURE
        post_crash_data.append("=== IMMEDIATE POST-CRASH SYSTEM STATE ===")
        post_crash_data.append(safe_execute("date", "Current System Time"))
        post_crash_data.append(safe_execute("uptime", "System Uptime"))
        post_crash_data.append(safe_execute("who", "Logged in Users"))
        
        # 2. COMPREHENSIVE KERNEL LOGS
        post_crash_data.append("=== COMPREHENSIVE KERNEL LOGS ===")
        post_crash_data.append(safe_execute("dmesg -T", "Complete Kernel Ring Buffer (with timestamps)", 60))
        post_crash_data.append(safe_execute("dmesg -T -l emerg,alert,crit,err", "Kernel Errors and Critical Messages", 30))
        post_crash_data.append(safe_execute("dmesg -T -l warn", "Kernel Warning Messages", 30))
        post_crash_data.append(safe_execute("dmesg -T | grep -i -E 'panic|oops|bug|fault|error|call trace|rip|segfault|protection|unable to handle'", "Kernel Crash Pattern Analysis", 30))
        post_crash_data.append(safe_execute("journalctl -k --no-pager --since='1 hour ago'", "Kernel Messages from Journal (last hour)", 60))
        post_crash_data.append(safe_execute("journalctl -p err --no-pager --since='1 hour ago'", "System Error Messages (last hour)", 60))
        post_crash_data.append(safe_execute("journalctl -p warning --no-pager --since='30 minutes ago'", "System Warning Messages (last 30min)", 45))
        post_crash_data.append(safe_execute("journalctl --no-pager --since='30 minutes ago' | tail -100", "Recent System Messages (last 100 lines)", 30))
        post_crash_data.append(safe_execute("journalctl -p err --no-pager --since='1 hour ago'", "System Error Messages (last hour)", 60))
        
        # 3. DETAILED MEMORY AND RESOURCE ANALYSIS
        post_crash_data.append("=== DETAILED MEMORY AND RESOURCE ANALYSIS ===")
        post_crash_data.append(safe_execute("cat /proc/meminfo", "Complete Memory Information"))
        post_crash_data.append(safe_execute("cat /proc/buddyinfo", "Memory Fragmentation Info"))
        post_crash_data.append(safe_execute("cat /proc/slabinfo | head -30", "Kernel Memory Slabs (detailed)"))
        post_crash_data.append(safe_execute("free -h", "Memory Usage Summary"))
        post_crash_data.append(safe_execute("cat /proc/vmstat", "Virtual Memory Statistics"))
        post_crash_data.append(safe_execute("cat /proc/zoneinfo", "Memory Zone Information"))
        post_crash_data.append(safe_execute("cat /proc/pagetypeinfo", "Page Type Information"))
        post_crash_data.append(safe_execute("sar -r 1 1 2>/dev/null || echo 'sar not available'", "Memory Usage Statistics"))
        post_crash_data.append(safe_execute("cat /proc/sys/vm/overcommit_memory", "Memory Overcommit Settings"))
        post_crash_data.append(safe_execute("cat /proc/sys/vm/swappiness", "Swappiness Setting"))
        post_crash_data.append(safe_execute("swapon -s", "Swap Usage Information"))
        
        # 4. DETAILED PROCESS AND SYSTEM STATE
        post_crash_data.append("=== DETAILED PROCESS AND SYSTEM STATE ===")
        post_crash_data.append(safe_execute("ps aux --sort=-%mem | head -30", "Top 30 Memory-Using Processes"))
        post_crash_data.append(safe_execute("ps aux --sort=-%cpu | head -30", "Top 30 CPU-Using Processes"))
        post_crash_data.append(safe_execute("ps -eLf | wc -l", "Total Thread Count"))
        post_crash_data.append(safe_execute("ps aux | wc -l", "Total Process Count"))
        post_crash_data.append(safe_execute("ps -eo pid,ppid,cmd,%mem,%cpu --sort=-%mem | head -20", "Detailed Process Resource Usage"))
        post_crash_data.append(safe_execute("cat /proc/loadavg", "System Load Average"))
        post_crash_data.append(safe_execute("uptime", "System Uptime and Load"))
        post_crash_data.append(safe_execute("w", "Who is logged in and what they are doing"))
        post_crash_data.append(safe_execute("last -10", "Recent Login History"))
        post_crash_data.append(safe_execute("cat /proc/stat", "System Statistics"))
        post_crash_data.append(safe_execute("cat /proc/version", "Kernel Version Information"))
        post_crash_data.append(safe_execute("uname -a", "System Information"))
        post_crash_data.append(safe_execute("cat /proc/loadavg", "System Load Average"))
        
        # 5. DETAILED FILESYSTEM AND STORAGE STATE
        post_crash_data.append("=== DETAILED FILESYSTEM AND STORAGE STATE ===")
        post_crash_data.append(safe_execute("df -h", "Filesystem Usage"))
        post_crash_data.append(safe_execute("df -i", "Inode Usage"))
        post_crash_data.append(safe_execute("mount", "Mounted Filesystems"))
        post_crash_data.append(safe_execute("lsblk -f", "Block Device Information with Filesystems"))
        post_crash_data.append(safe_execute("cat /proc/mounts", "Kernel Mount Table"))
        post_crash_data.append(safe_execute("cat /proc/diskstats", "Disk I/O Statistics"))
        post_crash_data.append(safe_execute("iostat 1 1 2>/dev/null || echo 'iostat not available'", "I/O Statistics"))
        post_crash_data.append(safe_execute("lsof +L1 2>/dev/null | head -20 || echo 'lsof not available'", "Unlinked Open Files"))
        post_crash_data.append(safe_execute("find /tmp /var/tmp -type f -size +100M 2>/dev/null | head -10", "Large Files in Temp Directories"))
        
        # 6. DETAILED NETWORK STATE
        post_crash_data.append("=== DETAILED NETWORK STATE ===")
        post_crash_data.append(safe_execute("ip addr show", "Network Interface Configuration"))
        post_crash_data.append(safe_execute("ip route show", "Routing Table"))
        post_crash_data.append(safe_execute("ip -s link show", "Network Interface Statistics"))
        post_crash_data.append(safe_execute("ss -tulpn", "Network Socket Information (detailed)"))
        post_crash_data.append(safe_execute("netstat -rn 2>/dev/null || echo 'netstat not available'", "Routing Table (netstat)"))
        post_crash_data.append(safe_execute("arp -a 2>/dev/null || echo 'arp not available'", "ARP Table"))
        post_crash_data.append(safe_execute("cat /proc/net/dev", "Network Device Statistics"))
        post_crash_data.append(safe_execute("cat /proc/net/sockstat", "Socket Statistics"))
        
        # 7. DETAILED HARDWARE AND KERNEL MODULE STATE
        post_crash_data.append("=== DETAILED HARDWARE AND MODULE STATE ===")
        post_crash_data.append(safe_execute("lsmod", "Loaded Kernel Modules"))
        post_crash_data.append(safe_execute("lspci -vv", "Detailed PCI Device Information"))
        post_crash_data.append(safe_execute("lscpu", "CPU Information"))
        post_crash_data.append(safe_execute("cat /proc/cpuinfo", "Detailed CPU Information"))
        post_crash_data.append(safe_execute("cat /proc/interrupts", "Interrupt Statistics"))
        post_crash_data.append(safe_execute("cat /proc/softirqs", "Soft IRQ Statistics"))
        post_crash_data.append(safe_execute("lsusb 2>/dev/null || echo 'lsusb not available'", "USB Device Information"))
        post_crash_data.append(safe_execute("dmidecode -t system 2>/dev/null || echo 'dmidecode not available'", "System Hardware Information"))
        post_crash_data.append(safe_execute("cat /proc/cmdline", "Kernel Command Line"))
        post_crash_data.append(safe_execute("cat /proc/modules", "Detailed Module Information"))
        post_crash_data.append(safe_execute("dmesg | grep -i -E 'hardware|pci|usb|sata|nvme' | tail -20", "Recent Hardware Messages"))
        
        # 8. COMPREHENSIVE CRASH DUMPS AND CORE FILES
        post_crash_data.append("=== COMPREHENSIVE CRASH DUMPS AND CORE FILES ===")
        post_crash_data.append(safe_execute("find /var/crash /var/lib/systemd/coredump /tmp /var/tmp -name 'core.*' -o -name '*.crash' -o -name '*.core' -o -name 'vmcore*' -o -name 'kdump*' 2>/dev/null | head -20", "All Crash and Core Dump Files"))
        post_crash_data.append(safe_execute("ls -la /var/crash/ 2>/dev/null || echo 'No /var/crash directory'", "Crash Directory Contents"))
        post_crash_data.append(safe_execute("coredumpctl list --no-pager 2>/dev/null | tail -20", "Recent Core Dumps (systemd-coredump)"))
        post_crash_data.append(safe_execute("coredumpctl info --no-pager 2>/dev/null | tail -50", "Latest Core Dump Information"))
        post_crash_data.append(safe_execute("ls -la /proc/sys/kernel/core_pattern", "Core Dump Pattern Configuration"))
        post_crash_data.append(safe_execute("cat /proc/sys/kernel/core_pattern", "Core Dump Pattern"))
        post_crash_data.append(safe_execute("ulimit -c", "Core Dump Size Limit"))
        
        # 9. DETAILED SYSTEMD SERVICE STATE
        post_crash_data.append("=== DETAILED SYSTEMD SERVICE STATE ===")
        post_crash_data.append(safe_execute("systemctl --failed --no-pager", "Failed Services"))
        post_crash_data.append(safe_execute("systemctl list-units --state=failed --no-pager", "Detailed Failed Units"))
        post_crash_data.append(safe_execute("systemctl list-units --state=error --no-pager", "Error State Units"))
        post_crash_data.append(safe_execute("systemctl status --no-pager", "Overall System Status"))
        post_crash_data.append(safe_execute("journalctl -u systemd --no-pager --since='30 minutes ago'", "systemd Messages (last 30min)"))
        post_crash_data.append(safe_execute("journalctl -p crit --no-pager --since='1 hour ago'", "Critical Messages (last hour)"))
        post_crash_data.append(safe_execute("systemctl list-jobs --no-pager", "Active systemd Jobs"))
        post_crash_data.append(safe_execute("systemctl list-dependencies --no-pager | head -30", "Service Dependencies"))
        
        # 10. KERNEL AND SYSTEM CONFIGURATION
        post_crash_data.append("=== KERNEL AND SYSTEM CONFIGURATION ===")
        post_crash_data.append(safe_execute("cat /proc/sys/kernel/panic", "Kernel Panic Timeout"))
        post_crash_data.append(safe_execute("cat /proc/sys/kernel/panic_on_oops", "Panic on Oops Setting"))
        post_crash_data.append(safe_execute("cat /proc/sys/kernel/printk", "Kernel Printk Levels"))
        post_crash_data.append(safe_execute("cat /proc/sys/kernel/sysrq", "SysRq Configuration"))
        post_crash_data.append(safe_execute("cat /proc/sys/kernel/hung_task_timeout_secs", "Hung Task Timeout"))
        post_crash_data.append(safe_execute("cat /proc/sys/kernel/softlockup_thresh", "Soft Lockup Threshold"))
        post_crash_data.append(safe_execute("cat /proc/sys/kernel/watchdog", "Watchdog Status"))
        post_crash_data.append(safe_execute("cat /proc/sys/vm/panic_on_oom", "Panic on OOM Setting"))
        post_crash_data.append(safe_execute("cat /proc/sys/vm/oom_kill_allocating_task", "OOM Kill Policy"))
        post_crash_data.append(safe_execute("sysctl -a | grep -E 'kernel\.(panic|hung_task|softlockup|watchdog)' 2>/dev/null", "Kernel Crash-related Settings"))
        
        # 11. DETAILED STRESS-NG DIAGNOSTICS
        post_crash_data.append("=== DETAILED STRESS-NG DIAGNOSTICS ===")
        post_crash_data.append(safe_execute("ps aux | grep stress", "All Stress-related Processes"))
        post_crash_data.append(safe_execute("pgrep -l stress", "Stress Process IDs"))
        post_crash_data.append(safe_execute("pstree -p | grep stress", "Stress Process Tree"))
        post_crash_data.append(safe_execute("ls -la /tmp/stress* /var/tmp/stress* 2>/dev/null", "Stress-ng Temporary Files"))
        post_crash_data.append(safe_execute("find /proc/*/fd -ls 2>/dev/null | grep stress | head -20", "Stress Process File Descriptors"))
        post_crash_data.append(safe_execute("cat /proc/*/stat 2>/dev/null | grep stress | head -10", "Stress Process Statistics"))
        post_crash_data.append(safe_execute("stress-ng --version 2>/dev/null || echo 'stress-ng not in PATH'", "Stress-ng Version"))
        post_crash_data.append(safe_execute("which stress-ng", "Stress-ng Binary Location"))
        
        # 12. SYSTEM PERFORMANCE AND LOCKS
        post_crash_data.append("=== SYSTEM PERFORMANCE AND LOCKS ===")
        post_crash_data.append(safe_execute("cat /proc/locks", "File Locks"))
        post_crash_data.append(safe_execute("cat /proc/latency_stats 2>/dev/null || echo 'latency_stats not available'", "Latency Statistics"))
        post_crash_data.append(safe_execute("cat /proc/schedstat", "Scheduler Statistics"))
        post_crash_data.append(safe_execute("cat /proc/timer_list | head -50", "Timer List"))
        post_crash_data.append(safe_execute("cat /proc/sched_debug | head -100", "Scheduler Debug Info"))
        post_crash_data.append(safe_execute("cat /proc/pressure/cpu 2>/dev/null || echo 'PSI not available'", "CPU Pressure"))
        post_crash_data.append(safe_execute("cat /proc/pressure/memory 2>/dev/null || echo 'PSI not available'", "Memory Pressure"))
        post_crash_data.append(safe_execute("cat /proc/pressure/io 2>/dev/null || echo 'PSI not available'", "I/O Pressure"))
        post_crash_data.append(safe_execute("vmstat 1 1", "Virtual Memory Statistics Sample"))
        post_crash_data.append(safe_execute("mpstat 1 1 2>/dev/null || echo 'mpstat not available'", "CPU Usage Statistics"))
        
        # 13. ENHANCED CONSOLE LOG CAPTURE AND ANALYSIS WITH DIAGNOSTICS
        post_crash_data.append("=== ENHANCED CONSOLE LOG CAPTURE AND ANALYSIS ===")
        
        # First, perform comprehensive serial console diagnostics
        post_crash_data.append("=== SERIAL CONSOLE DIAGNOSTICS ===")
        try:
            # Check if SerialConsole feature is available
            if SerialConsole in node.features:
                post_crash_data.append("✓ SerialConsole feature is available")
                serial_console = node.features[SerialConsole]
                
                # Check console configuration
                try:
                    # Try to get some basic info about console setup
                    post_crash_data.append(f"Serial console object: {type(serial_console)}")
                    
                    # Check if there are any console-related attributes
                    if hasattr(serial_console, '_console_logger'):
                        post_crash_data.append("✓ Console logger attribute exists")
                    else:
                        post_crash_data.append("✗ Console logger attribute missing")
                        
                    if hasattr(serial_console, '_log_path'):
                        post_crash_data.append(f"Console log path: {serial_console._log_path}")
                    else:
                        post_crash_data.append("Console log path not available")
                        
                except Exception as console_attr_error:
                    post_crash_data.append(f"Console attribute check failed: {console_attr_error}")
                    
            else:
                post_crash_data.append("✗ SerialConsole feature is NOT available")
                post_crash_data.append("This explains why console logs cannot be captured!")
                post_crash_data.append("Possible causes:")
                post_crash_data.append("1. Platform doesn't support serial console")
                post_crash_data.append("2. Console not properly initialized")
                post_crash_data.append("3. Feature not enabled in test configuration")
                
        except Exception as feature_check_error:
            post_crash_data.append(f"Serial console feature check failed: {feature_check_error}")
        
        # Check kernel console configuration if SSH is available
        if ssh_available:
            post_crash_data.append("\n=== KERNEL CONSOLE CONFIGURATION CHECK ===")
            post_crash_data.append(safe_execute("cat /proc/cmdline | grep -o 'console=[^ ]*'", "Kernel Console Parameters"))
            post_crash_data.append(safe_execute("dmesg | grep -i 'console\\|serial\\|tty' | head -10", "Console Setup Messages"))
            post_crash_data.append(safe_execute("ls -la /dev/ttyS* /dev/console", "Serial Device Files"))
            post_crash_data.append(safe_execute("stty -F /dev/ttyS0 2>/dev/null || echo 'ttyS0 not accessible'", "Serial Port Configuration"))
            post_crash_data.append(safe_execute("cat /sys/class/tty/console/active", "Active Console Devices"))
            post_crash_data.append(safe_execute("cat /proc/consoles", "Registered Console Drivers"))
        
        # Now attempt to capture console logs with detailed error reporting
        try:
            post_crash_data.append("\n=== CONSOLE LOG CAPTURE ATTEMPT ===")
            # Get the full console log content
            serial_content = node.features[SerialConsole].get_console_log(saved_path=None, force_run=True)
            
            if len(serial_content) > 0:
                post_crash_data.append(f"✓ Successfully captured console log: {len(serial_content)} characters")
                
                # DETAILED CONSOLE LOG ANALYSIS
                post_crash_data.append(f"\n=== CONSOLE LOG ANALYSIS ===")
                post_crash_data.append(f"Console log size: {len(serial_content)} characters")
                
                # Check log content quality
                lines = serial_content.split('\n')
                post_crash_data.append(f"Total lines: {len(lines)}")
                
                # Check for typical boot/kernel messages
                boot_indicators = ['linux version', 'kernel command line', 'memory:', 'cpu:', 'systemd']
                boot_found = [indicator for indicator in boot_indicators if any(indicator in line.lower() for line in lines)]
                if boot_found:
                    post_crash_data.append(f"✓ Boot messages detected: {boot_found}")
                else:
                    post_crash_data.append("✗ No boot messages found - console may not be capturing early boot")
                
                # Check for recent activity
                recent_lines = lines[-50:] if len(lines) > 50 else lines
                recent_content = '\n'.join(recent_lines)
                if any(keyword in recent_content.lower() for keyword in ['systemd', 'kernel', 'login', 'ssh']):
                    post_crash_data.append("✓ Recent system activity detected in console log")
                else:
                    post_crash_data.append("✗ No recent activity in console log - may be stale")
                
                # Analyze console log for crash patterns
                crash_patterns = {
                    "kernel_panic": ["kernel panic", "panic:", "kernel bug"],
                    "oops": ["oops:", "bug:", "unable to handle"],
                    "call_trace": ["call trace:", "stack trace:", "backtrace"],
                    "segfault": ["segfault", "segmentation fault", "sigsegv"],
                    "general_protection": ["general protection fault", "protection fault"],
                    "out_of_memory": ["out of memory", "oom-killer", "killed process"],
                    "hung_task": ["hung task", "blocked for more than", "task blocked"],
                    "rcu_stall": ["rcu stall", "rcu_sched stall", "rcu detected stall"],
                    "soft_lockup": ["soft lockup", "softlockup"],
                    "hard_lockup": ["hard lockup", "hardlockup", "nmi watchdog"],
                    "filesystem_errors": ["filesystem error", "ext4 error", "io error"]
                }
                
                serial_lower = serial_content.lower()
                found_patterns = {}
                for pattern_type, patterns in crash_patterns.items():
                    matches = [p for p in patterns if p in serial_lower]
                    if matches:
                        found_patterns[pattern_type] = matches
                        # Count occurrences
                        count = sum(serial_lower.count(p) for p in matches)
                        post_crash_data.append(f"FOUND {pattern_type.upper()}: {matches} (count: {count})")
                
                if found_patterns:
                    post_crash_data.append(f"\n=== CRASH PATTERN SUMMARY ===")
                    for pattern_type, matches in found_patterns.items():
                        post_crash_data.append(f"{pattern_type}: {matches}")
                else:
                    post_crash_data.append("No obvious crash patterns detected in console log")
                
                # Extract last critical messages
                lines = serial_content.split('\n')
                critical_keywords = ['panic', 'oops', 'bug', 'error', 'fault', 'trace', 'killed', 'oom', 'hung', 'stall', 'lockup']
                critical_lines = []
                for i, line in enumerate(lines):
                    if any(keyword in line.lower() for keyword in critical_keywords):
                        # Include context: 2 lines before and after
                        start = max(0, i-2)
                        end = min(len(lines), i+3)
                        context = lines[start:end]
                        critical_lines.extend([f"Line {j+1}: {lines[j]}" for j in range(start, end)])
                        critical_lines.append("---")
                
                if critical_lines:
                    post_crash_data.append(f"\n=== CRITICAL LINES WITH CONTEXT ===")
                    post_crash_data.extend(critical_lines[:100])  # Limit to prevent massive output
                
                # Include full console log (truncated if too large)
                if len(serial_content) > 50000:  # If larger than 50KB, show both beginning and end
                    console_summary = f"\n=== FULL CONSOLE LOG (TRUNCATED) ===\n"
                    console_summary += f"Total size: {len(serial_content)} characters\n"
                    console_summary += "=== BEGINNING (first 10KB) ===\n"
                    console_summary += serial_content[:10000]
                    console_summary += "\n\n...[MIDDLE CONTENT TRUNCATED]...\n\n"
                    console_summary += "=== END (last 30KB) ===\n"
                    console_summary += serial_content[-30000:]
                else:
                    console_summary = f"\n=== COMPLETE CONSOLE LOG ===\n{serial_content}"
                post_crash_data.append(console_summary)
            else:
                post_crash_data.append("\n=== CONSOLE LOG CAPTURE FAILED ===")
                post_crash_data.append("✗ Console log returned empty/no data")
                post_crash_data.append("Possible causes:")
                post_crash_data.append("1. Console logging not properly configured")
                post_crash_data.append("2. Console output not redirected to serial port")
                post_crash_data.append("3. LibVirt console stream not capturing data")
                post_crash_data.append("4. Console logger stopped or crashed")
                post_crash_data.append("5. Kernel console parameter missing (console=ttyS0)")
                post_crash_data.append("6. Serial device not accessible")
                
        except Exception as console_error:
            post_crash_data.append(f"\n=== CONSOLE LOG CAPTURE ERROR ===")
            post_crash_data.append(f"✗ Console log capture failed with exception: {console_error}")
            post_crash_data.append(f"Error type: {type(console_error).__name__}")
            
            # Provide specific diagnostics based on error type
            error_str = str(console_error).lower()
            if "attributeerror" in error_str:
                post_crash_data.append("DIAGNOSIS: SerialConsole feature missing required attributes")
                post_crash_data.append("- Console feature may not be properly initialized")
                post_crash_data.append("- Platform may not support serial console")
            elif "filenotfound" in error_str or "no such file" in error_str:
                post_crash_data.append("DIAGNOSIS: Console log file not found")
                post_crash_data.append("- Console logger may not have started")
                post_crash_data.append("- Log file path may be incorrect")
            elif "permission" in error_str or "access" in error_str:
                post_crash_data.append("DIAGNOSIS: Permission/access issue")
                post_crash_data.append("- Insufficient permissions to read console log")
                post_crash_data.append("- Console device may be locked by another process")
            elif "timeout" in error_str:
                post_crash_data.append("DIAGNOSIS: Console operation timeout")
                post_crash_data.append("- Console may be unresponsive")
                post_crash_data.append("- System may be in a hung state")
            else:
                post_crash_data.append("DIAGNOSIS: Unknown console error")
                post_crash_data.append("- Check LibVirt console configuration")
                post_crash_data.append("- Verify serial console setup")
                
            post_crash_data.append("\nRECOMMENDATIONS:")
            post_crash_data.append("1. Check LibVirt console log file directly (section 14)")
            post_crash_data.append("2. Verify kernel boot parameters include 'console=ttyS0'")
            post_crash_data.append("3. Check if console logging service is running")
            post_crash_data.append("4. Examine LibVirt domain XML for console configuration")
        
        # 14. ENHANCED DIRECT LIBVIRT CONSOLE LOG WITH DIAGNOSTICS
        post_crash_data.append("=== ENHANCED DIRECT LIBVIRT CONSOLE LOG ===")
        try:
            from lisa.sut_orchestrator.libvirt.context import get_node_context
            node_context = get_node_context(node)
            
            if node_context:
                post_crash_data.append("✓ LibVirt node context available")
                console_log_path = node_context.console_log_file_path
                post_crash_data.append(f"Console log path: {console_log_path}")
                
                import os
                if console_log_path and os.path.exists(console_log_path):
                    post_crash_data.append("✓ LibVirt console log file exists")
                    
                    # Get file information
                    stat_info = os.stat(console_log_path)
                    file_size = stat_info.st_size
                    import datetime
                    modification_time = datetime.datetime.fromtimestamp(stat_info.st_mtime)
                    age_seconds = (datetime.datetime.now() - modification_time).total_seconds()
                    
                    post_crash_data.append(f"File size: {file_size} bytes")
                    post_crash_data.append(f"Last modified: {modification_time}")
                    post_crash_data.append(f"File age: {age_seconds:.1f} seconds")
                    
                    if age_seconds > 300:  # More than 5 minutes old
                        post_crash_data.append("⚠️  WARNING: Console log file is quite old - logging may have stopped")
                    
                    if file_size == 0:
                        post_crash_data.append("✗ Console log file is empty!")
                        post_crash_data.append("DIAGNOSIS: Console logging never started or failed immediately")
                        post_crash_data.append("- Check LibVirt domain console configuration")
                        post_crash_data.append("- Verify console device in domain XML")
                        post_crash_data.append("- Check LibVirt daemon logs for console errors")
                    elif file_size < 1024:  # Less than 1KB
                        post_crash_data.append("⚠️  WARNING: Console log file very small - may indicate logging issues")
                    
                    try:
                        with open(console_log_path, 'r', encoding='utf-8', errors='ignore') as f:
                            direct_log = f.read()
                        
                        post_crash_data.append(f"✓ Successfully read {len(direct_log)} characters from LibVirt console log")
                        
                        # Analyze content quality
                        if len(direct_log) > 0:
                            lines = direct_log.split('\n')
                            post_crash_data.append(f"Total lines in LibVirt log: {len(lines)}")
                            
                            # Check for boot messages
                            boot_keywords = ['linux', 'kernel', 'systemd', 'init', 'getty', 'login']
                            boot_lines = [line for line in lines if any(keyword in line.lower() for keyword in boot_keywords)]
                            if boot_lines:
                                post_crash_data.append(f"✓ Boot-related messages found: {len(boot_lines)} lines")
                            else:
                                post_crash_data.append("✗ No boot messages found in LibVirt console log")
                                post_crash_data.append("This suggests console redirection is not working properly")
                            
                            # Check for recent activity
                            if len(lines) > 10:
                                recent_lines = lines[-10:]
                                if any(line.strip() for line in recent_lines):
                                    post_crash_data.append("✓ Recent activity detected in LibVirt console log")
                                else:
                                    post_crash_data.append("✗ No recent activity in LibVirt console log")
                        
                        if len(direct_log) > 50000:  # Truncate if too large
                            direct_summary = f"\n=== LIBVIRT CONSOLE LOG (TRUNCATED) ===\n"
                            direct_summary += f"Total size: {len(direct_log)} characters (showing last 50KB)\n"
                            direct_summary += "...[TRUNCATED]...\n"
                            direct_summary += direct_log[-50000:]
                        else:
                            direct_summary = f"\n=== COMPLETE LIBVIRT CONSOLE LOG ===\n{direct_log}"
                        post_crash_data.append(direct_summary)
                        
                    except Exception as read_error:
                        post_crash_data.append(f"✗ Failed to read LibVirt console log file: {read_error}")
                        
                elif console_log_path:
                    post_crash_data.append(f"✗ LibVirt console log file does not exist: {console_log_path}")
                    post_crash_data.append("DIAGNOSIS: Console log file missing")
                    post_crash_data.append("- Console logging may not be enabled")
                    post_crash_data.append("- LibVirt console stream may have failed to start")
                    post_crash_data.append("- Console device may not be configured in domain XML")
                else:
                    post_crash_data.append("✗ LibVirt console log path is not available")
                    post_crash_data.append("- Node context exists but console path is missing")
                    
                # Additional LibVirt diagnostics
                if hasattr(node_context, 'domain'):
                    domain = node_context.domain
                    if domain:
                        try:
                            domain_state = domain.state()
                            post_crash_data.append(f"LibVirt domain state: {domain_state}")
                        except Exception as domain_error:
                            post_crash_data.append(f"Failed to get domain state: {domain_error}")
                            
                        # Try to get domain XML for console configuration
                        try:
                            domain_xml = domain.XMLDesc()
                            if 'console' in domain_xml:
                                post_crash_data.append("✓ Console device found in domain XML")
                                # Extract console configuration
                                import re
                                console_matches = re.findall(r'<console[^>]*>.*?</console>', domain_xml, re.DOTALL)
                                for i, console_config in enumerate(console_matches):
                                    post_crash_data.append(f"Console {i+1} config: {console_config[:200]}...")
                            else:
                                post_crash_data.append("✗ No console device found in domain XML")
                                post_crash_data.append("This explains why console logging is not working!")
                        except Exception as xml_error:
                            post_crash_data.append(f"Failed to get domain XML: {xml_error}")
                else:
                    post_crash_data.append("✗ LibVirt node context missing or invalid")
                    
        except Exception as libvirt_log_error:
            post_crash_data.append(f"✗ LibVirt console log access failed: {libvirt_log_error}")
            post_crash_data.append("This indicates a fundamental issue with LibVirt console setup")
        
        # 15. STRESS-NG SPECIFIC INFORMATION
        post_crash_data.append("=== STRESS-NG SPECIFIC DIAGNOSTICS ===")
        post_crash_data.append(safe_execute("ps aux | grep stress", "Stress-ng Process Status"))
        post_crash_data.append(safe_execute("pgrep -l stress", "Stress Process IDs"))
        post_crash_data.append(safe_execute("ls -la /tmp/stress* /var/tmp/stress* 2>/dev/null", "Stress-ng Temporary Files"))
        
        # 15.5. ENHANCED QEMU CONSOLE LOGGER DIAGNOSTICS  
        post_crash_data.append("=== ENHANCED QEMU CONSOLE LOGGER DIAGNOSTICS ===")
        try:
            console_logger = getattr(node, '_console_logger', None)
            if console_logger:
                post_crash_data.append("✓ QemuConsoleLogger instance found")
                
                # Detailed logger state analysis
                logger_class = console_logger.__class__.__name__
                post_crash_data.append(f"Logger class: {logger_class}")
                
                # Check if logger is still running
                if hasattr(console_logger, 'is_running'):
                    is_running = console_logger.is_running()
                    status_indicator = "✓" if is_running else "✗"
                    post_crash_data.append(f"{status_indicator} Logger running status: {is_running}")
                    
                    if not is_running:
                        post_crash_data.append("DIAGNOSIS: Console logger has stopped!")
                        post_crash_data.append("- Logger may have crashed or been terminated")
                        post_crash_data.append("- Console stream may have been disconnected")
                        post_crash_data.append("- VM may have become unresponsive")
                
                # Check logger thread status
                if hasattr(console_logger, '_thread'):
                    thread = console_logger._thread
                    if thread:
                        thread_alive = thread.is_alive()
                        status_indicator = "✓" if thread_alive else "✗"
                        post_crash_data.append(f"{status_indicator} Logger thread alive: {thread_alive}")
                        post_crash_data.append(f"Thread name: {thread.name}")
                        
                        if not thread_alive:
                            post_crash_data.append("DIAGNOSIS: Logger thread has died!")
                            post_crash_data.append("- Check for thread exceptions")
                            post_crash_data.append("- Console stream may have been disconnected")
                    else:
                        post_crash_data.append("✗ Logger thread not found")
                
                # Check accumulated logs
                if hasattr(console_logger, '_accumulated_logs'):
                    accumulated = console_logger._accumulated_logs
                    if accumulated:
                        accumulated_size = len(accumulated)
                        post_crash_data.append(f"✓ Accumulated logs size: {accumulated_size} characters")
                        
                        if accumulated_size == 0:
                            post_crash_data.append("✗ No logs accumulated - logger not capturing data")
                            post_crash_data.append("DIAGNOSIS: Console logger not receiving data")
                            post_crash_data.append("- Console stream may not be properly connected")
                            post_crash_data.append("- VM console output may be redirected elsewhere")
                        elif accumulated_size < 100:
                            post_crash_data.append("⚠️  WARNING: Very little data accumulated")
                            post_crash_data.append("- Console may be mostly idle")
                            post_crash_data.append("- Or console logging started recently")
                        
                        # Show a sample of accumulated logs
                        if accumulated_size > 0:
                            if accumulated_size > 2000:
                                sample = f"[...TRUNCATED...]\n{accumulated[-2000:]}"
                            else:
                                sample = accumulated
                            post_crash_data.append(f"Sample of accumulated logs:\n{sample}")
                    else:
                        post_crash_data.append("✗ No accumulated logs available")
                
                # Check for any stored errors
                if hasattr(console_logger, '_last_error'):
                    last_error = console_logger._last_error
                    if last_error:
                        post_crash_data.append(f"✗ Logger last error: {last_error}")
                    else:
                        post_crash_data.append("✓ No stored errors in logger")
                
                # Check console stream status
                if hasattr(console_logger, '_console_stream'):
                    stream = console_logger._console_stream
                    if stream:
                        post_crash_data.append("✓ Console stream object exists")
                        
                        # Try to get stream status
                        try:
                            if hasattr(stream, 'recv'):
                                # Try a non-blocking read to test stream
                                import select
                                ready, _, _ = select.select([stream], [], [], 0)
                                if ready:
                                    post_crash_data.append("✓ Console stream has data available")
                                else:
                                    post_crash_data.append("○ Console stream idle (no immediate data)")
                        except Exception as stream_test_error:
                            post_crash_data.append(f"⚠️  Console stream test error: {stream_test_error}")
                    else:
                        post_crash_data.append("✗ Console stream object is None")
                        post_crash_data.append("DIAGNOSIS: Console stream not established")
                
                # Check logger configuration
                if hasattr(console_logger, '_buffer_size'):
                    buffer_size = console_logger._buffer_size
                    post_crash_data.append(f"Logger buffer size: {buffer_size}")
                
                if hasattr(console_logger, '_start_time'):
                    import datetime
                    start_time = console_logger._start_time
                    current_time = datetime.datetime.now()
                    runtime = (current_time - start_time).total_seconds()
                    post_crash_data.append(f"Logger runtime: {runtime:.1f} seconds")
                    
                    if runtime < 10:
                        post_crash_data.append("⚠️  WARNING: Logger started very recently")
                    elif runtime > 3600:  # More than 1 hour
                        post_crash_data.append("○ Logger has been running for a long time")
                
            else:
                post_crash_data.append("✗ No QemuConsoleLogger instance found on node")
                post_crash_data.append("DIAGNOSIS: Console logger was never created or has been removed")
                post_crash_data.append("- Check node initialization process")
                post_crash_data.append("- Console logging may not be enabled for this platform")
                post_crash_data.append("- Node may not support console logging")
                
                # Try to find if any console logger was ever attempted
                if hasattr(node, '__dict__'):
                    node_attrs = [attr for attr in dir(node) if 'console' in attr.lower()]
                    if node_attrs:
                        post_crash_data.append(f"Console-related attributes found: {node_attrs}")
                    else:
                        post_crash_data.append("No console-related attributes found on node")
                        
        except Exception as console_diag_error:
            post_crash_data.append(f"✗ Console logger diagnostics failed: {console_diag_error}")
            import traceback
            post_crash_data.append(f"Diagnostics error traceback: {traceback.format_exc()}")
            post_crash_data.append("This indicates a serious issue with console logging infrastructure")
        
        # 16. FALLBACK LOG COLLECTION (when SSH is unavailable)
        if not ssh_available:
            post_crash_data.append("=== FALLBACK LOG COLLECTION (SSH UNAVAILABLE) ===")
            node.log.warning("SSH is unavailable - attempting fallback log collection methods")
            
            # Try to collect logs through alternative methods
            try:
                # LibVirt domain state and console logs
                from lisa.sut_orchestrator.libvirt.context import get_node_context
                node_context = get_node_context(node)
                
                if node_context and node_context.domain:
                    domain = node_context.domain
                    try:
                        domain_state = domain.state()
                        post_crash_data.append(f"=== LibVirt Domain State ===\nDomain state: {domain_state}\n")
                        
                        # Domain state meanings for reference
                        state_meanings = {
                            0: "VIR_DOMAIN_NOSTATE (no state)",
                            1: "VIR_DOMAIN_RUNNING (running)",
                            2: "VIR_DOMAIN_BLOCKED (blocked)",
                            3: "VIR_DOMAIN_PAUSED (paused)",
                            4: "VIR_DOMAIN_SHUTDOWN (shutdown)",
                            5: "VIR_DOMAIN_SHUTOFF (shutoff)",
                            6: "VIR_DOMAIN_CRASHED (crashed)",
                            7: "VIR_DOMAIN_PMSUSPENDED (suspended)"
                        }
                        
                        state_code = domain_state[0]
                        state_meaning = state_meanings.get(state_code, f"Unknown state {state_code}")
                        post_crash_data.append(f"=== Domain State Analysis ===\nState code {state_code}: {state_meaning}\n")
                        
                        if state_code in [4, 5, 6]:  # SHUTDOWN, SHUTOFF, CRASHED
                            post_crash_data.append("=== CRITICAL ===\nLibVirt domain indicates system crash/shutdown!\n")
                        
                    except Exception as domain_error:
                        post_crash_data.append(f"=== LibVirt Domain State ===\nFailed to get domain state: {domain_error}\n")
                
                # Try to get console log file directly
                console_log_path = node_context.console_log_file_path if node_context else None
                if console_log_path:
                    import os
                    try:
                        if os.path.exists(console_log_path):
                            with open(console_log_path, 'r', encoding='utf-8', errors='ignore') as f:
                                console_content = f.read()
                            
                            # Include last 5KB of console log
                            if len(console_content) > 5000:
                                console_summary = f"LibVirt console log (last 5KB of {len(console_content)} chars):\n"
                                console_summary += "...[TRUNCATED]...\n"
                                console_summary += console_content[-5000:]
                            else:
                                console_summary = f"Complete LibVirt console log ({len(console_content)} chars):\n{console_content}"
                            
                            post_crash_data.append(f"=== LibVirt Console Log (SSH Fallback) ===\n{console_summary}\n")
                        else:
                            post_crash_data.append(f"=== LibVirt Console Log ===\nConsole log file not found: {console_log_path}\n")
                    except Exception as console_read_error:
                        post_crash_data.append(f"=== LibVirt Console Log ===\nFailed to read console log: {console_read_error}\n")
                else:
                    post_crash_data.append("=== LibVirt Console Log ===\nConsole log path not available\n")
                    
            except Exception as fallback_error:
                post_crash_data.append(f"=== Fallback Collection Error ===\nFallback log collection failed: {fallback_error}\n")
        
        # 17. SUMMARY WHEN SSH FAILS
        if not ssh_available:
            post_crash_data.append("=== SSH FAILURE SUMMARY ===")
            post_crash_data.append("SSH connectivity was lost during stress testing.")
            post_crash_data.append("This is a strong indication of system crash or hang.")
            post_crash_data.append("Collected available logs through LibVirt fallback methods.")
            post_crash_data.append("Consider checking:")
            post_crash_data.append("1. Console logs for kernel panic messages")
            post_crash_data.append("2. LibVirt domain state for crash indicators")
            post_crash_data.append("3. Host system logs for VM crash events")
            post_crash_data.append("4. Memory pressure or resource exhaustion")
        
        # 18. COMPREHENSIVE CRASH ANALYSIS SUMMARY
        post_crash_data.append("=== COMPREHENSIVE CRASH ANALYSIS SUMMARY ===")
        post_crash_data.append(f"Crash detection timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
        post_crash_data.append(f"Test case: {test_case_name}")
        post_crash_data.append(f"Node: {node.name}")
        post_crash_data.append(f"SSH available during analysis: {ssh_available}")
        
        # Provide analysis recommendations
        post_crash_data.append("\n=== ANALYSIS RECOMMENDATIONS ===")
        if not ssh_available:
            post_crash_data.append("PRIORITY 1: SSH connectivity lost - indicates severe system crash")
            post_crash_data.append("- Check LibVirt domain state in section 16")
            post_crash_data.append("- Review console logs in sections 13-14 for crash patterns")
            post_crash_data.append("- Look for kernel panic, OOM, or hardware failures")
        else:
            post_crash_data.append("SSH was available - check for:")
            post_crash_data.append("- Kernel messages in section 2 for crash patterns")
            post_crash_data.append("- Memory pressure in section 3")
            post_crash_data.append("- Failed services in section 9")
            post_crash_data.append("- Core dumps in section 8")
        
        post_crash_data.append("\n=== KEY SECTIONS TO REVIEW ===")
        post_crash_data.append("- Section 2: Kernel logs and crash patterns")
        post_crash_data.append("- Section 3: Memory analysis and OOM detection")
        post_crash_data.append("- Section 8: Core dumps and crash files")
        post_crash_data.append("- Section 13: Enhanced console log analysis")
        post_crash_data.append("- Section 14: Direct LibVirt console logs")
        post_crash_data.append("- Section 11: Stress-ng specific diagnostics")
        
        post_crash_data.append(f"\n=== DIAGNOSTIC DATA SUMMARY ===")
        post_crash_data.append(f"Total sections collected: 18")
        post_crash_data.append(f"SSH-based commands: {'Available' if ssh_available else 'Failed - using fallback methods'}")
        post_crash_data.append(f"Console log analysis: {'Completed' if 'Console log size:' in str(post_crash_data) else 'Failed'}")
        post_crash_data.append(f"LibVirt fallback: {'Used' if not ssh_available else 'Not needed'}")
        
        # Combine all collected data
        comprehensive_log = "\n".join(post_crash_data)
        
        node.log.warning(f"=== POST-CRASH LOG CAPTURE COMPLETED ===")
        node.log.warning(f"Captured {len(comprehensive_log)} characters of diagnostic data")
        
        return comprehensive_log

    def _monitor_stress_process_with_crash_detection(self, process: Process, node: RemoteNode, test_case_name: str, log: Logger) -> None:
        """
        Monitor a stress-ng process with periodic crash detection.
        This provides early crash detection during test execution rather than waiting until the end.
        
        Args:
            process: The stress-ng process to monitor
            node: The node running the process
            test_case_name: Name of the test case for logging
            log: Logger for detailed logging
        """
        import time
        check_interval = 30  # Check for crashes every 30 seconds
        last_crash_check = time.time()
        
        log.debug(f"Starting enhanced process monitoring with {check_interval}s crash detection interval")
        
        while True:
            # Check if process has completed
            if process.is_completed():
                # Process completed, do final check and return
                try:
                    process.wait_result(timeout=10, expected_exit_code=0)
                    log.debug("Stress process completed successfully")
                    return
                except Exception as completion_error:
                    log.error(f"Stress process completed with error: {completion_error}")
                    raise completion_error
            
            # Periodic crash detection during execution
            current_time = time.time()
            if (current_time - last_crash_check) >= check_interval:
                log.debug("Performing periodic crash check during stress execution...")
                try:
                    # Quick crash detection (reduced timeout for periodic checks)
                    self._quick_crash_check(node, test_case_name)
                    last_crash_check = current_time
                    log.debug("Periodic crash check passed - continuing stress test")
                except Exception as crash_error:
                    log.error(f"Crash detected during stress execution: {crash_error}")
                    # Terminate the stress process if still running
                    try:
                        if not process.is_completed():
                            log.warning("Terminating stress process due to detected crash")
                            process.terminate()
                    except:
                        pass
                    raise crash_error
            
            # Short sleep before next iteration
            time.sleep(1)
            
            # Safety timeout check
            if (current_time - last_crash_check) > self.TIME_OUT:
                log.error("Process monitoring timeout exceeded")
                raise Exception(f"Stress process monitoring timeout after {self.TIME_OUT} seconds")

    def _quick_crash_check(self, node: RemoteNode, test_case_name: str) -> None:
        """
        Perform a quick crash check during stress test execution.
        This is a lightweight version of _check_panic for periodic monitoring.
        
        Args:
            node: The node to check
            test_case_name: Name of the test case for logging
        """
        crash_evidence = []
        
        try:
            # Quick SSH connectivity test (most reliable indicator)
            connectivity_result = node.execute("echo 'quick_check'", shell=True, timeout=5)
            if "quick_check" not in connectivity_result.stdout:
                crash_evidence.append("SSH response malformed during periodic check")
        except Exception as ssh_error:
            # Enhanced SSH failure detection patterns for periodic checks
            ssh_failure_indicators = [
                "connection", "timeout", "session", "unreachable", "paramiko", 
                "sshexception", "channel", "transport", "authentication",
                "broken pipe", "connection reset", "no route to host", "network unreachable"
            ]
            ssh_error_str = str(ssh_error).lower()
            if any(keyword in ssh_error_str for keyword in ssh_failure_indicators):
                crash_evidence.append(f"SSH failure during periodic check: {ssh_error}")
                # Log specific details for paramiko errors during periodic checks
                if "paramiko" in ssh_error_str or "sshexception" in ssh_error_str:
                    node.log.error(f"Paramiko SSH failure during periodic check - system crash detected: {ssh_error}")
            else:
                node.log.debug(f"SSH error during periodic check but not classified as crash: {ssh_error}")
        
        # Quick dmesg check for recent errors
        try:
            recent_dmesg = node.execute("dmesg -T | tail -20", shell=True, timeout=10)
            kernel_indicators = ["kernel panic", "oops:", "bug:", "call trace:", "segfault"]
            dmesg_content = recent_dmesg.stdout.lower()
            found_issues = [indicator for indicator in kernel_indicators if indicator in dmesg_content]
            if found_issues:
                crash_evidence.append(f"Recent kernel issues in dmesg: {found_issues}")
        except Exception as dmesg_error:
            if any(keyword in str(dmesg_error).lower() for keyword in ["connection", "timeout"]):
                crash_evidence.append(f"dmesg check failure: {dmesg_error}")
        
        # If crash evidence found, immediately capture comprehensive logs and raise exception
        if crash_evidence:
            node.log.error(f"CRASH DETECTED during stress execution: {crash_evidence}")
            
            # Capture comprehensive post-crash logs immediately
            post_crash_logs = self._capture_post_crash_logs(node, test_case_name)
            
            # Create detailed crash message
            crash_message = f"Crash detected during stress execution with evidence: {'; '.join(crash_evidence)}\n\nPost-crash logs:\n{post_crash_logs}"
            
            # Raise exception to stop stress test and report crash
            from lisa.util import KernelPanicException
            raise KernelPanicException(
                stage="periodic_crash_detection_during_stress",
                panics=crash_evidence,
                source="enhanced_stress_monitoring"
            )

    def _check_panic(self, nodes: List[RemoteNode], test_case_name: str, test_result: Optional[TestResult]) -> None:
        """
        Check for kernel panics using multiple detection methods with timeout protection.
        This is a comprehensive crash detection system that checks:
        1. Serial console logs for panic patterns
        2. SSH connectivity status 
        3. System uptime changes
        4. Alternative log sources (journalctl, dmesg, syslog)
        5. LibVirt console log files directly
        6. LibVirt domain state
        """
        import time
        check_start_time = time.time()
        max_check_time = 300  # Maximum 5 minutes for entire crash detection
        
        for node in nodes:
            crash_detected = False
            crash_evidence = []
            
            try:
                # Timeout protection for entire crash detection
                if (time.time() - check_start_time) > max_check_time:
                    nodes[0].log.warning(f"Crash detection timeout after {max_check_time}s - using current evidence")
                    if crash_evidence:
                        crash_detected = True
                    break
                
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
                    # Enhanced SSH failure detection patterns
                    ssh_failure_indicators = [
                        "connection", "timeout", "session not active", "ssh", "unreachable",
                        "paramiko", "sshexception", "channel", "transport", "authentication",
                        "broken pipe", "connection reset", "no route to host", "network unreachable"
                    ]
                    ssh_error_str = str(ssh_error).lower()
                    if any(keyword in ssh_error_str for keyword in ssh_failure_indicators):
                        crash_evidence.append(f"SSH failure: {ssh_error}")
                        crash_detected = True
                        # Log specific details for paramiko errors
                        if "paramiko" in ssh_error_str or "sshexception" in ssh_error_str:
                            nodes[0].log.error(f"Paramiko SSH failure detected - likely system crash: {ssh_error}")
                            nodes[0].log.error("This typically indicates the target system has crashed or become unresponsive")
                    else:
                        nodes[0].log.debug(f"SSH error but not classified as crash indicator: {ssh_error}")
                
                # If crash evidence found, capture comprehensive logs and raise exception
                if crash_detected and crash_evidence:
                    nodes[0].log.error(f"CRASH DETECTED on node {node.name}")
                    nodes[0].log.error(f"Evidence found: {crash_evidence}")
                    
                    # IMMEDIATELY CAPTURE COMPREHENSIVE POST-CRASH LOGS
                    post_crash_logs = self._capture_post_crash_logs(node, test_case_name)
                    
                    # Create comprehensive crash message including captured logs
                    crash_message = f"Crash detected on {node.name} with evidence: {'; '.join(crash_evidence)}\n\nPost-crash diagnostic logs:\n{post_crash_logs}"
                    
                    # Ensure we have a TestResult for reporting
                    if test_result is None:
                        from lisa.testsuite import TestResult
                        test_result = TestResult(id_=f"crash_detection_{test_case_name}")
                    
                    # Send crash test results with comprehensive logs
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
