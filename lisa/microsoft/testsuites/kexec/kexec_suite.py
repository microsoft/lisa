# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import json
import shlex
import time
import uuid
from pathlib import PurePosixPath
from typing import Any, Dict, Tuple

from lisa import (
    Logger,
    Node,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.base_tools import Cat, Uname
from lisa.operating_system import Posix
from lisa.util import SkippedException
from lisa.util.shell import try_connect


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
    MARKER_DIR = "/var/lib/lisa"
    RECONNECT_TIMEOUT = 600  # 10 minutes
    RECONNECT_INTERVAL = 10  # Check every 10 seconds
    MAX_AFTER_UPTIME = 900  # 15 minutes - max uptime after kexec for validation

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
    def verify_kexec_reboot(self, node: Node, log: Logger) -> None:
        """
        Perform an end-to-end kexec reboot test.

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
        before_state = self._record_before_state(node, log)
        log.info(
            f"Before state: boot_id={before_state['boot_id']}, "
            f"kernel={before_state['uname']}, uptime={before_state['uptime']}s"
        )

        # Resolve kernel + initrd paths
        kernel_path, initrd_path = self._resolve_boot_artifacts(node, log)
        log.info(f"Resolved kernel={kernel_path}, initrd={initrd_path}")

        # Create marker with all info (includes nonce for unique filename)
        marker = self._create_marker(before_state, kernel_path, initrd_path)
        marker_path = self._write_marker(node, marker, log)

        # Ensure marker cleanup happens even on failure
        try:
            # Load kexec image
            self._load_kexec_image(
                node, kernel_path, initrd_path, before_state["cmdline"], log
            )

            # Trigger kexec reboot
            log.info("Triggering kexec reboot...")
            self._trigger_kexec_reboot(node, log)

            # Reconnect + validation
            log.info("Waiting for system to come back up...")
            self._wait_for_reconnect(node, log)

            after_state = self._record_after_state(node, log)
            log.info(
                f"After state: boot_id={after_state['boot_id']}, "
                f"kernel={after_state['uname']}, uptime={after_state['uptime']}s"
            )

            # Validate the reboot
            self._validate_kexec_reboot(
                node, marker, marker_path, before_state, after_state, log
            )

            log.info("Kexec reboot test completed successfully")
        finally:
            # Cleanup marker (best effort, don't fail test if cleanup fails)
            self._cleanup_marker(node, marker_path, log)
            # Unload kexec if still loaded (best effort)
            try:
                node.execute(
                    "kexec -u || true", sudo=True, shell=True, no_error_log=True
                )
            except Exception:
                pass  # Ignore cleanup errors

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

    def _record_before_state(self, node: RemoteNode, log: Logger) -> Dict[str, Any]:
        """
        Record system state before kexec reboot.

        Returns dict with boot_id, uname, uptime, cmdline.
        """
        log.debug("Recording pre-reboot state...")

        boot_id = (
            node.tools[Cat].read("/proc/sys/kernel/random/boot_id", sudo=True).strip()
        )
        uname_r = node.tools[Uname].get_linux_information().kernel_version_raw
        uptime_result = node.execute("cut -d. -f1 /proc/uptime", sudo=True)
        uptime = int(float(uptime_result.stdout.strip()))
        cmdline = node.tools[Cat].read("/proc/cmdline", sudo=True).strip()

        return {
            "boot_id": boot_id,
            "uname": uname_r,
            "uptime": uptime,
            "cmdline": cmdline,
        }

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
        for candidate in kernel_candidates:
            if node.execute(f"test -f {candidate}", sudo=True).exit_code == 0:
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
            if node.execute(f"test -f {candidate}", sudo=True).exit_code == 0:
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

    def _create_marker(
        self,
        before_state: Dict[str, Any],
        kernel_path: str,
        initrd_path: str,
    ) -> Dict[str, Any]:
        """Create marker file content for validation after reboot."""
        return {
            "nonce": str(uuid.uuid4()),
            "boot_id_before": before_state["boot_id"],
            "uname_before": before_state["uname"],
            "uptime_before": before_state["uptime"],
            "kexec_kernel": kernel_path,
            "kexec_initrd": initrd_path,
            "timestamp_epoch": time.time(),
        }

    def _write_marker(
        self, node: RemoteNode, marker: Dict[str, Any], log: Logger
    ) -> PurePosixPath:
        """Write marker file to disk for post-reboot validation.

        Returns the full path to the marker file.
        """
        marker_dir = PurePosixPath(self.MARKER_DIR)
        # Use nonce-specific filename to avoid collisions in concurrent runs
        marker_filename = f"kexec_marker_{marker['nonce']}.json"
        marker_path = marker_dir / marker_filename

        log.debug(f"Writing marker to {marker_path}")

        # Ensure directory exists
        node.execute(f"mkdir -p {marker_dir}", sudo=True)

        # Write marker as JSON using cat with here-document
        # to avoid quote escaping issues
        marker_json = json.dumps(marker, indent=2)
        write_cmd = f"cat > {marker_path} << 'EOF'\n{marker_json}\nEOF"
        result = node.execute(write_cmd, sudo=True, shell=True)

        if result.exit_code != 0:
            raise RuntimeError(
                f"Failed to write marker file to {marker_path}. "
                f"Exit code: {result.exit_code}"
            )

        # Verify marker file exists and has content
        verify_result = node.execute(f"test -s {marker_path}", sudo=True)
        if verify_result.exit_code != 0:
            raise RuntimeError(
                f"Marker file {marker_path} is empty or missing after write"
            )

        return marker_path

    def _load_kexec_image(
        self,
        node: RemoteNode,
        kernel_path: str,
        initrd_path: str,
        cmdline: str,
        log: Logger,
    ) -> None:
        """
        Load kexec image into kernel memory.

        Uses kexec -l to prepare the new kernel for execution.
        """
        log.info(f"Loading kexec image: {kernel_path}")

        # Unload any previously loaded kernel (ignore errors)
        node.execute("kexec -u || true", sudo=True, shell=True, no_error_log=True)

        # Build kexec load command with properly escaped paths and cmdline
        # Use shlex.quote to safely escape all arguments for shell
        kexec_cmd = (
            f"kexec -l {shlex.quote(kernel_path)} "
            f"--initrd={shlex.quote(initrd_path)} "
            f"--command-line={shlex.quote(cmdline)}"
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
        if "1" not in verify_result:
            log.debug("kexec_loaded sysfs shows unexpected value")

    def _trigger_kexec_reboot(self, node: RemoteNode, log: Logger) -> None:
        """
        Trigger kexec reboot.

        Tries systemctl kexec first, falls back to kexec -e.
        SSH connection will drop - this is expected.
        """
        # Try systemctl kexec first (cleaner shutdown)
        has_systemctl = node.execute("which systemctl", shell=True).exit_code == 0
        if has_systemctl:
            log.debug("Attempting systemctl kexec...")
            try:
                # This may disconnect; if it returns quickly with a failure,
                # fall back to kexec -e explicitly.
                result = node.execute(
                    "systemctl kexec",
                    sudo=True,
                    timeout=5,
                    expected_exit_code=None,
                    no_error_log=True,
                )
                if result.exit_code not in (0, None):
                    log.debug(
                        f"systemctl kexec failed with exit code "
                        f"{result.exit_code}, falling back to kexec -e..."
                    )
                    try:
                        node.execute(
                            "kexec -e",
                            sudo=True,
                            timeout=5,
                            expected_exit_code=None,
                            no_error_log=True,
                        )
                    except Exception as e:
                        log.debug(f"kexec -e disconnected as expected: {e}")
            except Exception as e:
                log.debug(f"systemctl kexec disconnected as expected: {e}")
        else:
            # Fallback to kexec -e
            log.debug("systemctl not available, using kexec -e...")
            try:
                node.execute(
                    "kexec -e",
                    sudo=True,
                    timeout=5,
                    expected_exit_code=None,
                    no_error_log=True,
                )
            except Exception as e:
                log.debug(f"kexec -e disconnected as expected: {e}")

        # Give the system a moment to start shutting down
        time.sleep(5)

    def _is_system_connected(self, node: RemoteNode, log: Logger) -> bool:
        """
        Check if system can be connected via SSH.
        Uses fresh connection attempt, not cached session.
        """
        try:
            try_connect(node._connection_info, ssh_timeout=10)  # pyright: ignore
            return True
        except Exception as e:
            log.debug(f"Connection check failed: {e}")
            return False

    def _wait_for_reconnect(self, node: RemoteNode, log: Logger) -> None:
        """
        Wait for system to reboot and reconnect.
        Uses kdump's pattern: test connection, close once, then work.
        """
        start_time = time.time()
        elapsed = 0

        while elapsed < self.RECONNECT_TIMEOUT:
            # First check if system is connectable (fresh connection test)
            if not self._is_system_connected(node, log):
                log.debug(f"System not connectable yet ({elapsed}s)")
                time.sleep(self.RECONNECT_INTERVAL)
                elapsed = int(time.time() - start_time)
                continue

            # System is connectable, close old session and execute command
            log.debug(f"System connectable after {elapsed}s, closing old session...")
            node.close()

            try:
                # Execute a simple command to verify
                result = node.execute("echo 'alive'", timeout=5)
                if result.exit_code == 0 and "alive" in result.stdout:
                    log.info(f"Reconnected successfully after {elapsed}s")
                    # Give system a few more seconds to stabilize
                    time.sleep(5)
                    return
            except Exception as e:
                log.debug(f"Command execution failed, retrying: {e}")

            time.sleep(self.RECONNECT_INTERVAL)
            elapsed = int(time.time() - start_time)

        raise RuntimeError(
            f"Failed to reconnect to node within {self.RECONNECT_TIMEOUT}s"
        )

    def _record_after_state(self, node: RemoteNode, log: Logger) -> Dict[str, Any]:
        """Record system state after kexec reboot."""
        log.debug("Recording post-reboot state...")

        boot_id = (
            node.tools[Cat].read("/proc/sys/kernel/random/boot_id", sudo=True).strip()
        )
        uname_r = node.tools[Uname].get_linux_information().kernel_version_raw
        uptime_result = node.execute("cut -d. -f1 /proc/uptime", sudo=True)
        uptime = int(float(uptime_result.stdout.strip()))

        return {
            "boot_id": boot_id,
            "uname": uname_r,
            "uptime": uptime,
        }

    def _validate_kexec_reboot(
        self,
        node: RemoteNode,
        marker: Dict[str, Any],
        marker_path: PurePosixPath,
        before_state: Dict[str, Any],
        after_state: Dict[str, Any],
        log: Logger,
    ) -> None:
        """
        Validate that kexec reboot was successful.

        Checks:
        - Marker file exists and matches
        - boot_id changed
        - uptime reset
        - System health
        """
        log.info("Validating kexec reboot...")

        # Read marker file
        marker_content = node.tools[Cat].read(str(marker_path), sudo=True)

        try:
            stored_marker = json.loads(marker_content)
        except json.JSONDecodeError as e:
            raise AssertionError(f"Marker file corrupted: {e}")

        # Validate nonce
        if stored_marker.get("nonce") != marker["nonce"]:
            raise AssertionError(
                f"Marker nonce mismatch. Expected: {marker['nonce']}, "
                f"Got: {stored_marker.get('nonce')}"
            )

        # Validate marker's stored boot_id matches before_state
        # (helps debugging if marker files get manually copied/reused)
        if stored_marker.get("boot_id_before") != before_state["boot_id"]:
            raise AssertionError(
                f"Marker boot_id mismatch. Expected: {before_state['boot_id']}, "
                f"Got: {stored_marker.get('boot_id_before')}. "
                "Marker file may be stale or corrupted."
            )

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

        # Validate uptime reset with threshold (handle slow reconnects)
        # After kexec boot, uptime should be small
        if after_state["uptime"] > self.MAX_AFTER_UPTIME:
            raise AssertionError(
                f"Uptime too high after reboot: {after_state['uptime']}s "
                f"(threshold: {self.MAX_AFTER_UPTIME}s). System may not have rebooted."
            )

        log.info(
            f"Uptime reset confirmed: {before_state['uptime']}s -> "
            f"{after_state['uptime']}s (threshold: {self.MAX_AFTER_UPTIME}s)"
        )

        # Check system health (best effort)
        self._check_system_health(node, log)

        # Optional: Check for kexec evidence in logs
        self._check_kexec_evidence(node, log)

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

    def _check_kexec_evidence(self, node: RemoteNode, log: Logger) -> None:
        """
        Check for kexec evidence in logs (best effort).

        This is informational only and not a hard requirement.
        """
        log.debug("Checking for kexec evidence in logs...")

        # Check dmesg
        try:
            dmesg_result = node.execute(
                "dmesg | grep -i kexec | head -n 5",
                sudo=True,
                shell=True,
            )
            if dmesg_result.exit_code == 0 and dmesg_result.stdout.strip():
                log.info(f"dmesg kexec evidence:\n{dmesg_result.stdout}")
        except Exception as e:
            log.debug(f"Could not check dmesg: {e}")

        # Check journalctl if available
        has_journalctl = node.execute("which journalctl", shell=True).exit_code == 0
        if has_journalctl:
            try:
                journal_result = node.execute(
                    "journalctl -b | grep -i kexec | head -n 5",
                    sudo=True,
                    shell=True,
                )
                if journal_result.exit_code == 0 and journal_result.stdout.strip():
                    log.info(f"journalctl kexec evidence:\n{journal_result.stdout}")
            except Exception as e:
                log.debug(f"Could not check journalctl: {e}")

    def _cleanup_marker(
        self, node: RemoteNode, marker_path: PurePosixPath, log: Logger
    ) -> None:
        """Remove marker file (best effort, don't fail on errors)."""
        log.debug(f"Cleaning up marker: {marker_path}")

        try:
            node.execute(f"rm -f {marker_path}", sudo=True)
        except Exception as e:
            log.debug(f"Failed to cleanup marker file {marker_path}: {e}")
