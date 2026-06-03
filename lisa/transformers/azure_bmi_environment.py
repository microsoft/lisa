# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Type

from dataclasses_json import dataclass_json
from marshmallow import validate

from lisa import schema
from lisa.node import Node
from lisa.sut_orchestrator.azure.common import (
    check_or_create_resource_group,
    get_compute_client,
    get_network_client,
    get_primary_ip_addresses,
    wait_operation,
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

        vnet = self._create_network(
            network_client=network_client,
            resource_group_name=rg_name,
            location=location,
            vnet_name=vnet_name,
            vnet_prefix=runbook.vnet_prefix,
            internal_subnet_name=runbook.internal_subnet_name,
            internal_subnet_prefix=runbook.internal_subnet_prefix,
            external_subnet_name=runbook.external_subnet_name,
            external_subnet_prefix=runbook.external_subnet_prefix,
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
        )

        jumphost_public_ip_id = self._create_public_ip(
            network_client=network_client,
            resource_group_name=rg_name,
            location=location,
            public_ip_name=f"{jumphost_name}-pip",
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

        self._create_host_group(
            compute_client=compute_client,
            resource_group_name=rg_name,
            location=location,
            host_group_name=host_group_name,
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

                host_id = self._create_host(
                    compute_client=compute_client,
                    resource_group_name=rg_name,
                    location=location,
                    host_group_name=host_group_name,
                    host_name=host_name,
                    host_sku=bmi_host_sku,
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
                    compute_client=compute_client,
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

                _, private_ip = self._get_vm_primary_ips(
                    platform=platform,
                    compute_client=compute_client,
                    resource_group_name=rg_name,
                    vm_name=bmi_name,
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

    def _create_network(
        self,
        network_client: Any,
        resource_group_name: str,
        location: str,
        vnet_name: str,
        vnet_prefix: str,
        internal_subnet_name: str,
        internal_subnet_prefix: str,
        external_subnet_name: str,
        external_subnet_prefix: str,
    ) -> Any:
        operation = network_client.virtual_networks.begin_create_or_update(
            resource_group_name=resource_group_name,
            virtual_network_name=vnet_name,
            parameters={
                "location": location,
                "address_space": {"address_prefixes": [vnet_prefix]},
                "subnets": [
                    {
                        "name": external_subnet_name,
                        "address_prefix": external_subnet_prefix,
                    },
                    {
                        "name": internal_subnet_name,
                        "address_prefix": internal_subnet_prefix,
                    },
                ],
            },
        )
        wait_operation(operation, failure_identity="create virtual network")
        return operation.result()

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
    ) -> Any:
        operation = network_client.network_security_groups.begin_create_or_update(
            resource_group_name=resource_group_name,
            network_security_group_name=nsg_name,
            parameters={"location": location},
        )
        wait_operation(operation, failure_identity="create network security group")
        nsg = operation.result()

        allow_nat = network_client.security_rules.begin_create_or_update(
            resource_group_name=resource_group_name,
            network_security_group_name=nsg_name,
            security_rule_name="AllowNatSshPorts",
            security_rule_parameters={
                "protocol": "Tcp",
                "source_port_range": "*",
                "destination_port_range": f"{nat_start_port}-{nat_end_port}",
                "source_address_prefix": "*",
                "destination_address_prefix": "*",
                "access": "Allow",
                "priority": 100,
                "direction": "Inbound",
            },
        )
        wait_operation(allow_nat, failure_identity="create NSG NAT rule")

        allow_ssh = network_client.security_rules.begin_create_or_update(
            resource_group_name=resource_group_name,
            network_security_group_name=nsg_name,
            security_rule_name="AllowJumpHostSsh",
            security_rule_parameters={
                "protocol": "Tcp",
                "source_port_range": "*",
                "destination_port_range": "22",
                "source_address_prefix": "*",
                "destination_address_prefix": "*",
                "access": "Allow",
                "priority": 101,
                "direction": "Inbound",
            },
        )
        wait_operation(allow_ssh, failure_identity="create NSG SSH rule")

        return nsg

    def _create_public_ip(
        self,
        network_client: Any,
        resource_group_name: str,
        location: str,
        public_ip_name: str,
    ) -> str:
        operation = network_client.public_ip_addresses.begin_create_or_update(
            resource_group_name=resource_group_name,
            public_ip_address_name=public_ip_name,
            parameters={
                "location": location,
                "sku": {"name": "Standard"},
                "public_ip_allocation_method": "Static",
            },
        )
        wait_operation(operation, failure_identity="create public ip")
        public_ip = operation.result()
        if not public_ip.id:
            raise LisaException("public ip id cannot be empty")
        if not isinstance(public_ip.id, str):
            raise LisaException("public ip id is not a string")
        return public_ip.id

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
                virtual_machine=vm,
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

        operation = network_client.network_interfaces.begin_create_or_update(
            resource_group_name=resource_group_name,
            network_interface_name=nic_name,
            parameters={
                "location": location,
                "enable_accelerated_networking": True,
                "enable_ip_forwarding": enable_ip_forwarding,
                "network_security_group": {"id": nsg_id},
                "ip_configurations": [ip_configuration],
            },
        )
        wait_operation(operation, failure_identity=f"create nic {nic_name}")
        nic = operation.result()
        if not nic.id:
            raise LisaException(f"nic id cannot be empty: {nic_name}")
        if not isinstance(nic.id, str):
            raise LisaException(f"nic id is not a string: {nic_name}")
        return nic.id

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

        operation = compute_client.virtual_machines.begin_create_or_update(
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
        )
        wait_operation(operation, failure_identity=f"create jumphost vm {vm_name}")

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
        operation = network_client.route_tables.begin_create_or_update(
            resource_group_name=resource_group_name,
            route_table_name=route_table_name,
            parameters={"location": location},
        )
        wait_operation(operation, failure_identity="create route table")
        route_table = operation.result()

        route_operation = network_client.routes.begin_create_or_update(
            resource_group_name=resource_group_name,
            route_table_name=route_table_name,
            route_name="NatRoute",
            route_parameters={
                "address_prefix": "0.0.0.0/0",
                "next_hop_type": "VirtualAppliance",
                "next_hop_ip_address": next_hop_ip,
            },
        )
        wait_operation(route_operation, failure_identity="create route entry")

        subnet = network_client.subnets.get(
            resource_group_name=resource_group_name,
            virtual_network_name=vnet_name,
            subnet_name=subnet_name,
        )
        subnet.route_table = {"id": route_table.id}

        subnet_update = network_client.subnets.begin_create_or_update(
            resource_group_name=resource_group_name,
            virtual_network_name=vnet_name,
            subnet_name=subnet_name,
            subnet_parameters=subnet,
        )
        wait_operation(subnet_update, failure_identity="associate route table")

    def _create_host_group(
        self,
        compute_client: Any,
        resource_group_name: str,
        location: str,
        host_group_name: str,
    ) -> None:
        operation = compute_client.dedicated_host_groups.begin_create_or_update(
            resource_group_name=resource_group_name,
            host_group_name=host_group_name,
            parameters={
                "location": location,
                "platform_fault_domain_count": 1,
                "automatic_placement": True,
            },
        )
        wait_operation(
            operation,
            failure_identity=f"create host group {host_group_name}",
        )

    def _create_host(
        self,
        compute_client: Any,
        resource_group_name: str,
        location: str,
        host_group_name: str,
        host_name: str,
        host_sku: str,
    ) -> str:
        operation = compute_client.dedicated_hosts.begin_create_or_update(
            resource_group_name=resource_group_name,
            host_group_name=host_group_name,
            host_name=host_name,
            parameters={
                "location": location,
                "sku": {"name": host_sku},
                "platform_fault_domain": 0,
                "auto_replace_on_failure": False,
            },
        )
        wait_operation(operation, failure_identity=f"create host {host_name}")
        host = operation.result()
        if not host.id:
            raise LisaException(f"host id cannot be empty: {host_name}")
        if not isinstance(host.id, str):
            raise LisaException(f"host id is not a string: {host_name}")
        return host.id

    def _create_bmi_vm(
        self,
        compute_client: Any,
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
        image_reference = self._build_image_reference(image)

        vm_parameters: Dict[str, Any] = {
            "location": location,
            "hardware_profile": {"vm_size": vm_size},
            "network_profile": {
                "network_interfaces": [{"id": nic_id, "primary": True}],
            },
            "storage_profile": {
                "image_reference": image_reference,
                "os_disk": {
                    "create_option": "FromImage",
                    "delete_option": "Delete",
                    "diff_disk_settings": {
                        "option": "Local",
                        "placement": "NvmeDisk",
                    },
                },
            },
            "host": {"id": host_id},
        }

        if not specialized:
            vm_parameters["os_profile"] = {
                "computer_name": vm_name,
                "admin_username": admin_username,
                "linux_configuration": {
                    "disable_password_authentication": not bool(admin_password),
                },
            }
            if admin_password:
                vm_parameters["os_profile"]["admin_password"] = admin_password

        operation = compute_client.virtual_machines.begin_create_or_update(
            resource_group_name=resource_group_name,
            vm_name=vm_name,
            parameters=vm_parameters,
        )
        wait_operation(operation, failure_identity=f"create bmi vm {vm_name}")

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
