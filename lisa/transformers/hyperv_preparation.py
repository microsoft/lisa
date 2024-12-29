import json
from retry import retry
from typing import Any, Dict, List, Type

from lisa import schema
from lisa.tools import PowerShell
from lisa.tools.hyperv import HyperV
from lisa.transformers.deployment_transformer import (
    DeploymentTransformer,
    DeploymentTransformerSchema,
)


class HyperVPreparationTransformer(DeploymentTransformer):
    """
    This Transformer configures Windows Azure VM as a Hyper-V environment.
    """

    @classmethod
    def type_name(cls) -> str:
        return "hyperv_preparation"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return DeploymentTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    @retry(tries=3, delay=10)
    def _internal_run(self) -> Dict[str, Any]:
        runbook: DeploymentTransformerSchema = self.runbook
        assert isinstance(runbook, DeploymentTransformerSchema)
        node = self._node
        powershell = node.tools[PowerShell]

        powershell.run_cmdlet(
            "Install-WindowsFeature -Name DHCP,Hyper-V  -IncludeManagementTools",
            force_run=True,
        )
        # Reboot the node to apply the changes
        node.reboot()
        hv = node.tools[HyperV]

        hv.setup_nat_networking(switch_name="InternalNAT", nat_name="InternalNAT")

        hv.configure_dhcp()
        return {}
