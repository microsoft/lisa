# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import List, Tuple
from unittest import TestCase
from unittest.mock import Mock, patch

from lisa.environment import EnvironmentStatus
from lisa.microsoft.testsuites.acc.bvt import ACCBasicTest
from lisa.microsoft.testsuites.core.timesync import TimeSync
from lisa.microsoft.testsuites.tvm.tvmsuite import TvmTest
from lisa.microsoft.testsuites.vm_extensions.azsecpack import AzSecPack
from lisa.microsoft.testsuites.vm_extensions.azureperformancediagnostics import (
    AzurePerformanceDiagnostics,
)
from lisa.operating_system import (
    BSD,
    CBLMariner,
    Debian,
    OsInformation,
    Redhat,
    Suse,
    Ubuntu,
    Windows,
)
from lisa.sut_orchestrator.azure.tools import VmGeneration
from lisa.testselector import _is_os_compatible, select_testcases
from lisa.testsuite import TestCaseMetadata, get_cases_metadata
from lisa.tools import Lscpu
from lisa.tools.lscpu import CpuArchitecture
from lisa.util import SkippedException, parse_version
from lisa.util.os_resolver import resolve_target_os

_CASES = get_cases_metadata()


class AdditionalUbuntuRequirementTestCase(TestCase):
    minimum_cases: List[Tuple[TestCaseMetadata, Tuple[int, int]]] = [
        (_CASES[f"{ACCBasicTest.__name__}.verify_sgx"], (18, 4)),
        (_CASES[f"{TimeSync.__name__}.verify_timesync_ptp"], (19, 10)),
        (_CASES[f"{TvmTest.__name__}.verify_secureboot_compatibility"], (18, 4)),
        (_CASES[f"{TvmTest.__name__}.verify_measuredboot_compatibility"], (18, 4)),
    ]
    major_cases: List[Tuple[TestCaseMetadata, Tuple[int, ...]]] = [
        (_CASES[f"{AzSecPack.__name__}.verify_azsecpack"], (18, 20, 22, 24)),
        (
            _CASES[
                f"{AzurePerformanceDiagnostics.__name__}."
                "verify_azure_performance_diagnostics"
            ],
            (14, 16, 18, 20),
        ),
    ]

    def test_minimum_release_boundaries(self) -> None:
        for case, minimum in self.minimum_cases:
            for major in range(14, 27):
                for month in range(1, 13):
                    with self.subTest(case=case.name, major=major, month=month):
                        self.assertEqual(
                            (major, month) >= minimum,
                            _is_os_compatible(
                                case, Ubuntu, parse_version(f"{major}.{month}.5")
                            ),
                        )

    def test_discrete_major_version_policies(self) -> None:
        for case, majors in self.major_cases:
            for major in range(12, 28):
                for month in range(1, 13):
                    with self.subTest(case=case.name, major=major, month=month):
                        self.assertEqual(
                            major in majors,
                            _is_os_compatible(
                                case, Ubuntu, parse_version(f"{major}.{month}.5")
                            ),
                        )

    def test_non_ubuntu_and_other_requirements_are_preserved(self) -> None:
        cases = [case for case, _ in self.minimum_cases] + [
            case for case, _ in self.major_cases
        ]
        for case in cases:
            self.assertTrue(_is_os_compatible(case, Ubuntu))
            for distro in (Debian, Redhat, Suse, CBLMariner):
                self.assertTrue(_is_os_compatible(case, distro, parse_version("1.0")))
            is_azsecpack = case is self.major_cases[0][0]
            self.assertEqual(is_azsecpack, _is_os_compatible(case, Windows))
            self.assertEqual(not is_azsecpack, _is_os_compatible(case, BSD))
            requirement = case.requirement
            self.assertEqual(
                EnvironmentStatus.Connected, requirement.environment_status
            )
            assert requirement.environment
            features = requirement.environment.nodes[0].features
            if case is self.minimum_cases[1][0]:
                self.assertFalse(features)
            else:
                self.assertTrue(features)

    def test_marketplace_selection_and_gate(self) -> None:
        cases = [case for case, _ in self.minimum_cases] + [
            case for case, _ in self.major_cases
        ]
        for enabled in (False, True):
            for release in (
                "16.04",
                "18.04",
                "19.10",
                "20.04",
                "22.04",
                "24.04",
                "26.04",
            ):
                with self.subTest(enabled=enabled, release=release):
                    target = resolve_target_os(
                        {
                            "enable_distro_pre_filtering": enabled,
                            "marketplace_image": (
                                f"Canonical UbuntuServer {release}-LTS latest"
                            ),
                        }
                    )
                    version = parse_version(release)
                    expected = {
                        case.full_name
                        for case, minimum in self.minimum_cases
                        if not enabled or (version.major, version.minor) >= minimum
                    } | {
                        case.full_name
                        for case, majors in self.major_cases
                        if not enabled or version.major in majors
                    }
                    selected = select_testcases(
                        init_cases=cases,
                        target_os=target.os_type if target else None,
                        target_os_version=target.version if target else None,
                    )
                    self.assertEqual(
                        expected, {case.metadata.full_name for case in selected}
                    )

    def test_existing_minimum_runtime_guards_are_retained(self) -> None:
        for case, _ in self.minimum_cases:
            with self.subTest(case=case.name):
                node = Mock()
                node.os = Ubuntu(node)
                node.os._information = OsInformation(
                    version=parse_version("16.04"), vendor="Canonical"
                )
                node.tools = {
                    Lscpu: Mock(
                        get_architecture=Mock(return_value=CpuArchitecture.X64)
                    ),
                    VmGeneration: Mock(get_generation=Mock(return_value="2")),
                }
                suite = case.suite.test_class(case.suite)
                with self.assertRaises(SkippedException):
                    if case is self.minimum_cases[0][0]:
                        case._func(suite, node=node, log=Mock())
                    else:
                        case._func(suite, node=node)
                node.execute.assert_not_called()

    def test_security_pack_arm64_restriction_remains_runtime_only(self) -> None:
        case = self.major_cases[0][0]
        suite = case.suite.test_class(case.suite)
        node = Mock()
        node.os = Ubuntu(node)
        node.os._information = OsInformation(
            version=parse_version("18.04"), vendor="Canonical"
        )
        self.assertTrue(_is_os_compatible(case, Ubuntu, parse_version("18.04")))
        with patch.object(
            node.os,
            "get_kernel_information",
            return_value=Mock(hardware_platform="aarch64"),
        ), self.assertRaises(SkippedException):
            case._func(suite, node=node, log=Mock(), result=Mock())
        node.execute.assert_not_called()

    def test_performance_diagnostics_runtime_major_version_check(self) -> None:
        case = self.major_cases[1][0]
        suite = case.suite.test_class(case.suite)
        for major in range(12, 27):
            with self.subTest(major=major):
                node = Mock()
                node.os = Ubuntu(node)
                node.os._information = OsInformation(
                    version=parse_version(f"{major}.04"), vendor="Canonical"
                )
                if major in (14, 16, 18, 20):
                    suite.before_case(log=Mock(), node=node)
                else:
                    with self.assertRaises(SkippedException):
                        suite.before_case(log=Mock(), node=node)
