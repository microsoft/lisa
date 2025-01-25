from typing import Any, Dict, List, Type

from lisa import schema
from lisa.tools import AzCopy, PowerShell
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
        azcopy = self._node.tools[AzCopy]
        azcopy.download_file(
            sas_url = r'url',
            localfile=r"C:\Ubuntu2404.vhdx"
        )
        node = self._node
        powershell = node.tools[PowerShell]
        powershell.run_cmdlet(
            "Install-WindowsFeature -Name DHCP,Hyper-V  -IncludeManagementTools",
            force_run=True,
        )
        node.reboot()
        powershell.run_cmdlet(
            "New-VMSwitch -Name 'InternalNAT' -SwitchType Internal",
            force_run=True,
        )
        powershell.run_cmdlet(
            "New-NetNat -Name 'InternalNAT' -InternalIPInterfaceAddressPrefix '192.168.0.0/24'",  # noqa: E501
            force_run=True,
        )
        powershell.run_cmdlet(
            'New-NetIPAddress -IPAddress 192.168.0.1 -InterfaceIndex (Get-NetAdapter | Where-Object { $_.Name -like "*InternalNAT)" } | Select-Object -ExpandProperty ifIndex) -PrefixLength 24',  # noqa: E501
            force_run=True,
        )
        return {}
