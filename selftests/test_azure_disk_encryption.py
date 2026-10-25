# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import inspect
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.microsoft.testsuites.vm_extensions.azure_disk_encryption import (
    AzureDiskEncryption,
)
from lisa.operating_system import Posix
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import AzureNodeSchema
from lisa.tools import Lscpu
from lisa.tools.lscpu import CpuArchitecture
from lisa.util import LisaException, SkippedException


class AzureDiskEncryptionEligibilityTestCase(TestCase):
    def setUp(self) -> None:
        self.node = MagicMock()
        self.node.os = MagicMock(spec=Posix)
        self.log = MagicMock()
        self.suite = inspect.unwrap(AzureDiskEncryption)(MagicMock())
        self.node.tools[Lscpu].get_architecture.return_value = CpuArchitecture.X64
        self.node.tools.reset_mock()
        self.node.os.is_package_in_repo.return_value = True

    def _set_vm_size(self, vm_size: str) -> None:
        self.node.capability.get_extended_runbook.return_value = AzureNodeSchema(
            vm_size=vm_size
        )

    def test_unsupported_sizes_skip_before_guest_access(self) -> None:
        for vm_size in (
            "Basic_A1",
            "Standard_A1",
            "Standard_A2m_v2",
            "Standard_L8s",
            "Standard_L8s_v2",
            "Standard_L8as_v3",
            "Standard_L8s_v5",
            "Standard_D2s_v6",
            "Standard_D192ds_v6",
            "Standard_E16bs_v6",
            "Standard_D16-4s_v6",
            "Standard_D2s_v7",
            "Standard_D2s_v10",
            "Standard_D2s_v100",
            "Standard_D2_v6_Promo",
            "standard_d2s_V6",
        ):
            with self.subTest(vm_size=vm_size):
                self._set_vm_size(vm_size)
                with patch.object(
                    self.suite, "_is_supported_linux_distro", return_value=True
                ):
                    with self.assertRaisesRegex(SkippedException, vm_size):
                        self.suite.before_case(self.log, node=self.node)
                self.node.tools.__getitem__.assert_not_called()
                self.node.os.is_package_in_repo.assert_not_called()
                self.node.os.install_packages.assert_not_called()

    def test_other_sizes_continue_existing_prerequisites(self) -> None:
        for vm_size in (
            "Standard_D2s_v5",
            "Standard_D2s_v3",
            "Standard_D2_v2_Promo",
            "Standard_DS2",
            "Standard_B2s",
            "Standard_E16-4s_v5",
            "Standard_M416ms_v2",
            "Standard_NG8ads_V620_v1",
        ):
            with self.subTest(vm_size=vm_size):
                self._set_vm_size(vm_size)
                self.node.os.reset_mock()
                with patch.object(
                    self.suite, "_is_supported_linux_distro", return_value=True
                ) as distro_check:
                    self.suite.before_case(self.log, node=self.node)
                distro_check.assert_called_once_with(self.node)
                self.node.capability.get_extended_runbook.assert_called_with(
                    AzureNodeSchema, AZURE
                )
                self.assertEqual(2, self.node.os.is_package_in_repo.call_count)
                self.assertEqual(2, self.node.os.install_packages.call_count)

    def test_missing_vm_size_fails_before_guest_access(self) -> None:
        self._set_vm_size("")
        with patch.object(self.suite, "_is_supported_linux_distro", return_value=True):
            with self.assertRaisesRegex(LisaException, "VM size"):
                self.suite.before_case(self.log, node=self.node)
        self.node.tools.__getitem__.assert_not_called()
        self.node.os.is_package_in_repo.assert_not_called()

    def test_unsupported_architecture_still_skips(self) -> None:
        self._set_vm_size("Standard_D2ps_v5")
        self.node.tools[Lscpu].get_architecture.return_value = CpuArchitecture.ARM64
        with self.assertRaises(SkippedException):
            self.suite.before_case(self.log, node=self.node)
        self.node.os.is_package_in_repo.assert_not_called()

    def test_unsupported_distro_still_skips(self) -> None:
        self._set_vm_size("Standard_D2s_v5")
        with patch.object(self.suite, "_is_supported_linux_distro", return_value=False):
            with self.assertRaises(SkippedException):
                self.suite.before_case(self.log, node=self.node)
        self.node.os.is_package_in_repo.assert_not_called()

    def test_unavailable_packages_are_not_installed(self) -> None:
        self._set_vm_size("Standard_D2s_v5")
        self.node.os.is_package_in_repo.return_value = False
        with patch.object(self.suite, "_is_supported_linux_distro", return_value=True):
            self.suite.before_case(self.log, node=self.node)
        self.assertEqual(2, self.node.os.is_package_in_repo.call_count)
        self.node.os.install_packages.assert_not_called()
