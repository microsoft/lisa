# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase

from lisa.microsoft.testsuites.vm_extensions.azure_keyvault_vm_extension import (
    AzureKeyVaultExtensionBvt,
)
from lisa.microsoft.testsuites.vm_extensions.AzureMonitorAgentLinux import (
    AzureMonitorAgentLinuxExtension,
)
from lisa.operating_system import CBLMariner, Redhat, Ubuntu, Windows
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
            (self.monitor, (16, 4), (22, 4)),
        ):
            for major in range(14, 27):
                for month in (1, 4, 5, 9, 10, 12):
                    with self.subTest(case=case.name, major=major, month=month):
                        self.assertEqual(
                            minimum <= (major, month) < maximum,
                            _is_os_compatible(
                                case, Ubuntu, parse_version(f"{major}.{month}.5")
                            ),
                        )
            self.assertTrue(_is_os_compatible(case, Ubuntu))

    def test_non_ubuntu_requirements_are_preserved(self) -> None:
        for case in (self.key_vault, self.monitor):
            for version in ("1.0", "99.0"):
                self.assertTrue(
                    _is_os_compatible(case, CBLMariner, parse_version(version))
                )
            self.assertFalse(_is_os_compatible(case, Windows))
        self.assertFalse(_is_os_compatible(self.key_vault, Redhat))
        self.assertTrue(_is_os_compatible(self.monitor, Redhat))
