# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch

from lisa.microsoft.testsuites.vm_extensions.azure_keyvault_vm_extension import (
    AzureKeyVaultExtensionBvt,
)
from lisa.microsoft.testsuites.vm_extensions.AzureMonitorAgentLinux import (
    AzureMonitorAgentLinuxExtension,
)
from lisa.operating_system import CBLMariner, OsInformation, Redhat, Ubuntu, Windows
from lisa.testselector import _is_os_compatible
from lisa.testsuite import get_cases_metadata
from lisa.util import parse_version


class ExtensionUbuntuRequirementTestCase(TestCase):
    key_vault = get_cases_metadata()[
        f"{AzureKeyVaultExtensionBvt.__name__}.verify_key_vault_extension"
    ]
    monitor = get_cases_metadata()[
        f"{AzureMonitorAgentLinuxExtension.__name__}.verify_azuremonitoragent_linux"
    ]

    def test_ubuntu_ranges(self) -> None:
        for case, minimum, maximum in (
            (self.key_vault, (20, 4), (22, 10)),
            (self.monitor, (16, 4), None),
        ):
            for major in range(14, 27):
                for month in (1, 4, 5, 9, 10, 12):
                    with self.subTest(case=case.name, major=major, month=month):
                        self.assertEqual(
                            minimum <= (major, month)
                            and (maximum is None or (major, month) < maximum),
                            _is_os_compatible(
                                case, Ubuntu, parse_version(f"{major}.{month}.5")
                            ),
                        )
            self.assertTrue(_is_os_compatible(case, Ubuntu))

    def test_mariner_release_requirements(self) -> None:
        for case in (self.key_vault, self.monitor):
            self.assertFalse(_is_os_compatible(case, CBLMariner, parse_version("1.0")))
            self.assertTrue(_is_os_compatible(case, CBLMariner, parse_version("2.0")))
            self.assertFalse(_is_os_compatible(case, Windows))
        self.assertFalse(
            _is_os_compatible(self.key_vault, CBLMariner, parse_version("99.0"))
        )
        self.assertFalse(_is_os_compatible(self.key_vault, Redhat))
        self.assertTrue(_is_os_compatible(self.monitor, Redhat))

    def test_monitor_current_and_future_releases_remain_supported(self) -> None:
        suite = self.monitor.suite.test_class(self.monitor.suite)
        for distro, releases in (
            (CBLMariner, ("2.0", "3.0", "4.0", "5.0", "99.0")),
            (Redhat, ("8.0", "9.0", "10.0", "11.0", "99.0")),
            (Ubuntu, ("18.04", "20.04", "22.04", "24.04", "26.04", "28.04", "99.04")),
        ):
            for release in releases:
                version = parse_version(release)
                for architecture in ("x86_64", "aarch64"):
                    with self.subTest(
                        distro=distro.__name__,
                        release=release,
                        architecture=architecture,
                    ):
                        self.assertTrue(
                            _is_os_compatible(self.monitor, distro, version)
                        )
                        node = MagicMock()
                        node.os = distro(node)
                        node.os._information = OsInformation(
                            version=version, vendor=distro.__name__, release=release
                        )
                        with patch.object(
                            node.os,
                            "get_kernel_information",
                            return_value=Mock(hardware_platform=architecture),
                        ):
                            suite.before_case(log=Mock(), node=node)
