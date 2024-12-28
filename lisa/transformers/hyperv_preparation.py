import json
import time
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

    def _wait_for_service_ready(self, service_name: str) -> None:
        node = self._node
        powershell = node.tools[PowerShell]
        # Wait for WMI service to be ready
        for _ in range(10):
            output = powershell.run_cmdlet(
                f"Get-Service {service_name}",
                force_run=True,
                output_json=True,
            )
            service_status = json.loads(output)
            print(service_status["Status"])
            if int(schema.WindowsServiceStatus.RUNNING) == service_status["Status"]:
                return
            time.sleep(5)

        raise AssertionError(f"'{service_name}' service is not ready")

    @retry(tries=3, delay=10)
    def _internal_run(self) -> Dict[str, Any]:
        runbook: DeploymentTransformerSchema = self.runbook
        assert isinstance(runbook, DeploymentTransformerSchema)
        node = self._node
        powershell = node.tools[PowerShell]

        # check if Hyper-V is already installed
        # output = powershell.run_cmdlet(
        #     "Get-WindowsOptionalFeature -Online -FeatureName Hyper-V",
        #     force_run=True,
        #     output_json=True,
        # )
        # feature = json.loads(output)
        # if feature["State"] == "Enabled":
        #     return {}
        # Install Hyper-V and DHCP server
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
