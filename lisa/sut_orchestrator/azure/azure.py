import json
import logging
import os
import re
from collections import UserDict
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type, cast

from azure.identity import DefaultAzureCredential  # type: ignore
from azure.mgmt.compute import ComputeManagementClient  # type: ignore
from azure.mgmt.compute.models import ResourceSku, VirtualMachine  # type: ignore
from azure.mgmt.network import NetworkManagementClient  # type: ignore
from azure.mgmt.network.models import InboundNatRule, NetworkInterface  # type: ignore
from azure.mgmt.resource import (  # type: ignore
    ResourceManagementClient,
    SubscriptionClient,
)
from azure.mgmt.resource.resources.models import (  # type: ignore
    Deployment,
    DeploymentMode,
    DeploymentProperties,
)
from dataclasses_json import LetterCase, dataclass_json  # type: ignore
from marshmallow import fields, validate

from lisa import schema
from lisa.environment import Environment
from lisa.node import Node
from lisa.platform_ import Platform
from lisa.secret import PATTERN_GUID, PATTERN_HEADTAIL, add_secret
from lisa.util import LisaException, constants, get_public_key_data

AZURE = "azure"

# used by azure
AZURE_DEPLOYMENT_NAME = "lisa_default_deployment_script"
AZURE_RG_NAME_KEY = "resource_group_name"

VM_SIZE_FALLBACK_PATTERNS = [
    re.compile(r"Standard_DS(\d)+_v2"),
    re.compile(r"Standard_A(\d)+"),
]

# names in arm template, they should be changed with template together.
RESOURCE_ID_LB = "lisa-loadBalancer"
RESOURCE_ID_PUBLIC_IP = "lisa-publicIPv4Address"
RESOURCE_ID_PORT_POSTFIX = "-ssh"
RESOURCE_ID_NIC_POSTFIX = "-nic"


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class AzureLocation:
    updated_time: datetime = field(
        default_factory=datetime.now,
        metadata=schema.metadata(
            fields.DateTime,
            encoder=datetime.isoformat,
            decoder=datetime.fromisoformat,
            data_key="updatedTime",
            format="iso",
        ),
    )
    location: str = ""
    skus_list: List[ResourceSku] = field(
        default_factory=list, metadata=schema.metadata(data_key="skus")
    )

    def serialize(self) -> None:
        if len(self.skus_list) > 0 and isinstance(self.skus_list[0], ResourceSku):
            skus_list: List[Any] = list()
            for sku_obj in self.skus_list:
                skus_list.append(sku_obj.as_dict())
            self.skus_list = skus_list

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        skus: Dict[str, ResourceSku] = dict()
        for sku in self.skus_list:
            sku_obj = ResourceSku.from_dict(sku)
            skus[sku_obj.name] = sku_obj
        self.skus = skus


if TYPE_CHECKING:
    LocationsDict = UserDict[str, Optional[AzureLocation]]
else:
    LocationsDict = UserDict


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class AzureLocations(LocationsDict):
    locations: List[AzureLocation] = field(default_factory=list)

    def __getitem__(self, location: str) -> Optional[AzureLocation]:
        for existing_location in self.locations:
            if location == existing_location.location:
                return existing_location
        return None

    def __setitem__(self, _: str, location: Optional[AzureLocation]) -> None:
        assert location
        for existing_location in self.locations:
            if location.location == existing_location.location:
                self.locations.remove(existing_location)
        self.locations.append(location)

    def serialize(self) -> None:
        for location in self.locations:
            location.serialize()


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class AzureArmParameterGallery:
    publisher: str = "Canonical"
    offer: str = "UbuntuServer"
    sku: str = "18.04-LTS"
    version: str = "Latest"


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class AzureArmParameterNode:
    name: str = ""
    vm_size: str = "Standard_A1_v2"
    gallery: Optional[AzureArmParameterGallery] = None
    vhd: Optional[str] = None

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        if self.gallery is None and self.vhd is None:
            raise LisaException("either gallery or vhd must be set one")
        elif self.gallery and self.vhd:
            raise LisaException("only one of gallery or vhd should be set")


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class AzureArmParameter:
    location: str = "westus2"
    admin_username: str = ""
    admin_password: str = ""
    admin_key_data: str = ""
    nodes: List[AzureArmParameterNode] = field(default_factory=list)

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        add_secret(self.admin_username, PATTERN_HEADTAIL)
        add_secret(self.admin_password)
        add_secret(self.admin_key_data)


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class AzurePlatformSchema:
    service_principal_tenant_id: str = field(
        default="",
        metadata=schema.metadata(
            data_key="servicePrincipalTenantId",
            validate=validate.Regexp(constants.GUID_REGEXP),
        ),
    )
    service_principal_client_id: str = field(
        default="",
        metadata=schema.metadata(
            data_key="servicePrincipalClientId",
            validate=validate.Regexp(constants.GUID_REGEXP),
        ),
    )
    service_principal_key: str = field(default="")
    subscription_id: str = field(
        default="",
        metadata=schema.metadata(
            data_key="subscriptionId", validate=validate.Regexp(constants.GUID_REGEXP),
        ),
    )

    resource_group_name: str = field(default="")
    location: str = field(default="westus2")

    log_level: str = field(
        default=logging.getLevelName(logging.WARN),
        metadata=schema.metadata(
            data_key="logLevel",
            validate=validate.OneOf(
                [
                    logging.getLevelName(logging.ERROR),
                    logging.getLevelName(logging.WARN),
                    logging.getLevelName(logging.INFO),
                    logging.getLevelName(logging.DEBUG),
                ]
            ),
        ),
    )

    # do actual deployment, or pass through for troubleshooting
    dry_run: bool = False
    # wait resource deleted or not
    wait_delete: bool = False

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        add_secret(self.service_principal_tenant_id, mask=PATTERN_GUID)
        add_secret(self.service_principal_client_id, mask=PATTERN_GUID)
        add_secret(self.service_principal_key)
        add_secret(self.subscription_id, mask=PATTERN_GUID)


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class AzureNodeSchema:
    vm_size: str = field(default="")
    vhd: str = ""

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        add_secret(self.vhd)


@dataclass
class EnvironmentContext:
    resource_group_name: str = ""
    resource_group_is_created: bool = False


@dataclass
class NodeContext:
    vm_name: str = ""
    username: str = ""
    password: str = ""
    private_key_file: str = ""


class AzurePlatform(Platform):
    def __init__(self) -> None:
        super().__init__()
        self._credential: DefaultAzureCredential = None
        self._enviornment_counter = 0

    @classmethod
    def platform_type(cls) -> str:
        return AZURE

    @property
    def platform_schema(self) -> Optional[Type[Any]]:
        return AzurePlatformSchema

    @property
    def node_schema(self) -> Optional[Type[Any]]:
        return AzureNodeSchema

    def _request_environment(self, environment: Environment) -> Environment:
        assert self._rm_client
        assert self._azure_runbook

        environment_context = environment.get_context(EnvironmentContext)
        if self._azure_runbook.resource_group_name:
            resource_group_name = self._azure_runbook.resource_group_name
        else:
            normalized_run_name = constants.NORMALIZE_PATTERN.sub(
                "_", constants.RUN_NAME
            )
            resource_group_name = f"{normalized_run_name}_e{self._enviornment_counter}"
            self._enviornment_counter += 1
            environment_context.resource_group_is_created = True

        self._get_location_info(self._azure_runbook.location)

        environment_context.resource_group_name = resource_group_name
        if self._azure_runbook.dry_run:
            self._log.info(f"dry_run: {self._azure_runbook.dry_run}")
        else:
            self._log.info(
                f"creating or updating resource group: {resource_group_name}"
            )
            self._rm_client.resource_groups.create_or_update(
                resource_group_name, {"location": self._azure_runbook.location}
            )

            try:
                deployment_parameters = self._create_deployment_parameters(
                    resource_group_name, environment
                )

                self._validate_template(deployment_parameters)

                self._deploy(deployment_parameters)

                self._initialize_nodes(environment)

            except Exception as identifier:
                self._delete_environment(environment)
                raise identifier

        return environment

    def _delete_environment(self, environment: Environment) -> None:
        environment_context = environment.get_context(EnvironmentContext)
        resource_group_name = environment_context.resource_group_name
        assert resource_group_name
        assert self._azure_runbook

        if (
            environment_context.resource_group_is_created
            and not self._runbook.reserve_environment
            and not self._azure_runbook.dry_run
        ):
            assert self._rm_client
            self._log.info(
                f"deleting resource group: {resource_group_name}, "
                f"wait: {self._azure_runbook.wait_delete}"
            )
            delete_operation = self._rm_client.resource_groups.begin_delete(
                resource_group_name
            )
            if self._azure_runbook.wait_delete:
                result = delete_operation.wait()
                if result:
                    raise LisaException(f"error on deleting resource group: {result}")
            else:
                self._log.debug("not wait deleting")
        else:
            self._log.info(f"skipped to delete resource group: {resource_group_name}")

    def _initialize(self) -> None:
        # set needed environment variables for authentication
        self._azure_runbook = self._runbook.get_extended_runbook(AzurePlatformSchema)
        assert self._azure_runbook, "platform runbook cannot be empty"

        # set azure log to warn level only
        logging.getLogger("azure").setLevel(self._azure_runbook.log_level)

        os.environ["AZURE_TENANT_ID"] = self._azure_runbook.service_principal_tenant_id
        os.environ["AZURE_CLIENT_ID"] = self._azure_runbook.service_principal_client_id
        os.environ["AZURE_CLIENT_SECRET"] = self._azure_runbook.service_principal_key

        self._credential = DefaultAzureCredential()

        self._sub_client = SubscriptionClient(self._credential)

        self._subscription_id = self._azure_runbook.subscription_id
        subscription = self._sub_client.subscriptions.get(self._subscription_id)
        if not subscription:
            raise LisaException(
                f"cannot find subscription id: '{self._subscription_id}'"
            )
        self._log.info(f"connected to subscription: '{subscription.display_name}'")

        self._rm_client = ResourceManagementClient(
            credential=self._credential, subscription_id=self._subscription_id
        )

    @lru_cache
    def _load_template(self) -> Any:
        template_file_path = Path(__file__).parent / "arm_template.json"
        with open(template_file_path, "r") as f:
            template = json.load(f)
        return template

    @lru_cache
    def _get_location_info(self, location: str) -> AzureLocation:
        cached_file_name = constants.CACHE_PATH.joinpath("azure_locations.json")
        should_refresh: bool = True
        location_data: Optional[AzureLocation] = None
        if cached_file_name.exists():
            with open(cached_file_name, "r") as f:
                data = json.load(f)
            locations_data = cast(
                AzureLocations, AzureLocations.schema().load(data)  # type:ignore
            )
            location_data = locations_data.get(location)
        else:
            locations_data = AzureLocations()

        if location_data:
            delta = datetime.now() - location_data.updated_time
            # refresh cached locations every 5 days.
            if delta.days < 5:
                should_refresh = False
                self._log.debug(
                    f"{location}: cache used: {location_data.updated_time}, "
                    f"sku count: {len(location_data.skus)}"
                )
            else:
                self._log.debug(
                    f"{location}: cache timeout: {location_data.updated_time},"
                    f"sku count: {len(location_data.skus)}"
                )
        else:
            self._log.debug(f"{location}: no cache found")
        if should_refresh:
            compute_client = ComputeManagementClient(
                credential=self._credential, subscription_id=self._subscription_id
            )

            all_skus: List[ResourceSku] = []
            paged_skus = compute_client.resource_skus.list(
                f"location eq '{location}'"
            ).by_page()
            for skus in paged_skus:
                for sku in skus:
                    try:
                        if sku.resource_type == "virtualMachines":
                            if sku.restrictions and any(
                                restriction.type == "Location"
                                for restriction in sku.restrictions
                            ):
                                # restricted on this location
                                continue
                            all_skus.append(sku)
                    except Exception as identifier:
                        self._log.error(f"unknown sku: {sku}")
                        raise identifier
            location_data = AzureLocation(location=location, skus_list=all_skus)
            locations_data[location_data.location] = location_data
            with open(cached_file_name, "w") as f:
                locations_data.serialize()
                json.dump(locations_data.to_dict(), f)  # type: ignore
            self._log.debug(
                f"{location_data.location}: new data, "
                f"sku: {len(location_data.skus_list)}"
            )

        assert location_data
        return location_data

    def _create_deployment_parameters(
        self, resource_group_name: str, environment: Environment
    ) -> Dict[str, Any]:
        assert environment.runbook, "env data cannot be None"
        env_runbook: schema.Environment = environment.runbook

        self._log.debug("creating deployment")
        # construct parameters
        arm_parameters = AzureArmParameter()
        arm_parameters.admin_username = self._runbook.admin_username
        if self._runbook.admin_private_key_file:
            arm_parameters.admin_key_data = get_public_key_data(
                self._runbook.admin_private_key_file
            )
        else:
            arm_parameters.admin_password = self._runbook.admin_password
        assert self._azure_runbook
        arm_parameters.location = self._azure_runbook.location

        nodes_parameters: List[AzureArmParameterNode] = []
        for node_runbook in env_runbook.nodes:
            assert isinstance(node_runbook, schema.NodeSpec)
            azure_node_runbook = node_runbook.get_extended_runbook(
                AzureNodeSchema, field_name=AZURE
            )
            gallery = AzureArmParameterGallery()
            node_parameter = AzureArmParameterNode(gallery=gallery)
            node_parameter.name = f"node-{len(nodes_parameters)}"
            if azure_node_runbook:
                if azure_node_runbook.vm_size:
                    node_parameter.vm_size = azure_node_runbook.vm_size
                if azure_node_runbook.vhd:
                    node_parameter.vhd = azure_node_runbook.vhd
                    node_parameter.gallery = None
            nodes_parameters.append(node_parameter)

            # init node
            node = environment.nodes.from_spec(node_runbook)
            node_context = node.get_context(NodeContext)
            node_context.vm_name = node_parameter.name
            node_context.username = arm_parameters.admin_username
            node_context.password = arm_parameters.admin_password
            node_context.private_key_file = self._runbook.admin_private_key_file

        arm_parameters.nodes = nodes_parameters

        # load template
        template = self._load_template()
        parameters = arm_parameters.to_dict()  # type:ignore
        parameters = {k: {"value": v} for k, v in parameters.items()}
        self._log.debug(f"parameters: {parameters}")
        deployment_properties = DeploymentProperties(
            mode=DeploymentMode.incremental, template=template, parameters=parameters,
        )

        return {
            AZURE_RG_NAME_KEY: resource_group_name,
            "deployment_name": AZURE_DEPLOYMENT_NAME,
            "parameters": Deployment(properties=deployment_properties),
        }

    def _validate_template(self, deployment_parameters: Dict[str, Any]) -> None:
        resource_group_name = deployment_parameters[AZURE_RG_NAME_KEY]
        self._log.debug("validating deployment")

        validate_operation: Any = None
        deployments = self._rm_client.deployments
        try:
            validate_operation = self._rm_client.deployments.begin_validate(
                **deployment_parameters
            )
            result = validate_operation.wait()
            if result:
                raise LisaException(f"deploy failed: {result}")
        except Exception as identifier:
            if validate_operation:
                deployment = deployments.get(resource_group_name, AZURE_DEPLOYMENT_NAME)
                # log more details for troubleshooting
                if deployment.properties.provisioning_state == "Failed":
                    errors = deployment.properties.error.details
                    for error in errors:
                        self._log.error(f"failed: {error.code}, {error.message}")
            raise identifier

        assert result is None, f"validate error: {result}"

    def _deploy(self, deployment_parameters: Dict[str, Any]) -> None:
        resource_group_name = deployment_parameters[AZURE_RG_NAME_KEY]
        self._log.info(f"deploying {resource_group_name}")

        deployment_operation: Any = None
        deployments = self._rm_client.deployments
        try:
            deployment_operation = deployments.begin_create_or_update(
                **deployment_parameters
            )
            result = deployment_operation.wait()
            if result:
                raise LisaException(f"deploy failed: {result}")
        except Exception as identifier:
            if deployment_operation:
                deployment = deployments.get(resource_group_name, AZURE_DEPLOYMENT_NAME)
                # log more details for troubleshooting
                if deployment.properties.provisioning_state == "Failed":
                    errors = deployment.properties.error.details
                    for error in errors:
                        self._log.error(f"failed: {error.code}, {error.message}")
            raise identifier

    def _initialize_nodes(self, environment: Environment) -> None:

        node_context_map: Dict[str, Node] = dict()
        for node in environment.nodes.list():
            node_context = node.get_context(NodeContext)
            node_context_map[node_context.vm_name] = node

        compute_client = ComputeManagementClient(
            credential=self._credential, subscription_id=self._subscription_id
        )
        environment_context = environment.get_context(EnvironmentContext)
        vms_map: Dict[str, VirtualMachine] = dict()
        vms = compute_client.virtual_machines.list(
            environment_context.resource_group_name
        )
        for vm in vms:
            vms_map[vm.name] = vm

        network_client = NetworkManagementClient(
            credential=self._credential, subscription_id=self._subscription_id
        )

        # load port mappings
        nat_rules_map: Dict[str, InboundNatRule] = dict()
        load_balancing = network_client.load_balancers.get(
            environment_context.resource_group_name, RESOURCE_ID_LB
        )
        for rule in load_balancing.inbound_nat_rules:
            name = rule.name[: -len(RESOURCE_ID_PORT_POSTFIX)]
            nat_rules_map[name] = rule

        # load nics
        nic_map: Dict[str, NetworkInterface] = dict()
        network_interfaces = network_client.network_interfaces.list(
            environment_context.resource_group_name
        )
        for nic in network_interfaces:
            name = nic.name[: -len(RESOURCE_ID_NIC_POSTFIX)]
            nic_map[name] = nic

        # get public IP
        public_ip_address = network_client.public_ip_addresses.get(
            environment_context.resource_group_name, RESOURCE_ID_PUBLIC_IP
        ).ip_address

        for vm_name, node in node_context_map.items():
            node_context = node.get_context(NodeContext)
            vm = vms_map[vm_name]
            nic = nic_map[vm_name]
            nat_rule = nat_rules_map[vm_name]

            address = nic.ip_configurations[0].private_ip_address
            port = nat_rule.backend_port
            public_port = nat_rule.frontend_port
            node.set_connection_info(
                address=address,
                port=port,
                public_address=public_ip_address,
                public_port=public_port,
                username=node_context.username,
                password=node_context.password,
                private_key_file=node_context.private_key_file,
            )
