from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Dict, List, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.sut_orchestrator.azure.tools import Waagent
from lisa.tools import Ls, Sed
from lisa.transformers.deployment_transformer import (
    DeploymentTransformer,
    DeploymentTransformerSchema,
)


@dataclass_json()
@dataclass
class DisableCloudComponentsTransformerSchema(DeploymentTransformerSchema):
    pass


class DisableCloudComponentsTransformer(DeploymentTransformer):
    """
    This Transformer prepares a marketplace image for lab testing.
    """

    @classmethod
    def type_name(cls) -> str:
        return "disable_cloud_components"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return DisableCloudComponentsTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def _internal_run(self) -> Dict[str, Any]:
        runbook: DisableCloudComponentsTransformerSchema = self.runbook
        assert isinstance(runbook, DisableCloudComponentsTransformerSchema)
        node = self._node
        sed = node.tools[Sed]
        ls = node.tools[Ls]

        node.tools[Waagent].deprovision()

        node.execute("touch /var/lib/waagent/disable_agent", sudo=True)
        node.execute("touch /var/lib/waagent/provisioned", sudo=True)
        node.execute("touch /etc/cloud/cloud-init.disabled", sudo=True)

        if ls.path_exists("/etc/netplan/50-cloud-init.yaml"):
            sed.delete_lines(
                "macaddress",
                PurePosixPath("/etc/netplan/50-cloud-init.yaml"),
                sudo=True,
            )

        return {}
