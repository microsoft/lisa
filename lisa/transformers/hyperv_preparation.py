from typing import Any, Dict, List, Type

from lisa import schema
from lisa.tools import HyperV
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

    def _internal_run(self) -> Dict[str, Any]:
        runbook: DeploymentTransformerSchema = self.runbook
        assert isinstance(runbook, DeploymentTransformerSchema)
        switch_name = "InternalNAT"

        # Enable Hyper-V
        hv = self._node.tools[HyperV]

        # Configure lisa working path to use free disk.
        hv.use_raw_disk_for_lisa_working_dir()

        # Create an internal switch.
        hv.create_switch(name=switch_name)

        hv.setup_nat_networking(switch_name=switch_name, nat_name=switch_name)

        # Configure Internal DHCP
        hv.enable_internal_dhcp()
        return {}
