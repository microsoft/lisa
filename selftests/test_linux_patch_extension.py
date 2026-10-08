# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import Mock

from lisa.microsoft.testsuites.vm_extensions.linux_patch_extension import (
    LinuxPatchExtensionBVT,
    _verify_lpe_supported_images,
    _verify_supported_arm64_images,
)
from lisa.operating_system import (
    BSD,
    CBLMariner,
    CentOs,
    Debian,
    FreeBSD,
    Oracle,
    OsInformation,
    Redhat,
    Suse,
    Ubuntu,
)
from lisa.sut_orchestrator import AZURE, HYPERV
from lisa.testselector import (
    _is_os_compatible,
    _is_platform_compatible,
    select_testcases,
)
from lisa.testsuite import get_cases_metadata
from lisa.util import SkippedException, parse_version
from lisa.util.os_resolver import resolve_target_os


class LinuxPatchRequirementTestCase(TestCase):
    case = get_cases_metadata()[
        f"{LinuxPatchExtensionBVT.__name__}.verify_vm_assess_patches"
    ]
    install_case = get_cases_metadata()[
        f"{LinuxPatchExtensionBVT.__name__}.verify_vm_install_patches"
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

    def test_inherited_platform_and_non_ubuntu_requirements_are_preserved(self) -> None:
        self.assertTrue(_is_platform_compatible(self.case, [AZURE]))
        self.assertFalse(_is_platform_compatible(self.case, [HYPERV]))
        for distro in (Redhat, CentOs, Oracle, Debian, Suse, CBLMariner):
            for version in ("1.0", "99.0"):
                self.assertTrue(
                    _is_os_compatible(self.case, distro, parse_version(version))
                )
        for excluded_distro in (BSD, FreeBSD):
            self.assertFalse(_is_os_compatible(self.case, excluded_distro))

    def test_install_case_is_unchanged(self) -> None:
        self.assertTrue(
            _is_os_compatible(self.install_case, Ubuntu, parse_version("24.04"))
        )
        self.assertTrue(_is_platform_compatible(self.install_case, [AZURE]))
        self.assertFalse(_is_os_compatible(self.install_case, BSD))

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

    def test_runtime_image_restrictions_remain(self) -> None:
        node = Mock()
        node.os = Ubuntu(node)
        node.os._information = OsInformation(
            version=parse_version("22.04"), vendor="Canonical"
        )
        log = Mock()
        _verify_lpe_supported_images(node, log, parse_version("22.4.2"))
        with self.assertRaises(SkippedException):
            _verify_lpe_supported_images(node, log, parse_version("22.4.3"))
        with self.assertRaises(SkippedException):
            _verify_lpe_supported_images(node, log, parse_version("21.10.2"))
        with self.assertRaises(SkippedException):
            _verify_supported_arm64_images(node, log, parse_version("22.4.2"))
        _verify_supported_arm64_images(node, log, parse_version("20.4.2"))
