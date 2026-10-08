# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import sys
from unittest import TestCase
from unittest.mock import Mock, patch

from lisa.environment import EnvironmentStatus
from lisa.microsoft.testsuites.display import modetest
from lisa.operating_system import (
    CBLMariner,
    Debian,
    OsInformation,
    Redhat,
    Suse,
    Ubuntu,
    Windows,
)
from lisa.search_space import ResultReason
from lisa.testselector import _is_os_compatible, select_testcases
from lisa.testsuite import TestCaseRuntimeData, TestResult, get_cases_metadata
from lisa.util import SkippedException, parse_version
from lisa.util.os_resolver import resolve_target_os

# The runbook extension loader supplies this alias during real test runs.
with patch.dict(sys.modules, {"microsoft.testsuites.display.modetest": modetest}):
    from lisa.microsoft.testsuites.display.drm import Drm


class DrmRequirementTestCase(TestCase):
    cases = [
        get_cases_metadata()[f"{Drm.__name__}.{name}"]
        for name in (
            "verify_drm_driver",
            "verify_dri_node",
            "verify_no_error_output",
            "verify_connection_status",
        )
    ]

    def test_ubuntu_release_boundaries_for_all_cases(self) -> None:
        for case in self.cases:
            for release, supported in (
                ("16.04", False),
                ("18.04", False),
                ("19.10", False),
                ("20.04", False),
                ("20.04.6", False),
                ("20.05", True),
                ("20.10", True),
                ("22.04", True),
                ("24.04", True),
                ("26.04", True),
            ):
                with self.subTest(case=case.name, release=release):
                    self.assertEqual(
                        supported,
                        _is_os_compatible(case, Ubuntu, parse_version(release)),
                    )
            self.assertTrue(_is_os_compatible(case, Ubuntu))

    def test_non_ubuntu_requirements_are_unchanged(self) -> None:
        for case in self.cases:
            for distro in (Redhat, Debian, Suse, CBLMariner):
                self.assertTrue(_is_os_compatible(case, distro, parse_version("20.04")))
            self.assertFalse(_is_os_compatible(case, Windows))

    def test_marketplace_selection_and_disabled_gate(self) -> None:
        for release in ("18.04", "20.04", "20.10", "22.04", "26.04"):
            for enabled in (False, True):
                target = resolve_target_os(
                    {
                        "enable_distro_pre_filtering": enabled,
                        "marketplace_image": (
                            f"Canonical UbuntuServer {release}-LTS latest"
                        ),
                    }
                )
                selected = select_testcases(
                    init_cases=self.cases,
                    target_os=target.os_type if target else None,
                    target_os_version=target.version if target else None,
                )
                expected = 4 if not enabled or release not in ("18.04", "20.04") else 0
                with self.subTest(release=release, enabled=enabled):
                    self.assertEqual(expected, len(selected))

    def test_actual_guest_version_is_checked_without_prefilter(self) -> None:
        for case in self.cases:
            for release in ("20.04.6", "20.10", "22.04"):
                with self.subTest(case=case.name, release=release):
                    node = Mock()
                    node.os = Ubuntu(node)
                    node.os._information = OsInformation(
                        version=parse_version(release), vendor="Canonical"
                    )
                    environment = Mock()
                    environment.status = EnvironmentStatus.Connected
                    environment.nodes.list.return_value = [node]
                    result = TestResult("drm", TestCaseRuntimeData(case))
                    requirement = case.requirement.environment
                    assert requirement
                    with patch.object(
                        requirement, "check", return_value=ResultReason()
                    ):
                        if release == "20.04.6":
                            with self.assertRaisesRegex(
                                SkippedException, "OS type mismatch"
                            ):
                                result.check_environment(environment)
                        else:
                            self.assertTrue(result.check_environment(environment))
