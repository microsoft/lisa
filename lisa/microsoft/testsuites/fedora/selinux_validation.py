# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from datetime import datetime, timedelta

from assertpy.assertpy import assert_that

from lisa import (
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import Fedora
from lisa.util import check_till_timeout


@TestSuiteMetadata(
    area="fedora",
    category="functional",
    description="""
    Fedora SELinux Validation Tests.

    Validates SELinux configuration, policy enforcement, and security
    tool functionality on Fedora cloud images.
    """,
)
class FedoraSELinuxValidation(TestSuite):
    _SELINUX_FS_MOUNT = "/sys/fs/selinux"

    def _assert_rpm_installed(self, node: Node, packages: list[str]) -> None:
        """Assert that packages are already installed."""
        for pkg in packages:
            result = node.execute(f"rpm -q {pkg}")
            assert_that(result.exit_code).described_as(
                f"{pkg} package must be installed"
            ).is_equal_to(0)

    def _backup_audit_rules(self, node: Node) -> str:
        """Backup current audit rules and clear them."""
        backup = node.execute(
            "auditctl -l | sed 's/^No rules$/# No rules/'", shell=True, sudo=True
        )
        node.execute("auditctl -D", sudo=True)
        node.execute("auditctl -w /etc/shadow -p w", sudo=True)
        return backup.stdout

    def _restore_audit_rules(self, node: Node, backup: str) -> None:
        """Restore audit rules from backup."""
        node.execute("auditctl -D", sudo=True, no_error_log=True)
        if backup.strip():
            node.execute(
                f"echo '{backup}' > /tmp/audit_backup && auditctl -R /tmp/audit_backup",
                shell=True, sudo=True, no_error_log=True
            )
            node.execute("rm -f /tmp/audit_backup", sudo=True, no_error_log=True)

    def _wait_for_service_active(
        self, node: Node, service: str, timeout: int = 30
    ) -> None:
        """Wait for a systemd service to become active."""
        def check_active() -> bool:
            result = node.execute(f"systemctl is-active {service}", no_error_log=True)
            return result.stdout.strip() == "active"

        check_till_timeout(
            check_active,
            timeout_message=f"{service} service did not become active",
            timeout=timeout,
        )

    def _assert_cmd_fails_with_error(
        self, node: Node, cmd: str, error_keywords: list[str], desc: str
    ) -> None:
        """Assert command fails or outputs error keywords."""
        result = node.execute(cmd, shell=True, sudo=True, no_error_log=True)
        combined = (result.stdout + result.stderr).lower()
        has_error = (
            any(kw in combined for kw in error_keywords) or result.exit_code != 0
        )
        assert_that(has_error).described_as(
            f"{desc} (got: {combined[:200]})"
        ).is_true()

    def _setenforce_and_verify(self, node: Node, value: str) -> None:
        """Run setenforce <value> and verify both exit code and enforce file."""
        r = node.execute(f"setenforce {value}", sudo=True)
        assert_that(r.exit_code).described_as(
            f"setenforce {value} must succeed"
        ).is_equal_to(0)
        grep = node.execute(f"grep {value} {self._SELINUX_FS_MOUNT}/enforce")
        assert_that(grep.exit_code).described_as(
            f"enforce file must contain {value} after setenforce {value}"
        ).is_equal_to(0)

    @TestCaseMetadata(
        description="""
        Verify setenforce command works correctly.

        Tests switching between SELinux enforcing and permissive modes,
        validates mode changes are reflected in the enforce file and
        audit logs, and verifies error handling for edge cases.
        """,
        priority=1,
        requirement=simple_requirement(supported_os=[Fedora]),
        use_new_environment=True,
    )
    def verify_setenforce(self, node: Node) -> None:
        self._assert_rpm_installed(node, ["libselinux", "libselinux-utils"])

        # setenforce binary must exist and be executable
        help_result = node.execute("setenforce --help", no_error_log=True)
        assert_that(help_result.exit_code).described_as(
            "setenforce binary must exist and be executable (--help exits 0 or 1)"
        ).is_in(0, 1)

        # auditctl must be present
        which_auditctl = node.execute("which auditctl")
        assert_that(which_auditctl.exit_code).described_as(
            "auditctl must be present for proper functioning"
        ).is_equal_to(0)

        # auditd must be active on boot; not started manually
        self._wait_for_service_active(node, "auditd", timeout=60)

        backup_rules = ""
        try:
            backup_rules = self._backup_audit_rules(node)
            node.log.info(f"Original audit rules:\n{backup_rules}")

            # timestamp - 1s mirrors bash `sleep 1`; time.sleep() not permitted in LISA
            raw_time = node.execute("date '+%m/%d/%Y %T'").stdout.strip()
            start_time = (
                datetime.strptime(raw_time, "%m/%d/%Y %H:%M:%S") - timedelta(seconds=1)
            ).strftime("%m/%d/%Y %H:%M:%S")

            # setenforce 1 → 0 → 1 with enforce file verification at each step
            self._setenforce_and_verify(node, "1")
            self._setenforce_and_verify(node, "0")
            self._setenforce_and_verify(node, "1")  # restore

            # poll until MAC_STATUS record appears, scoped to start_time
            def check_mac_status_enforcing1() -> bool:
                result = node.execute(
                    f'ausearch --input-logs -m MAC_STATUS -i -ts {start_time}'
                    ' | grep "type=MAC_STATUS"'
                    ' | grep "enforcing=1" | grep "old_enforcing=0"',
                    sudo=True, no_error_log=True, shell=True,
                )
                return result.exit_code == 0

            check_till_timeout(
                check_mac_status_enforcing1,
                timeout_message=(
                    "MAC_STATUS record enforcing=1 old_enforcing=0"
                    " not found in audit log"
                ),
                timeout=30,
            )

            # Verify enforcing=0 record exists
            avc0_result = node.execute(
                f'ausearch --input-logs -m MAC_STATUS -i -ts {start_time}'
                ' | grep "type=MAC_STATUS"'
                ' | grep "enforcing=0" | grep "old_enforcing=1"',
                sudo=True, no_error_log=True, shell=True,
            )
            assert_that(avc0_result.exit_code).described_as(
                "MAC_STATUS record enforcing=0 old_enforcing=1 must exist in audit log"
            ).is_equal_to(0)

            # Associated SYSCALL record must show comm=setenforce
            syscall_result = node.execute(
                f'ausearch --input-logs -m MAC_STATUS -i -ts {start_time}'
                ' | grep "type=SYSCALL" | grep "comm=setenforce"',
                sudo=True, no_error_log=True, shell=True,
            )
            assert_that(syscall_result.exit_code).described_as(
                "MAC_STATUS event with comm=setenforce must exist in audit log"
            ).is_equal_to(0)

            node.log.info("MAC_STATUS/SYSCALL audit records verified")

            # Edge case: selinuxfs unmounted
            umount_result = node.execute(
                f"umount --lazy {self._SELINUX_FS_MOUNT}", sudo=True, no_error_log=True
            )
            if umount_result.exit_code == 0:
                for val in ["1", "0", "Enforcing", "Permissive"]:
                    self._assert_cmd_fails_with_error(
                        node, f"setenforce {val} 2>&1",
                        ["selinux is disabled"],
                        f"setenforce {val} with selinuxfs unmounted"
                        " must indicate disabled",
                    )
                node.execute(
                    f"mount -t selinuxfs none {self._SELINUX_FS_MOUNT}",
                    sudo=True,
                )
                node.log.info("Edge case: selinuxfs unmounted passed")
            else:
                node.log.info(
                    "Edge case: selinuxfs unmounted skipped:"
                    " lazy umount not supported"
                )

            # Edge case: enforce file locked
            node.execute("touch /var/tmp/selinux_enforce_bind_test", sudo=True)
            node.execute("chattr +i /var/tmp/selinux_enforce_bind_test", sudo=True)
            node.execute(
                f"mount --bind /var/tmp/selinux_enforce_bind_test"
                f" {self._SELINUX_FS_MOUNT}/enforce",
                sudo=True,
            )
            try:
                for val in ["1", "0", "Enforcing", "Permissive"]:
                    self._assert_cmd_fails_with_error(
                        node, f"setenforce {val} 2>&1",
                        ["failed"],
                        f"setenforce {val} with bound enforce file must report failure"
                    )
            finally:
                node.execute(
                    f"umount {self._SELINUX_FS_MOUNT}/enforce 2>/dev/null || true",
                    shell=True, sudo=True, no_error_log=True
                )
                node.execute(
                    "chattr -i /var/tmp/selinux_enforce_bind_test 2>/dev/null || true",
                    shell=True, sudo=True, no_error_log=True
                )
                node.execute(
                    "rm -f /var/tmp/selinux_enforce_bind_test",
                    sudo=True,
                    no_error_log=True,
                )
            node.log.info("Edge case: enforce file locked passed")

            node.log.info("setenforce validation passed")

        finally:
            self._restore_audit_rules(node, backup_rules)
            node.log.info("audit rules restored after setenforce test")

    @TestCaseMetadata(
        description="""
        Verify SELinux info commands: sestatus, getenforce, and avcstat.

        Tests that getenforce accurately reports mode changes, sestatus
        displays all required policy fields and contexts, and avcstat
        shows live AVC cache statistics.
        """,
        priority=1,
        requirement=simple_requirement(supported_os=[Fedora]),
        use_new_environment=True,
    )
    def verify_selinux_info(self, node: Node) -> None:
        self._assert_rpm_installed(node, ["policycoreutils"])

        # === getenforce: mode read ===
        node.log.info("Checking getenforce...")
        getenforce = node.execute("getenforce")
        assert_that(getenforce.exit_code).described_as(
            "getenforce command must succeed"
        ).is_equal_to(0)

        mode = getenforce.stdout.strip()
        valid_modes = ["Enforcing", "Permissive", "Disabled"]
        assert_that(mode).described_as(
            f"getenforce must return valid mode, got: {mode}"
        ).is_in(*valid_modes)

        original_mode = mode

        if mode != "Disabled":
            enforce_file = node.execute(f"cat {self._SELINUX_FS_MOUNT}/enforce")
            expected_value = "1" if mode == "Enforcing" else "0"
            assert_that(enforce_file.stdout.strip()).described_as(
                f"enforce file must match getenforce mode {mode}"
            ).is_equal_to(expected_value)

        assert_that(mode).described_as(
            "Fedora cloud image should have SELinux in Enforcing mode"
        ).is_equal_to("Enforcing")

        # === getenforce: mode toggle ===
        try:
            # setenforce 0 → getenforce must report Permissive
            node.execute("setenforce 0", sudo=True)
            perm_check = node.execute("getenforce")
            assert_that(perm_check.stdout.strip()).described_as(
                "getenforce must report 'Permissive' after setenforce 0"
            ).is_equal_to("Permissive")

            # setenforce 1 → getenforce must report Enforcing
            node.execute("setenforce 1", sudo=True)
            enf_check = node.execute("getenforce")
            assert_that(enf_check.stdout.strip()).described_as(
                "getenforce must report 'Enforcing' after setenforce 1"
            ).is_equal_to("Enforcing")

        finally:
            restore_val = "1" if original_mode == "Enforcing" else "0"
            node.execute(f"setenforce {restore_val}", sudo=True, no_error_log=True)

        # === sestatus: standard fields ===
        node.log.info("Checking sestatus...")
        sestatus = node.execute("sestatus")
        assert_that(sestatus.exit_code).described_as(
            "sestatus command must succeed"
        ).is_equal_to(0)

        output = sestatus.stdout

        sestatus_fields = [
            (r"SELinux status:\s+enabled", "SELinux status: enabled"),
            (r"SELinuxfs mount:\s+/sys/fs/selinux", "SELinuxfs mount"),
            (
                r"SELinux mount point:\s+/sys/fs/selinux"
                r"|SELinux root directory:\s+\S+",
                "SELinux root directory",
            ),
            (r"Current mode:\s+enforcing", "Current mode: enforcing"),
            (r"Mode from config file:\s+\S+", "Mode from config file"),
            (r"Loaded policy name:\s+\S+", "Loaded policy name"),
            (r"Policy MLS status:\s+\S+", "Policy MLS status"),
            (r"Policy deny_unknown status:\s+\S+", "Policy deny_unknown status"),
            (r"Max kernel policy version:\s+\d+", "Max kernel policy version"),
        ]
        for pattern, desc in sestatus_fields:
            assert_that(output).described_as(
                f"sestatus must show {desc}"
            ).matches(pattern)

        # === sestatus: policy booleans ===
        sestatus_b = node.execute("sestatus -b")
        assert_that(sestatus_b.exit_code).described_as(
            "sestatus -b must succeed"
        ).is_equal_to(0)
        assert_that(sestatus_b.stdout).described_as(
            "sestatus -b must show 'Policy booleans:' header"
        ).contains("Policy booleans:")
        # mount_anyfile should be on; deny_ptrace should be off on default Fedora
        assert_that(sestatus_b.stdout).described_as(
            "sestatus -b must contain mount_anyfile on"
        ).matches(r"mount_anyfile\s+on")
        assert_that(sestatus_b.stdout).described_as(
            "sestatus -b must contain deny_ptrace off"
        ).matches(r"deny_ptrace\s+off")

        # === sestatus: security contexts ===
        sestatus_v = node.execute("sestatus -v")
        assert_that(sestatus_v.exit_code).described_as(
            "sestatus -v must succeed"
        ).is_equal_to(0)
        _CON = r"[a-z_]+_u:[a-z_]+_r:[a-z_]+_t:s\d+"
        for pattern, desc in [
            (r"Process contexts:", "Process contexts section"),
            (r"Current context:\s+" + _CON, "Current context with valid SELinux label"),
            (r"Init context:\s+system_u:system_r:init_t:s0", "Init context"),
            (r"File contexts:", "File contexts section"),
            (r"/etc/passwd\s+" + _CON, "/etc/passwd context with valid SELinux label"),
        ]:
            assert_that(sestatus_v.stdout).described_as(
                f"sestatus -v must show {desc}"
            ).matches(pattern)

        # === avcstat: cache statistics ===
        node.log.info("Checking avcstat...")
        avcstat1 = node.execute("avcstat")
        assert_that(avcstat1.exit_code).described_as(
            "avcstat command must succeed"
        ).is_equal_to(0)

        avc_output = avcstat1.stdout
        expected_columns = ["lookups", "hits", "misses", "allocs", "reclaims", "frees"]
        for col in expected_columns:
            assert_that(avc_output.lower()).described_as(
                f"avcstat must show '{col}' column"
            ).contains(col)
        assert_that(avc_output).described_as(
            "avcstat must show a row of numeric values"
        ).matches(r"\s+\d+\s+\d+\s+\d+\s+\d+\s+\d+\s+\d+")

        # Trigger a filesystem access to ensure AVC lookups increment between runs
        node.execute("ls /etc/passwd", no_error_log=True)
        avcstat2 = node.execute("avcstat")
        assert_that(avcstat2.stdout).described_as(
            "Two consecutive avcstat outputs must differ (AVC cache is active)"
        ).is_not_equal_to(avcstat1.stdout)

        node.log.info("selinux-info validation passed")
