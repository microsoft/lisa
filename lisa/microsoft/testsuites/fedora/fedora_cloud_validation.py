# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
Fedora Cloud Validation Tests

This test suite validates Fedora cloud image configuration and
functionality. Tests cover OS identification, package management,
boot validation, service status, system logging, and user management.
"""

import re
from typing import Dict

from assertpy.assertpy import assert_that

from lisa import (
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import Fedora
from lisa.tools import Cat


@TestSuiteMetadata(
    area="fedora",
    category="functional",
    description="""
    Fedora Cloud Image Validation Tests.

    Validates Fedora cloud image configuration across cloud platforms.
    Tests cover: OS identification, package management, boot validation,
    service status, system logging, and user management.
    """,
)
class FedoraCloudValidation(TestSuite):
    """
    Fedora cloud image validation tests.

    These tests validate that Fedora cloud images are properly configured
    and functional across different cloud platforms (Azure, AWS, etc.).
    """

    @TestCaseMetadata(
        description="""
        Verify Fedora edition self-identification.

        Validates /etc/os-release fields, fedora-release package version,
        SUPPORT_END date, and URL accessibility for all *_URL fields.
        """,
        priority=1,
        requirement=simple_requirement(supported_os=[Fedora]),
    )
    def verify_fedora_edition_identification(self, node: Node) -> None:
        """
        Verify that the Fedora image correctly identifies itself.

        Reads /etc/os-release and checks:
        - ID is "fedora"
        - VERSION contains VERSION_ID (e.g. "43" is in "Forty Three")
        - CPE_NAME includes :fedora:<VERSION_ID>
        - Installed fedora-release RPM version matches VERSION_ID
        - SUPPORT_END date is still in the future
        - PRETTY_NAME and VERSION keys are present
        - All *_URL keys return HTTP 2xx/3xx
        - hostnamectl mentions "Linux"
        - /etc/fedora-release matches "Fedora release N (Name)"
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

        # VERSION string must contain VERSION_ID
        version = fields.get("VERSION", "")
        assert_that(version).described_as(
            f"VERSION ({version}) must contain VERSION_ID ({version_id})"
        ).contains(version_id)

        # CPE_NAME must contain :fedora:<VERSION_ID>
        cpe = fields.get("CPE_NAME", "")
        assert_that(cpe).described_as(
            f"CPE_NAME must contain ':fedora:{version_id}'"
        ).contains(f":fedora:{version_id}")

        # Installed *-release RPM version must match VERSION_ID
        rpm_result = node.execute(
            "rpm -qa | grep fedora-release | tail -n1", shell=True
        )
        release_pkg = rpm_result.stdout.strip()
        if release_pkg:
            rpm_ver = node.execute(f"rpm -q --qf '%{{VERSION}}' {release_pkg}")
            assert_that(rpm_ver.stdout.strip()).described_as(
                f"Release package version must match VERSION_ID ({version_id})"
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

        # PRETTY_NAME and VERSION fields must exist
        assert_that(fields.get("PRETTY_NAME", "")).described_as(
            "/etc/os-release must have PRETTY_NAME"
        ).is_not_empty()
        assert_that(version).described_as(
            "/etc/os-release must have VERSION"
        ).is_not_empty()

        # hostnamectl must mention Linux (not just Fedora)
        hostnamectl = node.execute("hostnamectl")
        assert_that(hostnamectl.exit_code).described_as(
            "hostnamectl must succeed"
        ).is_equal_to(0)
        assert_that(hostnamectl.stdout).described_as(
            "hostnamectl must show 'Linux'"
        ).contains("Linux")

        # /etc/fedora-release must match: Fedora release <N> (<Name>)
        fedora_release = cat.read("/etc/fedora-release", force_run=True).strip()
        release_match = re.match(r"^Fedora release \d+ \([A-Za-z ]+\)$", fedora_release)
        assert_that(release_match is not None).described_as(
            f"/etc/fedora-release format invalid: '{fedora_release}'"
        ).is_true()

        node.log.info(
            f"Fedora edition validated: VERSION_ID={version_id}, "
            f"fedora-release='{fedora_release}'"
        )

        # Verify all *_URL fields in /etc/os-release return HTTP 2xx or 3xx
        url_fields = {k: v for k, v in fields.items() if k.endswith("_URL") and v}
        for key, url in url_fields.items():
            node.log.info(f"Checking URL: {key}={url}")
            curl = node.execute(
                "curl -IsSL --connect-timeout 5 --max-time 15 --retry 2"
                f' -w "%{{http_code}}" -o /dev/null "{url}"',
                shell=True,
                no_error_log=True,
                timeout=60,
            )
            assert_that(curl.exit_code).described_as(
                f"curl must succeed for {key}={url}"
            ).is_equal_to(0)
            http_code = curl.stdout.strip()
            assert_that(http_code[:1]).described_as(
                f"{key}={url} must return HTTP 2xx/3xx (got {http_code})"
            ).is_in("2", "3")
            node.log.info(f"{key} HTTP {http_code}: OK")

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

        Verifies systemctl --all --failed reports zero loaded failed units.
        """
        # Check for failed services
        result = node.execute("systemctl --all --failed --no-pager")
        node.log.info(f"systemctl --all --failed output:\n{result.stdout}")

        # Check for "0 loaded units" in output (success case)
        assert_that(result.stdout).described_as(
            f"No failed services allowed. Output: {result.stdout}"
        ).contains("0 loaded units")

        node.log.info("No failed services detected")
