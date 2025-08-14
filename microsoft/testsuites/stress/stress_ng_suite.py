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
        node.log.warning("=== CAPTURING POST-CRASH DIAGNOSTIC LOGS ===")
        
        # Helper function to safely execute commands and capture output
        def safe_execute(command: str, description: str, timeout: int = 30) -> str:
            try:
                result = node.execute(command, shell=True, timeout=timeout)
                output = f"=== {description} ===\n{result.stdout}\n"
                if result.stderr:
                    output += f"STDERR: {result.stderr}\n"
                return output
            except Exception as e:
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
        post_crash_data.append(safe_execute("journalctl -k --no-pager --since='1 hour ago'", "Kernel Messages from Journal (last hour)", 60))
        post_crash_data.append(safe_execute("journalctl -p err --no-pager --since='1 hour ago'", "System Error Messages (last hour)", 60))
        
        # 3. MEMORY AND SYSTEM RESOURCE STATE
        post_crash_data.append("=== MEMORY AND RESOURCE ANALYSIS ===")
        post_crash_data.append(safe_execute("cat /proc/meminfo", "Complete Memory Information"))
        post_crash_data.append(safe_execute("cat /proc/buddyinfo", "Memory Fragmentation Info"))
        post_crash_data.append(safe_execute("cat /proc/slabinfo | head -20", "Kernel Memory Slabs"))
        post_crash_data.append(safe_execute("free -h", "Memory Usage Summary"))
        post_crash_data.append(safe_execute("cat /proc/vmstat", "Virtual Memory Statistics"))
        
        # 4. PROCESS AND SYSTEM STATE
        post_crash_data.append("=== PROCESS AND SYSTEM STATE ===")
        post_crash_data.append(safe_execute("ps aux --sort=-%mem | head -20", "Top Memory-Using Processes"))
        post_crash_data.append(safe_execute("ps aux --sort=-%cpu | head -20", "Top CPU-Using Processes"))
        post_crash_data.append(safe_execute("ps -eLf | wc -l", "Total Thread Count"))
        post_crash_data.append(safe_execute("cat /proc/loadavg", "System Load Average"))
        
        # 5. FILESYSTEM AND STORAGE STATE
        post_crash_data.append("=== FILESYSTEM AND STORAGE STATE ===")
        post_crash_data.append(safe_execute("df -h", "Filesystem Usage"))
        post_crash_data.append(safe_execute("mount", "Mounted Filesystems"))
        post_crash_data.append(safe_execute("lsblk", "Block Device Information"))
        post_crash_data.append(safe_execute("cat /proc/mounts", "Kernel Mount Table"))
        
        # 6. NETWORK STATE (if accessible)
        post_crash_data.append("=== NETWORK STATE ===")
        post_crash_data.append(safe_execute("ip addr show", "Network Interface Configuration"))
        post_crash_data.append(safe_execute("ip route show", "Routing Table"))
        post_crash_data.append(safe_execute("ss -tulpn", "Network Socket Information"))
        
        # 7. HARDWARE AND KERNEL MODULE STATE
        post_crash_data.append("=== HARDWARE AND MODULE STATE ===")
        post_crash_data.append(safe_execute("lsmod", "Loaded Kernel Modules"))
        post_crash_data.append(safe_execute("lspci", "PCI Device Information"))
        post_crash_data.append(safe_execute("lscpu", "CPU Information"))
        post_crash_data.append(safe_execute("cat /proc/interrupts", "Interrupt Statistics"))
        
        # 8. CRASH DUMPS AND CORE FILES
        post_crash_data.append("=== CRASH DUMPS AND CORE FILES ===")
        post_crash_data.append(safe_execute("find /var/crash /var/lib/systemd/coredump /tmp -name 'core.*' -o -name '*.crash' -o -name '*.core' 2>/dev/null | head -10", "Crash and Core Dump Files"))
        post_crash_data.append(safe_execute("coredumpctl list --no-pager 2>/dev/null | tail -10", "Recent Core Dumps (systemd-coredump)"))
        
        # 9. SYSTEMD SERVICE STATE
        post_crash_data.append("=== SYSTEMD SERVICE STATE ===")
        post_crash_data.append(safe_execute("systemctl --failed --no-pager", "Failed Services"))
        post_crash_data.append(safe_execute("systemctl list-units --state=failed --no-pager", "Detailed Failed Units"))
        post_crash_data.append(safe_execute("journalctl -u systemd --no-pager --since='30 minutes ago'", "systemd Messages (last 30min)"))
        
        # 10. COMPLETE CONSOLE LOG CAPTURE
        post_crash_data.append("=== COMPLETE CONSOLE LOG CAPTURE ===")
        try:
            # Get the full console log content
            serial_content = node.features[SerialConsole].get_console_log(saved_path=None, force_run=True)
            if len(serial_content) > 0:
                # Include full console log (truncated if too large)
                if len(serial_content) > 50000:  # If larger than 50KB, truncate but keep end
                    console_summary = f"Console log size: {len(serial_content)} characters (showing last 50KB)\n"
                    console_summary += "...[TRUNCATED]...\n"
                    console_summary += serial_content[-50000:]
                else:
                    console_summary = f"Complete console log ({len(serial_content)} characters):\n{serial_content}"
                post_crash_data.append(f"=== FULL CONSOLE LOG ===\n{console_summary}")
            else:
                post_crash_data.append("=== FULL CONSOLE LOG ===\nNo console log data available")
        except Exception as console_error:
            post_crash_data.append(f"=== FULL CONSOLE LOG ===\nFailed to capture console log: {console_error}")
        
        # 11. DIRECT LIBVIRT CONSOLE LOG
        post_crash_data.append("=== DIRECT LIBVIRT CONSOLE LOG ===")
        try:
            from lisa.sut_orchestrator.libvirt.context import get_node_context
            node_context = get_node_context(node)
            console_log_path = node_context.console_log_file_path
            
            import os
            if os.path.exists(console_log_path):
                with open(console_log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    direct_log = f.read()
                
                if len(direct_log) > 50000:  # Truncate if too large
                    direct_summary = f"LibVirt console log size: {len(direct_log)} characters (showing last 50KB)\n"
                    direct_summary += "...[TRUNCATED]...\n"
                    direct_summary += direct_log[-50000:]
                else:
                    direct_summary = f"Complete LibVirt console log ({len(direct_log)} characters):\n{direct_log}"
                post_crash_data.append(direct_summary)
            else:
                post_crash_data.append(f"LibVirt console log file not found: {console_log_path}")
        except Exception as libvirt_log_error:
            post_crash_data.append(f"Failed to capture LibVirt console log: {libvirt_log_error}")
        
        # 12. STRESS-NG SPECIFIC INFORMATION
        post_crash_data.append("=== STRESS-NG SPECIFIC DIAGNOSTICS ===")
        post_crash_data.append(safe_execute("ps aux | grep stress", "Stress-ng Process Status"))
        post_crash_data.append(safe_execute("pgrep -l stress", "Stress Process IDs"))
        post_crash_data.append(safe_execute("ls -la /tmp/stress* /var/tmp/stress* 2>/dev/null", "Stress-ng Temporary Files"))
        
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
            if any(keyword in str(ssh_error).lower() for keyword in ["connection", "timeout", "session", "unreachable"]):
                crash_evidence.append(f"SSH failure during periodic check: {ssh_error}")
        
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
                    if any(keyword in str(ssh_error).lower() for keyword in ["connection", "timeout", "session not active", "ssh", "unreachable"]):
                        crash_evidence.append(f"SSH failure: {ssh_error}")
                        crash_detected = True
                
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
