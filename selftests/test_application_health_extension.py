# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase

from lisa.microsoft.testsuites.vm_extensions.applicationhealthextension import (
    ApplicationHealthExtension,
)
from lisa.operating_system import (
    SLES,
    CBLMariner,
    CentOs,
    Debian,
    Oracle,
    Redhat,
    Suse,
    Ubuntu,
    Windows,
)
from lisa.testselector import _is_os_compatible, select_testcases
from lisa.testsuite import get_cases_metadata
from lisa.util import parse_version
from lisa.util.os_resolver import resolve_target_os


class ApplicationHealthRequirementTestCase(TestCase):
    case = get_cases_metadata()[
        f"{ApplicationHealthExtension.__name__}.verify_application_health_extension"
    ]

    def test_ubuntu_releases_exclude_22_10_and_newer(self) -> None:
        for major in range(14, 28):
            for month in (1, 4, 10, 12):
                with self.subTest(major=major, month=month):
                    self.assertEqual(
                        (major, month) < (22, 10),
                        _is_os_compatible(
                            self.case, Ubuntu, parse_version(f"{major}.{month}.5")
                        ),
                    )

    def test_unknown_ubuntu_release_is_retained(self) -> None:
        self.assertTrue(_is_os_compatible(self.case, Ubuntu))

    def test_non_ubuntu_filtering_is_unchanged(self) -> None:
        for distro in (Redhat, CentOs, Oracle, Debian, Suse, SLES, CBLMariner):
            for version in ("1.0", "99.0"):
                with self.subTest(distro=distro, version=version):
                    self.assertTrue(
                        _is_os_compatible(self.case, distro, parse_version(version))
                    )
        self.assertFalse(_is_os_compatible(self.case, Windows))

    def test_marketplace_prefilter_and_disabled_gate(self) -> None:
        for image, supported in (
            ("Canonical UbuntuServer 16.04-LTS latest", True),
            ("Canonical 0001-com-ubuntu-pro-microsoft pro-fips-18_04 latest", True),
            ("Canonical 0001-com-ubuntu-server-focal 20_04-lts latest", True),
            ("Canonical 0001-com-ubuntu-server-jammy 22_04-lts latest", True),
            ("Canonical UbuntuServer 22_10 latest", False),
            ("Canonical UbuntuServer 23_04 latest", False),
            ("Canonical ubuntu-24_04-lts server latest", False),
            ("Canonical ubuntu-25_10 server-arm64 latest", False),
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
