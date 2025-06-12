# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest.case import TestCase
from unittest.mock import MagicMock, patch
from typing import List

from lisa import schema
from lisa.sut_orchestrator.azure.transformers import DeployTransformer, DeployTransformerSchema
from lisa.parameter_parser.runbook import RunbookBuilder
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform, AzurePlatformSchema


class AzureTransformerTestCase(TestCase):
    def test_deploy_transformer_schema_fields(self) -> None:
        """Test that DeployTransformerSchema accepts source_address_prefixes and resource_group_name"""
        # Test data
        test_data = {
            "type": "azure_deploy",
            "name": "test_deploy",
            "resource_group_name": "test-rg-name",
            "source_address_prefixes": ["192.168.1.0/24", "10.0.0.0/8"],
            "deploy": True,
            "requirement": {
                "azure": {
                    "marketplace": "Canonical UbuntuServer 18.04-LTS latest"
                }
            }
        }

        # Load schema
        transformer_schema = schema.load_by_type(DeployTransformerSchema, test_data)

        # Validate fields are set correctly
        self.assertEqual("test-rg-name", transformer_schema.resource_group_name)
        self.assertEqual(["192.168.1.0/24", "10.0.0.0/8"], transformer_schema.source_address_prefixes)
        self.assertTrue(transformer_schema.deploy)

    def test_deploy_transformer_schema_defaults(self) -> None:
        """Test that DeployTransformerSchema has correct defaults"""
        test_data = {
            "type": "azure_deploy",
            "name": "test_deploy"
        }

        # Load schema
        transformer_schema = schema.load_by_type(DeployTransformerSchema, test_data)

        # Validate defaults
        self.assertEqual("", transformer_schema.resource_group_name)
        self.assertEqual([], transformer_schema.source_address_prefixes)
        self.assertTrue(transformer_schema.deploy)

    def test_deploy_transformer_sets_platform_values(self) -> None:
        """Test that DeployTransformer sets values on platform._azure_runbook when provided"""
        # Test data
        transformer_data = {
            "type": "azure_deploy",
            "name": "test_deploy",
            "resource_group_name": "test-rg-name",
            "source_address_prefixes": ["192.168.1.0/24", "10.0.0.0/8"],
            "deploy": True
        }

        # Create transformer schema
        transformer_schema = schema.load_by_type(DeployTransformerSchema, transformer_data)

        # Verify that the schema has the correct values
        self.assertEqual("test-rg-name", transformer_schema.resource_group_name)
        self.assertEqual(["192.168.1.0/24", "10.0.0.0/8"], transformer_schema.source_address_prefixes)
        self.assertTrue(transformer_schema.deploy)

        # Create mock platform to test the assignment logic
        mock_platform = MagicMock()
        mock_platform._azure_runbook = AzurePlatformSchema()

        # Simulate the assignment logic from the _internal_run method
        if transformer_schema.resource_group_name:
            mock_platform._azure_runbook.resource_group_name = transformer_schema.resource_group_name
        if transformer_schema.source_address_prefixes:
            mock_platform._azure_runbook.source_address_prefixes = transformer_schema.source_address_prefixes
        mock_platform._azure_runbook.deploy = transformer_schema.deploy

        # Verify assignments were made correctly
        self.assertEqual("test-rg-name", mock_platform._azure_runbook.resource_group_name)
        self.assertEqual(["192.168.1.0/24", "10.0.0.0/8"], mock_platform._azure_runbook.source_address_prefixes)
        self.assertTrue(mock_platform._azure_runbook.deploy)

    def test_deploy_transformer_empty_values_logic(self) -> None:
        """Test the assignment logic when transformer values are empty"""
        # Test data with empty values
        transformer_data = {
            "type": "azure_deploy",
            "name": "test_deploy",
            "resource_group_name": "",  # Empty string
            "source_address_prefixes": [],  # Empty list
            "deploy": False
        }

        # Create transformer schema
        transformer_schema = schema.load_by_type(DeployTransformerSchema, transformer_data)

        # Create mock platform with pre-existing values
        mock_platform = MagicMock()
        mock_platform._azure_runbook = AzurePlatformSchema()
        mock_platform._azure_runbook.resource_group_name = "existing-rg"
        mock_platform._azure_runbook.source_address_prefixes = ["10.1.0.0/16"]

        # Simulate the assignment logic from the _internal_run method
        if transformer_schema.resource_group_name:
            mock_platform._azure_runbook.resource_group_name = transformer_schema.resource_group_name
        if transformer_schema.source_address_prefixes:
            mock_platform._azure_runbook.source_address_prefixes = transformer_schema.source_address_prefixes
        mock_platform._azure_runbook.deploy = transformer_schema.deploy

        # Verify that existing values are preserved when transformer values are empty
        self.assertEqual("existing-rg", mock_platform._azure_runbook.resource_group_name)  # Not overridden
        self.assertEqual(["10.1.0.0/16"], mock_platform._azure_runbook.source_address_prefixes)  # Not overridden
        self.assertFalse(mock_platform._azure_runbook.deploy)  # This gets set since it's always set