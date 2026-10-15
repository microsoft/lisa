# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import MagicMock

from lisa.features.security_profile import (
    SecurityProfile,
    SecurityProfileSettings,
    SecurityProfileType,
)
from lisa.microsoft.testsuites.core.lsvmbus import VmbusDeviceNames
from lisa.operating_system import BSD, Ubuntu
from lisa.tools import Lscpu
from lisa.tools.lscpu import CpuType


class VmbusDeviceNamesTestCase(TestCase):
    def _create_node(
        self, profile: SecurityProfileType, cpu_type: CpuType
    ) -> MagicMock:
        node = MagicMock()
        node.os = MagicMock(spec=Ubuntu)
        node.features[
            SecurityProfile
        ].get_settings.return_value = SecurityProfileSettings(security_profile=profile)
        node.tools[Lscpu].get_cpu_type.return_value = cpu_type
        return node

    def test_confidential_device_names(self) -> None:
        required_names = [
            "Operating system shutdown",
            "Heartbeat",
            "Synthetic network adapter",
            "Synthetic SCSI Controller",
        ]
        for profile in (SecurityProfileType.CVM, SecurityProfileType.Stateless):
            for cpu_type in CpuType:
                with self.subTest(profile=profile, cpu_type=cpu_type):
                    node = self._create_node(profile, cpu_type)
                    expected = required_names.copy()
                    if cpu_type != CpuType.Intel:
                        expected.insert(1, "Time Synchronization")
                    self.assertEqual(VmbusDeviceNames(False, node).names, expected)

    def test_non_confidential_device_names(self) -> None:
        for profile in (SecurityProfileType.Standard, SecurityProfileType.SecureBoot):
            for is_gen1 in (False, True):
                with self.subTest(profile=profile, is_gen1=is_gen1):
                    node = self._create_node(profile, CpuType.Intel)
                    expected = [
                        "Operating system shutdown",
                        "Time Synchronization",
                        "Heartbeat",
                        "Synthetic network adapter",
                        "Synthetic SCSI Controller",
                        "Data Exchange",
                        "Synthetic mouse",
                        "Synthetic keyboard",
                    ]
                    if is_gen1:
                        expected.append("Synthetic IDE Controller")
                    self.assertEqual(VmbusDeviceNames(is_gen1, node).names, expected)
                    node.tools[Lscpu].get_cpu_type.assert_not_called()

    def test_bsd_device_names(self) -> None:
        node = self._create_node(SecurityProfileType.CVM, CpuType.Intel)
        node.os = MagicMock(spec=BSD)
        self.assertEqual(
            VmbusDeviceNames(False, node).names,
            [
                "Hyper-V Shutdown",
                "Hyper-V Timesync",
                "Hyper-V Heartbeat",
                "Hyper-V KBD",
                "Hyper-V Network Interface",
                "Hyper-V SCSI",
            ],
        )
        node.tools[Lscpu].get_cpu_type.assert_not_called()
