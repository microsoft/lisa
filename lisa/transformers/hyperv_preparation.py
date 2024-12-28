import json
import time
from retry import retry
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
    def _create_vswitch(
        self,
        powershell: PowerShell,
        switch_name: str,
        switch_type: str,
    ) -> None:
        # Check if the Hyper-V switch already exists
        output = powershell.run_cmdlet(
            f"Get-VMSwitch -Name '{switch_name}'",
            force_run=True,
            output_json=True,
        )
        switch_exists = json.loads(output)
        if switch_exists:
            return
        # Create and Configure the Hyper-V switch
        powershell.run_cmdlet(
            f"New-VMSwitch -Name '{switch_name}' -SwitchType {switch_type}",
            force_run=True,
        )
        powershell.run_cmdlet(
            f"New-NetNat -Name '{switch_name}' -InternalIPInterfaceAddressPrefix '192.168.0.0/24' -Confirm:$false",  # noqa: E501
            force_run=True,
        )
        powershell.run_cmdlet(
            'New-NetIPAddress -IPAddress 192.168.0.1 -InterfaceIndex (Get-NetAdapter | Where-Object { $_.Name -like "*InternalNAT)" } | Select-Object -ExpandProperty ifIndex) -PrefixLength 24',  # noqa: E501
            force_run=True,
        )

    def _internal_run(self) -> Dict[str, Any]:
        runbook: DeploymentTransformerSchema = self.runbook
        assert isinstance(runbook, DeploymentTransformerSchema)
        node = self._node
        powershell = node.tools[PowerShell]

        # check if Hyper-V is already installed
        output = powershell.run_cmdlet(
            "Get-WindowsOptionalFeature -Online -FeatureName Hyper-V",
            force_run=True,
            output_json=True,
        )
        # Install Hyper-V and DHCP server
        powershell.run_cmdlet(
            "Install-WindowsFeature -Name DHCP,Hyper-V  -IncludeManagementTools",
            force_run=True,
        )
        # Reboot the node to apply the changes
        node.reboot()
        self._create_vswitch(powershell, "InternalNAT", "Internal")

        self._configure_dhcp(powershell, dhcp_scope_name="DHCPInternalNAT")
        return {}

    def _configure_dhcp(self, powershell: PowerShell, dhcp_scope_name: str) -> None:
        # check if DHCP server is already configured
        output = powershell.run_cmdlet(
            "Get-DhcpServerv4Scope",
            force_run=True,
            output_json=True,
        )
        scope_exists = json.loads(output)
        if scope_exists:
            return
        # Configure the DHCP server
        powershell.run_cmdlet(
            f'Add-DhcpServerV4Scope -Name "{dhcp_scope_name}" -StartRange 192.168.0.50 -EndRange 192.168.0.100 -SubnetMask 255.255.255.0',  # noqa: E501
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
        self._wait_for_service_ready("dhcpserver")
