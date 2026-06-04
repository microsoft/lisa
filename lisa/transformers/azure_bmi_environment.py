# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Type

from dataclasses_json import dataclass_json
from marshmallow import validate

from lisa import schema
from lisa.node import Node
from lisa.sut_orchestrator.azure.common import (
    associate_route_table_to_subnet,
    check_or_create_resource_group,
    create_or_update_dedicated_host,
    create_or_update_dedicated_host_group,
    create_or_update_network_interface,
    create_or_update_network_security_group,
    create_or_update_network_security_rule,
    create_or_update_public_ip,
    create_or_update_route,
    create_or_update_route_table,
    create_or_update_virtual_machine,
    create_or_update_virtual_network,
    get_compute_client,
    get_network_client,
    get_primary_ip_addresses,
)
from lisa.sut_orchestrator.azure.transformers import _load_platform
from lisa.transformer import Transformer
from lisa.transformers.deployment_transformer import (
    DeploymentTransformer,
    DeploymentTransformerSchema,
)
from lisa.util import (
    LisaException,
    check_till_timeout,
    field_metadata,
    get_datetime_path,
)

DEFAULT_LOCATION = "southeastus5"
DEFAULT_JUMPHOST_IMAGE = "Canonical:0001-com-ubuntu-server-jammy:22_04-lts-gen2:latest"
DEFAULT_JUMPHOST_VM_SIZE = "Standard_DS2_v2"
DEFAULT_BMI_VM_SIZE = "ND144isr_ETH_GB200_metal_v6"
DEFAULT_BMI_HOST_SKU = "GPCv6GB200S186_ETH_metal-Type1"

RUNBOOK_VAR_LOCATION = "bmi_location"
RUNBOOK_VAR_JUMPHOST_IMAGE = "bmi_jumphost_image"
RUNBOOK_VAR_JUMPHOST_VM_SIZE = "bmi_jumphost_vm_size"
RUNBOOK_VAR_JUMPHOST_USERNAME = "bmi_jumphost_username"
RUNBOOK_VAR_BMI_VM_SIZE = "bmi_vm_size"
RUNBOOK_VAR_BMI_HOST_SKU = "bmi_host_sku"
RUNBOOK_VAR_BMI_ADMIN_USERNAME = "bmi_admin_username"
RUNBOOK_VAR_BMI_ADMIN_PASSWORD = "bmi_admin_password"


@dataclass_json
@dataclass
class AzureBmiEnvironmentTransformerSchema(schema.Transformer):
    location: str = DEFAULT_LOCATION
    resource_group_name: str = ""
    deployment_subscription_id: str = ""

    bmi_image: str = field(default="", metadata=field_metadata(required=True))
    bmi_count: int = field(
        default=2,
        metadata=field_metadata(validate=validate.Range(min=1, max=50)),
    )
    bmi_vm_size: str = DEFAULT_BMI_VM_SIZE
    bmi_host_sku: str = DEFAULT_BMI_HOST_SKU
    bmi_specialized_image: bool = True

    vnet_name: str = ""
    vnet_prefix: str = "10.0.0.0/16"
    internal_subnet_name: str = "internal_subnet"
    internal_subnet_prefix: str = "10.0.1.0/24"
    external_subnet_name: str = "external_subnet"
    external_subnet_prefix: str = "10.0.2.0/24"

    host_group_name: str = ""
    nsg_name: str = ""

    jumphost_name: str = ""
    jumphost_username: str = "lisatest"
    jumphost_password: str = field(
        default="", metadata=field_metadata(required=True)
    )
    jumphost_vm_size: str = DEFAULT_JUMPHOST_VM_SIZE
    jumphost_image: str = DEFAULT_JUMPHOST_IMAGE

    bmi_admin_username: str = "azhpcuser"
    bmi_admin_password: str = ""

    nat_start_port: int = field(
        default=50000,
        metadata=field_metadata(validate=validate.Range(min=1, max=65500)),
    )


class AzureBmiEnvironmentTransformer(Transformer):
    @classmethod
    def type_name(cls) -> str:
        return "azure_bmi_environment"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return AzureBmiEnvironmentTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return [
            "resource_group_name",
            "jumphost_public_ip",
            "jumphost_username",
            "jumphost_password",
            "jumphost_name",
            "bmi_names",
            "bmi_private_ips",
            "bmi_ssh_ports",
            "host_group_name",
            "vnet_name",
        ]

    def _internal_run(self) -> Dict[str, Any]:
        runbook: AzureBmiEnvironmentTransformerSchema = self.runbook
        platform = _load_platform(self._runbook_builder, self.type_name())

        location = self._resolve_runbook_value(
            runbook.location,
            RUNBOOK_VAR_LOCATION,
            DEFAULT_LOCATION,
        )
        jumphost_image = self._resolve_runbook_value(
            runbook.jumphost_image,
            RUNBOOK_VAR_JUMPHOST_IMAGE,
            DEFAULT_JUMPHOST_IMAGE,
        )
        jumphost_vm_size = self._resolve_runbook_value(
            runbook.jumphost_vm_size,
            RUNBOOK_VAR_JUMPHOST_VM_SIZE,
            DEFAULT_JUMPHOST_VM_SIZE,
        )
        jumphost_username = self._resolve_runbook_value(
            runbook.jumphost_username,
            RUNBOOK_VAR_JUMPHOST_USERNAME,
            "lisatest",
        )
        bmi_vm_size = self._resolve_runbook_value(
            runbook.bmi_vm_size,
            RUNBOOK_VAR_BMI_VM_SIZE,
            DEFAULT_BMI_VM_SIZE,
        )
        bmi_host_sku = self._resolve_runbook_value(
            runbook.bmi_host_sku,
            RUNBOOK_VAR_BMI_HOST_SKU,
            DEFAULT_BMI_HOST_SKU,
        )
        bmi_admin_username = self._resolve_runbook_value(
            runbook.bmi_admin_username,
            RUNBOOK_VAR_BMI_ADMIN_USERNAME,
            "azhpcuser",
        )
        bmi_admin_password = self._resolve_runbook_value(
            runbook.bmi_admin_password,
            RUNBOOK_VAR_BMI_ADMIN_PASSWORD,
            "",
        )
        # Reuse the Azure platform's source_address_prefixes resolution
        # (which falls back to the caller's public IP via get_public_ip()).
        source_address_prefixes = platform._get_ip_addresses()

        if runbook.deployment_subscription_id:
            platform.subscription_id = runbook.deployment_subscription_id

        rg_name = runbook.resource_group_name or f"lisa-bmi-{get_datetime_path()}"
        vnet_name = runbook.vnet_name or f"{rg_name}-vnet"
        host_group_name = runbook.host_group_name or f"{rg_name}-hostgroup"
        nsg_name = runbook.nsg_name or f"{rg_name}-nsg"
        jumphost_name = runbook.jumphost_name or f"{rg_name}-jumphost"

        check_or_create_resource_group(
            credential=platform.credential,
            subscription_id=platform.subscription_id,
            cloud=platform.cloud,
            resource_group_name=rg_name,
            location=location,
            log=self._log,
        )

        network_client = get_network_client(platform)
        compute_client = get_compute_client(platform)

        vnet = create_or_update_virtual_network(
            network_client=network_client,
            resource_group_name=rg_name,
            virtual_network_name=vnet_name,
            location=location,
            address_prefixes=[runbook.vnet_prefix],
            subnets=[
                {
                    "name": runbook.external_subnet_name,
                    "address_prefix": runbook.external_subnet_prefix,
                },
                {
                    "name": runbook.internal_subnet_name,
                    "address_prefix": runbook.internal_subnet_prefix,
                },
            ],
            log=self._log,
        )
        internal_subnet_id, external_subnet_id = self._get_subnet_ids(
            virtual_network=vnet,
            internal_subnet_name=runbook.internal_subnet_name,
            external_subnet_name=runbook.external_subnet_name,
        )

        nsg = self._create_nsg(
            network_client=network_client,
            resource_group_name=rg_name,
            location=location,
            nsg_name=nsg_name,
            nat_start_port=runbook.nat_start_port,
            nat_end_port=runbook.nat_start_port + runbook.bmi_count,
            source_address_prefixes=source_address_prefixes,
        )

        jumphost_public_ip_id = create_or_update_public_ip(
            network_client=network_client,
            resource_group_name=rg_name,
            public_ip_address_name=f"{jumphost_name}-pip",
            location=location,
            log=self._log,
        )

        jumphost_external_nic_id = self._create_nic(
            network_client=network_client,
            resource_group_name=rg_name,
            location=location,
            nic_name=f"{jumphost_name}-external-nic",
            subnet_id=external_subnet_id,
            nsg_id=nsg.id,
            enable_ip_forwarding=False,
            public_ip_id=jumphost_public_ip_id,
        )
        jumphost_internal_nic_id = self._create_nic(
            network_client=network_client,
            resource_group_name=rg_name,
            location=location,
            nic_name=f"{jumphost_name}-internal-nic",
            subnet_id=internal_subnet_id,
            nsg_id=nsg.id,
            enable_ip_forwarding=True,
            public_ip_id="",
        )

        self._create_jumphost_vm(
            compute_client=compute_client,
            resource_group_name=rg_name,
            location=location,
            vm_name=jumphost_name,
            vm_size=jumphost_vm_size,
            image=jumphost_image,
            username=jumphost_username,
            password=runbook.jumphost_password,
            external_nic_id=jumphost_external_nic_id,
            internal_nic_id=jumphost_internal_nic_id,
        )

        jumphost_public_ip, jumphost_external_private_ip = self._get_vm_primary_ips(
            platform=platform,
            compute_client=compute_client,
            resource_group_name=rg_name,
            vm_name=jumphost_name,
        )
        jumphost_internal_private_ip = self._get_nic_private_ip(
            network_client=network_client,
            resource_group_name=rg_name,
            nic_name=f"{jumphost_name}-internal-nic",
        )

        self._create_route_table(
            network_client=network_client,
            resource_group_name=rg_name,
            location=location,
            route_table_name=f"{rg_name}-nat-route",
            subnet_name=runbook.internal_subnet_name,
            vnet_name=vnet_name,
            next_hop_ip=jumphost_internal_private_ip,
        )

        create_or_update_dedicated_host_group(
            compute_client=compute_client,
            resource_group_name=rg_name,
            host_group_name=host_group_name,
            location=location,
            platform_fault_domain_count=1,
            automatic_placement=True,
            log=self._log,
        )

        jumphost = self._connect_jumphost(
            address=jumphost_public_ip,
            username=jumphost_username,
            password=runbook.jumphost_password,
        )

        try:
            self._configure_jumphost_nat(
                jumphost=jumphost,
                external_private_ip=jumphost_external_private_ip,
            )

            bmi_names: List[str] = []
            bmi_private_ips: List[str] = []
            bmi_ssh_ports: List[str] = []

            next_port = runbook.nat_start_port
            for index in range(1, runbook.bmi_count + 1):
                bmi_name = f"{rg_name}-bmi-{index}"
                host_name = f"{bmi_name}-host"
                nic_name = f"{bmi_name}-nic"

                host_id = create_or_update_dedicated_host(
                    compute_client=compute_client,
                    resource_group_name=rg_name,
                    host_group_name=host_group_name,
                    host_name=host_name,
                    location=location,
                    host_sku=bmi_host_sku,
                    platform_fault_domain=0,
                    auto_replace_on_failure=False,
                    log=self._log,
                )

                nic_id = self._create_nic(
                    network_client=network_client,
                    resource_group_name=rg_name,
                    location=location,
                    nic_name=nic_name,
                    subnet_id=internal_subnet_id,
                    nsg_id=nsg.id,
                    enable_ip_forwarding=False,
                    public_ip_id="",
                )

                self._create_bmi_vm(
                    platform=platform,
                    resource_group_name=rg_name,
                    location=location,
                    vm_name=bmi_name,
                    vm_size=bmi_vm_size,
                    image=runbook.bmi_image,
                    nic_id=nic_id,
                    host_id=host_id,
                    specialized=runbook.bmi_specialized_image,
                    admin_username=bmi_admin_username,
                    admin_password=bmi_admin_password,
                )

                # BMI VMs don't have a public IP; read private IP from the NIC.
                private_ip = self._get_nic_private_ip(
                    network_client=network_client,
                    resource_group_name=rg_name,
                    nic_name=nic_name,
                )

                next_port += 1
                self._add_nat_prerouting_rule(
                    jumphost=jumphost,
                    source_port=next_port,
                    destination_ip=private_ip,
                )

                bmi_names.append(bmi_name)
                bmi_private_ips.append(private_ip)
                bmi_ssh_ports.append(str(next_port))
        finally:
            jumphost.close()

        return {
            "resource_group_name": rg_name,
            "jumphost_public_ip": jumphost_public_ip,
            "jumphost_username": jumphost_username,
            "jumphost_password": runbook.jumphost_password,
            "jumphost_name": jumphost_name,
            "bmi_names": ",".join(bmi_names),
            "bmi_private_ips": ",".join(bmi_private_ips),
            "bmi_ssh_ports": ",".join(bmi_ssh_ports),
            "host_group_name": host_group_name,
            "vnet_name": vnet_name,
        }

    def _get_subnet_ids(
        self,
        virtual_network: Any,
        internal_subnet_name: str,
        external_subnet_name: str,
    ) -> Tuple[str, str]:
        subnets_by_name = {subnet.name: subnet.id for subnet in virtual_network.subnets}
        internal_subnet_id = subnets_by_name.get(internal_subnet_name)
        external_subnet_id = subnets_by_name.get(external_subnet_name)
        if not internal_subnet_id or not external_subnet_id:
            raise LisaException("failed to resolve internal/external subnet ids")
        return internal_subnet_id, external_subnet_id

    def _create_nsg(
        self,
        network_client: Any,
        resource_group_name: str,
        location: str,
        nsg_name: str,
        nat_start_port: int,
        nat_end_port: int,
        source_address_prefixes: List[str],
    ) -> Any:
        # NSG rules accept either a single 'source_address_prefix' or a list
        # via 'source_address_prefixes' (mutually exclusive).
        if len(source_address_prefixes) == 1:
            source_keys: Dict[str, Any] = {
                "source_address_prefix": source_address_prefixes[0],
            }
        else:
            source_keys = {
                "source_address_prefixes": source_address_prefixes,
            }
        nsg = create_or_update_network_security_group(
            network_client=network_client,
            resource_group_name=resource_group_name,
            network_security_group_name=nsg_name,
            location=location,
            log=self._log,
        )

        create_or_update_network_security_rule(
            network_client=network_client,
            resource_group_name=resource_group_name,
            network_security_group_name=nsg_name,
            security_rule_name="AllowNatSshPorts",
            security_rule_parameters={
                "protocol": "Tcp",
                "source_port_range": "*",
                "destination_port_range": f"{nat_start_port}-{nat_end_port}",
                "destination_address_prefix": "*",
                "access": "Allow",
                "priority": 100,
                "direction": "Inbound",
                **source_keys,
            },
            failure_identity="create NSG NAT rule",
            log=self._log,
        )

        create_or_update_network_security_rule(
            network_client=network_client,
            resource_group_name=resource_group_name,
            network_security_group_name=nsg_name,
            security_rule_name="AllowJumpHostSsh",
            security_rule_parameters={
                "protocol": "Tcp",
                "source_port_range": "*",
                "destination_port_range": "22",
                "destination_address_prefix": "*",
                "access": "Allow",
                "priority": 101,
                "direction": "Inbound",
                **source_keys,
            },
            failure_identity="create NSG SSH rule",
            log=self._log,
        )

        return nsg

    def _get_vm_primary_ips(
        self,
        platform: Any,
        compute_client: Any,
        resource_group_name: str,
        vm_name: str,
    ) -> Tuple[str, str]:
        public_ip_address: str = ""
        private_ip_address: str = ""

        def _check_vm_ip_ready() -> bool:
            nonlocal public_ip_address
            nonlocal private_ip_address
            vm = compute_client.virtual_machines.get(
                resource_group_name=resource_group_name,
                vm_name=vm_name,
            )
            public_ip, private_ip = get_primary_ip_addresses(
                platform=platform,
                resource_group_name=resource_group_name,
                vm=vm,
            )
            public_ip_address = str(public_ip or "")
            private_ip_address = str(private_ip or "")
            return bool(private_ip_address)

        check_till_timeout(
            _check_vm_ip_ready,
            timeout_message=f"wait for VM IPs ready: {vm_name}",
            timeout=300,
            interval=5,
        )

        return public_ip_address, private_ip_address

    def _create_nic(
        self,
        network_client: Any,
        resource_group_name: str,
        location: str,
        nic_name: str,
        subnet_id: str,
        nsg_id: str,
        enable_ip_forwarding: bool,
        public_ip_id: str,
    ) -> str:
        ip_configuration: Dict[str, Any] = {
            "name": f"{nic_name}-ipconfig",
            "subnet": {"id": subnet_id},
        }
        if public_ip_id:
            ip_configuration["public_ip_address"] = {"id": public_ip_id}

        return create_or_update_network_interface(
            network_client=network_client,
            resource_group_name=resource_group_name,
            network_interface_name=nic_name,
            location=location,
            enable_accelerated_networking=True,
            enable_ip_forwarding=enable_ip_forwarding,
            network_security_group_id=nsg_id,
            ip_configurations=[ip_configuration],
            log=self._log,
        )

    def _get_nic_private_ip(
        self,
        network_client: Any,
        resource_group_name: str,
        nic_name: str,
    ) -> str:
        nic = network_client.network_interfaces.get(
            resource_group_name=resource_group_name,
            network_interface_name=nic_name,
        )
        if not nic.ip_configurations or not nic.ip_configurations[0].private_ip_address:
            raise LisaException(f"private ip not found on nic: {nic_name}")
        return str(nic.ip_configurations[0].private_ip_address)

    def _create_jumphost_vm(
        self,
        compute_client: Any,
        resource_group_name: str,
        location: str,
        vm_name: str,
        vm_size: str,
        image: str,
        username: str,
        password: str,
        external_nic_id: str,
        internal_nic_id: str,
    ) -> None:
        image_reference = self._build_image_reference(image)

        create_or_update_virtual_machine(
            compute_client=compute_client,
            resource_group_name=resource_group_name,
            vm_name=vm_name,
            parameters={
                "location": location,
                "hardware_profile": {"vm_size": vm_size},
                "storage_profile": {"image_reference": image_reference},
                "os_profile": {
                    "computer_name": vm_name,
                    "admin_username": username,
                    "admin_password": password,
                    "linux_configuration": {
                        "disable_password_authentication": False,
                    },
                },
                "network_profile": {
                    "network_interfaces": [
                        {"id": external_nic_id, "primary": True},
                        {"id": internal_nic_id, "primary": False},
                    ]
                },
            },
            failure_identity=f"create jumphost vm {vm_name}",
            log=self._log,
        )

    def _create_route_table(
        self,
        network_client: Any,
        resource_group_name: str,
        location: str,
        route_table_name: str,
        subnet_name: str,
        vnet_name: str,
        next_hop_ip: str,
    ) -> None:
        route_table = create_or_update_route_table(
            network_client=network_client,
            resource_group_name=resource_group_name,
            route_table_name=route_table_name,
            location=location,
            log=self._log,
        )

        create_or_update_route(
            network_client=network_client,
            resource_group_name=resource_group_name,
            route_table_name=route_table_name,
            route_name="NatRoute",
            route_parameters={
                "address_prefix": "0.0.0.0/0",
                "next_hop_type": "VirtualAppliance",
                "next_hop_ip_address": next_hop_ip,
            },
            log=self._log,
        )

        associate_route_table_to_subnet(
            network_client=network_client,
            resource_group_name=resource_group_name,
            virtual_network_name=vnet_name,
            subnet_name=subnet_name,
            route_table_id=route_table.id,
            log=self._log,
        )

    def _create_bmi_vm(
        self,
        platform: Any,
        resource_group_name: str,
        location: str,
        vm_name: str,
        vm_size: str,
        image: str,
        nic_id: str,
        host_id: str,
        specialized: bool,
        admin_username: str,
        admin_password: str,
    ) -> None:
        # BMI VMs (GB200, NvmeDisk ephemeral placement) require
        # Microsoft.Compute api-version 2024-03-01 or newer. The bundled
        # azure-mgmt-compute (30.x) only ships up to 2023-07-01, so issue
        # the PUT directly against ARM with a pinned api-version.
        image_reference = self._build_sig_image_reference(image)

        # camelCase keys per ARM contract (SDK normally maps these).
        vm_body: Dict[str, Any] = {
            "location": location,
            "properties": {
                "hardwareProfile": {"vmSize": vm_size},
                "networkProfile": {
                    "networkInterfaces": [
                        {"id": nic_id, "properties": {"primary": True}}
                    ],
                },
                "storageProfile": {
                    "imageReference": self._image_reference_to_arm(image_reference),
                    "osDisk": {
                        "createOption": "FromImage",
                        "deleteOption": "Delete",
                        "caching": "ReadOnly",
                        "diffDiskSettings": {
                            "option": "Local",
                            "placement": "NvmeDisk",
                        },
                    },
                },
                "host": {"id": host_id},
            },
        }

        if not specialized:
            os_profile: Dict[str, Any] = {
                "computerName": vm_name,
                "adminUsername": admin_username,
                "linuxConfiguration": {
                    "disablePasswordAuthentication": not bool(admin_password),
                },
            }
            if admin_password:
                os_profile["adminPassword"] = admin_password
            vm_body["properties"]["osProfile"] = os_profile

        self._put_vm_via_rest(
            platform=platform,
            resource_group_name=resource_group_name,
            vm_name=vm_name,
            vm_body=vm_body,
        )

    def _image_reference_to_arm(
        self, image_reference: Dict[str, str]
    ) -> Dict[str, str]:
        # Translate snake_case keys produced by _build_*_image_reference
        # to the camelCase ARM contract.
        key_map = {
            "exact_version": "exactVersion",
            "shared_gallery_image_id": "sharedGalleryImageId",
            "community_gallery_image_id": "communityGalleryImageId",
        }
        return {key_map.get(k, k): v for k, v in image_reference.items()}

    def _put_vm_via_rest(
        self,
        platform: Any,
        resource_group_name: str,
        vm_name: str,
        vm_body: Dict[str, Any],
    ) -> None:
        import json
        import time

        import requests

        api_version = "2024-11-01"
        resource_manager = platform.cloud.endpoints.resource_manager.rstrip("/")
        scope = f"{resource_manager}/.default"
        token = platform.credential.get_token(scope).token
        url = (
            f"{resource_manager}/subscriptions/{platform.subscription_id}"
            f"/resourceGroups/{resource_group_name}/providers/Microsoft.Compute"
            f"/virtualMachines/{vm_name}?api-version={api_version}"
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        vm_size = vm_body["properties"]["hardwareProfile"]["vmSize"]
        image_reference = vm_body["properties"]["storageProfile"]["imageReference"]
        self._log.debug(
            f"creating bmi vm '{vm_name}' in resource group "
            f"'{resource_group_name}' (vm_size={vm_size}, "
            f"image_reference={image_reference}, "
            f"api_version={api_version})"
        )

        response = requests.put(
            url, headers=headers, data=json.dumps(vm_body), timeout=300
        )
        if response.status_code not in (200, 201, 202):
            raise LisaException(
                f"failed to create bmi vm '{vm_name}': "
                f"status={response.status_code} body={response.text}"
            )

        async_url = (
            response.headers.get("Azure-AsyncOperation")
            or response.headers.get("Location")
        )
        if not async_url:
            self._log.debug(
                f"created bmi vm '{vm_name}' (no async operation header)"
            )
            return

        # Poll the LRO until completion.
        deadline = time.time() + 60 * 60  # 60 minutes
        while time.time() < deadline:
            poll = requests.get(async_url, headers=headers, timeout=300)
            if poll.status_code in (200, 201):
                try:
                    payload = poll.json()
                except ValueError:
                    payload = {}
                status = str(payload.get("status") or "").lower()
                if status in ("succeeded",):
                    self._log.debug(f"created bmi vm '{vm_name}'")
                    return
                if status in ("failed", "canceled"):
                    raise LisaException(
                        f"failed to create bmi vm '{vm_name}': {poll.text}"
                    )
            elif poll.status_code == 202:
                pass
            else:
                raise LisaException(
                    f"failed polling bmi vm '{vm_name}': "
                    f"status={poll.status_code} body={poll.text}"
                )
            retry_after = int(poll.headers.get("Retry-After", "10"))
            time.sleep(max(retry_after, 5))

        raise LisaException(
            f"timed out waiting for bmi vm '{vm_name}' to be created"
        )

    def _build_image_reference(self, image: str) -> Dict[str, str]:
        if image.startswith("/subscriptions/"):
            return {"id": image}

        if ":" in image:
            parts = image.split(":")
        else:
            parts = image.split()

        if len(parts) != 4:
            raise LisaException(
                "image must be a resource id, colon-delimited marketplace image, "
                "or '<publisher> <offer> <sku> <version>'"
            )

        return {
            "publisher": parts[0],
            "offer": parts[1],
            "sku": parts[2],
            "version": parts[3],
        }

    def _build_sig_image_reference(self, image: str) -> Dict[str, str]:
        # For Shared Image Gallery (SIG) image versions, the Azure VM
        # 'image_reference' must point at the gallery image (definition) id
        # and pin the version via 'exact_version'. Example image input:
        # /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Compute/
        #   galleries/<gallery>/images/<image>/versions/<version>
        if image.startswith("/subscriptions/") and "/galleries/" in image:
            marker = "/versions/"
            version_index = image.find(marker)
            if version_index == -1:
                raise LisaException(
                    f"SIG image id is missing '/versions/<version>' segment: {image}"
                )
            image_definition_id = image[:version_index]
            exact_version = image[version_index + len(marker):].strip("/")
            if not exact_version:
                raise LisaException(
                    f"SIG image id has empty version segment: {image}"
                )
            return {
                "id": image_definition_id,
                "exact_version": exact_version,
            }

        return self._build_image_reference(image)

    def _connect_jumphost(self, address: str, username: str, password: str) -> Node:
        connection = schema.RemoteNode(
            name="bmi-jumphost",
            address=address,
            port=22,
            username=username,
            password=password,
        )
        node: Optional[Node] = None

        def _connect() -> bool:
            nonlocal node
            try:
                deployment_transformer = DeploymentTransformer(
                    runbook=DeploymentTransformerSchema(
                        type=DeploymentTransformer.type_name(),
                        connection=connection,
                        name="bmi-jumphost-connector",
                    ),
                    runbook_builder=self._runbook_builder,
                )
                node = deployment_transformer._node
                return True
            except Exception as identifier:
                self._log.debug(
                    f"jumphost is not reachable yet at {address}: {identifier}"
                )
                return False

        check_till_timeout(
            _connect,
            timeout_message="wait for jump host ssh ready",
            timeout=900,
            interval=10,
        )
        if not node:
            raise LisaException("failed to connect to jump host")
        return node

    def _resolve_runbook_value(
        self,
        runbook_value: str,
        variable_name: str,
        default_value: str,
    ) -> str:
        if runbook_value:
            return runbook_value

        variable = self._runbook_builder.variables.get(variable_name)
        if variable and variable.data:
            return str(variable.data)

        return default_value

    def _configure_jumphost_nat(self, jumphost: Node, external_private_ip: str) -> None:
        jumphost.execute(
            "sudo sysctl -w net.ipv4.ip_forward=1",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="failed to enable IP forwarding",
        )

        get_external_interface = (
            "set -e; "
            f"iface=$(ip -o addr show | awk '/{external_private_ip}/ "
            "{print $2; exit}'); "
            "test -n \"$iface\"; "
            "echo $iface"
        )
        interface_result = jumphost.execute(
            get_external_interface,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "failed to resolve jump host external interface"
            ),
        )
        external_interface = interface_result.stdout.strip()

        jumphost.execute(
            "sudo iptables -t nat -C POSTROUTING "
            f"-o {external_interface} -j MASQUERADE || "
            "sudo iptables -t nat -A POSTROUTING "
            f"-o {external_interface} -j MASQUERADE",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="failed to configure jump host NAT",
        )

    def _add_nat_prerouting_rule(
        self,
        jumphost: Node,
        source_port: int,
        destination_ip: str,
    ) -> None:
        jumphost.execute(
            "sudo iptables -t nat -C PREROUTING "
            f"-p tcp --dport {source_port} -j DNAT --to-destination {destination_ip}:22 "
            "|| sudo iptables -t nat -A PREROUTING "
            f"-p tcp --dport {source_port} -j DNAT --to-destination {destination_ip}:22",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"failed to configure DNAT rule for port {source_port}"
            ),
        )
