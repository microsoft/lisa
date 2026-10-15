from typing import Any, cast
from unittest import TestCase

from lisa.microsoft.testsuites.vm_extensions.AzureMonitorAgentLinux import (
    AzureMonitorAgentLinuxExtension,
)


class AzureMonitorAgentLinuxExtensionTestCase(TestCase):
    def setUp(self) -> None:
        suite_class = cast(Any, AzureMonitorAgentLinuxExtension).__wrapped__
        self.suite = object.__new__(suite_class)

    def test_supported_version(self) -> None:
        self.assertTrue(self.suite._is_supported_version(10, [8, 9, 10]))

    def test_newer_version(self) -> None:
        self.assertTrue(self.suite._is_supported_version(11, [8, 9, 10]))

    def test_older_unsupported_version(self) -> None:
        self.assertFalse(self.suite._is_supported_version(7, [8]))

    def test_unlisted_version_below_latest(self) -> None:
        self.assertFalse(self.suite._is_supported_version(9, [8, 10]))
