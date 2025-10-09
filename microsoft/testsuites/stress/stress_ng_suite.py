# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import logging
from pathlib import Path, PurePath
from typing import Any, Dict, List, Tuple, cast

import yaml

from lisa import (
    Environment,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.base_tools import Cat
from lisa.features import SerialConsole
from lisa.messages import TestStatus, send_sub_test_result_message
from lisa.testsuite import TestResult
from lisa.tools import StressNg
from lisa.util import SkippedException
from lisa.util.logger import Logger
from lisa.util.process import Process
from microsoft.utils.console_log_helper import configure_console_logging


@TestSuiteMetadata(
    area="stress-ng",
    category="stress",
    description="""
    A suite for running the various classes of stressors provided
    by stress-ng.
    """,
)
class StressNgTestSuite(TestSuite):
    # Timeout for longhaul stress testing: 435600 seconds (121 hours)
    TIME_OUT = 435600
    CONFIG_VARIABLE = "stress_ng_jobs"

    @TestCaseMetadata(
        description="""
        Runs a stress-ng jobfile. The path to the jobfile must be specified
        using a runbook variable named "stress_ng_jobs". For more info about
        jobfiles refer:
        https://manpages.ubuntu.com/manpages/jammy/man1/stress-ng.1.html
        """,
        priority=5,
        timeout=TIME_OUT,
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

    @TestCaseMetadata(
        description="""
        Multi-VM stress test using stress-ng jobfiles.

        Executes stress-ng jobfiles across multiple VMs
        (VMs are deployed via runbook configuration).

        Each VM in the environment runs the specified stress-ng jobfiles
        to stress host CPU and memory resources simultaneously.

        Required runbook variables:
        - stress_ng_jobs: Jobfile(s) to execute on each VM

        Optional runbook variables for VM deployment:
        - stress_ng_node_count: Number of VMs to deploy
        - stress_ng_cpu_count: CPU cores per VM
        - stress_ng_memory_mb: Memory per VM in MB

        Note: This test requires an environment with at least 2 nodes for
        meaningful multi-VM stress testing.
        """,
        priority=4,
        timeout=TIME_OUT,
        requirement=simple_requirement(
            min_count=2,
            min_core_count=1,
            min_memory_mb=1024,
        ),
    )
    def multi_vm_stress_test(
        self,
        log: Logger,
        variables: Dict[str, Any],
        environment: Environment,
        result: TestResult,
    ) -> None:
        """
        Execute multi-VM stress test across multiple VMs.
        The runbook controls the actual VM deployment based on variables.
        This test simply uses whatever environment is provided.
        """

        nodes = [cast(RemoteNode, node) for node in environment.nodes.list()]

        # Phase 1: Ensure GRUB has console parameters and do controlled reboot
        # This ensures console logging works reliably (XML cmdline may be ignored)
        # Reboot happens BEFORE stress tests to avoid killing stress-ng mid-run
        log.info("Phase 1: Configuring console parameters in GRUB and rebooting VMs...")
        for node in nodes:
            try:
                # Check if all required console parameters are present in GRUB
                check_result = node.execute(
                    "grep -Eq 'console=ttyS0' /etc/default/grub && "
                    "grep -Eq 'console=hvc0' /etc/default/grub && "
                    "grep -Eq 'ignore_loglevel' /etc/default/grub && "
                    "grep -Eq 'printk\\.time=1' /etc/default/grub",
                    sudo=True,
                    shell=True,
                    no_error_log=True,
                )

                if check_result.exit_code != 0:
                    log.info(
                        f"Console parameters missing in GRUB on {node.name}. "
                        f"Adding and rebooting..."
                    )

                    # Remove any existing console= parameters to prevent duplicates
                    # Then add them in the correct order (hvc0 first, ttyS0 LAST)
                    # ttyS0 last makes it the primary /dev/console
                    # Libvirt reads from ttyS0 via <console target="serial">
                    node.execute(
                        "sed -i 's/console=[^ ]*//g' /etc/default/grub && "
                        "sed -i 's/ignore_loglevel//g' /etc/default/grub && "
                        "sed -i 's/printk\\.time=[^ ]*//g' /etc/default/grub && "
                        "sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT=\"/&"
                        "console=hvc0,115200 console=ttyS0,115200 "
                        "ignore_loglevel printk.time=1 /' /etc/default/grub",
                        sudo=True,
                        shell=True,
                        expected_exit_code=0,
                    )

                    # Update GRUB configuration
                    node.execute(
                        "update-grub || grub2-mkconfig -o /boot/grub2/grub.cfg",
                        sudo=True,
                        shell=True,
                    )

                    # Immediate deterministic reboot (not scheduled)
                    log.info(f"Rebooting {node.name} immediately...")
                    node.reboot()

                    # Wait for cloud-init to complete before proceeding
                    node.execute(
                        "cloud-init status --wait || true",
                        sudo=True,
                        shell=True,
                        timeout=300,
                    )
                    log.info(f"{node.name} reboot complete, cloud-init finished")

                    # Verify console configuration after reboot
                    try:
                        cmdline_result = node.execute(
                            "cat /proc/cmdline", sudo=True, no_error_log=True
                        )
                        console_result = node.execute(
                            "cat /proc/consoles", sudo=True, no_error_log=True
                        )
                        log.info(
                            f"{node.name} /proc/cmdline: "
                            f"{cmdline_result.stdout.strip()}"
                        )
                        log.info(
                            f"{node.name} /proc/consoles: "
                            f"{console_result.stdout.strip()}"
                        )

                        # Verify hvc0 appears after ttyS0 in cmdline (hvc0 is primary)
                        cmdline = cmdline_result.stdout
                        if "console=hvc0" in cmdline and "console=ttyS0" in cmdline:
                            hvc0_pos = cmdline.rfind("console=hvc0")
                            ttyS0_pos = cmdline.rfind("console=ttyS0")
                            if ttyS0_pos > hvc0_pos:
                                log.info(
                                    f"✓ {node.name} console ordering correct: "
                                    f"ttyS0 is last (primary)"
                                )
                            else:
                                log.warning(
                                    f"⚠ {node.name} console ordering incorrect: "
                                    f"ttyS0 should be after hvc0"
                                )
                    except Exception as verify_error:
                        log.warning(
                            f"Could not verify console config on {node.name}: "
                            f"{verify_error}"
                        )
                else:
                    log.info(
                        f"GRUB already has full console args on {node.name}, "
                        f"skipping reboot"
                    )

                    # Cancel any pending scheduled shutdowns from previous attempts
                    node.execute(
                        "shutdown -c || true", sudo=True, shell=True, no_error_log=True
                    )
            except Exception as e:
                log.warning(
                    f"Failed to configure GRUB on {node.name}: {e}. "
                    f"Console logs may be incomplete."
                )

        # Phase 2: Configure console logging and verify
        log.info("Phase 2: Configuring console logging and verifying...")
        for node in nodes:
            try:
                configure_console_logging(
                    node,
                    log,
                    loglevel=8,  # Maximum verbosity
                    persistent=False,  # Already persisted via GRUB
                    expected_console=None,  # Auto-detect (hvc0, ttyS0, or ttyS1)
                )
            except Exception as e:
                log.warning(
                    f"Failed to configure console logging on {node.name}: {e}. "
                    f"Console logs may be incomplete."
                )

        # Phase 3: Execute the stress test
        log.info("Phase 3: Running stress tests...")
        if self.CONFIG_VARIABLE not in variables:
            raise SkippedException("No jobfile provided for multi-VM stress test")

        jobs = variables[self.CONFIG_VARIABLE]
        if not isinstance(jobs, list):
            jobs = [job.strip() for job in str(jobs).split(",")]

        # Execute each jobfile across all VMs
        for job_file in jobs:
            self._run_stress_ng_job(job_file, environment, result, log)

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
        finally:
            # Always save serial console logs for debugging
            self._save_serial_console_logs(nodes, class_name, environment.log)

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
            self._check_panic(nodes)
            raise execution_error

        finally:
            # Always save serial console logs for debugging, regardless of test result
            self._save_serial_console_logs(nodes, job_file_name, log)

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

    def _check_panic(self, nodes: List[RemoteNode]) -> None:
        for node in nodes:
            node.features[SerialConsole].check_panic(saved_path=None, force_run=True)

    def _save_serial_console_logs(
        self, nodes: List[RemoteNode], job_file_name: str, log: Logger
    ) -> None:
        """
        Save serial console logs for all nodes.

        This captures console logs regardless of test pass/fail status
        to aid in debugging console logging issues.

        Args:
            nodes: List of nodes to capture console logs from
            job_file_name: Name of the job file (used in log path)
            log: Logger instance
        """
        for node in nodes:
            try:
                if node.features.is_supported(SerialConsole):
                    serial_console = node.features[SerialConsole]
                    log_dir = (
                        node.local_log_path
                        / f"serial_console_{node.name}_{job_file_name}"
                    )
                    log_dir.mkdir(parents=True, exist_ok=True)
                    serial_console.get_console_log(log_dir, force_run=True)
                    log.debug(f"Saved serial console log for {node.name} to {log_dir}")
            except Exception as e:
                log.warning(f"Failed to save serial console log for {node.name}: {e}")

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
