import ipaddress
import json
from functools import partial
from typing import Any, List, cast

import requests
from azure.mgmt.resource import SubscriptionClient  # type: ignore
from retry import retry

from lisa.environment import Environment
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.util import hookimpl, plugin_manager
from lisa.util.logger import get_logger

# this module enable nsg for azure deployment

_get_logger = partial(get_logger, "nsg")


def get_tenant_id(environment: Environment) -> str:
    platform = cast(AzurePlatform, environment.platform)
    sub_client = SubscriptionClient(credential=platform.credential)
    subscription = sub_client.subscriptions.get(
        subscription_id=platform.subscription_id
    )

    return str(subscription.tenant_id)


def get_subscription_id(environment: Environment) -> str:
    platform = cast(AzurePlatform, environment.platform)
    subscription = platform.subscription_id

    return str(subscription)


class AzureNsgEnablement:
    _ms_tenant_id = "72f988bf-86f1-41af-91ab-2d7cd011db47"
    _nrms_subscriptions: List[str] = [
        # LSG_Quality_NewVMSKU_Validation
        "65521efe-6a7f-454e-9916-82eb59020194",
        # EdgeOS_Mariner_Platform_Marketplace
        "381ca650-6545-4303-a1db-a6a7349ce486",
        # Linux Integration Services TEST AUTOMATION ONLY
        "0cc2a67a-58b9-4e4f-98a8-bfa46a28e896",
    ]
    _disabled_subscriptions: List[str] = [
        # LSG - 1 [Cirrus]
        "38e26629-7592-4e7d-95fe-e66f4eb3c52f",
        # az qualify subscription
        "cafd0154-31a7-4df9-9485-c590bc0b7bf6",
    ]

    def __init__(self) -> None:
        self._cached_ip_addresses: List[str] = []

    _rules_template_ms = """
        {
            "name": "1ESPoolSSH",
            "properties": {
                "description": "Allows SSH traffic",
                "protocol": "Tcp",
                "sourcePortRange": "*",
                "destinationPortRange": "22",
                "sourceAddressPrefix": "1ESResourceManager",
                "destinationAddressPrefix": "*",
                "access": "Allow",
                "priority": 200,
                "direction": "Inbound",
                "sourcePortRanges": [],
                "destinationPortRanges": [],
                "sourceAddressPrefixes": [],
                "destinationAddressPrefixes": []
            }
        },
        {
            "name": "1ESLibvirtSSH",
            "properties": {
                "description": "Allows SSH traffic to Libvirt Platform Guests",
                "protocol": "Tcp",
                "sourcePortRange": "*",
                "destinationPortRange": "49152-49352",
                "sourceAddressPrefix": "1ESResourceManager",
                "destinationAddressPrefix": "*",
                "access": "Allow",
                "priority": 208,
                "direction": "Inbound",
                "sourcePortRanges": [],
                "destinationPortRanges": [],
                "sourceAddressPrefixes": [],
                "destinationAddressPrefixes": []
            }
        },
        {
            "name": "1ESPoolKVM",
            "properties": {
                "description": "Allows nested VM SSH traffic",
                "protocol": "Tcp",
                "sourceAddressPrefix": "1ESResourceManager",
                "sourcePortRange": "*",
                "destinationPortRange": "60020-60030",
                "destinationAddressPrefix": "*",
                "access": "Allow",
                "priority": 204,
                "direction": "Inbound"
            }
        },
        {"name": "ManagedVPNSSH",
            "properties": {
                "description": "Allows SSH traffic",
                "protocol": "Tcp",
                "sourcePortRange": "*",
                "destinationPortRange": "22",
                "sourceAddressPrefix": "",
                "destinationAddressPrefix": "*",
                "access": "Allow",
                "priority": 201,
                "direction": "Inbound",
                "sourcePortRanges": [],
                "destinationPortRanges": [],
                "sourceAddressPrefixes": [
                    "20.120.143.192/28",
                    "20.241.227.160/28",
                    "20.31.68.160/28",
                    "20.198.165.176/28",
                    "20.83.242.194/32"
                ],
                "destinationAddressPrefixes": []
            }
        },
        {
            "name": "CorpNetPublicSSH",
            "properties": {
                "description": "Allows SSH traffic",
                "protocol": "Tcp",
                "sourcePortRange": "*",
                "destinationPortRange": "22",
                "sourceAddressPrefix": "CorpNetPublic",
                "destinationAddressPrefix": "*",
                "access": "Allow",
                "priority": 202,
                "direction": "Inbound",
                "sourcePortRanges": [],
                "destinationPortRanges": [],
                "sourceAddressPrefixes": [],
                "destinationAddressPrefixes": []
            }
        },
        {
            "name": "CorpNetSawSSH",
            "properties": {
                "description": "Allows SSH traffic",
                "protocol": "Tcp",
                "sourcePortRange": "*",
                "destinationPortRange": "22",
                "sourceAddressPrefix": "CorpNetSAW",
                "destinationAddressPrefix": "*",
                "access": "Allow",
                "priority": 203,
                "direction": "Inbound",
                "sourcePortRanges": [],
                "destinationPortRanges": [],
                "sourceAddressPrefixes": [],
                "destinationAddressPrefixes": []
            }
        },
        {
            "name": "AitlResourceProviderSSH",
            "properties": {
                "description": "Allows SSH traffic from AITLs RP",
                "protocol": "Tcp",
                "sourcePortRange": "*",
                "destinationPortRange": "22",
                "sourceAddressPrefix": "AzureImageTestingForLinux",
                "destinationAddressPrefix": "*",
                "access": "Allow",
                "priority": 207,
                "direction": "Inbound",
                "sourcePortRanges": [],
                "destinationPortRanges": [],
                "sourceAddressPrefixes": [],
                "destinationAddressPrefixes": []
            }
        },
    """
    _rules_template_common = """
        {
            "name": "LISATriggerSSH",
            "properties": {
                "description": "Allows SSH traffic",
                "protocol": "Tcp",
                "sourcePortRange": "*",
                "destinationPortRange": "22",
                "destinationAddressPrefix": "*",
                "access": "Allow",
                "priority": 205,
                "direction": "Inbound"
            }
        },
        {
            "name": "LISATriggerKVMs",
            "properties": {
                "description": "Allows nested VM SSH traffic",
                "protocol": "Tcp",
                "sourcePortRange": "*",
                "destinationPortRange": "60020-60030",
                "destinationAddressPrefix": "*",
                "access": "Allow",
                "priority": 206,
                "direction": "Inbound"
            }
        }
    """
    # This rule is for AzQ runs and used after talking to NetIso team.
    # It is understood that there will be S360 alerts with this.
    _rules_template_nrms = """
        {
            "name": "LISATriggerSSH",
            "properties": {
                "description": "Allows SSH traffic",
                "protocol": "Tcp",
                "sourcePortRange": "*",
                "destinationPortRange": "22",
                "destinationAddressPrefix": "*",
                "access": "Allow",
                "priority": 100,
                "direction": "Inbound"
            }
        },
        {
            "name": "LISATriggerKVMs",
            "properties": {
                "description": "Allows nested VM SSH traffic",
                "protocol": "Tcp",
                "sourcePortRange": "*",
                "destinationPortRange": "60020-60030",
                "destinationAddressPrefix": "*",
                "access": "Allow",
                "priority": 206,
                "direction": "Inbound"
            }
        }
    """
    _nsg_resource_template_ends = """
            ]
        }
    }
    """
    _nsg_resource_template_starts = """
    {
        "type": "Microsoft.Network/networkSecurityGroups",
        "name": "internal-nsg",
        "location": "[parameters('location')]",
        "apiVersion": "2020-05-01",
        "properties": {
            "securityRules": [
    """
    _nsg_reference = """
    {
      "networkSecurityGroup": {
        "id": "[resourceId('Microsoft.Network/networkSecurityGroups', 'internal-nsg')]"
      }
    }
    """
    _nsg_resource_id_template = (
        "[resourceId('Microsoft.Network/networkSecurityGroups', 'internal-nsg')]"
    )

    @hookimpl
    def azure_update_arm_template(
        self, template: Any, environment: Environment
    ) -> None:
        # generate rules
        subscription_id = get_subscription_id(environment=environment)
        if subscription_id.lower() in self._disabled_subscriptions:
            return

        if subscription_id.lower() in self._nrms_subscriptions:
            rules = self._rules_template_nrms
        else:
            rules = self._rules_template_common
        tenant_id = get_tenant_id(environment=environment)
        if tenant_id.lower() == self._ms_tenant_id:
            rules = self._rules_template_ms + rules

        nsg = (
            self._nsg_resource_template_starts
            + rules
            + self._nsg_resource_template_ends
        )

        # add resource definition
        nsg_resource = json.loads(nsg)
        for i in range(len(nsg_resource["properties"]["securityRules"])):
            rule_name: str = nsg_resource["properties"]["securityRules"][i]["name"]
            if rule_name.startswith("LISATrigger"):
                nsg_resource["properties"]["securityRules"][i]["properties"][
                    "sourceAddressPrefixes"
                ] = self._get_ip_addresses()

        resources = template["resources"]

        if isinstance(resources, list):
            resources.append(nsg_resource)
        elif isinstance(resources, dict):
            resources["nsg_resource"] = nsg_resource
        else:
            # Log unexpected type
            log = _get_logger()
            log.error(f"Unexpected resources type: {type(resources)}")

        # add dependency
        vnet_resource = self._get_resource(
            resources, "Microsoft.Network/virtualNetworks"
        )
        if "dependsOn" not in vnet_resource:
            vnet_resource["dependsOn"] = []
        vnet_resource["dependsOn"].append(self._nsg_resource_id_template)

        subnet_resources = vnet_resource["properties"]["copy"]
        subnet_resource = self._get_resource_by_name(subnet_resources, "subnets")
        subnet_resource["input"]["properties"].update(json.loads(self._nsg_reference))

    @retry(tries=10, delay=0.5)
    def _get_external_ip_address(self) -> str:
        response = requests.get("https://api.ipify.org/")
        result = response.text
        ipaddress.ip_address(result)
        log = _get_logger()
        log.debug(f"get LISA external ip address: {result}")
        return result

    def _get_resource(self, resources: Any, type_name: str) -> Any:
        resource: Any = None
        if isinstance(resources, dict):
            resources = resources.values()
        for item in resources:
            if item["type"] == type_name:
                resource = item
                break
        assert resource
        return resource

    def _get_resource_by_name(self, resources: Any, res_name: str) -> Any:
        resource: Any = None
        for item in resources:
            if item["name"] == res_name:
                resource = item
                break
        assert resource
        return resource

    def _get_ip_addresses(self) -> List[str]:
        if self._cached_ip_addresses:
            return self._cached_ip_addresses

        external_ip_address_str = self._get_external_ip_address()

        self._cached_ip_addresses = [external_ip_address_str]
        return self._cached_ip_addresses


plugin_manager.register(AzureNsgEnablement())
