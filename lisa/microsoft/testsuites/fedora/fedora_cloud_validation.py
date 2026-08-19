# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
Fedora Cloud Validation Tests

This test suite validates Fedora cloud image configuration and
functionality. Tests cover OS identification, service status validation,
package management, and reboot integrity.
"""

from logging import Logger
from typing import Any, Dict
from uuid import uuid4

from assertpy.assertpy import assert_that

from lisa import (
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.base_tools import Service
from lisa.operating_system import Fedora
from lisa.tools import Cat, Journalctl, Pgrep, Reboot
from lisa.util import check_till_timeout


@TestSuiteMetadata(
    area="fedora",
    category="functional",
    description="""
    Fedora Cloud Image Validation Tests.

    Validates Fedora cloud image configuration across cloud platforms.
    Tests cover: OS identification, service status validation,
    package management, and reboot integrity.
    """,
)
class FedoraCloudValidation(TestSuite):
    """
    Fedora cloud image validation tests.

    These tests validate that Fedora cloud images are properly configured
    and functional across different cloud platforms (Azure, AWS, etc.).
    """

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        if type(node.os) is not Fedora:
            raise SkippedException(
                f"{node.os.information.full_version} is not supported; "
                "this suite runs on Fedora only (excluding subclasses)."
            )

    def _check_journal_corruption(self, node: Node, boot_id: str = "") -> None:
        """Scan journalctl for filesystem corruption or recovery errors."""
        corruption_keywords = [
            "dirty bit",
            "corrupt",
            "run fsck",
            "recovery",
            "recovering",
            "tree-log replay",
        ]
        journalctl = node.tools[Journalctl]
        boot_logs = journalctl.first_n_logs_from_boot(boot_id=boot_id, no_of_lines=0)
        matches = [
            line
            for line in boot_logs.splitlines()
            if any(kw in line.lower() for kw in corruption_keywords)
            and "recovery algorithm" not in line.lower()
        ]
        assert_that(matches).described_as(
            "No filesystem corruption or recovery errors should appear in journalctl"
        ).is_empty()

    def _assert_chronyd_state(
        self,
        node: Node,
        service: Service,
        expected_enabled: bool,
        expected_active: bool,
        context: str,
    ) -> None:
        assert_that(service.is_service_enabled("chronyd.service")).described_as(
            f"chronyd enablement must be correct {context}"
        ).is_equal_to(expected_enabled)

        assert_that(service.is_service_running("chronyd.service")).described_as(
            f"chronyd activity must be correct {context}"
        ).is_equal_to(expected_active)

        pgrep = node.tools[Pgrep]
        chronyd_processes = [
            process
            for process in pgrep.get_processes("chronyd")
            if process.name == "chronyd"
        ]
        if expected_active:
            assert_that(chronyd_processes).described_as(
                f"chronyd must be running {context}"
            ).is_not_empty()
        else:
            assert_that(chronyd_processes).described_as(
                f"chronyd must not be running {context}"
            ).is_empty()

    @TestCaseMetadata(
        description="""
        Verify Fedora edition self-identification.

        Validates Cloud Edition metadata in /etc/os-release and the
        fedora-release-common package version.
        """,
        priority=1,
        requirement=simple_requirement(supported_os=[Fedora]),
    )
    def verify_fedora_edition_identification(self, node: Node) -> None:
        """
        Verify that the Fedora image correctly identifies itself.

        Reads /etc/os-release and checks:
        - ID is "fedora"
        - VERSION is present
        - VARIANT and VARIANT_ID identify Fedora Cloud
        - CPE_NAME includes :fedora:<VERSION_ID>
        - Installed fedora-release-common RPM version matches VERSION_ID
        - SUPPORT_END date is still in the future
        - PRETTY_NAME field is present
        """
        cat = node.tools[Cat]

        # Source /etc/os-release and parse into a dict
        os_release_content = cat.read("/etc/os-release", force_run=True)

        fields: Dict[str, str] = {}
        for line in os_release_content.splitlines():
            if "=" in line:
                key, _, val = line.partition("=")
                fields[key.strip()] = val.strip().strip('"')

        # ID must be 'fedora'
        assert_that(fields.get("ID", "").lower()).described_as(
            "/etc/os-release ID must be 'fedora'"
        ).is_equal_to("fedora")

        version_id = fields.get("VERSION_ID", "")
        assert_that(version_id).described_as(
            "/etc/os-release must have VERSION_ID"
        ).is_not_empty()

        # VERSION field must exist
        version = fields.get("VERSION", "")
        assert_that(version).described_as(
            "/etc/os-release must have VERSION"
        ).is_not_empty()

        variant = fields.get("VARIANT", "")
        assert_that(variant).described_as(
            "Fedora Cloud images must identify the Cloud Edition"
        ).is_equal_to("Cloud Edition")
        assert_that(fields.get("VARIANT_ID", "")).described_as(
            "Fedora Cloud images must use the cloud variant identifier"
        ).is_equal_to("cloud")

        # CPE_NAME must contain :fedora:<VERSION_ID>
        cpe = fields.get("CPE_NAME", "")
        assert_that(cpe).described_as(
            f"CPE_NAME must contain ':fedora:{version_id}'"
        ).contains(f":fedora:{version_id}")

        # Installed fedora-release-common RPM version must match VERSION_ID
        rpm_ver = node.execute("rpm -q --qf '%{VERSION}' fedora-release-common")
        assert_that(rpm_ver.exit_code).described_as(
            "fedora-release-common must be installed"
        ).is_equal_to(0)
        assert_that(rpm_ver.stdout.strip()).described_as(
            f"fedora-release-common version must match VERSION_ID ({version_id})"
        ).is_equal_to(version_id)

        # SUPPORT_END must be in the future
        support_end = fields.get("SUPPORT_END", "")
        if support_end:
            date_check = node.execute(
                f'[ "$(date +%s)" -lt "$(date -d "{support_end}" +%s)" ]',
                shell=True,
            )
            assert_that(date_check.exit_code).described_as(
                f"SUPPORT_END ({support_end}) must be in the future"
            ).is_equal_to(0)

        # PRETTY_NAME field must exist
        assert_that(fields.get("PRETTY_NAME", "")).described_as(
            "/etc/os-release must have PRETTY_NAME"
        ).is_not_empty()

        node.log.info(f"Fedora edition validated: VERSION_ID={version_id}")

    @TestCaseMetadata(
        description="""
        Verify no failed systemd services after boot.

        Checks that all systemd services started successfully by verifying
        systemctl reports zero failed units.
        """,
        priority=1,
        requirement=simple_requirement(supported_os=[Fedora]),
    )
    def verify_services_started(self, node: Node) -> None:
        """
        Validate no systemd services are in failed state.

        Waits for system to settle (exit 'starting' state), then verifies
        systemctl is-system-running reports 'running'.
        """
        check_till_timeout(
            func=lambda: node.execute("systemctl is-system-running").stdout.strip()
            not in ("initializing", "starting"),
            timeout_message="System did not settle within 60 seconds",
            timeout=60,
            interval=5,
        )
        state = node.execute("systemctl is-system-running").stdout.strip()

        # After settling, verify system is running
        if state != "running":
            failed_units_result = node.execute(
                "systemctl --all --failed --no-legend --plain --no-pager"
            )
            node.log.info(f"Failed units:\n{failed_units_result.stdout}")
            assert_that(state).described_as(
                f"System must be running (got {state}). "
                f"Failed: {failed_units_result.stdout}"
            ).is_equal_to("running")

        boot_journal = node.execute("journalctl -b --no-pager")
        assert_that(boot_journal.exit_code).described_as(
            "journalctl must read the current boot journal successfully"
        ).is_equal_to(0)
        assert_that(boot_journal.stdout.lower()).described_as(
            "no service may be discarded from boot due to an ordering cycle"
        ).does_not_contain("deleted to break ordering cycle")

        node.log.info("No failed services detected")

    @TestCaseMetadata(
        description="""
        Verify DNF package install and remove operations work correctly.

        Tests package installation, RPM database verification, config file
        modification detection, and package removal via DNF.

        Requires a fresh environment because packages are installed and removed,
        leaving the OS in a modified state unsuitable for other tests.
        """,
        priority=1,
        requirement=simple_requirement(supported_os=[Fedora]),
        use_new_environment=True,
    )
    def verify_package_install_remove(self, node: Node) -> None:
        """
        Test packages (autofs and mc) install, RPM verify, and remove cycle via DNF.
        """
        # Test packages that are commonly available but not pre-installed
        test_packages = ["autofs", "mc"]

        # Ensure packages are absent before testing install — guards against
        # image variants that may pre-install these packages.
        for package in test_packages:
            node.execute(f"dnf remove -y {package}", sudo=True, no_error_log=True)

        for package in test_packages:
            install_result = node.execute(
                f"dnf install -y {package}",
                sudo=True,
                timeout=240,  # 4 min: DNF resolves deps + downloads
            )
            assert_that(install_result.exit_code).described_as(
                f"DNF install of {package} must succeed"
            ).is_equal_to(0)

            dnf_list = node.execute(
                f"dnf list --installed {package}", no_error_log=True
            )
            assert_that(dnf_list.exit_code).described_as(
                f"DNF must list {package} as installed"
            ).is_equal_to(0)

            rpm_result = node.execute(f"rpm -q {package}")
            assert_that(rpm_result.exit_code).described_as(
                f"Package {package} must be in RPM database after install"
            ).is_equal_to(0)

            # Use --noconfig for autofs whose postinstall scriptlet modifies its
            # own config files (would cause a false failure on the clean check).
            verify_result = node.execute(
                f"rpm --verify --noconfig {package}", sudo=True
            )
            assert_that(verify_result.exit_code).described_as(
                f"RPM verification of {package} (non-config files) must pass"
                " on a clean install"
            ).is_equal_to(0)

            last_config = node.execute(f"rpm -qlc {package} | tail -n1", shell=True)
            if last_config.stdout.strip():
                config_path = last_config.stdout.strip()
                node.execute(f"touch '{config_path}'", sudo=True)
                verify_modified = node.execute(
                    f"rpm --verify {package}", no_error_log=True, sudo=True
                )
                # rpm --verify returns a bitmask (e.g. 8 for mtime); assert non-zero
                assert_that(verify_modified.exit_code).described_as(
                    f"rpm --verify {package} must report failure"
                    " after config file modification"
                ).is_not_equal_to(0)
            else:
                node.log.debug(
                    f"{package} has no config files; skipping modification check"
                )

            node.log.debug(f"Package {package} installed and verified")

        remove_result = node.execute(
            f"dnf remove -y {' '.join(test_packages)}", sudo=True
        )
        assert_that(remove_result.exit_code).described_as(
            "DNF remove must succeed"
        ).is_equal_to(0)

        for package in test_packages:
            dnf_check = node.execute(
                f"dnf list --installed {package}", no_error_log=True
            )
            assert_that(dnf_check.exit_code).described_as(
                f"Package {package} must not be listed as installed after removal"
            ).is_not_equal_to(0)

            rpm_check = node.execute(f"rpm -q {package}", no_error_log=True)
            assert_that(rpm_check.exit_code).described_as(
                f"Package {package} must not be in RPM database after removal"
            ).is_not_equal_to(0)

        node.log.debug(f"Package install/remove test passed for {test_packages}")

    @TestCaseMetadata(
        description="""
        Verify system can reboot cleanly without mount point issues.

        Tests system reboot and validates no filesystem corruption or
        recovery errors appear in journalctl before and after reboot.

        Requires a fresh environment to ensure a clean boot journal
        baseline unaffected by prior test activity.
        """,
        priority=1,
        requirement=simple_requirement(supported_os=[Fedora]),
        use_new_environment=True,
    )
    def verify_reboot_and_mounts(self, node: Node) -> None:
        """
        Reboot and assert no filesystem corruption or recovery errors
        in the journal.
        """
        self._check_journal_corruption(node)

        reboot = node.tools[Reboot]
        reboot.reboot()

        self._check_journal_corruption(node, boot_id="-1")
        self._check_journal_corruption(
            node
        )  # check again after reboot to ensure no new errors

    @TestCaseMetadata(
        description="""
        Verify Fedora boots successfully to a usable state.

        Confirms the cloud image reaches its configured systemd target and
        accepts commands through the connected session.
        """,
        priority=1,
        requirement=simple_requirement(supported_os=[Fedora]),
    )
    def verify_base_startup(self, node: Node) -> None:
        default_target = node.execute("systemctl get-default")
        assert_that(default_target.exit_code).described_as(
            "systemctl must report the default boot target"
        ).is_equal_to(0)

        target = default_target.stdout.strip()
        assert_that(target).described_as(
            "the configured default boot target must be present"
        ).is_not_empty()

        active_target = node.execute(f"systemctl is-active {target}")
        assert_that(active_target.exit_code).described_as(
            f"Fedora must reach its configured default boot target {target}"
        ).is_equal_to(0)
        assert_that(active_target.stdout.strip()).described_as(
            f"the configured default boot target {target} must be active"
        ).is_equal_to("active")

        shell_check = node.execute("id -u")
        assert_that(shell_check.exit_code).described_as(
            "the connected session must execute commands after boot"
        ).is_equal_to(0)

    @TestCaseMetadata(
        description="""
        Verify SELinux is enabled in Enforcing mode after boot.

        Confirms the Fedora cloud image reports Enforcing through getenforce.
        """,
        priority=1,
        requirement=simple_requirement(supported_os=[Fedora]),
    )
    def verify_base_selinux(self, node: Node) -> None:
        getenforce = node.execute("getenforce")
        assert_that(getenforce.exit_code).described_as(
            "getenforce must execute successfully"
        ).is_equal_to(0)
        assert_that(getenforce.stdout.strip()).described_as(
            "SELinux must be enabled in Enforcing mode after boot"
        ).is_equal_to("Enforcing")

    @TestCaseMetadata(
        description="""
        Verify Fedora can update packages through the DNF command line.

        Uses the default repositories when updates are available, otherwise
        enables updates-testing for the update transaction.
        """,
        priority=1,
        requirement=simple_requirement(supported_os=[Fedora]),
        use_new_environment=True,
    )
    def verify_update_cli(self, node: Node) -> None:
        node.mark_dirty()

        update_command = "dnf update -y"
        check_result = node.execute(
            "dnf check-update --refresh",
            sudo=True,
            no_error_log=True,
            timeout=600,  # Allow 10 minutes to refresh repository metadata.
        )
        assert_that(check_result.exit_code).described_as(
            "dnf check-update must return 0 when current or 100 when updates "
            "are available; inspect repository errors in the command output"
        ).is_in(0, 100)

        if check_result.exit_code == 0:
            check_result = node.execute(
                "dnf --enablerepo=updates-testing check-update --refresh",
                sudo=True,
                no_error_log=True,
                timeout=600,  # Allow 10 minutes to refresh testing metadata.
            )
            assert_that(check_result.exit_code).described_as(
                "updates-testing must return 0 when current or 100 when updates "
                "are available; inspect repository errors in the command output"
            ).is_in(0, 100)
            if check_result.exit_code == 0:
                raise SkippedException(
                    "No package updates are available from the default or "
                    "updates-testing repositories. Retry with an older Fedora image."
                )
            update_command = "dnf --enablerepo=updates-testing update -y"

        update_result = node.execute(
            update_command,
            sudo=True,
            timeout=1200,  # Allow 20 minutes for metadata and package updates.
        )
        assert_that(update_result.exit_code).described_as(
            "dnf update must complete successfully; inspect repository and "
            "dependency errors in the command output"
        ).is_equal_to(0)

    @TestCaseMetadata(
        description="""
        Verify systemd service lifecycle operations using chronyd.

        Validates that chronyd can be stopped, started, enabled, and disabled,
        and that its configured state persists correctly across reboots.
        """,
        priority=1,
        requirement=simple_requirement(supported_os=[Fedora]),
        use_new_environment=True,
    )
    def verify_service_manipulation(self, node: Node) -> None:
        node.mark_dirty()
        reboot = node.tools[Reboot]
        systemctl = node.tools[Service]

        try:
            systemctl.stop_service("chronyd.service")
            for command in (
                "systemctl disable chronyd.service",
                "systemctl disable chrony-wait.service",
            ):
                result = node.execute(command, sudo=True)
                assert_that(result.exit_code).described_as(
                    f"{command} must succeed before the first reboot"
                ).is_equal_to(0)

            reboot.reboot()
            self._assert_chronyd_state(
                node,
                systemctl,
                expected_enabled=False,
                expected_active=False,
                context="after disabling it and rebooting",
            )

            systemctl.start_service("chronyd.service")
            self._assert_chronyd_state(
                node,
                systemctl,
                expected_enabled=False,
                expected_active=True,
                context="after starting it manually",
            )

            systemctl.stop_service("chronyd.service")
            self._assert_chronyd_state(
                node,
                systemctl,
                expected_enabled=False,
                expected_active=False,
                context="after stopping it manually",
            )

            systemctl.enable_service("chronyd.service")

            reboot.reboot()
            self._assert_chronyd_state(
                node,
                systemctl,
                expected_enabled=True,
                expected_active=True,
                context="after enabling it and rebooting",
            )

            disable_result = node.execute(
                "systemctl disable chronyd.service", sudo=True
            )
            assert_that(disable_result.exit_code).described_as(
                "chronyd must be disabled successfully"
            ).is_equal_to(0)

            reboot.reboot()
            self._assert_chronyd_state(
                node,
                systemctl,
                expected_enabled=False,
                expected_active=False,
                context="after the final disable and reboot",
            )
        finally:
            systemctl.enable_service("chronyd.service")
            systemctl.start_service("chronyd.service")
            systemctl.start_service("chrony-wait.service")

    @TestCaseMetadata(
        description="""
        Verify system logging via journalctl is working.

        Tests that journald captures boot logs, audit entries, and
        validates no filesystem corruption errors before/after reboot.
        """,
        priority=1,
        requirement=simple_requirement(supported_os=[Fedora]),
        use_new_environment=True,
    )
    def verify_system_logging(self, node: Node) -> None:
        """
        Validate system logging functionality.

        Verifies journalctl has log entries, audit records, and rsyslog
        writes to /var/log/secure when installed.
        """
        # journalctl current boot must not be empty and must contain audit entries
        journalctl = node.tools[Journalctl]
        boot_logs = journalctl.first_n_logs_from_boot(boot_id="", no_of_lines=0)
        assert_that(boot_logs).described_as(
            "journalctl must return log content"
        ).is_not_empty()

        assert_that(boot_logs).described_as(
            "journalctl must contain audit entries"
        ).contains("audit")

        test_tag = "lisa-system-logging"
        test_message = f"lisa-system-logging-validation-{uuid4()}"
        logger_result = node.execute(
            f"logger -p authpriv.notice -t {test_tag} {test_message}"
        )
        assert_that(logger_result.exit_code).described_as(
            "logger must submit a current system log message"
        ).is_equal_to(0)

        def journal_contains_test_message() -> bool:
            result = node.execute(
                f"journalctl --since '5 minutes ago' --no-pager -t {test_tag}",
                no_error_log=True,
            )
            return test_message in result.stdout

        check_till_timeout(
            journal_contains_test_message,
            timeout_message=(
                "the current test message did not appear in journald; "
                "inspect systemd-journald status and configuration"
            ),
            timeout=30,  # Allow journald time to persist the message.
            interval=2,
        )

        if node.os.package_exists("rsyslog"):  # type: ignore[attr-defined]

            def secure_log_contains_test_message() -> bool:
                result = node.execute(
                    f"grep -F '{test_message}' /var/log/secure",
                    sudo=True,
                    no_error_log=True,
                )
                return result.exit_code == 0

            check_till_timeout(
                secure_log_contains_test_message,
                timeout_message=(
                    "the current authpriv test message did not appear in "
                    "/var/log/secure; inspect rsyslog status and authpriv routing"
                ),
                timeout=30,  # Allow rsyslog time to flush the message.
                interval=2,
            )

            secure_log = node.execute(
                "tail -n 1 /var/log/secure",
                sudo=True,
                no_error_log=True,
            )
            assert_that(secure_log.stdout.strip()).described_as(
                "/var/log/secure must contain current log entries"
            ).is_not_empty()

        # Corruption scan before reboot
        self._check_journal_corruption(node)

        # Reboot and re-scan
        reboot = node.tools[Reboot]
        reboot.reboot()

        self._check_journal_corruption(node, boot_id="-1")
        self._check_journal_corruption(node)
