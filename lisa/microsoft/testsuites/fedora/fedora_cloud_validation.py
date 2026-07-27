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
from lisa.tools import Cat, Reboot
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

        def check_unmount_errors() -> None:
            error_check = node.execute(
                "journalctl --boot --no-pager"
                " | grep -iv 'recovery algorithm'"
                " | grep -iE '(corrupt|run fsck|recovery|recovering|tree-log replay)'",
                shell=True,
                no_error_log=True,
            )
            assert_that(error_check.stdout.strip()).described_as(
                "No filesystem corruption or recovery errors"
                " should appear in journalctl"
            ).is_empty()

        check_unmount_errors()

        reboot = node.tools[Reboot]
        reboot.reboot()

        check_unmount_errors()
