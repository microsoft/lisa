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

from assertpy.assertpy import assert_that

from lisa import (
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import Fedora
from lisa.tools import Cat, Journalctl, Reboot, Usermod
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

    @TestCaseMetadata(
        description="""
        Verify Fedora edition self-identification.

        Validates /etc/os-release fields, fedora-release-common package version,
        and SUPPORT_END date.
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
            failed_units_result = node.execute("systemctl --all --failed --no-pager")
            node.log.info(f"Failed units:\n{failed_units_result.stdout}")
            assert_that(state).described_as(
                f"System must be running (got {state}). "
                f"Failed: {failed_units_result.stdout}"
            ).is_equal_to("running")

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
        Base startup smoke test after machine startup.

        Validates baseline cloud image readiness: dmidecode retrieves system
        info, pciutils installs and lspci -nn enumerates PCI devices, and
        SELinux is in Enforcing mode with working mode switching.
        """,
        priority=1,
        requirement=simple_requirement(supported_os=[Fedora]),
        use_new_environment=True,
    )
    def verify_startup_and_selinux(self, node: Node) -> None:
        """
        Startup smoke test: validates dmidecode, pciutils/lspci, and SELinux.

        Verifies:
        - dmidecode retrieves system product name
        - pciutils is removed then reinstalled to exercise a full install cycle
        - lspci -nn succeeds after fresh install
        - SELinux is Enforcing by default and can toggle to Permissive and back
        """
        node.os.install_packages("dmidecode")  # type: ignore[attr-defined]
        node.mark_dirty()
        dmidecode = node.execute("dmidecode -s system-product-name", sudo=True)
        assert_that(dmidecode.exit_code).described_as(
            "dmidecode must retrieve system product name"
        ).is_equal_to(0)
        node.log.info(f"System product: {dmidecode.stdout.strip()}")

        # Remove pciutils before reinstalling to exercise a full install cycle
        node.execute("dnf remove -y pciutils", sudo=True, no_error_log=True)
        install_pciutils = node.execute(
            "dnf install -y pciutils",
            sudo=True,
            timeout=120,  # 2 min: DNF resolves deps + downloads
        )
        assert_that(install_pciutils.exit_code).described_as(
            "pciutils must install successfully after removal"
        ).is_equal_to(0)

        lspci = node.execute("lspci -nn")
        assert_that(lspci.exit_code).described_as(
            "lspci -nn must succeed after fresh pciutils install"
        ).is_equal_to(0)

        # SELinux mode toggle
        getenforce = node.execute("getenforce")
        assert_that(getenforce.stdout.strip()).described_as(
            "SELinux must be Enforcing before setenforce test"
        ).is_equal_to("Enforcing")

        try:
            setenforce_ret = node.execute("setenforce 0", sudo=True)
            assert_that(setenforce_ret.exit_code).described_as(
                "setenforce 0 must succeed"
            ).is_equal_to(0)
            permissive_check = node.execute("getenforce")
            assert_that(permissive_check.stdout.strip()).described_as(
                "SELinux must be Permissive after setenforce 0"
            ).is_equal_to("Permissive")
        finally:
            # Always restore Enforcing to avoid leaving SELinux in Permissive
            ret = node.execute("setenforce 1", sudo=True, no_error_log=True)
            if ret.exit_code != 0:
                node.log.warning(
                    f"setenforce 1 failed during cleanup (exit {ret.exit_code}): "
                    f"{ret.stderr}"
                )

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

        # If rsyslog is installed, /var/log/secure must exist
        if node.os.package_exists("rsyslog"):  # type: ignore[attr-defined]
            secure_log = node.execute("test -e /var/log/secure", sudo=True)
            assert_that(secure_log.exit_code).described_as(
                "/var/log/secure must exist when rsyslog is installed"
            ).is_equal_to(0)

        # Corruption scan before reboot
        self._check_journal_corruption(node)

        # Reboot and re-scan
        reboot = node.tools[Reboot]
        reboot.reboot()

        self._check_journal_corruption(node, boot_id="-1")
        self._check_journal_corruption(node)

    @TestCaseMetadata(
        description="""
        Verify user management operations (create, modify, delete).

        Tests useradd, usermod, chpasswd, account locking/unlocking,
        and userdel for complete user lifecycle management.
        """,
        priority=1,
        requirement=simple_requirement(supported_os=[Fedora]),
        use_new_environment=True,
    )
    def verify_user_management(self, node: Node) -> None:
        test_user = "lisatestuser"
        test_group = "lisatestgroup"
        test_group2 = (
            "lisatestgroup2"  # separate group to meaningfully test add_user_to_group
        )

        try:
            node.mark_dirty()
            # Create test group
            result = node.execute(f"groupadd {test_group}", sudo=True)
            assert_that(result.exit_code).described_as(
                f"Creating group {test_group} must succeed"
            ).is_equal_to(0)

            result = node.execute(f"groupadd {test_group2}", sudo=True)
            assert_that(result.exit_code).described_as(
                f"Creating group {test_group2} must succeed"
            ).is_equal_to(0)

            # Create test user
            result = node.execute(
                f"useradd -m -s /bin/bash -G {test_group} {test_user}",
                sudo=True,
            )
            assert_that(result.exit_code).described_as(
                f"Creating user {test_user} must succeed"
            ).is_equal_to(0)

            # Set password via chpasswd
            chpasswd = node.execute(
                f'echo "{test_user}:L1saTestPass!" | chpasswd',
                shell=True,
                sudo=True,
            )
            assert_that(chpasswd.exit_code).described_as(
                f"chpasswd for {test_user} must succeed"
            ).is_equal_to(0)

            # Verify user exists via id
            id_result = node.execute(f"id {test_user}")
            assert_that(id_result.exit_code).described_as(
                f"id {test_user} must succeed"
            ).is_equal_to(0)

            # Verify groups — confirm test_group was assigned at useradd time
            groups_result = node.execute(f"groups {test_user}")
            assert_that(groups_result.exit_code).described_as(
                f"groups {test_user} must succeed"
            ).is_equal_to(0)
            assert_that(groups_result.stdout).described_as(
                f"{test_user} must be a member of {test_group} after useradd"
            ).contains(test_group)

            node.os.install_packages("zsh")  # type: ignore[attr-defined]
            usermod_shell = node.execute(f"usermod -s /bin/zsh {test_user}", sudo=True)
            assert_that(usermod_shell.exit_code).described_as(
                f"usermod -s /bin/zsh for {test_user} must succeed"
            ).is_equal_to(0)

            # Modify: add user to test_group2 using Usermod tool
            # (test_group was already assigned at useradd time; use a different group
            # so add_user_to_group is actually exercised)
            node.tools[Usermod].add_user_to_group(
                group=test_group2, user=test_user, sudo=True
            )

            # Verify user appears in /etc/passwd using Cat tool
            passwd_content = node.tools[Cat].read("/etc/passwd", force_run=True)
            assert_that(passwd_content).described_as(
                f"{test_user} must appear in /etc/passwd"
            ).contains(test_user)

            # Verify groups again — both groups must appear in output
            groups_result2 = node.execute(f"groups {test_user}")
            assert_that(groups_result2.exit_code).described_as(
                f"groups {test_user} must succeed after modifications"
            ).is_equal_to(0)
            assert_that(groups_result2.stdout).described_as(
                f"{test_user} must be a member of {test_group2} after add_user_to_group"
            ).contains(test_group2)

            # Lock user account
            lock_result = node.execute(f"usermod -L {test_user}", sudo=True)
            assert_that(lock_result.exit_code).described_as(
                "Locking user account must succeed"
            ).is_equal_to(0)

            # Verify account is locked — check second field of passwd -S output
            passwd_status = node.execute(f"passwd -S {test_user}", sudo=True)
            assert_that(passwd_status.exit_code).described_as(
                f"passwd -S {test_user} must succeed"
            ).is_equal_to(0)
            passwd_fields = passwd_status.stdout.split()
            assert_that(len(passwd_fields)).described_as(
                f"passwd -S output must have at least 2 fields for {test_user}"
            ).is_greater_than_or_equal_to(2)
            assert_that(passwd_fields[1]).described_as(
                "passwd -S second field must be 'L' when account is locked"
            ).is_equal_to("L")

            # Unlock user account
            unlock_result = node.execute(f"usermod -U {test_user}", sudo=True)
            assert_that(unlock_result.exit_code).described_as(
                "Unlocking user account must succeed"
            ).is_equal_to(0)

            # Verify unlock — check second field of passwd -S output
            unlock_status = node.execute(f"passwd -S {test_user}", sudo=True)
            assert_that(unlock_status.exit_code).described_as(
                f"passwd -S {test_user} must succeed after unlock"
            ).is_equal_to(0)
            unlock_fields = unlock_status.stdout.split()
            assert_that(len(unlock_fields)).described_as(
                f"passwd -S output must have at least 2 fields for {test_user}"
            ).is_greater_than_or_equal_to(2)
            assert_that(unlock_fields[1]).described_as(
                "passwd -S second field must be 'P' when account is unlocked"
            ).is_equal_to("P")

            # Remove user and verify deletion
            userdel_result = node.execute(f"userdel -r {test_user}", sudo=True)
            assert_that(userdel_result.exit_code).described_as(
                f"userdel -r {test_user} must succeed"
            ).is_equal_to(0)

            id_after = node.execute(f"id {test_user}", no_error_log=True)
            assert_that(id_after.exit_code).described_as(
                f"id {test_user} must fail after userdel"
            ).is_not_equal_to(0)

        finally:
            node.execute(f"userdel -r {test_user}", sudo=True, no_error_log=True)
            node.execute(f"groupdel {test_group}", sudo=True, no_error_log=True)
            node.execute(f"groupdel {test_group2}", sudo=True, no_error_log=True)
