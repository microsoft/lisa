from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from lisa.node import Node
from lisa.testsuite import TestCaseMetadata, TestSuite, TestSuiteMetadata

if TYPE_CHECKING:
    from lisa.util import Logger


def _get_imds_compute_url(api_version: str = "2021-02-01") -> str:
    """Generate IMDS compute endpoint URL with specified API version."""
    # Note: HTTP (not HTTPS) is required for Azure IMDS - this is by design
    base_url = "http://169.254.169.254/metadata/instance/compute"
    return f"{base_url}?api-version={api_version}"  # noqa: S104


@TestSuiteMetadata(
    area="sanity",
    category="functional",
    description=(
        "Basic sanity checks to ensure the test VM is not compromised when "
        "using non-marketplace images."
    ),
)
class SanitySuite(TestSuite):
    """
    Sanity checks that are cheap and vendor-agnostic.
    Only run on non-marketplace images (AITL custom builds, gallery images, etc).
    """

    # Constants for IMDS retry configuration
    IMDS_MAX_RETRIES = 2
    IMDS_RETRY_DELAY_SECONDS = 1.0
    IMDS_API_VERSION = "2021-02-01"

    # Constants for file permission checks
    SSH_AUTHORIZED_KEYS_MAX_MODE = 0o600
    SSH_CONFIG_MAX_MODE = 0o644
    SHADOW_FILE_OTHERS_PERMISSIONS_MASK = 0o007  # Last 3 bits for 'others' permissions
    WORLD_WRITABLE_MASK = 0o002  # World write bit

    # System file paths
    CRITICAL_SYSTEM_FILES = [
        "/etc/passwd",
        "/etc/shadow",
        "/etc/ssh/sshd_config",
        "/bin/sh",
    ]

    # ------------------------- helpers (no decorators) -------------------------

    def _is_marketplace_image(self, node: Node) -> bool:
        """
        Return True if the VM image comes from Marketplace (per Azure metadata).
        Falls back to False on any failure (prefer running safety checks).
        Uses retry mechanism to handle transient IMDS failures.
        """
        imds_url = _get_imds_compute_url(self.IMDS_API_VERSION)

        # Total 3 attempts: 0, 1, 2
        for attempt_number in range(self.IMDS_MAX_RETRIES + 1):
            try:
                # Cloud-init installs curl/wget typically; use wget --header for IMDS.
                command = (
                    "wget -qO- --header Metadata:true "
                    f"'{imds_url}' || "
                    "curl -s -H Metadata:true "
                    f"'{imds_url}'"
                )
                response = node.execute(command, sudo=False)
                if response.exit_code != 0 or not response.stdout:
                    if attempt_number < self.IMDS_MAX_RETRIES:
                        self._log.debug(
                            f"IMDS attempt {attempt_number + 1} failed, retrying..."
                        )
                        time.sleep(self.IMDS_RETRY_DELAY_SECONDS)
                        continue
                    self._log.debug(
                        "All IMDS attempts failed, assuming non-marketplace image"
                    )
                    return False

                metadata = json.loads(response.stdout)
                # Heuristic: marketplace images have plan/publisher/offer/sku metadata.
                publisher = str(metadata.get("publisher", "")).strip().lower()
                offer = str(metadata.get("offer", "")).strip().lower()
                sku = str(metadata.get("sku", "")).strip().lower()

                self._log.debug(
                    f"IMDS response: publisher='{publisher}', "
                    f"offer='{offer}', sku='{sku}'"
                )

                # If all three exist, treat as marketplace.
                is_marketplace_image = bool(publisher and offer and sku)
                image_type = (
                    "marketplace" if is_marketplace_image else "non-marketplace"
                )
                self._log.debug(f"Detected {image_type} image")
                return is_marketplace_image

            except json.JSONDecodeError as json_error:
                self._log.debug(
                    f"IMDS JSON parse error on attempt {attempt_number + 1}: "
                    f"{json_error}"
                )
                if attempt_number < self.IMDS_MAX_RETRIES:
                    time.sleep(self.IMDS_RETRY_DELAY_SECONDS)
                    continue
            except Exception as general_error:
                self._log.debug(
                    f"IMDS error on attempt {attempt_number + 1}: {general_error}"
                )
                if attempt_number < self.IMDS_MAX_RETRIES:
                    time.sleep(self.IMDS_RETRY_DELAY_SECONDS)
                    continue

        # If all attempts failed, assume non-marketplace (prefer running checks)
        self._log.debug("All IMDS attempts failed, defaulting to non-marketplace image")
        return False

    def _check_ssh_security(self, log: "Logger", node: Node) -> None:
        """
        Check SSH configuration for obvious security issues.
        Only checks clear violations, not subjective configurations.
        """
        # Check SSH-related file permissions (if they exist)
        ssh_security_checks = [
            (
                "/root/.ssh/authorized_keys",
                self.SSH_AUTHORIZED_KEYS_MAX_MODE,
                "should not be world-readable",
            ),
            (
                "/etc/ssh/sshd_config",
                self.SSH_CONFIG_MAX_MODE,
                "should not be world-writable",
            ),
        ]

        for file_path, max_safe_mode, security_description in ssh_security_checks:
            # Only check if file exists - missing files are not an error
            existence_check_command = f"test -f '{file_path}'"
            existence_response = node.execute(existence_check_command, sudo=True)
            if existence_response.exit_code == 0:
                permissions_command = f"stat -c '%a' '{file_path}'"
                permissions_response = node.execute(permissions_command, sudo=True)
                if (
                    permissions_response.exit_code == 0
                    and permissions_response.stdout.strip()
                ):
                    try:
                        # Parse octal mode
                        file_mode = int(permissions_response.stdout.strip(), 8)
                        if file_mode > max_safe_mode:
                            # Use assert for clear security violations
                            raise AssertionError(
                                f"{file_path} has mode {file_mode:o}, "
                                f"{security_description}. "
                                f"Expected mode should be {max_safe_mode:o} "
                                f"or more restrictive."
                            )
                        log.debug(
                            f"{file_path} permissions check passed "
                            f"(mode: {file_mode:o})"
                        )
                    except ValueError as parsing_error:
                        log.debug(
                            f"Could not parse mode for {file_path}: " f"{parsing_error}"
                        )

    def _check_user_accounts(self, log: "Logger", node: Node) -> None:
        """
        Check for obvious user account anomalies.
        Only flags clear security violations, not subjective configurations.
        """
        # Check for multiple UID 0 accounts (clear security issue)
        uid_zero_check_command = "awk -F: '$3==0 {print $1}' /etc/passwd"
        uid_check_response = node.execute(uid_zero_check_command, sudo=True)
        if uid_check_response.exit_code == 0 and uid_check_response.stdout.strip():
            uid_zero_users = [
                username.strip()
                for username in uid_check_response.stdout.strip().split("\n")
                if username.strip()
            ]

            # Filter out 'root' - it's expected to have UID 0
            non_root_uid_zero_users = [
                username for username in uid_zero_users if username != "root"
            ]

            if non_root_uid_zero_users:
                # Multiple UID 0 accounts is a clear security violation
                raise AssertionError(
                    f"Found non-root users with UID 0: {non_root_uid_zero_users}. "
                    f"Only 'root' should have UID 0."
                )

            log.debug(f"User account UID check passed. UID 0 users: {uid_zero_users}")
        else:
            log.debug(
                "Could not check UID 0 accounts - /etc/passwd may be inaccessible"
            )

    def _should_run_sanity(self, node: Node) -> bool:
        """
        Only run sanity checks on non-marketplace images.
        """
        return not self._is_marketplace_image(node)

    def _check_basic_integrity(self, log: "Logger", node: Node) -> None:
        """
        Comprehensive but conservative integrity checks:
        - critical system files exist and are regular files
        - /etc/shadow permissions sane
        - no unexpected world-writable bits on key files
        - SSH security configuration checks
        - basic user account anomaly detection
        All checks are designed to avoid false positives in normal environments.
        """
        log.debug("Starting basic integrity checks...")

        # 1) Important files should exist.
        for critical_file_path in self.CRITICAL_SYSTEM_FILES:
            file_existence_response = node.execute(
                f"test -f '{critical_file_path}'", sudo=True
            )
            assert (
                file_existence_response.exit_code == 0
            ), f"missing or invalid file: {critical_file_path}"
        log.debug("Critical system files existence check passed")

        # 2) /etc/shadow should not be world-readable.
        shadow_stat_response = node.execute("stat -c '%a' /etc/shadow", sudo=True)
        assert shadow_stat_response.exit_code == 0, "cannot stat /etc/shadow"
        shadow_file_mode = int(shadow_stat_response.stdout.strip().strip("'"))
        # typically 640 or 600; reject anything with 'others' read/write/exec.
        others_permissions = shadow_file_mode & self.SHADOW_FILE_OTHERS_PERMISSIONS_MASK
        assert others_permissions == 0, (
            f"/etc/shadow mode suspicious: {shadow_file_mode:o}, "
            f"others have permissions: {others_permissions}"
        )
        log.debug("Shadow file permissions check passed")

        # 3) sshd_config should not be world-writable.
        sshd_config_stat_response = node.execute(
            "stat -c '%a' /etc/ssh/sshd_config", sudo=True
        )
        assert sshd_config_stat_response.exit_code == 0, "cannot stat sshd_config"
        sshd_config_mode = int(sshd_config_stat_response.stdout.strip().strip("'"))
        is_world_writable = (sshd_config_mode & self.WORLD_WRITABLE_MASK) != 0
        assert not is_world_writable, (
            f"sshd_config must not be world-writable, "
            f"current mode: {sshd_config_mode:o}"
        )
        log.debug("SSH config permissions check passed")

        # 4) SSH security checks (new)
        self._check_ssh_security(log, node)
        log.debug("SSH security checks passed")

        # 5) User account checks (new)
        self._check_user_accounts(log, node)
        log.debug("User account checks passed")

    # --------------------------- actual test case -----------------------------

    @TestCaseMetadata(
        description=(
            "Run comprehensive integrity checks only on non-marketplace images to "
            "detect obvious compromise indicators including: unsafe file permissions, "
            "missing critical files, SSH security issues, and user account anomalies. "
            "All checks are conservative to avoid false positives."
        ),
        priority=3,
    )
    def verify_vm_not_compromised(self, log: "Logger", node: Node) -> None:
        """
        If the image is from marketplace, skip. Otherwise run comprehensive but
        conservative integrity checks to catch obvious compromise indicators.
        """
        if not self._should_run_sanity(node):
            self._log.skip(
                "Skipping sanity check: marketplace image detected per IMDS."
            )
            return

        log.info("Running non-marketplace VM comprehensive sanity checks...")
        try:
            self._check_basic_integrity(log, node)
            log.info("All sanity checks completed successfully.")
        except Exception as integrity_check_error:
            log.error(f"Sanity check failed: {integrity_check_error}")
            raise
