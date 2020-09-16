import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

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
from retry import retry  # type: ignore

from lisa import schema, search_space
from lisa.environment import Environment
from lisa.node import Node
from lisa.platform_ import Platform
from lisa.secret import PATTERN_GUID, PATTERN_HEADTAIL, add_secret
from lisa.util import LisaException, constants, get_public_key_data
from lisa.util.logger import Logger
from lisa.util.perf_timer import create_timer

AZURE = "azure"

# used by azure
AZURE_DEPLOYMENT_NAME = "lisa_default_deployment_script"
AZURE_RG_NAME_KEY = "resource_group_name"

VM_SIZE_FALLBACK_LEVELS = [
    re.compile(r"Standard_DS(\d)+_v2"),
    re.compile(r"Standard_A(\d)+"),
]
LOCATIONS = ["westus2", "eastus2"]
RESOURCE_GROUP_LOCATION = "westus2"

# names in arm template, they should be changed with template together.
RESOURCE_ID_LB = "lisa-loadBalancer"
RESOURCE_ID_PUBLIC_IP = "lisa-publicIPv4Address"
RESOURCE_ID_PORT_POSTFIX = "-ssh"
RESOURCE_ID_NIC_POSTFIX = "-nic"


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class AzureCapability:
    location: str
    vm_size: str
    capability: schema.NodeSpace
    estimated_cost: int
    resource_sku: Dict[str, Any]


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
    capabilities: List[AzureCapability] = field(default_factory=list)


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
    locations: Optional[Union[str, List[str]]] = field(default=None)

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
    # do actual deployment, or try to retrieve existing vms
    deploy: bool = True
    # wait resource deleted or not
    wait_delete: bool = False

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        add_secret(self.service_principal_tenant_id, mask=PATTERN_GUID)
        add_secret(self.service_principal_client_id, mask=PATTERN_GUID)
        add_secret(self.service_principal_key)
        add_secret(self.subscription_id, mask=PATTERN_GUID)

        if not self.locations:
            self.locations = LOCATIONS


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class AzureNodeSchema:
    vm_size: str = field(default="")
    location: str = field(default="")
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
        self._eligable_capabilities: Optional[Dict[str, List[AzureCapability]]] = None

    @classmethod
    def platform_type(cls) -> str:
        return AZURE

    def _prepare_environment(self, environment: Environment, log: Logger) -> bool:
        """
        Main flow

        _initialize_eligable_vm_sizes for all environments.
        1. load location, vm size patterns firstly.
        2. load avaiablbe vm sizes for each location.
        3. match vm sizes by pattern.

        for each environment
        1. If predefined location exists on node level, check conflict and use it.
        2. If predefined vm size exists on node level, check exists and use it.
        3. check capability for each node by order of pattern.
        4. get min capability for each match
        """

        is_success: bool = False

        if environment.runbook.nodes_requirement:
            nodes_requirement = environment.runbook.nodes_requirement
            node_count = len(nodes_requirement)
            # fills predefined locations here.
            predefined_caps: List[Any] = [None] * node_count
            # make sure all vms are in same location.
            existing_location: str = ""
            predefined_cost: int = 0

            assert self._eligable_capabilities

            # check locations
            for req in nodes_requirement:
                # apply azure specified values
                # they will pass into arm template
                node_runbook: AzureNodeSchema = req.get_extended_runbook(
                    AzureNodeSchema, AZURE
                )
                if node_runbook.location:
                    if existing_location:
                        # if any one has different location, calculate again
                        if existing_location != node_runbook.location:
                            raise LisaException(
                                f"predefined node must be in same location, "
                                f"previous: {existing_location}, "
                                f"found: {node_runbook.location}"
                            )
                    else:
                        existing_location = node_runbook.location

            if existing_location:
                locations = [existing_location]
            else:
                locations = LOCATIONS

            # check eligab locations
            found_or_skipped = False
            for location_name in locations:
                predefined_cost = 0
                predefined_caps = [None] * node_count
                for req_index, req in enumerate(nodes_requirement):
                    found_or_skipped = False
                    node_runbook = req.get_extended_runbook(AzureNodeSchema, AZURE)
                    if not node_runbook.vm_size:
                        # not to check, if no vm_size set
                        found_or_skipped = True
                        continue

                    # find predefined vm size on all avaiable's.
                    location_info: AzureLocation = self._get_location_info(
                        location_name, log
                    )
                    for azure_cap in location_info.capabilities:
                        if azure_cap.vm_size == node_runbook.vm_size:
                            predefined_cost += azure_cap.estimated_cost

                            min_cap = req.generate_min_capability(azure_cap.capability)
                            # apply azure specified values
                            # they will pass into arm template
                            min_runbook = min_cap.get_extended_runbook(
                                AzureNodeSchema, AZURE
                            )
                            # the location may not be set
                            min_runbook.location = location_name
                            min_runbook.vm_size = azure_cap.vm_size
                            if not existing_location:
                                existing_location = location_name
                            predefined_caps[req_index] = min_cap
                            found_or_skipped = True
                            break
                    if not found_or_skipped:
                        # if not found any, skip and try next location
                        break
                if found_or_skipped:
                    # if found all, skip other locations
                    break
            if not found_or_skipped:
                # no location meet requirement
                raise LisaException(
                    f"cannot find predefined vm size [{node_runbook.vm_size}] "
                    f"in location [{locations}]"
                )
            for location_name, location_caps in self._eligable_capabilities.items():
                # in each location, all node must be found
                # fill them as None and check after meeted capability
                found_capabilities: List[Any] = list(predefined_caps)

                # skip unmatched location
                if existing_location and existing_location != location_name:
                    continue

                estimated_cost: int = 0
                for azure_cap in location_caps:
                    for req_index, req in enumerate(nodes_requirement):
                        if found_capabilities[req_index]:
                            # found, so skipped
                            continue

                        check_result = req.check(azure_cap.capability)
                        if check_result.result:
                            min_cap = req.generate_min_capability(azure_cap.capability)

                            # apply azure specified values
                            # they will pass into arm template
                            node_runbook = min_cap.get_extended_runbook(
                                AzureNodeSchema, AZURE
                            )
                            if node_runbook.location:
                                assert node_runbook.location == azure_cap.location, (
                                    f"predefined location [{node_runbook.location}] "
                                    f"must be same as "
                                    f"cap location [{azure_cap.location}]"
                                )
                            else:
                                node_runbook.location = azure_cap.location
                            if not node_runbook.vm_size:
                                node_runbook.vm_size = azure_cap.vm_size

                            estimated_cost += azure_cap.estimated_cost

                            found_capabilities[req_index] = min_cap
                    if all(x for x in found_capabilities):
                        break

                if all(x for x in found_capabilities):
                    # all found and replace current requirement
                    environment.runbook.nodes_requirement = found_capabilities
                    environment.cost = estimated_cost + predefined_cost
                    is_success = True
                    log.debug(
                        f"requirement meet, "
                        f"cost: {environment.cost}, "
                        f"cap: {environment.runbook.nodes_requirement}"
                    )
                    break
        return is_success

    def _deploy_environment(self, environment: Environment, log: Logger) -> None:
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

        environment_context.resource_group_name = resource_group_name
        if self._azure_runbook.dry_run:
            log.info(f"dry_run: {self._azure_runbook.dry_run}")
        else:
            try:
                if self._azure_runbook.deploy:
                    log.info(
                        f"creating or updating resource group: {resource_group_name}"
                    )
                    self._rm_client.resource_groups.create_or_update(
                        resource_group_name, {"location": RESOURCE_GROUP_LOCATION}
                    )
                else:
                    log.info(f"reusing resource group: {resource_group_name}")

                deployment_parameters = self._create_deployment_parameters(
                    resource_group_name, environment, log
                )

                if self._azure_runbook.deploy:
                    self._validate_template(deployment_parameters, log)
                    self._deploy(deployment_parameters, log)

                # Even skipped deploy, try best to initialize nodes
                self._initialize_nodes(environment)

            except Exception as identifier:
                self._delete_environment(environment, log)
                raise identifier
        environment.is_ready = True

    def _delete_environment(self, environment: Environment, log: Logger) -> None:
        environment_context = environment.get_context(EnvironmentContext)
        resource_group_name = environment_context.resource_group_name
        assert resource_group_name
        assert self._azure_runbook

        if not environment_context.resource_group_is_created:
            log.info(
                f"skipped to delete resource group: {resource_group_name}, "
                f"as it's not created by this run."
            )
        elif self._runbook.reserve_environment:
            log.info(
                f"skipped to delete resource group: {resource_group_name}, "
                f"as runbook set to reserve environment."
            )
        elif self._azure_runbook.dry_run:
            log.info(
                f"skipped to delete resource group: {resource_group_name}, "
                f"as it's a dry run."
            )
        else:
            assert self._rm_client
            log.info(
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
                log.debug("not wait deleting")

    def _initialize(self) -> None:
        # set needed environment variables for authentication
        azure_runbook = self._runbook.get_extended_runbook(AzurePlatformSchema)
        assert azure_runbook, "platform runbook cannot be empty"
        self._azure_runbook = azure_runbook

        # set azure log to warn level only
        logging.getLogger("azure").setLevel(azure_runbook.log_level)

        os.environ["AZURE_TENANT_ID"] = azure_runbook.service_principal_tenant_id
        os.environ["AZURE_CLIENT_ID"] = azure_runbook.service_principal_client_id
        os.environ["AZURE_CLIENT_SECRET"] = azure_runbook.service_principal_key

        self._credential = DefaultAzureCredential()

        self._sub_client = SubscriptionClient(self._credential)

        self._subscription_id = azure_runbook.subscription_id
        subscription = self._sub_client.subscriptions.get(self._subscription_id)
        if not subscription:
            raise LisaException(
                f"cannot find subscription id: '{self._subscription_id}'"
            )
        self._log.info(f"connected to subscription: '{subscription.display_name}'")

        self._rm_client = ResourceManagementClient(
            credential=self._credential, subscription_id=self._subscription_id
        )
        self._initialize_eligable_vm_sizes(self._log)

    @lru_cache
    def _load_template(self) -> Any:
        template_file_path = Path(__file__).parent / "arm_template.json"
        with open(template_file_path, "r") as f:
            template = json.load(f)
        return template

    @lru_cache
    @retry(tries=2)  # type: ignore
    def _get_location_info(self, location: str, log: Logger) -> AzureLocation:
        cached_file_name = constants.CACHE_PATH.joinpath("azure_locations.json")
        should_refresh: bool = True
        location_data: Optional[AzureLocation] = None
        if cached_file_name.exists():
            try:
                with open(cached_file_name, "r") as f:
                    loaded_data: Dict[str, Any] = json.load(f)
                locations_data: Dict[str, AzureLocation] = dict()
                for loc_name, loc_data in loaded_data.items():
                    loc_obj: AzureLocation = AzureLocation.schema().load(  # type:ignore
                        loc_data
                    )
                    locations_data[loc_name] = loc_obj
            except Exception as identifier:
                # if schema changed, There may be exception, remove cache and retry
                # Note: retry on this method depends on decorator
                log.debug("error on loading cache, delete cache and retry.")
                cached_file_name.unlink()
                raise identifier
            location_data = locations_data.get(location)
        else:
            locations_data = dict()

        if location_data:
            delta = datetime.now() - location_data.updated_time
            # refresh cached locations every 5 days.
            if delta.days < 5:
                should_refresh = False
                log.debug(
                    f"{location}: cache used: {location_data.updated_time}, "
                    f"sku count: {len(location_data.capabilities)}"
                )
            else:
                log.debug(
                    f"{location}: cache timeout: {location_data.updated_time},"
                    f"sku count: {len(location_data.capabilities)}"
                )
        else:
            log.debug(f"{location}: no cache found")
        if should_refresh:
            compute_client = ComputeManagementClient(
                credential=self._credential, subscription_id=self._subscription_id
            )

            log.debug(f"{location}: querying")
            all_skus: List[AzureCapability] = []
            paged_skus = compute_client.resource_skus.list(
                f"location eq '{location}'"
            ).by_page()
            for skus in paged_skus:
                for sku_obj in skus:
                    try:
                        if sku_obj.resource_type == "virtualMachines":
                            if sku_obj.restrictions and any(
                                restriction.type == "Location"
                                for restriction in sku_obj.restrictions
                            ):
                                # restricted on this location
                                continue
                            resource_sku = sku_obj.as_dict()
                            capability = self._resource_sku_to_capability(
                                location, sku_obj
                            )

                            # estimate vm cost for priority
                            assert isinstance(capability.core_count, int)
                            assert isinstance(capability.gpu_count, int)
                            estimated_cost = (
                                capability.core_count + capability.gpu_count * 100
                            )
                            azure_capability = AzureCapability(
                                location=location,
                                vm_size=sku_obj.name,
                                capability=capability,
                                resource_sku=resource_sku,
                                estimated_cost=estimated_cost,
                            )
                            all_skus.append(azure_capability)
                    except Exception as identifier:
                        log.error(f"unknown sku: {sku_obj}")
                        raise identifier
            location_data = AzureLocation(location=location, capabilities=all_skus)
            locations_data[location_data.location] = location_data
            log.debug(f"{location}: saving to disk")
            with open(cached_file_name, "w") as f:
                saved_data: Dict[str, Any] = dict()
                for name, value in locations_data.items():
                    saved_data[name] = value.to_dict()  # type: ignore
                json.dump(saved_data, f)
            log.debug(
                f"{location_data.location}: new data, "
                f"sku: {len(location_data.capabilities)}"
            )

        assert location_data
        return location_data

    def _create_deployment_parameters(
        self, resource_group_name: str, environment: Environment, log: Logger
    ) -> Dict[str, Any]:
        assert environment.runbook, "env data cannot be None"
        assert environment.runbook.nodes_requirement, "node requirement cannot be None"

        log.debug("creating deployment")
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

        nodes_parameters: List[AzureArmParameterNode] = []
        for node_space in environment.runbook.nodes_requirement:
            assert isinstance(
                node_space, schema.NodeSpace
            ), f"actual: {type(node_space)}"
            azure_node_runbook = node_space.get_extended_runbook(
                AzureNodeSchema, field_name=AZURE
            )

            # init node
            node = environment.nodes.from_requirement(node_space)
            gallery = AzureArmParameterGallery()
            node_arm_parameter = AzureArmParameterNode(gallery=gallery)
            node_arm_parameter.name = f"node-{len(nodes_parameters)}"
            if azure_node_runbook:
                if azure_node_runbook.vm_size:
                    node_arm_parameter.vm_size = azure_node_runbook.vm_size
                if azure_node_runbook.vhd:
                    node_arm_parameter.vhd = azure_node_runbook.vhd
                    node_arm_parameter.gallery = None
            nodes_parameters.append(node_arm_parameter)

            node_context = node.get_context(NodeContext)
            # vm's name, use to find it from azure
            node_context.vm_name = node_arm_parameter.name
            node_context.username = arm_parameters.admin_username
            node_context.password = arm_parameters.admin_password
            node_context.private_key_file = self._runbook.admin_private_key_file

        arm_parameters.nodes = nodes_parameters

        # load template
        template = self._load_template()
        parameters = arm_parameters.to_dict()  # type:ignore
        parameters = {k: {"value": v} for k, v in parameters.items()}
        log.debug(f"parameters: {parameters}")
        deployment_properties = DeploymentProperties(
            mode=DeploymentMode.incremental, template=template, parameters=parameters,
        )

        return {
            AZURE_RG_NAME_KEY: resource_group_name,
            "deployment_name": AZURE_DEPLOYMENT_NAME,
            "parameters": Deployment(properties=deployment_properties),
        }

    def _validate_template(
        self, deployment_parameters: Dict[str, Any], log: Logger
    ) -> None:
        resource_group_name = deployment_parameters[AZURE_RG_NAME_KEY]
        log.debug("validating deployment")

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
                        log.error(f"failed: {error.code}, {error.message}")
            raise identifier

        assert result is None, f"validate error: {result}"

    def _deploy(self, deployment_parameters: Dict[str, Any], log: Logger) -> None:
        resource_group_name = deployment_parameters[AZURE_RG_NAME_KEY]
        timer = create_timer()
        log.info(f"deploying {resource_group_name}")

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
                        log.error(f"failed: {error.code}, {error.message}")
            raise identifier
        log.info(f"deployed with {timer}")

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
            vm = vms_map.get(vm_name, None)
            if not vm:
                raise LisaException(
                    f"cannot find vm: '{vm_name}', make sure deployment is correct."
                )
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

    def _resource_sku_to_capability(
        self, location: str, resource_sku: ResourceSku
    ) -> schema.NodeSpace:
        # fill in default values, in case no capability meet.
        node_space = schema.NodeSpace(
            node_count=1,
            core_count=0,
            disk_count=0,
            memory_mb=0,
            nic_count=0,
            gpu_count=0,
            features=search_space.SetSpace[schema.Feature](is_allow_set=True),
            excluded_features=search_space.SetSpace[schema.Feature](is_allow_set=False),
        )
        node_space.name = f"{location}_{resource_sku.name}"
        for sku_capability in resource_sku.capabilities:
            name = sku_capability.name
            if name == "vCPUs":
                node_space.core_count = int(sku_capability.value)
            elif name == "MaxDataDiskCount":
                node_space.disk_count = search_space.IntRange(
                    max=int(sku_capability.value)
                )
            elif name == "MemoryGB":
                node_space.memory_mb = int(float(sku_capability.value) * 1024)
            elif name == "MaxNetworkInterfaces":
                node_space.nic_count = search_space.IntRange(
                    max=int(sku_capability.value)
                )
            elif name == "GPUs":
                node_space.gpu_count = int(sku_capability.value)

        return node_space

    def _initialize_eligable_vm_sizes(self, log: Logger) -> None:
        # load eligable vm sizes
        # 1. location is selected
        # 2. vm size supported in current location
        # 3. vm size match predefined pattern
        if self._eligable_capabilities is None:
            assert self._azure_runbook
            if isinstance(self._azure_runbook.locations, str):
                location_names = [self._azure_runbook.locations]
            else:
                assert isinstance(
                    self._azure_runbook.locations, list
                ), f"actual: {type(self._azure_runbook.locations)}"
                location_names = self._azure_runbook.locations

            available_capabilities: Dict[str, List[AzureCapability]] = dict()

            # loop all locations
            for location_name in location_names:
                location_capabilities: List[AzureCapability] = []
                location_info: AzureLocation = self._get_location_info(
                    location_name, log
                )

                # loop all fall back levels
                for fallback_pattern in VM_SIZE_FALLBACK_LEVELS:
                    level_capabilities: List[AzureCapability] = []

                    # loop all capabilities
                    for capability in location_info.capabilities:
                        if fallback_pattern.match(capability.vm_size):
                            level_capabilities.append(capability)

                    # sort by rough cost
                    level_capabilities.sort(key=lambda x: (x.estimated_cost))
                    log.debug(
                        f"{location_name}, pattern '{fallback_pattern.pattern}'"
                        f" {len(level_capabilities)} candidates: "
                        f"{[x.vm_size for x in level_capabilities]}"
                    )
                    location_capabilities.extend(level_capabilities)
                available_capabilities[location_name] = location_capabilities
            self._eligable_capabilities = available_capabilities
