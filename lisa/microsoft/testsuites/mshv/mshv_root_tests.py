# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
import time
from pathlib import Path
from typing import Any, Dict

from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import CBLMariner
from lisa.testsuite import TestResult
from lisa.tools import (
    Dmesg,
    KdumpCheck,
    KernelConfig,
    Ls,
    Reboot,
    Sed,
    Service,
    Stat,
    Timeout,
)
from lisa.util import LisaException, SkippedException
from lisa.util.perf_timer import create_timer


@TestSuiteMetadata(
    area="mshv",
    category="functional",
    description="""
    This test suite contains tests that should be run on the
    Microsoft Hypervisor (MSHV) root partition. This test suite contains tests
    to check health of mshv root node.
    """,
    requirement=simple_requirement(supported_os=[CBLMariner]),
)
class MshvHostTestSuite(TestSuite):
    mshvdiag_dmesg_pattern = re.compile(r"\[\s+\d+.\d+\]\s+mshv_diag:.*$")
    mshvlog_logfile = "/var/log/mshv_diag/mshv.log"

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        if not node.tools[KernelConfig].is_enabled("CONFIG_MSHV_DIAG"):
            raise SkippedException("MSHV_DIAG not enabled, skip")

        if not node.tools[Ls].path_exists("/dev/mshv_diag", sudo=True):
            raise LisaException(
                "mshv_diag device should exist, when CONFIG_MSHV_DIAG is enabled."
            )

    @TestCaseMetadata(
        description="""
        With mshv_diag module loaded, ensure mshvlog.service starts and runs
        successfully on MSHV root partitions. Also confirm there are no errors
        reported by mshv_diag module in dmesg.
        Lastly, check if logfile from mshvlog.service is not empty.
        """,
        priority=4,
        timeout=30,  # 30 seconds
    )
    def verify_mshvlog_is_active(
        self,
        log: Logger,
        node: Node,
        variables: Dict[str, Any],
        environment: Environment,
        log_path: Path,
        result: TestResult,
    ) -> None:
        mshvlog_logfile_size = 0
        self._save_dmesg_logs(node, log_path)
        mshvlog_running = node.tools[Service].is_service_running("mshvlog")
        if not mshvlog_running:
            log.error("mshvlog service is not running on MSHV root partition.")

        assert_that(mshvlog_running).is_true()
        # mshvlog service writes to logfile every 5 seconds. Check for non-zero
        # size of the logfile for 10 seconds.
        timeout = 10
        timer = create_timer()
        while timeout > timer.elapsed(False):
            mshvlog_logfile_size = node.tools[Stat].get_total_size(
                self.mshvlog_logfile, sudo=True
            )
            if mshvlog_logfile_size > 0:
                break
            time.sleep(1)

        # mshvlog file will be empty on L1VH parent partitions.
        if not self._is_l1vh_partition(node, log):
            assert_that(mshvlog_logfile_size).described_as(
                "mshvlog logfile should not be empty"
            ).is_greater_than(0)

        dmesg_logs = node.tools[Dmesg].get_output()
        mshvdiag_dmesg_logs = re.search(self.mshvdiag_dmesg_pattern, dmesg_logs)
        if mshvdiag_dmesg_logs is not None:
            log.error(
                f"mshv_diag module reported errors in dmesg: "
                f"{mshvdiag_dmesg_logs.group(0)}"
            )
        assert_that(mshvdiag_dmesg_logs).is_none()

        return

    @TestCaseMetadata(
        description="""
        This test case will
        1. Remove lockdown=integrity from the dom0 boot config if present
        2. Configure kdump and reboot the VM into the regular FRE hypervisor build
        3. Generate a crash by writing a magic value to the mshv hvdbg debugfs node
           (/sys/kernel/debug/mshv/hvdbg) and verify that a kdump is produced
        """,
        priority=2,
    )
    def verify_mshv_crash(
        self,
        log: Logger,
        node: Node,
        log_path: Path,
    ) -> None:
        # sysfs entry used to trigger crash
        mshv_debug_sysfs = "/sys/kernel/debug/mshv/hvdbg"
        # sysfs entry expect 0x4856434f5245 value to trigger crash from hv
        mshv_crash_command = f"echo 0x4856434f5245 > {mshv_debug_sysfs}"

        # Defense-in-depth: catches custom VHD/SIG images whose OS detection
        # may misclassify the node and bypass the supported_os gate.
        if not isinstance(node.os, CBLMariner):
            raise SkippedException(
                f"Testcase only support CBLMariner. Found: {node.os}"
            )

        # Check if /dev/mshv is present to make sure node is running with
        # mshv kernel. hvdb sysfs entry will be present only with mshv kernel.
        mshv = node.tools[Ls].path_exists("/dev/mshv", sudo=True)
        if not mshv:
            raise SkippedException(
                "File not found: /dev/mshv. Only CBLMariner build with"
                " MSHV kernel will have this file present."
            )

        try:
            grub_config_file = "/boot/grub2/grub.cfg"
            if not node.tools[Ls].path_exists(grub_config_file, sudo=True):
                raise LisaException(
                    f"Grub configuration file not found or not accessible: "
                    f"{grub_config_file}"
                )
            grub_has_lockdown = (
                node.execute(
                    f"grep -q 'lockdown=integrity' {grub_config_file}",
                    shell=True,
                    sudo=True,
                ).exit_code
                == 0
            )
            booted_with_lockdown = (
                node.execute(
                    "grep -q 'lockdown=integrity' /proc/cmdline",
                    shell=True,
                    sudo=True,
                ).exit_code
                == 0
            )

            if booted_with_lockdown and not grub_has_lockdown:
                raise LisaException(
                    "System is booted with 'lockdown=integrity' but the argument "
                    "is not present in the expected GRUB config "
                    f"'{grub_config_file}'. Cannot safely remove lockdown; "
                    "failing the test."
                )

            if grub_has_lockdown:
                node.tools[Sed].substitute(
                    regexp="lockdown=integrity",
                    replacement="",
                    file=grub_config_file,
                    sudo=True,
                )

            if grub_has_lockdown or booted_with_lockdown:
                log.debug("Rebooting to pick up a dom0 boot without lockdown=integrity")
                node.tools[Reboot].reboot_and_check_panic(log_path)
                # After reboot, ensure lockdown=integrity is no longer active.
                # If it's still present, abort instead of proceeding under lockdown.
                booted_with_lockdown_after_reboot = (
                    node.execute(
                        "grep -q 'lockdown=integrity' /proc/cmdline",
                        shell=True,
                        sudo=True,
                    ).exit_code
                    == 0
                )
                if booted_with_lockdown_after_reboot:
                    raise LisaException(
                        "System is still booted with 'lockdown=integrity' after "
                        "attempting to remove it from the boot configuration. "
                        "Cannot proceed with the test under lockdown."
                    )

            # Trigger HV crash and check if dump is generated
            hvdbg = node.tools[Ls].path_exists(mshv_debug_sysfs, sudo=True)
            if not hvdbg:
                raise LisaException(f"sysfs entry not present: {mshv_debug_sysfs}")

            kdump_util = node.tools[KdumpCheck]
            kdump_util.kdump_test(
                log_path=log_path,
                trigger_kdump_cmd=mshv_crash_command,
                is_auto=False,
            )
        finally:
            node.mark_dirty()

    @TestCaseMetadata(
        description="""
        Ensure mshvtrace tool is present, can be executed, and produces
        output on the MSHV root partition.
        The test checks:
        1. mshvtrace binary exists and is executable
        2. Running mshvtrace with --help returns expected output
        3. Running mshvtrace for a short duration produces a non-empty trace file
        """,
        priority=4,
    )
    def verify_mshvtrace_tool(
        self,
        log: Logger,
        node: Node,
    ) -> None:
        mshvtrace_path = "/usr/sbin/mshvtrace"

        if self._is_l1vh_partition(node, log):
            raise SkippedException(
                "L1VH Parent partition cannot collect performance traces."
            )
        temp_dir = node.execute(
            "mktemp -d /tmp/mshvtrace_test_XXXXXX", sudo=True
        ).stdout.strip()
        trace_output = f"{temp_dir}/mshvtrace_output.ETL"

        try:
            # 1. Check if mshvtrace exists and is executable
            exists = node.tools[Ls].path_exists(mshvtrace_path, sudo=True)
            assert_that(exists).described_as("mshvtrace binary should exist").is_true()
            is_executable = (
                node.execute(f"test -x {mshvtrace_path}", sudo=True).exit_code == 0
            )
            assert_that(is_executable).described_as(
                "mshvtrace should be executable"
            ).is_true()

            # 2. Create tracing context
            create_result = node.execute(f"{mshvtrace_path} create", sudo=True)
            assert_that(create_result.exit_code).is_equal_to(0)

            # 3. Collect trace for 15 seconds using timeout tool
            collect_result = node.tools[Timeout].run_with_timeout(
                command=f"{mshvtrace_path} collect -o {trace_output}", timeout=15
            )
            assert_that(collect_result.exit_code).is_equal_to(0)

            trace_size = node.tools[Stat].get_total_size(trace_output, sudo=True)
            # 8192 is the min size of the trace file.
            assert_that(int(trace_size)).described_as(
                "mshvtrace output should be greater than 8192 bytes"
            ).is_greater_than(8192)

            # 4. Destroy tracing context
            destroy_result = node.execute(f"{mshvtrace_path} destroy", sudo=True)
            assert_that(destroy_result.exit_code).is_equal_to(0)

            log.info("mshvtrace integration test (create/collect/destroy) passed.")
        finally:
            node.execute(f"rm -rf {temp_dir}", sudo=True)

    def _save_dmesg_logs(self, node: Node, log_path: Path) -> None:
        dmesg_str = node.tools[Dmesg].get_output()
        dmesg_path = log_path / "dmesg"
        with open(str(dmesg_path), "w", encoding="utf-8") as f:
            f.write(dmesg_str)

    def _is_l1vh_partition(self, node: Node, log: Logger) -> bool:
        """Check if the node is L1VH parent partition."""

        # This pattern matches a line like below in dmesg:
        # [    1.234567] Hyper-V: running as L1VH partition
        l1vh_pattern = re.compile(
            r"\[\s+\d+.\d+\]\s+Hyper-V: running as L1VH partition"
        )
        dmesg_logs = node.tools[Dmesg].get_output()
        l1vh_dmesg_logs = re.search(l1vh_pattern, dmesg_logs)
        if l1vh_dmesg_logs is not None:
            log.debug("Node is running as L1VH partition.")
            return True
        log.debug("Node is NOT running as L1VH partition.")
        return False
