# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest.case import TestCase

from lisa import LisaException
from lisa.sut_orchestrator.azure.features import AzureExtension


class AzureExtensionFeatureTestCase(TestCase):
    def test_normalize_two_part_type_handler_version(self) -> None:
        extension = object.__new__(AzureExtension)

        self.assertEqual(
            ("1.45", False), extension.normalize_type_handler_version("1.45")
        )

    def test_normalize_three_part_type_handler_version(self) -> None:
        extension = object.__new__(AzureExtension)

        self.assertEqual(
            ("1.45", True), extension.normalize_type_handler_version("1.45.1")
        )

    def test_normalize_four_part_type_handler_version(self) -> None:
        extension = object.__new__(AzureExtension)

        self.assertEqual(
            ("1.45", True), extension.normalize_type_handler_version("1.45.1.2")
        )

    def test_normalize_rejects_five_part_type_handler_version(self) -> None:
        extension = object.__new__(AzureExtension)

        with self.assertRaises(LisaException):
            extension.normalize_type_handler_version("1.45.1.2.3")

    def test_type_handler_versions_equal_with_trailing_zero(self) -> None:
        self.assertTrue(
            AzureExtension.are_type_handler_versions_equal("1.45.0", "1.45.0.0")
        )

    def test_three_part_type_handler_versions_equal_exactly(self) -> None:
        self.assertTrue(
            AzureExtension.are_type_handler_versions_equal("1.45.1", "1.45.1")
        )

    def test_four_part_type_handler_versions_equal_exactly(self) -> None:
        self.assertTrue(
            AzureExtension.are_type_handler_versions_equal("1.45.1.2", "1.45.1.2")
        )

    def test_three_part_type_handler_versions_not_equal(self) -> None:
        self.assertFalse(
            AzureExtension.are_type_handler_versions_equal("1.45.1", "1.45.0.0")
        )

    def test_four_part_type_handler_versions_not_equal(self) -> None:
        self.assertFalse(
            AzureExtension.are_type_handler_versions_equal("1.45.1.2", "1.45.1.3")
        )

    def test_type_handler_versions_not_equal_when_invalid(self) -> None:
        self.assertFalse(
            AzureExtension.are_type_handler_versions_equal("1.45.0", "unknown")
        )
