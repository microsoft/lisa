# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import shlex
import time
import uuid
from typing import Any, Dict, Tuple

from func_timeout import FunctionTimedOut

from lisa import (
    Logger,
    Node,
    RemoteNode,
    TestCaseMetadata,
    TestResult,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.base_tools import Cat, Uname
from lisa.operating_system import Posix
from lisa.tools import Ls, Who
from lisa.util import LisaException, SkippedException, create_timer


@TestSuiteMetadata(
    area="kexec",
    category="functional",
    description="""
    Test suite for kexec functionality.
    Validates kernel's ability to load and execute a new kernel
    without going through BIOS/firmware reboot.
    """,
)
class KexecSuite(TestSuite):
    RECONNECT_TIMEOUT = 600  # 10 minutes
    RECONNECT_INTERVAL = 10  # Check every 10 seconds

    @TestCaseMetadata(
        description="""
        End-to-end kexec reboot test.

        Validates that the system can:
        1. Load a new kernel image via kexec
        2. Execute kexec reboot (bypassing firmware)
        3. Successfully boot into the kexec'd kernel
        4. Maintain system health after kexec reboot

        This test verifies the core kexec functionality by performing
        a controlled kernel-to-kernel reboot and validating the transition.
        """,
        priority=3,
    )
    def verify_kexec_reboot_systemd(
        self, node: Node, log: Logger, result: TestResult
    ) -> None:
        """
        Test kexec reboot via systemctl kexec (graceful, systemd-integrated path).

        This tests the systemd integration where shutdown scripts run
        before kexec executes. Tests that systemd properly handles
        kexec as a reboot mechanism.
        """
        # Check systemctl availability early
        if node.execute("which systemctl", shell=True).exit_code != 0:
            raise SkippedException("systemctl not available on this system")

        self._run_kexec_test(node, log, result, use_systemctl=True)

    @TestCaseMetadata(
        description="""
        Test kexec reboot via direct kexec -e command.

        Validates raw kernel kexec execution without systemd involvement.
        Tests the core kexec mechanism where the new kernel is executed
        immediately without running shutdown scripts.
        """,
        priority=3,
    )
    def verify_kexec_reboot_direct(
        self, node: Node, log: Logger, result: TestResult
    ) -> None:
        """
        Test kexec reboot via kexec -e (direct kernel execution).

        This tests the raw kexec path where the loaded kernel is
        executed immediately without systemd coordination.
        """
        self._run_kexec_test(node, log, result, use_systemctl=False)

    def _run_kexec_test(
        self, node: Node, log: Logger, result: TestResult, use_systemctl: bool
    ) -> None:
        """
        Common test flow for kexec reboot tests.

        Args:
            result: TestResult for serial console log capture on failure
            use_systemctl: If True, use systemctl kexec; if False, use kexec -e

        Test flow:
        - Record pre-reboot state (boot_id, uptime, kernel version)
        - Resolve kernel and initrd paths
        - Load kexec image
        - Trigger kexec reboot
        - Reconnect and validate post-reboot state
        """
        if not isinstance(node, RemoteNode):
            raise SkippedException("kexec test requires remote node")

        if not isinstance(node.os, Posix):
            raise SkippedException("kexec test requires Linux/Posix OS")

        # Check kexec support and ensure tools are installed
        self._ensure_kexec_tools_installed(node, log)
        self._check_kernel_kexec_support(node, log)

        # Record "before" state
        before_state = self._record_state(node, log, include_cmdline=True)
        log.info(
            f"Before state: boot_id={before_state['boot_id']}, "
            f"kernel={before_state['uname']}, uptime={before_state['uptime']}s"
        )

        # Resolve kernel + initrd paths
        kernel_path, initrd_path = self._resolve_boot_artifacts(node, log)
        log.info(f"Resolved kernel={kernel_path}, initrd={initrd_path}")

        # Create unique nonce for cmdline validation
        nonce = str(uuid.uuid4())
        log.info(f"Created nonce: {nonce}")

        # Load kexec image with cmdline nonce
        self._load_kexec_image(
            node, kernel_path, initrd_path, before_state["cmdline"], nonce, log
        )

        # Trigger kexec reboot
        method = "systemctl kexec" if use_systemctl else "kexec -e"
        log.info(f"Triggering kexec reboot via {method}...")
        # Get boot time before triggering reboot
        last_boot_time = self._get_last_boot_time(node)
        self._trigger_kexec_reboot(node, log, use_systemctl=use_systemctl)

        # Reconnect + validation
        log.info("Waiting for system to come back up...")
        self._wait_for_reconnect(node, log, last_boot_time)

        after_state = self._record_state(node, log, force_run=True)
        log.info(
            f"After state: boot_id={after_state['boot_id']}, "
            f"kernel={after_state['uname']}, uptime={after_state['uptime']}s"
        )

        # Validate the reboot
        try:
            self._validate_kexec_reboot(node, nonce, before_state, after_state, log)
        except Exception:
            # Capture serial console logs on validation failure for debugging
            try:
                result.capture_serial_console_log()
            except Exception as e:
                log.debug(f"Failed to capture serial console log: {e}")
            raise

    def _ensure_kexec_tools_installed(self, node: RemoteNode, log: Logger) -> None:
        """
        Ensure kexec-tools package is installed.

        Raises SkippedException if installation fails.
        """
        kexec_check = node.execute("which kexec", shell=True)
        if kexec_check.exit_code == 0:
            log.debug("kexec tool is already installed")
            return

        log.info("kexec tool not found, installing kexec-tools package...")
        if not isinstance(node.os, Posix):
            raise SkippedException("Cannot install kexec-tools on non-Posix OS")

        node.os.install_packages("kexec-tools")

        # Verify installation
        verify_check = node.execute("which kexec", shell=True)
        if verify_check.exit_code != 0:
            raise SkippedException(
                "Failed to install kexec-tools package. "
                "Package may not be available for this distro."
            )
        log.info("kexec-tools installed successfully")

    def _check_kernel_kexec_support(self, node: RemoteNode, log: Logger) -> None:
        """
        Check if kernel has kexec support enabled.

        Verifies CONFIG_KEXEC kernel config or sysfs interface.
        Note: Actual load-time support will be validated when kexec -l runs.
        """
        log.debug("Checking kernel kexec support...")

        # Try multiple methods to check CONFIG_KEXEC
        config_result = node.execute(
            "zcat /proc/config.gz 2>/dev/null | grep -E '^CONFIG_KEXEC[_=]' || "
            "(modprobe configs 2>/dev/null && "
            "zcat /proc/config.gz 2>/dev/null | grep -E '^CONFIG_KEXEC[_=]') || "
            "echo 'CONFIG_NOT_AVAILABLE'",
            shell=True,
            sudo=True,
        )

        # Check for CONFIG_KEXEC=y (required for kexec -l which we use)
        # Note: CONFIG_KEXEC_FILE=y is different and requires signed kernels
        if "CONFIG_KEXEC=y" in config_result.stdout:
            log.debug("Kernel config confirms kexec support")
            return

        # Fallback: check for kexec sysfs file (proves kernel support)
        if node.execute("test -f /sys/kernel/kexec_loaded", sudo=True).exit_code == 0:
            log.debug("kexec sysfs interface found (kernel has kexec support)")
            return

        # If we can't confirm support, log info about proceeding anyway
        # Actual support will be proven when kexec -l succeeds or fails
        log.debug(f"Config probe output: {config_result.stdout.strip()}")
        log.info(
            "Could not verify kernel kexec support via config or sysfs. "
            "Will attempt to proceed; kexec -l will fail if unsupported."
        )

    def _record_state(
        self,
        node: RemoteNode,
        log: Logger,
        force_run: bool = False,
        include_cmdline: bool = False,
    ) -> Dict[str, Any]:
        """
        Record system state.

        Args:
            force_run: Use force_run=True to bypass cache (for post-reboot reads)
            include_cmdline: Include /proc/cmdline in returned state

        Returns dict with boot_id, uname, uptime, and optionally cmdline.
        """
        boot_id = (
            node.tools[Cat]
            .read("/proc/sys/kernel/random/boot_id", sudo=True, force_run=force_run)
            .strip()
        )
        uname_r = node.tools[Uname].get_linux_information().kernel_version_raw
        uptime_result = node.execute("cut -d. -f1 /proc/uptime", sudo=True)
        uptime = int(float(uptime_result.stdout.strip()))

        state = {
            "boot_id": boot_id,
            "uname": uname_r,
            "uptime": uptime,
        }

        if include_cmdline:
            state["cmdline"] = (
                node.tools[Cat]
                .read("/proc/cmdline", sudo=True, force_run=force_run)
                .strip()
            )

        return state

    def _resolve_boot_artifacts(self, node: RemoteNode, log: Logger) -> Tuple[str, str]:
        """
        Resolve kernel and initrd paths for current running kernel.

        Tries multiple distro-specific patterns.
        Returns (kernel_path, initrd_path).
        """
        log.debug("Resolving boot artifacts...")

        uname_r = node.tools[Uname].get_linux_information().kernel_version_raw

        # Kernel candidates (in priority order)
        kernel_candidates = [
            f"/boot/vmlinuz-{uname_r}",  # Debian/Ubuntu/RHEL
            "/boot/vmlinuz",  # Some minimal distros
            "/boot/vmlinuz-linux",  # Arch-like
        ]

        # Initrd candidates (in priority order)
        initrd_candidates = [
            f"/boot/initrd.img-{uname_r}",  # Debian/Ubuntu
            f"/boot/initramfs-{uname_r}.img",  # RHEL/CentOS/Fedora
            "/boot/initramfs-linux.img",  # Arch-like
            f"/boot/initrd-{uname_r}",  # Some SUSE variants
        ]

        # Find kernel
        kernel_path = None
        ls = node.tools[Ls]
        for candidate in kernel_candidates:
            if ls.path_exists(candidate, sudo=True):
                kernel_path = candidate
                log.debug(f"Found kernel: {kernel_path}")
                break

        if not kernel_path:
            # Fallback: find newest vmlinuz*
            find_result = node.execute(
                "ls -t /boot/vmlinuz* 2>/dev/null | head -n1",
                shell=True,
                sudo=True,
            )
            if find_result.exit_code == 0 and find_result.stdout.strip():
                kernel_path = find_result.stdout.strip()
                log.debug(f"Fallback kernel found: {kernel_path}")

        if not kernel_path:
            raise SkippedException("No suitable kernel found in /boot")

        # Find initrd
        initrd_path = None
        for candidate in initrd_candidates:
            if ls.path_exists(candidate, sudo=True):
                initrd_path = candidate
                log.debug(f"Found initrd: {initrd_path}")
                break

        if not initrd_path:
            # Fallback: find newest initr*
            find_result = node.execute(
                "ls -t /boot/initr* /boot/initramfs* 2>/dev/null | head -n1",
                shell=True,
                sudo=True,
            )
            if find_result.exit_code == 0 and find_result.stdout.strip():
                initrd_path = find_result.stdout.strip()
                log.debug(f"Fallback initrd found: {initrd_path}")

        if not initrd_path:
            raise SkippedException("No suitable initrd found in /boot")

        return kernel_path, initrd_path

    def _load_kexec_image(
        self,
        node: RemoteNode,
        kernel_path: str,
        initrd_path: str,
        cmdline: str,
        nonce: str,
        log: Logger,
    ) -> None:
        """
        Load kexec image into kernel memory.

        Uses kexec -l to prepare the new kernel for execution.
        Appends a unique cmdline nonce to prove kexec reboot occurred.
        """
        log.info(f"Loading kexec image: {kernel_path}")

        # Unload any previously loaded kernel (ignore errors)
        node.execute("kexec -u || true", sudo=True, shell=True, no_error_log=True)

        # Append nonce to cmdline to prove we actually booted via kexec
        # (not a firmware reboot)
        kexec_marker = f"lisa_kexec_nonce={nonce}"
        new_cmdline = f"{cmdline} {kexec_marker}"
        log.info(f"Appending cmdline marker: {kexec_marker}")

        # Build kexec load command with properly escaped paths and cmdline
        # Use shlex.quote to safely escape all arguments for shell
        kexec_cmd = (
            f"kexec -l {shlex.quote(kernel_path)} "
            f"--initrd={shlex.quote(initrd_path)} "
            f"--command-line={shlex.quote(new_cmdline)}"
        )

        result = node.execute(kexec_cmd, sudo=True, shell=True)

        if result.exit_code != 0:
            # Cleanup on failure
            node.execute("kexec -u || true", sudo=True, shell=True, no_error_log=True)
            raise RuntimeError(
                f"Failed to load kexec image. Exit code: {result.exit_code}\n"
                f"Stdout: {result.stdout}\n"
                f"Stderr: {result.stderr}"
            )

        log.info("Kexec image loaded successfully")

        # Verify load status
        verify_result = node.tools[Cat].read("/sys/kernel/kexec_loaded", sudo=True)
        if verify_result.strip() != "1":
            log.debug(f"unexpected /sys/kernel/kexec_loaded: {verify_result.strip()!r}")

    def _trigger_kexec_reboot(
        self, node: RemoteNode, log: Logger, use_systemctl: bool
    ) -> None:
        """
        Trigger kexec reboot using specified method.

        Args:
            use_systemctl: If True, use systemctl kexec; if False, use kexec -e

        SSH connection may disconnect during this operation.
        """
        if use_systemctl:
            try:
                node.execute(
                    "systemctl kexec",
                    sudo=True,
                    timeout=5,
                    expected_exit_code=None,
                    no_error_log=True,
                )
            except Exception as e:
                log.debug(f"systemctl kexec may have disconnected: {e}")
        else:
            try:
                node.execute(
                    "kexec -e",
                    sudo=True,
                    timeout=5,
                    expected_exit_code=None,
                    no_error_log=True,
                )
            except Exception as e:
                log.debug(f"kexec -e may have disconnected: {e}")

        # Give the system a moment to start shutting down
        time.sleep(5)

    def _get_last_boot_time(self, node: RemoteNode) -> Any:
        """
        Get last boot time using Who tool (with Uptime fallback).
        Matches Reboot tool's _get_last_boot_time implementation.
        """
        try:
            last_boot_time = node.tools[Who].last_boot()
        except Exception:
            # Fallback to uptime if who fails
            from lisa.tools import Uptime

            last_boot_time = node.tools[Uptime].since_time()
        return last_boot_time

    def _wait_for_reconnect(
        self, node: RemoteNode, log: Logger, last_boot_time: Any
    ) -> None:
        """
        Wait for system to reboot and reconnect.
        Uses Reboot tool's pattern: close connection and retry until boot time changes.
        """
        timer = create_timer()
        connected: bool = False
        tried_times: int = 0
        current_boot_time = last_boot_time

        # The previous steps may take longer time than time out. After that, it
        # needs to connect at least once.
        while (timer.elapsed(False) < self.RECONNECT_TIMEOUT) or tried_times < 1:
            tried_times += 1
            try:
                node.close()
                current_boot_time = self._get_last_boot_time(node)
                connected = True
            except FunctionTimedOut as e:
                # The FunctionTimedOut must be caught separated, or the process
                # will exit.
                log.debug(f"ignorable timeout exception: {e}")
            except Exception as e:
                # error is ignorable, as ssh may be closed suddenly.
                log.debug(f"ignorable ssh exception: {e}")
            log.debug(f"reconnected with uptime: {current_boot_time}")
            if last_boot_time < current_boot_time:
                break

            time.sleep(self.RECONNECT_INTERVAL)

        if last_boot_time == current_boot_time:
            if connected:
                raise LisaException(
                    "timeout to wait reboot, the node may not perform reboot."
                )
            else:
                raise LisaException(
                    "timeout to wait reboot, the node may stuck on reboot command."
                )

    def _validate_kexec_reboot(
        self,
        node: RemoteNode,
        nonce: str,
        before_state: Dict[str, Any],
        after_state: Dict[str, Any],
        log: Logger,
    ) -> None:
        """
        Validate that kexec reboot was successful.

        Checks:
        - Cmdline nonce present
        - boot_id changed (proves reboot occurred)
        - System health
        """
        log.info("Validating kexec reboot...")

        # PRIMARY VALIDATION: Check cmdline nonce
        # This is the most reliable proof that we booted via kexec
        kexec_marker = f"lisa_kexec_nonce={nonce}"
        # Use Cat tool with force_run to avoid cached output after reboot
        cmdline_after = (
            node.tools[Cat].read("/proc/cmdline", sudo=True, force_run=True).strip()
        )
        if kexec_marker not in cmdline_after:
            # Gather diagnostic info from previous boot logs
            diagnostic_info = ""
            has_journalctl = node.execute("which journalctl", shell=True).exit_code == 0
            if has_journalctl:
                try:
                    # Check previous boot (-b-1) for kexec evidence
                    journal_result = node.execute(
                        "journalctl -b-1 | grep -i kexec | head -n 10",
                        sudo=True,
                        shell=True,
                    )
                    if journal_result.exit_code == 0 and journal_result.stdout.strip():
                        diagnostic_info = (
                            f"\n\nDiagnostic - Previous boot kexec evidence:\n"
                            f"{journal_result.stdout}"
                        )
                except Exception:
                    pass  # Diagnostic only, don't fail on errors

            raise AssertionError(
                f"kexec cmdline marker not found after reboot.\n"
                f"Expected marker: {kexec_marker}\n"
                f"Actual /proc/cmdline: {cmdline_after}\n"
                f"This indicates the system rebooted via firmware, not kexec."
                f"{diagnostic_info}"
            )
        log.info(f"Cmdline marker validated: {kexec_marker}")

        # Validate boot_id changed
        if after_state["boot_id"] == before_state["boot_id"]:
            raise AssertionError(
                f"boot_id did not change! Still: {after_state['boot_id']}\n"
                "System may not have actually rebooted via kexec."
            )

        log.info(
            f"boot_id changed: {before_state['boot_id'][:8]}... -> "
            f"{after_state['boot_id'][:8]}..."
        )

        # Check system health (best effort)
        self._check_system_health(node, log)

    def _check_system_health(self, node: RemoteNode, log: Logger) -> None:
        """Check basic system health after reboot."""
        has_systemctl = node.execute("which systemctl", shell=True).exit_code == 0
        if has_systemctl:
            result = node.execute("systemctl is-system-running", sudo=True)
            state = result.stdout.strip()

            if state in ["running", "degraded"]:
                log.info(f"System state: {state}")
            else:
                log.info(
                    f"System in unexpected state: {state}. "
                    "This may indicate issues after kexec reboot."
                )
        else:
            log.debug("systemctl not available, skipping health check")
