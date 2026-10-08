# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import Mock

from lisa.microsoft.testsuites.vm_extensions.mdm import MetricsExtension
from lisa.operating_system import (
    CBLMariner,
    Debian,
    Oracle,
    OsInformation,
    Redhat,
    Ubuntu,
    Windows,
)
from lisa.sut_orchestrator import AZURE, HYPERV, READY
from lisa.testselector import (
    _is_os_compatible,
    _is_platform_compatible,
    select_testcases,
)
from lisa.testsuite import get_cases_metadata
from lisa.util import SkippedException, parse_version
from lisa.util.os_resolver import resolve_target_os


class MetricsExtensionRequirementTestCase(TestCase):
    case = get_cases_metadata()[f"{MetricsExtension.__name__}.verify_metricsextension"]

    def test_ubuntu_release_boundaries(self) -> None:
        for major in range(16, 27):
            for month in range(1, 13):
                with self.subTest(major=major, month=month):
                    self.assertEqual(
                        (18, 4) <= (major, month) < (20, 10),
                        _is_os_compatible(
                            self.case, Ubuntu, parse_version(f"{major}.{month}.5")
                        ),
                    )
        self.assertTrue(_is_os_compatible(self.case, Ubuntu))

    def test_platform_and_non_ubuntu_requirements_are_unchanged(self) -> None:
        for platform in (AZURE, READY):
            self.assertTrue(_is_platform_compatible(self.case, [platform]))
        self.assertFalse(_is_platform_compatible(self.case, [HYPERV]))
        for distro in (CBLMariner, Debian, Redhat, Oracle):
            for version in ("1.0", "99.0"):
                self.assertTrue(
                    _is_os_compatible(self.case, distro, parse_version(version))
                )
        self.assertFalse(_is_os_compatible(self.case, Windows))

    def test_marketplace_selection_and_disabled_gate(self) -> None:
        for release, supported in (
            ("16.04", False),
            ("18.04", True),
            ("19.10", True),
            ("20.04", True),
            ("20.10", False),
            ("22.04", False),
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

    def test_runtime_exact_release_check_is_preserved(self) -> None:
        suite = self.case.suite.test_class(self.case.suite)
        for release in ("19.10", "22.04"):
            with self.subTest(release=release):
                node = Mock()
                node.os = Ubuntu(node)
                node.os._information = OsInformation(
                    version=parse_version(release),
                    vendor="Canonical",
                    release=release,
                )
                with self.assertRaises(SkippedException):
                    self.case._func(suite, node=node, log=Mock())
                node.execute.assert_not_called()
