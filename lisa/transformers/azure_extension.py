# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from typing import Any, Dict, List, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.transformers.deployment_transformer import (
    DeploymentTransformer,
    DeploymentTransformerSchema,
)
from lisa.util import LisaException, field_metadata


@dataclass_json()
@dataclass
class AzureExtensionTransformerSchema(DeploymentTransformerSchema):
    """
    Schema for Azure Extension Transformer.
    Installs or updates an Azure VM Extension before test execution.
    """

    extension_name: str = field(default="", metadata=field_metadata(required=True))
    publisher: str = field(default="", metadata=field_metadata(required=True))
    type_handler_version: str = field(
        default="", metadata=field_metadata(required=True)
    )

    settings: Dict[str, Any] = field(default_factory=dict)

    enable_automatic_upgrade: bool = False
    auto_upgrade_minor_version: bool = False


class AzureExtensionTransformer(DeploymentTransformer):
    """
    Installs Azure VM Extensions on a deployed node.

    This transformer inherits from DeploymentTransformer to work with
    azure_deploy and azure_vhd transformers, ensuring connection object
    availability.
    """

    @classmethod
    def type_name(cls) -> str:
        return "azure_extension"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return AzureExtensionTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def _validate(self) -> None:
        """Validate that the node supports Azure extensions."""
        runbook: AzureExtensionTransformerSchema = self.runbook

        if not runbook.extension_name:
            raise LisaException("extension_name is required")
        if not runbook.publisher:
            raise LisaException("publisher is required")
        if not runbook.type_handler_version:
            raise LisaException("type_handler_version is required")

        # Check if node supports AzureExtension feature
        if not self._node.features.is_supported(AzureExtension):
            raise LisaException(
                f"Node '{self._node.name}' does not support " f"AzureExtension feature."
            )

    def _internal_run(self) -> Dict[str, Any]:
        runbook: AzureExtensionTransformerSchema = self.runbook
        log = self._log
        node = self._node

        extension = node.features[AzureExtension]

        log.info(
            f"Installing Azure extension '{runbook.extension_name}' "
            f"on node '{node.name}'"
        )

        result = extension.create_or_update(
            name=runbook.extension_name,
            publisher=runbook.publisher,
            type_=runbook.extension_name,
            type_handler_version=runbook.type_handler_version,
            settings=runbook.settings,
            enable_automatic_upgrade=runbook.enable_automatic_upgrade,
            auto_upgrade_minor_version=runbook.auto_upgrade_minor_version,
        )

        # Check provisioning result
        state = result.get("provisioning_state", "Unknown")
        if state != "Succeeded":
            raise LisaException(
                f"Extension '{runbook.extension_name}' provisioning failed on "
                f"node '{node.name}': {state}"
            )

        log.info(
            f"Extension '{runbook.extension_name}' installed successfully "
            f"on '{node.name}'"
        )

        return {
            "extension_name": runbook.extension_name,
            "node_name": node.name,
            "provisioning_state": state,
        }
