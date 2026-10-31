# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import importlib
from typing import Type
from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch

from lisa import OsRequirement
from lisa.operating_system import CBLMariner, OperatingSystem, OsInformation, Redhat
from lisa.sut_orchestrator.azure.tools import VmGeneration
from lisa.testselector import _is_os_compatible, select_testcases
from lisa.testsuite import TestCaseMetadata, get_cases_metadata
from lisa.util import SkippedException, parse_version
from lisa.util.os_resolver import infer_target_os_info

for _module in (
    "azure.net.component",
    "bpf.bpf_support",
    "bpf.libbpf_tools",
    "core.azure_image_standard",
    "core.sched_core",
    "core.timesync",
    "core.zram",
    "docker.dockersuite",
    "firewalld.firewalldsuite",
    "network.lwtunnel",
    "packages.ant_test",
    "packages.curl_test",
    "security.openssl",
    "tvm.tvmsuite",
    "vm_extensions.applicationhealthextension",
    "vm_extensions.azsecpack",
    "vm_extensions.AzureMonitorAgentLinux",
    "vm_extensions.azureperformancediagnostics",
    "vm_extensions.azure_disk_encryption",
    "vm_extensions.azure_keyvault_vm_extension",
    "vm_extensions.mdm",
    "vm_extensions.networkwatcherextension",
):
    importlib.import_module(f"lisa.microsoft.testsuites.{_module}")

_CASES = list(get_cases_metadata().values())
_HOOK_SUITES = {
    "NetworkComponentTest",
    "BpfSuite",
    "LibbpfToolsSuite",
    "SchedCore",
    "ZramCompression",
    "FirewalldSuite",
    "LwtunnelSuite",
    "AntSuite",
    "CurlSuite",
}


def _has_release(case: TestCaseMetadata, distro: Type[OperatingSystem]) -> bool:
    return any(
        isinstance(entry, OsRequirement)
        and entry.has_version
        and entry.os_type is distro
        for entry in case.requirement.os_type or []
    )


class OsVersionMigrationTestCase(TestCase):
    def test_migrated_case_counts(self) -> None:
        self.assertEqual(53, sum(_has_release(case, CBLMariner) for case in _CASES))
        self.assertEqual(14, sum(_has_release(case, Redhat) for case in _CASES))

    def test_selection_deltas(self) -> None:
        for distro, images in (
            (
                CBLMariner,
                (
                    (
                        "MicrosoftCBLMariner cbl-mariner-test "
                        "cbl-mariner-2-test latest",
                        42,
                    ),
                    ("MicrosoftCBLMariner azure-linux-3 azure-linux-3 latest", 31),
                    ("microsoftazurelinux azurelinux-4 4 latest", 15),
                    ("microsoftazurelinux azurelinux-4 4-arm64 latest", 15),
                ),
            ),
            (
                Redhat,
                (
                    ("redhat RHEL 6.10 latest", 13),
                    ("redhat RHEL 8_3 latest", 1),
                    ("redhat RHEL 810-gen2 latest", 1),
                    ("redhat RHEL 9_5 latest", 4),
                    ("redhat RHEL 100-gen2 latest", 7),
                ),
            ),
        ):
            cases = [case for case in _CASES if _has_release(case, distro)]
            for image, dropped in images:
                with self.subTest(image=image):
                    target = infer_target_os_info({"marketplace_image": image})
                    assert target
                    baseline = select_testcases(
                        init_cases=cases, target_os=distro, apply_stable_gate=False
                    )
                    selected = select_testcases(
                        init_cases=cases,
                        target_os=distro,
                        target_os_version=target.version,
                        target_os_version_precision=target.version_precision,
                        apply_stable_gate=False,
                    )
                    self.assertEqual(len(cases), len(baseline))
                    self.assertEqual(dropped, len(baseline) - len(selected))
                    if distro is CBLMariner and target.version == parse_version("4"):
                        names = {case.metadata.name for case in selected}
                        for case in cases:
                            if case.suite.name in ("AntSuite", "CurlSuite"):
                                self.assertIn(case.name, names)
                            elif case.suite.name == "LibbpfToolsSuite":
                                self.assertNotIn(case.name, names)

    def test_every_new_exclusion_is_implied_by_runtime_guard(self) -> None:
        releases = (
            "0.0",
            "1.0",
            "1.1",
            "2.0",
            "2.1",
            "3.0",
            "3.1",
            "4.0",
            "4.1",
            "6.9",
            "7.0",
            "7.3",
            "7.4",
            "7.9",
            "8.0",
            "8.0.1",
            "8.1",
            "8.2",
            "8.3",
            "8.9",
            "8.10",
            "9.0",
            "9.9",
            "10.0",
        )
        checked = 0
        for distro in (CBLMariner, Redhat):
            for case in (case for case in _CASES if _has_release(case, distro)):
                for release in releases:
                    version = parse_version(release)
                    if _is_os_compatible(case, distro, version):
                        continue
                    for architecture in ("x86_64", "aarch64"):
                        with self.subTest(
                            case=case.full_name,
                            distro=distro.__name__,
                            release=release,
                            architecture=architecture,
                        ):
                            checked += 1
                            node = MagicMock()
                            node.os = distro(node)
                            node.os._information = OsInformation(
                                version=version, vendor=distro.__name__, release=release
                            )
                            node.tools[VmGeneration].get_generation.return_value = "2"
                            suite = case.suite.test_class(case.suite)
                            with patch.object(
                                node.os,
                                "get_kernel_information",
                                return_value=Mock(hardware_platform=architecture),
                            ):
                                if hasattr(suite, "_is_supported_linux_distro"):
                                    self.assertFalse(
                                        suite._is_supported_linux_distro(node)
                                    )
                                else:
                                    with self.assertRaises(SkippedException):
                                        if case.suite.name in _HOOK_SUITES:
                                            suite.before_case(log=Mock(), node=node)
                                        elif hasattr(suite, "_is_supported"):
                                            suite._is_supported(node)
                                        elif hasattr(suite, "_skip_if_not_supported"):
                                            suite._skip_if_not_supported(node)
                                        else:
                                            case._func(suite, node=node)
        self.assertGreater(checked, 1000)
