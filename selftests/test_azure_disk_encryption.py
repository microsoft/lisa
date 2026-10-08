# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import Mock

from lisa.microsoft.testsuites.vm_extensions.azure_disk_encryption import (
    AzureDiskEncryption,
)
from lisa.operating_system import (
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
from lisa.tools import Lscpu
from lisa.tools.lscpu import CpuArchitecture
from lisa.util import SkippedException, parse_version
from lisa.util.os_resolver import resolve_target_os


class AzureDiskEncryptionRequirementTestCase(TestCase):
    case = get_cases_metadata()[
        f"{AzureDiskEncryption.__name__}.verify_azure_disk_encryption_enabled"
    ]

    def test_ubuntu_release_boundaries(self) -> None:
        for major in range(14, 28):
            for month in range(1, 13):
                with self.subTest(major=major, month=month):
                    self.assertEqual(
                        (18, 4) <= (major, month) < (22, 10),
                        _is_os_compatible(
                            self.case, Ubuntu, parse_version(f"{major}.{month}.5")
                        ),
                    )

    def test_unknown_ubuntu_release_is_retained(self) -> None:
        self.assertTrue(_is_os_compatible(self.case, Ubuntu))

    def test_non_ubuntu_filtering_is_unchanged(self) -> None:
        for distro in (Redhat, CentOs, Oracle, Debian, Suse, CBLMariner):
            for version in ("1.0", "99.0"):
                with self.subTest(distro=distro, version=version):
                    self.assertTrue(
                        _is_os_compatible(self.case, distro, parse_version(version))
                    )
        self.assertFalse(_is_os_compatible(self.case, Windows))

    def test_marketplace_prefilter_and_disabled_gate(self) -> None:
        for image, supported in (
            ("Canonical UbuntuServer 16.04-LTS latest", False),
            ("Canonical 0001-com-ubuntu-pro-microsoft pro-fips-18_04 latest", True),
            ("Canonical 0001-com-ubuntu-server-focal 20_04-lts latest", True),
            ("Canonical 0001-com-ubuntu-server-jammy 22_04-lts latest", True),
            ("Canonical UbuntuServer 20_10 latest", True),
            ("Canonical UbuntuServer 22_10 latest", False),
            ("Canonical ubuntu-24_04-lts server latest", False),
            ("Canonical ubuntu-26_04-lts server-cvm latest", False),
        ):
            for enabled in (False, True):
                with self.subTest(image=image, enabled=enabled):
                    target = resolve_target_os(
                        {
                            "enable_distro_pre_filtering": enabled,
                            "marketplace_image": image,
                        }
                    )
                    selected = select_testcases(
                        init_cases=[self.case],
                        target_os=target.os_type if target else None,
                        target_os_version=target.version if target else None,
                    )
                    self.assertEqual(supported or not enabled, bool(selected))

    def test_runtime_minor_version_guard_is_retained(self) -> None:
        suite = self.case.suite.test_class(self.case.suite)
        node = Mock()
        node.os = Ubuntu(node)
        node.os._information = OsInformation(
            version=parse_version("20.10"), vendor="Canonical"
        )
        node.tools = {
            Lscpu: Mock(get_architecture=Mock(return_value=CpuArchitecture.X64))
        }
        self.assertTrue(_is_os_compatible(self.case, Ubuntu, parse_version("20.10")))
        with self.assertRaises(SkippedException):
            suite.before_case(log=Mock(), node=node)
