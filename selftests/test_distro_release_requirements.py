# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from argparse import Namespace
from importlib import import_module
from typing import Dict, List, Tuple, Type
from unittest import TestCase
from unittest.mock import Mock, patch

from lisa import OsRequirement, commands, schema
from lisa.operating_system import (
    AlmaLinux,
    CBLMariner,
    CentOs,
    Debian,
    Linux,
    OperatingSystem,
    Oracle,
    OsInformation,
    Redhat,
    Suse,
    Ubuntu,
)
from lisa.runners.lisa_runner import LisaRunner
from lisa.testselector import _is_os_compatible, select_testcases
from lisa.testsuite import get_cases_metadata
from lisa.util import LisaException, SkippedException, parse_version
from lisa.util.os_requirement import matches_os_requirement
from lisa.util.os_resolver import infer_target_os_info, resolve_target_os
from lisa.variable import VariableEntry
from selftests.test_distro_prefilter import _build_case


class DistroReleaseInferenceTestCase(TestCase):
    def test_observed_marketplace_skus(self) -> None:
        # Representative SKU names returned by Azure CLI in eastus, 2026-10-23.
        images = [
            (
                CBLMariner,
                "microsoftcblmariner azure-linux-3 azure-linux-3 latest",
                "3",
                "4",
            ),
            (
                CBLMariner,
                "microsoftcblmariner azure-linux-3 "
                "azure-linux-3-arm64-gen2-fips latest",
                "3",
                "4",
            ),
            (
                CBLMariner,
                "microsoftcblmariner azure-linux-3 "
                "azure-linux-3-kernel-mshv-arm64 latest",
                "3",
                "4",
            ),
            (
                CBLMariner,
                "microsoftcblmariner azure-linux-3 azure-linux-3-cvm latest",
                "3",
                "4",
            ),
            (Redhat, "redhat RHEL 6.10 latest", "6.10", None),
            (Redhat, "redhat RHEL 79-gen2 latest", "7.9", None),
            (Redhat, "redhat RHEL 810-gen2 latest", "8.10", None),
            (Redhat, "redhat RHEL 8_10 latest", "8.10", None),
            (Redhat, "redhat RHEL 95_gen2 latest", "9.5", None),
            (Redhat, "redhat RHEL 100-gen2 latest", "10.0", None),
            (Redhat, "redhat RHEL 101-gen2 latest", "10.1", None),
            (Redhat, "redhat RHEL 10_2 latest", "10.2", None),
            (Redhat, "redhat RHEL 8-LVM latest", "8", "9"),
            (Redhat, "redhat RHEL 10-lvm-gen2 latest", "10", "11"),
            (Redhat, "redhat rhel-arm64 9_5-arm64 latest", "9.5", None),
            (Redhat, "redhat rhel-cvm 10_2_cvm latest", "10.2", None),
            (Debian, "debian debian-10 10-cloudinit latest", "10", "11"),
            (Debian, "debian debian-11 11-backports-arm64-v2 latest", "11", "12"),
            (Debian, "debian debian-12 12-gen2 latest", "12", "13"),
            (Debian, "debian debian-13 13-backports-gen2 latest", "13", "14"),
            (Oracle, "oracle Oracle-Linux 77 latest", "7.7", None),
            (Oracle, "oracle Oracle-Linux 8 latest", "8", "9"),
            (Oracle, "oracle Oracle-Linux 81-gen2 latest", "8.1", None),
            (Oracle, "oracle Oracle-Linux ol8_2-gen2 latest", "8.2", None),
            (Oracle, "oracle Oracle-Linux ol810-lvm-gen2 latest", "8.10", None),
            (Oracle, "oracle Oracle-Linux ol97-arm64-lvm-gen2 latest", "9.7", None),
            (Oracle, "oracle Oracle-Linux ol101-lvm latest", "10.1", None),
            (Oracle, "oracle Oracle-Linux ol102-arm64-lvm-gen2 latest", "10.2", None),
            (CentOs, "openlogic CentOS 6.10 latest", "6.10", None),
            (CentOs, "openlogic CentOS 7_9-arm64 latest", "7.9", None),
            (CentOs, "openlogic CentOS 8_5-gen2 latest", "8.5", None),
            (CentOs, "openlogic CentOS-LVM 7-lvm-gen2 latest", "7", "8"),
        ]
        for distro, image, release, upper in images:
            with self.subTest(image=image):
                target = infer_target_os_info({"marketplace_image": image})
                assert target
                self.assertIs(target.os_type, distro)
                self.assertEqual(parse_version(release), target.version)
                self.assertEqual(
                    parse_version(upper) if upper else None, target.version_upper_bound
                )

    def test_explicit_gallery_and_vhd_names(self) -> None:
        for name, distro, release, upper in (
            ("azure-linux-3-gen2", CBLMariner, "3", "4"),
            ("cbl-mariner-2.0-gen2", CBLMariner, "2.0", None),
            ("rhel-8.3-x64-gen2", Redhat, "8.3", None),
            ("debian-12-arm64", Debian, "12", "13"),
            ("oracle-linux-8.10-lvm", Oracle, "8.10", None),
            ("centos-7_9-gen2", CentOs, "7.9", None),
        ):
            for key, image in (
                ("shared_gallery", f"sub/rg/gallery/{name}/99.1.0"),
                (
                    "community_gallery_image",
                    f"/galleries/g/images/{name}/versions/99.1.0",
                ),
                (
                    "vhd",
                    f"https://account.blob.core.windows.net/vhds/{name}.vhd?sv=99.0",
                ),
            ):
                with self.subTest(image=image):
                    target = infer_target_os_info({key: image})
                    assert target
                    self.assertIs(target.os_type, distro)
                    self.assertEqual(parse_version(release), target.version)
                    self.assertEqual(
                        parse_version(upper) if upper else None,
                        target.version_upper_bound,
                    )

    def test_unknown_conflicting_and_unrelated_numbers(self) -> None:
        for image in (
            "redhat RHEL custom 8.3.20261023",
            "redhat RHEL 8_3_1 latest",
            "redhat RHEL kernel-8.3 latest",
            "redhat rhel-test-billing 8_3 latest",
            "oracle weblogic-141200-jdk17-ol810 ol810 latest",
            "oracle Oracle-Linux ol12345-lvm latest",
            "debian debian-12 13-gen2 latest",
            "debian debian-sid-daily sid latest",
            "microsoftcblmariner azure-linux-3 azure-linux-4 latest",
            "/galleries/debian-12/images/debian-custom/versions/12.0",
            "/images/rhel-kernel-8.3/versions/8.3",
            "/images/rhel-8.3-rhel-9.5/versions/1.0",
            "redhat RHEL 8_3 latest,redhat RHEL 9_5 latest",
        ):
            with self.subTest(image=image):
                target = infer_target_os_info({"image": image})
                assert target
                self.assertIsNone(target.version)
                self.assertIsNone(target.version_upper_bound)

    def test_first_image_source_and_gate(self) -> None:
        variables = {
            "marketplace_image": "redhat RHEL custom 8.3.0",
            "shared_gallery": "/images/rhel-8.3/versions/1.0",
        }
        target = infer_target_os_info(variables)
        assert target
        self.assertIsNone(target.version)
        self.assertIsNone(resolve_target_os(variables))
        self.assertIsNotNone(
            resolve_target_os({**variables, "enable_distro_pre_filtering": True})
        )


class DistroReleaseMatchingTestCase(TestCase):
    def test_bounds_and_validation(self) -> None:
        for distro in (CBLMariner, Redhat, CentOs, Oracle, Debian):
            for bounds in (("8", "9"), ("8.3", "8.10")):
                entry = OsRequirement(
                    distro, min_version=bounds[0], max_version=bounds[1]
                )
                self.assertTrue(entry.matches_release(parse_version(bounds[0])))
                self.assertFalse(entry.matches_release(parse_version(bounds[1])))
            for invalid in ("", "08", "8.03", "8.3.1", "8.x", ">=8", "-1", "8-3"):
                with self.subTest(distro=distro, invalid=invalid), self.assertRaises(
                    LisaException
                ):
                    OsRequirement(distro, min_version=invalid)
            with self.assertRaises(LisaException):
                OsRequirement(distro, min_version="9", max_version="8")
        with self.assertRaises(LisaException):
            OsRequirement(Ubuntu, min_version="22")

    def test_major_only_overlap_is_deferred(self) -> None:
        for minimum, maximum, match in (
            ("8.3", "9", None),
            ("8", "8.3", None),
            ("8", "9", True),
            ("9", "10", False),
            ("7", "8", False),
        ):
            entry = OsRequirement(Redhat, min_version=minimum, max_version=maximum)
            self.assertIs(
                match,
                matches_os_requirement(
                    entry,
                    Redhat,
                    parse_version("8"),
                    prefilter=True,
                    version_upper_bound=parse_version("9"),
                ),
            )
            for allow in (True, False):
                case = _build_case(
                    "range", **{"supported_os" if allow else "unsupported_os": [entry]}
                )
                self.assertEqual(
                    match is not False if allow else match is not True,
                    _is_os_compatible(
                        case, Redhat, parse_version("8"), parse_version("9")
                    ),
                )

    def test_concrete_distro_isolation_and_class_inheritance(self) -> None:
        for base, child in (
            (Debian, Ubuntu),
            (Redhat, Oracle),
            (Redhat, CentOs),
            (Redhat, AlmaLinux),
        ):
            entry = OsRequirement(base, max_version="99")
            self.assertFalse(matches_os_requirement(entry, child, parse_version("8")))
            self.assertTrue(matches_os_requirement(base, child))
            self.assertTrue(matches_os_requirement(OsRequirement(base), child))
            self.assertIsNone(
                matches_os_requirement(entry, Linux, parse_version("8"), prefilter=True)
            )

    def test_selection_and_gate_preserve_partial_releases(self) -> None:
        case = _build_case(
            "rhel_minimum", unsupported_os=[OsRequirement(Redhat, max_version="8.3")]
        )
        for sku, selected in (
            ("8-LVM", True),
            ("8_2", False),
            ("8_3", True),
            ("custom", True),
        ):
            for gate in (False, True):
                target = resolve_target_os(
                    {
                        "enable_distro_pre_filtering": gate,
                        "marketplace_image": f"redhat RHEL {sku} latest",
                    }
                )
                results = select_testcases(
                    init_cases=[case],
                    target_os=target.os_type if target else None,
                    target_os_version=target.version if target else None,
                    target_os_version_upper_bound=(
                        target.version_upper_bound if target else None
                    ),
                )
                self.assertEqual(not gate or selected, bool(results))

    def test_list_and_runner_pass_release_precision(self) -> None:
        builder = Mock()
        builder.variables = {
            "enable_distro_pre_filtering": VariableEntry("gate", True),
            "marketplace_image": VariableEntry("image", "redhat RHEL 8-LVM latest"),
        }
        builder.partial_resolve.return_value = []
        runbook = schema.Runbook()
        runbook.platform = [schema.Platform(type="ready")]
        runner = LisaRunner(builder, runbook, 0, {})
        with patch("lisa.runner.BaseRunner._initialize"), patch(
            "lisa.runners.lisa_runner.select_testcases",
            side_effect=RuntimeError("captured"),
        ) as runner_select:
            with self.assertRaisesRegex(RuntimeError, "captured"):
                runner._initialize()
        for list_all in (False, True):
            with patch(
                "lisa.commands.RunbookBuilder.from_path", return_value=builder
            ), patch("lisa.commands.select_testcases", return_value=[]) as list_select:
                commands.list_start(
                    Namespace(
                        runbook="unused", variables=[], list_all=list_all, type="case"
                    )
                )
            for key in (
                "target_os",
                "target_os_version",
                "target_os_version_upper_bound",
            ):
                self.assertEqual(
                    runner_select.call_args.kwargs[key],
                    list_select.call_args.kwargs[key],
                )
        self.assertEqual(
            parse_version("9"),
            runner_select.call_args.kwargs["target_os_version_upper_bound"],
        )


class DistroReleaseMetadataTestCase(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        for module in (
            "bpf.bpf_support",
            "bpf.libbpf_tools",
            "core.zram",
            "core.sched_core",
            "network.lwtunnel",
            "firewalld.firewalldsuite",
            "azure.net.component",
            "core.floppy",
            "tvm.tvmsuite",
            "vm_extensions.applicationhealthextension",
            "vm_extensions.networkwatcherextension",
            "vm_extensions.AzureMonitorAgentLinux",
            "vm_extensions.azsecpack",
            "vm_extensions.azureperformancediagnostics",
            "vm_extensions.azure_disk_encryption",
            "vm_extensions.azure_keyvault_vm_extension",
            "vm_extensions.mdm",
        ):
            import_module(f"lisa.microsoft.testsuites.{module}")

    def test_native_suite_release_metadata(self) -> None:
        cases = {case.name: case for case in get_cases_metadata().values()}
        minimum_cases = (
            "verify_btf_sysfs_exists",
            "verify_lwtunnel_bpf_support",
            "verify_zram_crypto_zstd",
            "verify_zram_crypto_lz4",
            "verify_sched_core_basic",
            "verify_firewalld",
            "verify_net_conntrack",
            "verify_net_ipset",
            "verify_net_iptables",
        )
        major_three_cases = (
            "verify_libbpf_tools_package_available",
            "verify_libbpf_tools_binaries_executable",
            "verify_bpf_profile_captures_stacks",
            "verify_bpf_profile_stack_filtering",
            "verify_bpf_profile_no_resource_leak",
            "verify_bpf_profile_handles_edge_cases",
        )
        for name in minimum_cases + major_three_cases:
            case = cases[name]
            for major in (1, 2, 3, 4):
                with self.subTest(case=name, major=major):
                    self.assertEqual(
                        major >= 3 if name in minimum_cases else major == 3,
                        _is_os_compatible(case, CBLMariner, parse_version(str(major))),
                    )
            self.assertTrue(_is_os_compatible(case, CBLMariner))
            self.assertFalse(_is_os_compatible(case, Ubuntu))

    def test_extension_release_ranges(self) -> None:
        cases = {case.name: case for case in get_cases_metadata().values()}
        ranges: List[
            Tuple[Tuple[str, ...], Dict[Type[OperatingSystem], Tuple[int, int]]]
        ] = [
            (
                ("verify_application_health_extension", "verify_azure_network_watcher"),
                {
                    Redhat: (7, 9),
                    CentOs: (6, 8),
                    Oracle: (6, 8),
                    Debian: (7, 9),
                    CBLMariner: (2, 4),
                },
            ),
            (
                ("verify_azuremonitoragent_linux",),
                {
                    Redhat: (7, 10),
                    CentOs: (7, 9),
                    Oracle: (7, 10),
                    Debian: (9, 12),
                    CBLMariner: (2, 4),
                },
            ),
            (
                ("verify_azsecpack",),
                {
                    Redhat: (7, 10),
                    CentOs: (7, 8),
                    Oracle: (8, 10),
                    Debian: (10, 13),
                    CBLMariner: (2, 4),
                },
            ),
            (
                ("verify_azure_performance_diagnostics",),
                {
                    Redhat: (7, 9),
                    CentOs: (6, 8),
                    Oracle: (6, 8),
                    Debian: (8, 12),
                    CBLMariner: (2, 3),
                },
            ),
            (("verify_key_vault_extension",), {CBLMariner: (2, 3)}),
            (("verify_metricsextension",), {CBLMariner: (1, 3), Debian: (10, 11)}),
        ]
        for names, distros in ranges:
            for name in names:
                for distro, (minimum, maximum) in distros.items():
                    self.assertTrue(_is_os_compatible(cases[name], distro))
                    for major in range(1, 15):
                        for minor in (0, 5, 10):
                            with self.subTest(
                                case=name, distro=distro, major=major, minor=minor
                            ):
                                self.assertEqual(
                                    minimum <= major < maximum,
                                    _is_os_compatible(
                                        cases[name],
                                        distro,
                                        parse_version(f"{major}.{minor}"),
                                    ),
                                )
                if name != "verify_key_vault_extension":
                    for distro in (Suse, AlmaLinux):
                        self.assertTrue(
                            _is_os_compatible(cases[name], distro, parse_version("1"))
                        )

    def test_runtime_supported_releases_are_never_prefiltered(self) -> None:
        cases = {case.name: case for case in get_cases_metadata().values()}
        names = (
            "verify_application_health_extension",
            "verify_azure_network_watcher",
            "verify_azuremonitoragent_linux",
            "verify_azsecpack",
            "verify_azure_performance_diagnostics",
            "verify_azure_disk_encryption_enabled",
            "verify_azure_disk_encryption_provisioned",
            "verify_key_vault_extension",
            "verify_metricsextension",
        )
        for name in names:
            case = cases[name]
            suite = case.suite.test_class(case.suite)
            raises_on_unsupported = name in (
                "verify_azsecpack",
                "verify_metricsextension",
            )
            guard = getattr(
                suite,
                "_is_supported"
                if raises_on_unsupported
                else "_is_supported_linux_distro",
            )
            for distro in (CBLMariner, Redhat, CentOs, Oracle, Debian):
                for major in range(1, 14):
                    for minor in (0, 1, 3, 4, 5, 10):
                        release = f"{major}.{minor}"
                        node = Mock()
                        node.os = distro(node)
                        node.os._information = OsInformation(
                            version=parse_version(release),
                            release=release,
                            vendor=distro.__name__,
                        )
                        for arch in ("x86_64", "aarch64"):
                            with patch.object(
                                node.os,
                                "get_kernel_information",
                                return_value=Mock(hardware_platform=arch),
                            ):
                                try:
                                    result = guard(node)
                                except SkippedException:
                                    supported = False
                                else:
                                    supported = raises_on_unsupported or result
                            if supported:
                                with self.subTest(
                                    case=name, distro=distro, release=release, arch=arch
                                ):
                                    self.assertTrue(
                                        _is_os_compatible(
                                            case, distro, parse_version(release)
                                        )
                                    )

    def test_minor_release_thresholds(self) -> None:
        cases = {case.name: case for case in get_cases_metadata().values()}
        for name in (
            "verify_secureboot_compatibility",
            "verify_measuredboot_compatibility",
        ):
            for distro, minimum in (
                (Debian, "11"),
                (Redhat, "8.3"),
                (CentOs, "8.3"),
                (Oracle, "8.3"),
            ):
                for version in ("7.9", "8.2", "8.3", "9.5", "11"):
                    self.assertEqual(
                        parse_version(version) >= parse_version(minimum),
                        _is_os_compatible(cases[name], distro, parse_version(version)),
                    )
            self.assertTrue(
                _is_os_compatible(cases[name], AlmaLinux, parse_version("8"))
            )
        for version in ("7.7", "7.8", "7.9"):
            self.assertEqual(
                version != "7.7",
                _is_os_compatible(
                    cases["verify_floppy_module_is_blacklisted"],
                    CentOs,
                    parse_version(version),
                ),
            )
        for name in (
            "verify_azure_disk_encryption_enabled",
            "verify_azure_disk_encryption_provisioned",
        ):
            for distro in (Redhat, CentOs, Oracle, CBLMariner):
                self.assertTrue(_is_os_compatible(cases[name], distro))
                for major in range(1, 11):
                    for minor in (0, 1, 3, 4, 5, 10):
                        if distro is CBLMariner:
                            supported = major == 2
                        elif distro is Oracle:
                            supported = major == 8 and minor >= 5
                        else:
                            supported = (
                                (major == 7 and minor >= 4)
                                or (major == 8 and minor >= 1)
                                or (distro is Redhat and major == 9)
                            )
                        with self.subTest(
                            case=name, distro=distro, major=major, minor=minor
                        ):
                            self.assertEqual(
                                supported,
                                _is_os_compatible(
                                    cases[name],
                                    distro,
                                    parse_version(f"{major}.{minor}"),
                                ),
                            )
            self.assertTrue(
                _is_os_compatible(cases[name], AlmaLinux, parse_version("8"))
            )
