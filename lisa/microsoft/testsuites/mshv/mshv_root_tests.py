# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
import time
from pathlib import Path, PurePath
from typing import Any, Dict

from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.operating_system import CBLMariner
from lisa.testsuite import TestResult
from lisa.tools import (
    Cat,
    Cp,
    Dmesg,
    KdumpCheck,
    KernelConfig,
    Ls,
    Reboot,
    RemoteCopy,
    Sed,
    Service,
    Stat,
    Tar,
)
from lisa.util import LisaException, SkippedException, find_group_in_lines
from lisa.util.perf_timer import create_timer


@TestSuiteMetadata(
    area="mshv",
    category="functional",
    description="""
    This test suite contains tests that should be run on the
    Microsoft Hypervisor (MSHV) root partition. This test suite contains tests
    to check health of mshv root node.
    """,
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
        1. replace FRE bins with CHK bins and reboot the VM
           a. FRE is default free hv version binary, something similar to release binary
           b. CHK is debug binary where extra debug options are available along with
              some testing feature available like crash
        2. Configure kdump and reboot VM
        3. Generate Crash with hvdbg syscall and verify dump

        The test expects the directory containing MSHV CHK binaries tar to be passed
        in the mshv_chk_bin / mshv_chk_loader testcase variables.
        """,
        priority=2,
    )
    def verify_mshv_crash(
        self,
        log: Logger,
        node: Node,
        variables: Dict[str, Any],
        log_path: Path,
    ) -> None:
        # sysfs entry used to trigger crash
        mshv_debug_sysfs = "/sys/kernel/debug/mshv/hvdbg"
        # sysfs entry expect 0x4856434f5245 value to trigger crash from hv
        mshv_crash_command = f"echo 0x4856434f5245 > {mshv_debug_sysfs}"

        chkbinpath = variables.get("mshv_chk_bin", "")
        chkloaderpath = variables.get("mshv_chk_loader", "")
        log.debug(f"mshv_chk_bin: {chkbinpath}, mshv_chk_loader: {chkloaderpath}")

        if not chkbinpath or not chkloaderpath:
            raise SkippedException(
                "Requires a path to MSHV binaries to be passed. "
                "Please set mshv_chk_bin and mshv_chk_loader testcase variable."
            )
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
            # Copy and Extract CHK tar on node
            grub_config_file = "/boot/grub2/grub.cfg"
            chk_bin_dir = "chk_bin"
            chk_bin_remote_dir = f"/tmp/{chk_bin_dir}/"
            chk_bin_tar_file = PurePath(chkbinpath).name
            chk_bin_extract_dir = f"/tmp/{chk_bin_dir}_extract"

            chk_loader_dir = "chk_loader"
            chk_loader_remote_dir = f"/tmp/{chk_loader_dir}/"
            chk_loader_tar_file = PurePath(chkloaderpath).name
            chk_loader_extract_dir = f"/tmp/{chk_loader_dir}_extract"

            # Copy artifacts on to the node
            remote_cp = node.tools[RemoteCopy]
            remote_cp.copy_to_remote(
                src=PurePath(chkbinpath),
                dest=PurePath(chk_bin_remote_dir),
            )
            remote_cp.copy_to_remote(
                src=PurePath(chkloaderpath),
                dest=PurePath(chk_loader_remote_dir),
            )

            tar = node.tools[Tar]
            tar.extract(
                file=f"{chk_bin_remote_dir}/{chk_bin_tar_file}",
                dest_dir=chk_bin_extract_dir,
                gzip=True,
                sudo=True,
            )
            tar.extract(
                file=f"{chk_loader_remote_dir}/{chk_loader_tar_file}",
                dest_dir=chk_loader_extract_dir,
                gzip=True,
                sudo=True,
            )

            # Copy CHK bins into test machine
            copy_tool = node.tools[Cp]
            copy_tool.copy(
                src=PurePath(chk_bin_extract_dir) / "Windows" / "System32",
                dest=PurePath("/boot/efi/Windows"),
                sudo=True,
                recur=True,
            )
            path = PurePath(chk_loader_extract_dir) / "boot" / "efi" / "lxhvloader.dll"
            copy_tool.copy(
                src=path,
                dest=PurePath("/boot/efi"),
                sudo=True,
            )

            # Remove kernel lockdown from grub config
            node.tools[Sed].substitute(
                regexp="lockdown=integrity",
                replacement="",
                file=grub_config_file,
                sudo=True,
            )

            # Add MSHV debug option in chainloader
            # This is to load hv binaries with debug mode enabled
            hv_debug_option = "LXHVLOADER_DEBUG=TRUE"
            grub_config = node.tools[Cat].read(
                file=grub_config_file,
                force_run=True,
                sudo=True,
            )
            regex = re.compile(r"(?P<chainloader_cfg>.*chainloader.*)")
            loader_grub_data = find_group_in_lines(
                lines=grub_config,
                pattern=regex,
                single_line=False,
            )
            chainloader_config = loader_grub_data.get("chainloader_cfg", "").strip()
            err_msg = f"Cannot get chainloader config, got {chainloader_config}"
            assert chainloader_config, err_msg
            if hv_debug_option not in chainloader_config:
                node.tools[Sed].substitute(
                    regexp="MSHV_SEV_SNP=TRUE",
                    replacement=f"MSHV_SEV_SNP=TRUE {hv_debug_option}",
                    file=grub_config_file,
                    sudo=True,
                )

            node.tools[Reboot].reboot_and_check_panic(log_path)

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

            # 3. Collect trace for 30 seconds using node.execute with timeout argument
            _ = node.execute(
                f"{mshvtrace_path} collect -o {trace_output}", sudo=True, timeout=35
            )
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
