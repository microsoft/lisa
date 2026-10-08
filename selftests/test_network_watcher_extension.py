# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import Mock

from lisa.microsoft.testsuites.vm_extensions.networkwatcherextension import (
    NetworkWatcherExtension,
)
from lisa.operating_system import (
    SLES,
    CBLMariner,
    CentOs,
    Debian,
    Oracle,
    OsInformation,
    Redhat,
    Suse,
    Ubuntu,
    Windows,
)
from lisa.testselector import _is_os_compatible, select_testcases
from lisa.testsuite import get_cases_metadata
from lisa.util import SkippedException, parse_version
from lisa.util.os_resolver import resolve_target_os


class NetworkWatcherRequirementTestCase(TestCase):
    case = get_cases_metadata()[
        f"{NetworkWatcherExtension.__name__}.verify_azure_network_watcher"
    ]

    def test_ubuntu_release_boundaries(self) -> None:
        for major in range(14, 28):
            for month in range(1, 13):
                with self.subTest(major=major, month=month):
                    self.assertEqual(
                        (16, 4) <= (major, month) < (22, 10),
                        _is_os_compatible(
                            self.case, Ubuntu, parse_version(f"{major}.{month}.5")
                        ),
                    )
        self.assertTrue(_is_os_compatible(self.case, Ubuntu))

    def test_non_ubuntu_filtering_is_unchanged(self) -> None:
        for distro in (Redhat, CentOs, Oracle, Debian, Suse, SLES, CBLMariner):
            for version in ("1.0", "99.0"):
                self.assertTrue(
                    _is_os_compatible(self.case, distro, parse_version(version))
                )
        self.assertFalse(_is_os_compatible(self.case, Windows))

    def test_marketplace_selection_and_disabled_gate(self) -> None:
        for release, supported in (
            ("14.04", False),
            ("16.04", True),
            ("18.04", True),
            ("20.04", True),
            ("21.10", True),
            ("22.04", True),
            ("22.10", False),
            ("24.04", False),
            ("26.04", False),
        ):
            for enabled in (True, False):
                with self.subTest(release=release, enabled=enabled):
                    target = resolve_target_os(
                        {
                            "enable_distro_pre_filtering": enabled,
                            "marketplace_image": (
                                f"Canonical UbuntuServer {release}-LTS latest"
                            ),
                        }
                    )
                    selected = select_testcases(
                        init_cases=[self.case],
                        target_os=target.os_type if target else None,
                        target_os_version=target.version if target else None,
                    )
                    self.assertEqual(not enabled or supported, bool(selected))

    def test_runtime_major_version_check_is_retained(self) -> None:
        suite = self.case.suite.test_class(self.case.suite)
        for release in ("16.04", "18.04", "20.04", "21.10", "22.04"):
            with self.subTest(release=release):
                node = Mock()
                node.os = Ubuntu(node)
                node.os._information = OsInformation(
                    version=parse_version(release), vendor="Canonical"
                )
                if release == "21.10":
                    with self.assertRaises(SkippedException):
                        suite.before_case(log=Mock(), node=node)
                else:
                    suite.before_case(log=Mock(), node=node)
