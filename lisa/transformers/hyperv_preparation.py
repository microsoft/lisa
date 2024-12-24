from typing import Any, Dict, List, Type

from lisa import schema
from lisa.tools import PowerShell
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
        node = self._node
        powershell = node.tools[PowerShell]
        # Install Hyper-V and DHCP server
        powershell.run_cmdlet(
            "Install-WindowsFeature -Name DHCP,Hyper-V  -IncludeManagementTools",
            force_run=True,
        )
        # Reboot the node to apply the changes
        node.reboot()

        # Create and Configure the Hyper-V switch
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
        # Configure the DHCP server
        powershell.run_cmdlet(
            'Add-DhcpServerV4Scope -Name "DHCP-$switchName" -StartRange 192.168.0.50 -EndRange 192.168.0.100 -SubnetMask 255.255.255.0',  # noqa: E501
            force_run=True,
        )
        powershell.run_cmdlet(
            "Set-DhcpServerV4OptionValue -Router 192.168.0.1 -DnsServer 168.63.129.16",
            force_run=True,
        )
        # Restart the DHCP server to apply the changes
        powershell.run_cmdlet(
            "Restart-service dhcpserver",
            force_run=True,
        )
        return {}
