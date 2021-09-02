# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import copy
import json
import logging
import os
import re
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple, Type, Union

from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute.models import (  # type: ignore
    PurchasePlan,
    ResourceSku,
    VirtualMachine,
    VirtualMachineImage,
)
from azure.mgmt.marketplaceordering.models import AgreementTerms  # type: ignore
from azure.mgmt.network.models import NetworkInterface, PublicIPAddress  # type: ignore
from azure.mgmt.resource import SubscriptionClient  # type: ignore
from azure.mgmt.resource.resources.models import (  # type: ignore
    Deployment,
    DeploymentMode,
    DeploymentProperties,
)
from dataclasses_json import dataclass_json
from marshmallow import fields, validate
from retry import retry

from lisa import feature, schema, search_space
from lisa.environment import Environment
from lisa.node import Node, RemoteNode
from lisa.platform_ import Platform
from lisa.secret import PATTERN_GUID, PATTERN_HEADTAIL, add_secret
from lisa.sut_orchestrator.azure.tools import VmGeneration, Waagent
from lisa.tools import Dmesg, Modinfo
from lisa.util import (
    LisaException,
    constants,
    dump_file,
    get_matched_str,
    get_public_key_data,
    plugin_manager,
    set_filtered_fields,
)
from lisa.util.logger import Logger

from . import features
from .common import (
    AZURE,
    AZURE_SHARED_RG_NAME,
    AzureNodeSchema,
    AzureVmMarketplaceSchema,
    AzureVmPurchasePlanSchema,
    DataDiskCreateOption,
    DataDiskSchema,
    check_or_create_resource_group,
    check_or_create_storage_account,
    get_compute_client,
    get_environment_context,
    get_marketplace_ordering_client,
    get_network_client,
    get_node_context,
    get_or_create_storage_container,
    get_resource_management_client,
    get_storage_account_name,
    wait_copy_blob,
    wait_operation,
)

# used by azure
AZURE_DEPLOYMENT_NAME = "lisa_default_deployment_script"
AZURE_RG_NAME_KEY = "resource_group_name"
AZURE_INTERNAL_ERROR_PATTERN = re.compile(
    r"OSProvisioningInternalError: OS Provisioning failed "
    r"for VM.*due to an internal error."
)

VM_SIZE_FALLBACK_PATTERNS = [
    # exclude Standard_DS1_v2, because one core is too slow,
    # and doesn't work in some distro
    re.compile(r"Standard_DS((?!1)[\d])_v2"),
    re.compile(r"Standard_DS([\d]{2})_v2"),
    re.compile(r".*"),
]
LOCATIONS = [
    "westus2",
    "eastus2",
    "southeastasia",
    "eastus",
    "southcentralus",
    "northeurope",
    "westeurope",
    "brazilsouth",
    "australiaeast",
    "uksouth",
]
RESOURCE_GROUP_LOCATION = "westus2"

# names in arm template, they should be changed with template together.
RESOURCE_ID_PORT_POSTFIX = "-ssh"
RESOURCE_ID_NIC_PATTERN = re.compile(r"([\w]+-[\d]+)-nic-0")
RESOURCE_ID_PUBLIC_IP_PATTERN = re.compile(r"([\w]+-[\d]+)-public-ip")

# Ubuntu 18.04:
# [    0.000000] Hyper-V Host Build:18362-10.0-3-0.3198
# FreeBSD 11.3:
# Hyper-V Version: 10.0.18362 [SP3]
# bitnami dreamfactory 1.7 1.7.8
# [    1.283478] hv_vmbus: Hyper-V Host Build:18362-10.0-3-0.3256; Vmbus version:3.0
HOST_VERSION_PATTERN = re.compile(
    r"Hyper-V (?:Host Build|Version):[ ]?([^\r\n;]*)", re.M
)

# normal
# [    0.000000] Linux version 5.4.0-1043-azure (buildd@lgw01-amd64-026) (gcc ...
KERNEL_VERSION_PATTERN = re.compile(r"Linux version (?P<kernel_version>.+?) ", re.M)

# 2021/03/31 00:05:17.431693 INFO Daemon Azure Linux Agent Version:2.2.38
# 2021/04/19 13:16:28 Windows Azure Linux Agent Version: WALinuxAgent-2.0.14
WALA_VERSION_PATTERN = re.compile(
    r"Azure Linux Agent Version:(?: WALinuxAgent-)?(?P<wala_version>.+?)[\n\r]", re.M
)

KEY_HOST_VERSION = "host_version"
KEY_VM_GENERATION = "vm_generation"
KEY_KERNEL_VERSION = "kernel_version"
KEY_WALA_VERSION = "wala_version"
ATTRIBUTE_FEATURES = "features"

SAS_URL_PATTERN = re.compile(
    r"^https?://.*?.blob.core.windows.net/.*?\?.*?"
    r"st=.*?&se=(?P<year>[\d]{4})-(?P<month>[\d]{2})-(?P<day>[\d]{2}).*?&sig=.*$"
)
SAS_COPIED_CONTAINER_NAME = "lisa-sas-copied"

_global_sas_vhd_copy_lock = Lock()


@dataclass_json()
@dataclass
class AzureCapability:
    location: str
    vm_size: str
    capability: schema.NodeSpace
    estimated_cost: int
    resource_sku: Dict[str, Any]

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        # reload features settings with platform specified types.
        _convert_to_azure_node_space(self.capability)


@dataclass_json()
@dataclass
class AzureLocation:
    updated_time: datetime = field(
        default_factory=datetime.now,
        metadata=schema.metadata(
            fields.DateTime,
            encoder=datetime.isoformat,
            decoder=datetime.fromisoformat,
            format="iso",
        ),
    )
    location: str = ""
    capabilities: List[AzureCapability] = field(default_factory=list)


@dataclass_json()
@dataclass
class AzureArmParameter:
    resource_group_name: str = ""
    storage_name: str = ""
    location: str = ""
    admin_username: str = ""
    admin_password: str = ""
    admin_key_data: str = ""
    availability_set_tags: Dict[str, str] = field(default_factory=dict)
    availability_set_properties: Dict[str, Any] = field(default_factory=dict)
    enable_sriov: Optional[bool] = None
    nodes: List[AzureNodeSchema] = field(default_factory=list)
    data_disks: List[DataDiskSchema] = field(default_factory=list)

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        add_secret(self.admin_username, PATTERN_HEADTAIL)
        add_secret(self.admin_password)
        add_secret(self.admin_key_data)

        if not self.availability_set_properties:
            self.availability_set_properties: Dict[str, Any] = {
                "platformFaultDomainCount": 1,
                "platformUpdateDomainCount": 1,
            }


@dataclass_json()
@dataclass
class AzurePlatformSchema:
    service_principal_tenant_id: str = field(
        default="",
        metadata=schema.metadata(
            validate=validate.Regexp(constants.GUID_REGEXP),
        ),
    )
    service_principal_client_id: str = field(
        default="",
        metadata=schema.metadata(
            validate=validate.Regexp(constants.GUID_REGEXP),
        ),
    )
    service_principal_key: str = field(default="")
    subscription_id: str = field(
        default="",
        metadata=schema.metadata(
            validate=validate.Regexp(constants.GUID_REGEXP),
        ),
    )

    resource_group_name: str = field(default="")
    availability_set_tags: Optional[Dict[str, str]] = field(default=None)
    availability_set_properties: Optional[Dict[str, Any]] = field(default=None)
    locations: Optional[Union[str, List[str]]] = field(default=None)

    log_level: str = field(
        default=logging.getLevelName(logging.WARN),
        metadata=schema.metadata(
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
        if self.service_principal_tenant_id:
            add_secret(self.service_principal_tenant_id, mask=PATTERN_GUID)
        if self.subscription_id:
            add_secret(self.subscription_id, mask=PATTERN_GUID)

        if self.service_principal_client_id or self.service_principal_key:
            add_secret(self.service_principal_client_id, mask=PATTERN_GUID)
            add_secret(self.service_principal_key)
            if not self.service_principal_client_id or not self.service_principal_key:
                raise LisaException(
                    "service_principal_client_id and service_principal_key "
                    "should be specified either both or not."
                )

        if not self.locations:
            self.locations = LOCATIONS


class AzurePlatform(Platform):
    def __init__(self, runbook: schema.Platform) -> None:
        super().__init__(runbook=runbook)
        self._eligible_capabilities: Dict[str, List[AzureCapability]] = {}
        self._locations_data_cache: Dict[str, AzureLocation] = {}

    @classmethod
    def type_name(cls) -> str:
        return AZURE

    @classmethod
    def supported_features(cls) -> List[Type[feature.Feature]]:
        return [
            features.Disk,
            features.Gpu,
            features.Nvme,
            features.SerialConsole,
            features.Sriov,
            features.StartStop,
        ]

    def _prepare_environment(  # noqa: C901
        self, environment: Environment, log: Logger
    ) -> bool:
        # TODO: Reduce this function's complexity and remove the disabled warning.
        """
        Main flow

        1. load location, vm size patterns firstly.
        2. load available vm sizes for each location.
        3. match vm sizes by pattern.

        for each environment
        1. If predefined location exists on node level, check conflict and use it.
        2. If predefined vm size exists on node level, check exists and use it.
        3. check capability for each node by order of pattern.
        4. get min capability for each match
        """
        is_success: bool = True

        if environment.runbook.nodes_requirement:
            is_success = False
            nodes_requirement = environment.runbook.nodes_requirement
            node_count = len(nodes_requirement)
            # fills predefined locations here.
            predefined_caps: List[Any] = [None] * node_count
            # make sure all vms are in same location.
            existing_location: str = ""
            predefined_cost: int = 0

            for req in nodes_requirement:
                # covert to azure node space, so the azure extensions can be loaded.
                _convert_to_azure_node_space(req)

                # check locations
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

            # check eligible locations
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

                    # find predefined vm size on all available's.
                    location_info: AzureLocation = self._get_location_info(
                        location_name, log
                    )
                    matched_score: float = 0
                    matched_cap: Optional[AzureCapability] = None
                    matcher = SequenceMatcher(None, node_runbook.vm_size.lower(), "")
                    for azure_cap in location_info.capabilities:
                        matcher.set_seq2(azure_cap.vm_size.lower())
                        if (
                            node_runbook.vm_size.lower() in azure_cap.vm_size.lower()
                            and matched_score < matcher.ratio()
                        ):
                            matched_cap = azure_cap
                            matched_score = matcher.ratio()
                    if matched_cap:
                        predefined_cost += matched_cap.estimated_cost

                        min_cap = self._generate_min_capability(
                            req, matched_cap, location_name
                        )

                        if not existing_location:
                            existing_location = location_name
                        predefined_caps[req_index] = min_cap
                        found_or_skipped = True
                    else:
                        # if not found any, skip and try next location
                        break
                if found_or_skipped:
                    # if found all, skip other locations
                    break
            if not found_or_skipped:
                # no location/vm_size meets requirement, so generate mockup to
                # continue to test. It applies to some preview vm_size may not
                # be listed by API.
                location = next((x for x in locations))
                for req_index, req in enumerate(nodes_requirement):
                    if not node_runbook.vm_size or predefined_caps[req_index]:
                        continue

                    log.info(
                        f"Cannot find vm_size {node_runbook.vm_size} in {location}. "
                        f"Mockup capability to run tests."
                    )
                    mock_up_capability = self._generate_mockup_capability(
                        node_runbook.vm_size, location
                    )
                    min_cap = self._generate_min_capability(
                        req, mock_up_capability, location
                    )
                    predefined_caps[req_index] = min_cap

            for location_name in locations:
                # in each location, all node must be found
                # fill them as None and check after met capability
                found_capabilities: List[Any] = list(predefined_caps)

                # skip unmatched location
                if existing_location and existing_location != location_name:
                    continue

                estimated_cost: int = 0
                location_caps = self._get_eligible_vm_sizes(location_name, log)
                for req_index, req in enumerate(nodes_requirement):
                    for azure_cap in location_caps:
                        if found_capabilities[req_index]:
                            # found, so skipped
                            break

                        check_result = req.check(azure_cap.capability)
                        if check_result.result:
                            min_cap = self._generate_min_capability(
                                req, azure_cap, azure_cap.location
                            )

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

        environment_context = get_environment_context(environment=environment)
        if self._azure_runbook.resource_group_name:
            resource_group_name = self._azure_runbook.resource_group_name
        else:
            normalized_run_name = constants.NORMALIZE_PATTERN.sub(
                "_", constants.RUN_NAME
            )
            resource_group_name = f"{normalized_run_name}_e{environment.id}"
            environment_context.resource_group_is_created = True

        environment_context.resource_group_name = resource_group_name
        if self._azure_runbook.dry_run:
            log.info(f"dry_run: {self._azure_runbook.dry_run}")
        else:
            try:
                if self._azure_runbook.deploy:
                    log.info(
                        f"creating or updating resource group: [{resource_group_name}]"
                    )
                    self._rm_client.resource_groups.create_or_update(
                        resource_group_name, {"location": RESOURCE_GROUP_LOCATION}
                    )
                else:
                    log.info(f"reusing resource group: [{resource_group_name}]")

                location, deployment_parameters = self._create_deployment_parameters(
                    resource_group_name, environment, log
                )

                if self._azure_runbook.deploy:
                    self._validate_template(deployment_parameters, log)
                    self._deploy(location, deployment_parameters, log)

                # Even skipped deploy, try best to initialize nodes
                self._initialize_nodes(environment, log)
            except Exception as identifier:
                self._delete_environment(environment, log)
                raise identifier

    def _delete_environment(self, environment: Environment, log: Logger) -> None:
        environment_context = get_environment_context(environment=environment)
        resource_group_name = environment_context.resource_group_name
        # the resource group name is empty when it is not deployed for some reasons,
        # like capability doesn't meet case requirement.
        if not resource_group_name:
            return
        assert self._azure_runbook

        if not environment_context.resource_group_is_created:
            log.info(
                f"skipped to delete resource group: {resource_group_name}, "
                f"as it's not created by this run."
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
            delete_operation: Any = None
            try:
                delete_operation = self._rm_client.resource_groups.begin_delete(
                    resource_group_name
                )
            except Exception as identifer:
                log.debug(f"exception on delete resource group: {identifer}")
            if delete_operation and self._azure_runbook.wait_delete:
                result = wait_operation(delete_operation)
                if result:
                    raise LisaException(f"error on deleting resource group: {result}")
            else:
                log.debug("not wait deleting")

    def _get_node_information(self, node: Node) -> Dict[str, str]:
        information: Dict[str, Any] = {}

        node.log.debug("detecting lis version...")
        modinfo = node.tools[Modinfo]
        information["lis_version"] = modinfo.get_version("hv_vmbus")

        node.log.debug("detecting vm generation...")
        information[KEY_VM_GENERATION] = node.tools[VmGeneration].get_generation()
        node.log.debug(f"vm generation: {information[KEY_VM_GENERATION]}")

        return information

    def _get_kernel_version(self, node: Node) -> str:
        result: str = ""

        if not result and hasattr(node, ATTRIBUTE_FEATURES):
            # try to get kernel version in Azure. use it, when uname doesn't work
            node.log.debug("detecting kernel version from serial log...")
            serial_console = node.features[features.SerialConsole]
            result = serial_console.get_matched_str(KERNEL_VERSION_PATTERN)

        return result

    def _get_host_version(self, node: Node) -> str:
        result: str = ""

        try:
            if node.is_connected and node.is_posix:
                node.log.debug("detecting host version from dmesg...")
                dmesg = node.tools[Dmesg]
                result = get_matched_str(
                    dmesg.get_output(), HOST_VERSION_PATTERN, first_match=False
                )
        except Exception as identifier:
            # it happens on some error vms. Those error should be caught earlier in
            # test cases not here. So ignore any error here to collect information only.
            node.log.debug(f"error on run dmesg: {identifier}")

        # if not get, try again from serial console log.
        # skip if node is not initialized.
        if not result and hasattr(node, ATTRIBUTE_FEATURES):
            node.log.debug("detecting host version from serial log...")
            serial_console = node.features[features.SerialConsole]
            result = serial_console.get_matched_str(HOST_VERSION_PATTERN)

        return result

    def _get_wala_version(self, node: Node) -> str:
        result = ""

        try:
            if node.is_connected and node.is_posix:
                node.log.debug("detecting wala version...")
                waagent = node.tools[Waagent]
                result = waagent.get_version()
        except Exception as identifier:
            # it happens on some error vms. Those error should be caught earlier in
            # test cases not here. So ignore any error here to collect information only.
            node.log.debug(f"error on run waagent: {identifier}")

        if not result and hasattr(node, ATTRIBUTE_FEATURES):
            node.log.debug("detecting wala agent version from serial log...")
            serial_console = node.features[features.SerialConsole]
            result = serial_console.get_matched_str(WALA_VERSION_PATTERN)

        return result

    def _get_platform_information(self, environment: Environment) -> Dict[str, str]:
        result: Dict[str, str] = {}
        azure_runbook: AzurePlatformSchema = self.runbook.get_extended_runbook(
            AzurePlatformSchema
        )

        result[AZURE_RG_NAME_KEY] = get_environment_context(
            environment
        ).resource_group_name
        if azure_runbook.availability_set_properties:
            for (
                property_name,
                property_value,
            ) in azure_runbook.availability_set_properties.items():
                if property_name in [
                    "platformFaultDomainCount",
                    "platformUpdateDomainCount",
                ]:
                    continue
                if isinstance(property_value, dict):
                    for key, value in property_value.items():
                        result[key] = value
        if azure_runbook.availability_set_tags:
            for key, value in azure_runbook.availability_set_tags.items():
                result[key] = value

        return result

    def _get_environment_information(self, environment: Environment) -> Dict[str, str]:
        information: Dict[str, str] = {}
        node_runbook: Optional[AzureNodeSchema] = None
        if environment.nodes:
            node: Optional[Node] = environment.default_node
        else:
            node = None
        if node:
            node_runbook = node.capability.get_extended_runbook(AzureNodeSchema, AZURE)

            # some information get from two places, so create separated methods to
            # query them.
            try:
                host_version = self._get_host_version(node)
                if host_version:
                    information[KEY_HOST_VERSION] = host_version
            except Exception as identifier:
                node.log.exception("error on get host version", exc_info=identifier)

            try:
                kernel_version = self._get_kernel_version(node)
                if kernel_version:
                    information[KEY_KERNEL_VERSION] = kernel_version
            except Exception as identifier:
                node.log.exception("error on get kernel version", exc_info=identifier)

            try:
                wala_version = self._get_wala_version(node)
                if wala_version:
                    information[KEY_WALA_VERSION] = wala_version
            except Exception as identifier:
                node.log.exception("error on get waagent version", exc_info=identifier)

            information.update(self._get_platform_information(environment))

            if node.is_connected and node.is_posix:
                information.update(self._get_node_information(node))
        elif environment.capability and environment.capability.nodes:
            # get deployment information, if failed on preparing phase
            node_space = environment.capability.nodes[0]
            node_runbook = node_space.get_extended_runbook(
                AzureNodeSchema, type_name=AZURE
            )

        if node_runbook:
            information["location"] = node_runbook.location
            information["vmsize"] = node_runbook.vm_size
            information["image"] = node_runbook.get_image_name()

        return information

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        # set needed environment variables for authentication
        azure_runbook: AzurePlatformSchema = self.runbook.get_extended_runbook(
            AzurePlatformSchema
        )
        assert azure_runbook, "platform runbook cannot be empty"
        self._azure_runbook = azure_runbook

        # set azure log to warn level only
        logging.getLogger("azure").setLevel(azure_runbook.log_level)

        if azure_runbook.service_principal_tenant_id:
            os.environ["AZURE_TENANT_ID"] = azure_runbook.service_principal_tenant_id
        if azure_runbook.service_principal_client_id:
            os.environ["AZURE_CLIENT_ID"] = azure_runbook.service_principal_client_id
        if azure_runbook.service_principal_key:
            os.environ["AZURE_CLIENT_SECRET"] = azure_runbook.service_principal_key

        self.credential = DefaultAzureCredential()
        self._sub_client = SubscriptionClient(self.credential)

        self.subscription_id = azure_runbook.subscription_id

        # suppress warning message by search for different credential types
        azure_identity_logger = logging.getLogger("azure.identity")
        azure_identity_logger.setLevel(logging.ERROR)
        subscription = self._sub_client.subscriptions.get(self.subscription_id)
        azure_identity_logger.setLevel(logging.WARN)

        if not subscription:
            raise LisaException(
                f"Cannot find subscription id: '{self.subscription_id}'. "
                f"Make sure it exists and current account can access it."
            )
        self._log.info(
            f"connected to subscription: "
            f"{subscription.id}, '{subscription.display_name}'"
        )

        check_or_create_resource_group(
            self.credential,
            self.subscription_id,
            AZURE_SHARED_RG_NAME,
            RESOURCE_GROUP_LOCATION,
            self._log,
        )

        self._rm_client = get_resource_management_client(
            self.credential, self.subscription_id
        )

    @lru_cache
    def _load_template(self) -> Any:
        template_file_path = Path(__file__).parent / "arm_template.json"
        with open(template_file_path, "r") as f:
            template = json.load(f)
        return template

    @retry(tries=10, delay=1, jitter=(0.5, 1))  # type: ignore
    def _load_location_info_from_file(
        self, cached_file_name: Path, log: Logger
    ) -> Optional[AzureLocation]:
        loaded_obj: Optional[AzureLocation] = None
        if cached_file_name.exists():
            try:
                with open(cached_file_name, "r") as f:
                    loaded_data: Dict[str, Any] = json.load(f)
                loaded_obj = schema.load_by_type(AzureLocation, loaded_data)
            except Exception as identifier:
                # if schema changed, There may be exception, remove cache and retry
                # Note: retry on this method depends on decorator
                log.debug(
                    f"error on loading cache, delete cache and retry. {identifier}"
                )
                cached_file_name.unlink()
                raise identifier
        return loaded_obj

    def _get_location_info(self, location: str, log: Logger) -> AzureLocation:
        cached_file_name = constants.CACHE_PATH.joinpath(
            f"azure_locations_{location}.json"
        )
        should_refresh: bool = True
        location_data = self._locations_data_cache.get(location, None)
        if not location_data:
            location_data = self._load_location_info_from_file(
                cached_file_name=cached_file_name, log=log
            )

        if location_data:
            delta = datetime.now() - location_data.updated_time
            # refresh cached locations every 1 day.
            if delta.days < 1:
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
            compute_client = get_compute_client(self)

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
            self._locations_data_cache[location_data.location] = location_data
            log.debug(f"{location}: saving to disk")
            with open(cached_file_name, "w") as f:
                json.dump(location_data.to_dict(), f)  # type: ignore
            log.debug(
                f"{location_data.location}: new data, "
                f"sku: {len(location_data.capabilities)}"
            )

        assert location_data
        self._locations_data_cache[location] = location_data
        return location_data

    def _create_deployment_parameters(
        self, resource_group_name: str, environment: Environment, log: Logger
    ) -> Tuple[str, Dict[str, Any]]:
        assert environment.runbook, "env data cannot be None"
        assert environment.runbook.nodes_requirement, "node requirement cannot be None"

        log.debug("creating deployment")
        # construct parameters
        arm_parameters = AzureArmParameter()
        copied_fields = [
            "availability_set_tags",
            "availability_set_properties",
        ]
        set_filtered_fields(self._azure_runbook, arm_parameters, copied_fields)

        arm_parameters.admin_username = self.runbook.admin_username
        if self.runbook.admin_private_key_file:
            arm_parameters.admin_key_data = get_public_key_data(
                self.runbook.admin_private_key_file
            )
        else:
            arm_parameters.admin_password = self.runbook.admin_password

        environment_context = get_environment_context(environment=environment)
        arm_parameters.resource_group_name = environment_context.resource_group_name
        nodes_parameters: List[AzureNodeSchema] = []
        for node_space in environment.runbook.nodes_requirement:
            assert isinstance(
                node_space, schema.NodeSpace
            ), f"actual: {type(node_space)}"

            azure_node_runbook = node_space.get_extended_runbook(
                AzureNodeSchema, type_name=AZURE
            )
            # Subscription Id is used by Shared Gallery images located
            # in subscription different from where LISA is run
            azure_node_runbook.subscription_id = self.subscription_id
            # init node
            node = environment.create_node_from_requirement(
                node_space,
            )
            azure_node_runbook = self._create_node_runbook(
                len(nodes_parameters),
                node_space,
                log,
            )
            # save parsed runbook back, for example, the version of marketplace may be
            # parsed from latest to a specified version.
            node.capability.set_extended_runbook(azure_node_runbook)
            nodes_parameters.append(azure_node_runbook)

            # Set data disk array
            arm_parameters.data_disks = self._generate_data_disks(
                node, azure_node_runbook
            )

            if not arm_parameters.location:
                # take first one's location
                arm_parameters.location = azure_node_runbook.location

            # save vm's information into node
            node_context = get_node_context(node)
            node_context.resource_group_name = environment_context.resource_group_name
            # vm's name, use to find it from azure
            node_context.vm_name = azure_node_runbook.name
            # ssh related information will be filled back once vm is created
            node_context.username = arm_parameters.admin_username
            node_context.password = arm_parameters.admin_password
            node_context.private_key_file = self.runbook.admin_private_key_file

            log.info(f"vm setting: {azure_node_runbook}")

        arm_parameters.nodes = nodes_parameters
        arm_parameters.storage_name = get_storage_account_name(
            self.subscription_id, arm_parameters.location
        )
        if node.capability.has_feature(features.Sriov.name()):
            arm_parameters.enable_sriov = True
        else:
            self._log.debug(
                "use synthetic network since used size doesn't have Sriov capability"
            )
            arm_parameters.enable_sriov = False

        # the arm template may be updated by the hooks, so make a copy to avoid
        # the original template is modified.
        template = deepcopy(self._load_template())
        plugin_manager.hook.azure_update_arm_template(
            template=template, environment=environment
        )

        # composite deployment properties
        parameters = arm_parameters.to_dict()  # type:ignore
        parameters = {k: {"value": v} for k, v in parameters.items()}
        log.debug(f"parameters: {parameters}")
        deployment_properties = DeploymentProperties(
            mode=DeploymentMode.incremental,
            template=template,
            parameters=parameters,
        )

        # dump arm_template and arm_parameters to file
        template_dump_path = environment.log_path / "arm_template.json"
        param_dump_path = environment.log_path / "arm_template_parameters.json"
        dump_file(template_dump_path, json.dumps(template, indent=4))
        dump_file(param_dump_path, json.dumps(parameters, indent=4))

        return (
            arm_parameters.location,
            {
                AZURE_RG_NAME_KEY: resource_group_name,
                "deployment_name": AZURE_DEPLOYMENT_NAME,
                "parameters": Deployment(properties=deployment_properties),
            },
        )

    def _create_node_runbook(
        self,
        index: int,
        node_space: schema.NodeSpace,
        log: Logger,
    ) -> AzureNodeSchema:
        azure_node_runbook = node_space.get_extended_runbook(
            AzureNodeSchema, type_name=AZURE
        )

        if not azure_node_runbook.name:
            azure_node_runbook.name = f"node-{index}"
        if not azure_node_runbook.vm_size:
            raise LisaException("vm_size is not detected before deploy")
        if not azure_node_runbook.location:
            raise LisaException("location is not detected before deploy")
        if azure_node_runbook.nic_count <= 0:
            raise LisaException(
                f"nic_count need at least 1, but {azure_node_runbook.nic_count}"
            )
        if azure_node_runbook.vhd:
            # vhd is higher priority
            azure_node_runbook.vhd = self._get_deployable_vhd_path(
                azure_node_runbook.vhd, azure_node_runbook.location, log
            )
            azure_node_runbook.marketplace = None
            azure_node_runbook.shared_gallery = None
        elif azure_node_runbook.shared_gallery:
            azure_node_runbook.marketplace = None
        elif azure_node_runbook.marketplace:
            # marketplace value is already set in runbook
            pass
        else:
            # set to default marketplace, if nothing specified
            azure_node_runbook.marketplace = AzureVmMarketplaceSchema()

        if azure_node_runbook.marketplace:
            # resolve Latest to specified version
            azure_node_runbook.marketplace = self._parse_marketplace_image(
                azure_node_runbook.location, azure_node_runbook.marketplace
            )
        if azure_node_runbook.marketplace and not azure_node_runbook.purchase_plan:
            azure_node_runbook.purchase_plan = self._process_marketplace_image_plan(
                azure_node_runbook.location, azure_node_runbook.marketplace
            )

        # Set disk type
        assert node_space.disk, "node space must have disk defined."
        assert isinstance(node_space.disk.disk_type, schema.DiskType)
        azure_node_runbook.disk_type = features.get_azure_disk_type(
            node_space.disk.disk_type
        )
        azure_node_runbook.data_disk_caching_type = (
            node_space.disk.data_disk_caching_type
        )
        assert isinstance(
            node_space.disk.data_disk_iops, int
        ), f"actual: {type(node_space.disk.data_disk_iops)}"
        azure_node_runbook.data_disk_iops = node_space.disk.data_disk_iops
        assert isinstance(
            node_space.disk.data_disk_size, int
        ), f"actual: {type(node_space.disk.data_disk_size)}"
        azure_node_runbook.data_disk_size = node_space.disk.data_disk_size

        return azure_node_runbook

    def _validate_template(
        self, deployment_parameters: Dict[str, Any], log: Logger
    ) -> None:
        log.debug("validating deployment")

        validate_operation: Any = None
        try:
            validate_operation = self._rm_client.deployments.begin_validate(
                **deployment_parameters
            )
            result = wait_operation(validate_operation)
            if result:
                raise LisaException(f"validation failed: {result}")
        except Exception as identifier:
            error_messages: List[str] = [str(identifier)]

            if isinstance(identifier, HttpResponseError) and identifier.error:
                # no validate_operation returned, the message may include
                # some errors, so check details
                error_messages = self._parse_detail_errors(identifier.error)

            raise LisaException("\n".join(error_messages))

        assert result is None, f"validate error: {result}"

    def _deploy(
        self, location: str, deployment_parameters: Dict[str, Any], log: Logger
    ) -> None:
        resource_group_name = deployment_parameters[AZURE_RG_NAME_KEY]
        storage_account_name = get_storage_account_name(self.subscription_id, location)
        check_or_create_storage_account(
            self.credential,
            self.subscription_id,
            storage_account_name,
            AZURE_SHARED_RG_NAME,
            location,
            log,
        )

        log.info(f"resource group '{resource_group_name}' deployment is in progress...")
        deployment_operation: Any = None
        deployments = self._rm_client.deployments
        try:
            deployment_operation = deployments.begin_create_or_update(
                **deployment_parameters
            )
            result = wait_operation(deployment_operation)
            if result:
                raise LisaException(f"deploy failed: {result}")
        except HttpResponseError as identifier:
            # Some errors happens underlying, so there is no detail errors from API.
            # For example,
            # azure.core.exceptions.HttpResponseError:
            #    Operation returned an invalid status 'OK'
            assert identifier.error, f"HttpResponseError: {identifier}"

            error_message = "\n".join(self._parse_detail_errors(identifier.error))
            if "OSProvisioningTimedOut: OS Provisioning for VM" in error_message:
                # Provisioning timeout causes by waagent is not ready.
                # In smoke test, it still can verify some information.
                # Eat information here, to run test case any way.
                #
                # It may cause other cases fail on assumptions. In this case, we can
                # define a flag in config, to mark this exception is ignorable or not.
                log.error(
                    f"provisioning time out, try to run case. "
                    f"Exception: {error_message}"
                )
            elif get_matched_str(error_message, AZURE_INTERNAL_ERROR_PATTERN):
                # Similar situation with OSProvisioningTimedOut
                # Some OSProvisioningInternalError caused by it doesn't support
                # SSH key authentication
                # e.g. hpe hpestoreoncevsa hpestoreoncevsa-3187 3.18.7
                # After passthrough this exception,
                # actually the 22 port of this VM is open.
                log.error(
                    f"provisioning failed for an internal error, try to run case. "
                    f"Exception: {error_message}"
                )
            else:
                plugin_manager.hook.azure_deploy_failed(error_message=error_message)
                raise LisaException(error_message)

    def _parse_detail_errors(self, error: Any) -> List[str]:
        # original message may be a summary, get lowest level details.
        if hasattr(error, "details") and error.details:
            errors: List[str] = []
            for detail in error.details:
                errors.extend(self._parse_detail_errors(detail))
        else:
            try:
                # it returns serialized json string in message sometime
                parsed_error = json.loads(
                    error.message, object_hook=lambda x: SimpleNamespace(**x)
                )
                errors = self._parse_detail_errors(parsed_error.error)
            except Exception:
                # load failed, it should be a real error message string
                errors = [f"{error.code}: {error.message}"]
        return errors

    # the VM may not be queried after deployed. use retry to mitigate it.
    @retry(exceptions=LisaException, tries=150, delay=2)  # type: ignore
    def _load_vms(
        self, environment: Environment, log: Logger
    ) -> Dict[str, VirtualMachine]:
        compute_client = get_compute_client(self)
        environment_context = get_environment_context(environment=environment)

        log.debug(
            f"listing vm in resource group "
            f"'{environment_context.resource_group_name}'"
        )
        vms_map: Dict[str, VirtualMachine] = {}
        vms = compute_client.virtual_machines.list(
            environment_context.resource_group_name
        )
        for vm in vms:
            vms_map[vm.name] = vm
            log.debug(f"  found vm {vm.name}")
        if not vms_map:
            raise LisaException(
                f"deployment succeeded, but VM not found in 5 minutes "
                f"from '{environment_context.resource_group_name}'"
            )
        return vms_map

    @retry(exceptions=LisaException, tries=150, delay=2)  # type: ignore
    def _load_nics(
        self, environment: Environment, log: Logger
    ) -> Dict[str, NetworkInterface]:
        network_client = get_network_client(self)
        environment_context = get_environment_context(environment=environment)

        log.debug(
            f"listing network interfaces in resource group "
            f"'{environment_context.resource_group_name}'"
        )
        # load nics
        nics_map: Dict[str, NetworkInterface] = {}
        network_interfaces = network_client.network_interfaces.list(
            environment_context.resource_group_name
        )
        for nic in network_interfaces:
            # nic name is like node-0-nic-2, get vm name part for later pick
            # only find primary nic, which is ended by -nic-0
            node_name_from_nic = RESOURCE_ID_NIC_PATTERN.findall(nic.name)
            if node_name_from_nic:
                name = node_name_from_nic[0]
                nics_map[name] = nic
                log.debug(f"  found nic '{name}', and saved for next step.")
            else:
                log.debug(
                    f"  found nic '{nic.name}', but dropped, "
                    "because it's not primary nic."
                )
        if not nics_map:
            raise LisaException(
                f"deployment succeeded, but network interfaces not found in 5 minutes "
                f"from '{environment_context.resource_group_name}'"
            )
        return nics_map

    @retry(exceptions=LisaException, tries=150, delay=2)  # type: ignore
    def _load_public_ips(
        self, environment: Environment, log: Logger
    ) -> Dict[str, PublicIPAddress]:
        network_client = get_network_client(self)
        environment_context = get_environment_context(environment=environment)

        log.debug(
            f"listing public ips in resource group "
            f"'{environment_context.resource_group_name}'"
        )
        # get public IP
        public_ip_addresses = network_client.public_ip_addresses.list(
            environment_context.resource_group_name
        )
        public_ips_map: Dict[str, PublicIPAddress] = {}
        for ip_address in public_ip_addresses:
            # nic name is like node-0-nic-2, get vm name part for later pick
            # only find primary nic, which is ended by -nic-0
            node_name_from_public_ip = RESOURCE_ID_PUBLIC_IP_PATTERN.findall(
                ip_address.name
            )
            if node_name_from_public_ip:
                name = node_name_from_public_ip[0]
                public_ips_map[name] = ip_address
                log.debug(
                    f"  found public IP '{ip_address.name}', and saved for next step."
                )
            else:
                log.debug(
                    f"  found public IP '{ip_address.name}', but dropped "
                    "because it's not primary nic."
                )
        if not public_ips_map:
            raise LisaException(
                f"deployment succeeded, but public ips not found in 5 minutes "
                f"from '{environment_context.resource_group_name}'"
            )
        return public_ips_map

    def _initialize_nodes(self, environment: Environment, log: Logger) -> None:
        node_context_map: Dict[str, Node] = {}
        for node in environment.nodes.list():
            node_context = get_node_context(node)
            node_context_map[node_context.vm_name] = node

        vms_map: Dict[str, VirtualMachine] = self._load_vms(environment, log)
        nics_map: Dict[str, NetworkInterface] = self._load_nics(environment, log)
        public_ips_map: Dict[str, PublicIPAddress] = self._load_public_ips(
            environment, log
        )

        for vm_name, node in node_context_map.items():
            node_context = get_node_context(node)
            vm = vms_map.get(vm_name, None)
            if not vm:
                raise LisaException(
                    f"cannot find vm: '{vm_name}', make sure deployment is correct."
                )
            nic = nics_map[vm_name]
            public_ip = public_ips_map[vm_name]
            assert (
                public_ip.ip_address
            ), f"public IP address cannot be empty, public_ip object: {public_ip}"

            address = nic.ip_configurations[0].private_ip_address
            if not node.name:
                node.name = vm_name

            assert isinstance(node, RemoteNode)
            node.set_connection_info(
                address=address,
                port=22,
                public_address=public_ip.ip_address,
                public_port=22,
                username=node_context.username,
                password=node_context.password,
                private_key_file=node_context.private_key_file,
            )

    def _resource_sku_to_capability(  # noqa: C901
        self, location: str, resource_sku: ResourceSku
    ) -> schema.NodeSpace:
        # fill in default values, in case no capability meet.
        node_space = schema.NodeSpace(
            node_count=1,
            core_count=0,
            memory_mb=0,
            nic_count=0,
            gpu_count=0,
        )
        node_space.name = f"{location}_{resource_sku.name}"
        node_space.features = search_space.SetSpace[schema.FeatureSettings](
            is_allow_set=True
        )
        node_space.disk = features.AzureDiskOptionSettings()
        node_space.disk.disk_type = search_space.SetSpace[schema.DiskType](
            is_allow_set=True, items=[]
        )
        node_space.disk.data_disk_iops = search_space.IntRange(min=0)
        node_space.disk.data_disk_size = search_space.IntRange(min=0)
        for sku_capability in resource_sku.capabilities:
            if resource_sku.family in ["standardLSv2Family"]:
                node_space.features.add(
                    schema.FeatureSettings.create(features.Nvme.name())
                )
            name = sku_capability.name
            if name == "vCPUs":
                node_space.core_count = int(sku_capability.value)
            elif name == "MaxDataDiskCount":
                node_space.disk.data_disk_count = search_space.IntRange(
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
                # update features list if gpu feature is supported
                node_space.features.add(
                    schema.FeatureSettings.create(features.Gpu.name())
                )
            elif name == "AcceleratedNetworkingEnabled":
                # refer https://docs.microsoft.com/en-us/azure/virtual-machines/dcv2-series#configuration # noqa: E501
                # standardDCSv2Family doesn't support `Accelerated Networking`
                # but API return `True`, fix this issue temporarily
                # will revert it till bug fixed.
                if "standardDCSv2Family" == resource_sku.family:
                    continue
                if eval(sku_capability.value) is True:
                    # update features list if sriov feature is supported
                    node_space.features.add(
                        schema.FeatureSettings.create(features.Sriov.name())
                    )
            elif name == "PremiumIO":
                if eval(sku_capability.value) is True:
                    node_space.disk.disk_type.add(schema.DiskType.PremiumSSDLRS)
            elif name == "EphemeralOSDiskSupported":
                if eval(sku_capability.value) is True:
                    node_space.disk.disk_type.add(schema.DiskType.Ephemeral)

        # set a min value for nic_count work around for an azure python sdk bug
        # nic_count is 0 when get capability for some sizes e.g. Standard_D8a_v3
        if node_space.nic_count == 0:
            node_space.nic_count = 1

        # all nodes support following features
        node_space.features.update(
            [
                schema.FeatureSettings.create(features.StartStop.name()),
                schema.FeatureSettings.create(features.SerialConsole.name()),
            ]
        )
        node_space.disk.disk_type.add(schema.DiskType.StandardHDDLRS)
        node_space.disk.disk_type.add(schema.DiskType.StandardSSDLRS)

        return node_space

    def _get_eligible_vm_sizes(
        self, location: str, log: Logger
    ) -> List[AzureCapability]:
        # load eligible vm sizes
        # 1. vm size supported in current location
        # 2. vm size match predefined pattern

        location_capabilities: List[AzureCapability] = []

        if location not in self._eligible_capabilities:
            location_info: AzureLocation = self._get_location_info(location, log)
            # loop all fall back levels
            for fallback_pattern in VM_SIZE_FALLBACK_PATTERNS:
                level_capabilities: List[AzureCapability] = []

                # loop all capabilities
                for capability in location_info.capabilities:
                    if fallback_pattern.match(capability.vm_size):
                        level_capabilities.append(capability)

                # sort by rough cost
                level_capabilities.sort(key=lambda x: (x.estimated_cost))
                log.debug(
                    f"{location}, pattern '{fallback_pattern.pattern}'"
                    f" {len(level_capabilities)} candidates: "
                    f"{[x.vm_size for x in level_capabilities]}"
                )
                location_capabilities.extend(level_capabilities)
            self._eligible_capabilities[location] = location_capabilities
        return self._eligible_capabilities[location]

    def _parse_marketplace_image(
        self, location: str, marketplace: AzureVmMarketplaceSchema
    ) -> AzureVmMarketplaceSchema:
        compute_client = get_compute_client(self)
        new_marketplace = copy.copy(marketplace)
        if marketplace.version.lower() == "latest":
            # latest doesn't work, it needs a specified version.
            versioned_images = compute_client.virtual_machine_images.list(
                location=location,
                publisher_name=marketplace.publisher,
                offer=marketplace.offer,
                skus=marketplace.sku,
            )
            # any one should be the same to get purchase plan
            new_marketplace.version = versioned_images[-1].name
        return new_marketplace

    def _process_marketplace_image_plan(
        self, location: str, marketplace: AzureVmMarketplaceSchema
    ) -> Optional[PurchasePlan]:
        """
        this method to fill plan, if a VM needs it. If don't fill it, the deployment
        will be failed.

        1. Get image_info to check if there is a plan.
        2. If there is a plan, it may need to check and accept terms.
        """
        image_info = self._get_image_info(location, marketplace)
        plan: Optional[AzureVmPurchasePlanSchema] = None
        if image_info.plan:
            # if there is a plan, it may need to accept term.
            marketplace_client = get_marketplace_ordering_client(self)
            term: Optional[AgreementTerms] = None
            try:
                term = marketplace_client.marketplace_agreements.get(
                    offer_type="virtualmachine",
                    publisher_id=marketplace.publisher,
                    offer_id=marketplace.offer,
                    plan_id=image_info.plan.name,
                )
            except Exception as identifier:
                raise LisaException(
                    f"error on getting marketplace agreement: {identifier}"
                )

            assert term
            if term.accepted is False:
                term.accepted = True
                marketplace_client.marketplace_agreements.create(
                    offer_type="virtualmachine",
                    publisher_id=marketplace.publisher,
                    offer_id=marketplace.offer,
                    plan_id=image_info.plan.name,
                    parameters=term,
                )
            plan = AzureVmPurchasePlanSchema(
                name=image_info.plan.name,
                product=image_info.plan.product,
                publisher=image_info.plan.publisher,
            )
        return plan

    def _generate_mockup_capability(
        self, vm_size: str, location: str
    ) -> AzureCapability:

        # some vm size cannot be queried from API, so use default capability to
        # run with best guess on capability.
        node_space = schema.NodeSpace(
            node_count=1,
            core_count=search_space.IntRange(min=1),
            memory_mb=search_space.IntRange(min=0),
            nic_count=search_space.IntRange(min=1),
            gpu_count=search_space.IntRange(min=0),
        )
        node_space.disk = features.AzureDiskOptionSettings()
        node_space.disk.data_disk_count = search_space.IntRange(min=0)
        node_space.disk.disk_type = search_space.SetSpace[schema.DiskType](
            is_allow_set=True, items=[]
        )
        node_space.disk.disk_type.add(schema.DiskType.PremiumSSDLRS)
        node_space.disk.disk_type.add(schema.DiskType.Ephemeral)
        node_space.disk.disk_type.add(schema.DiskType.StandardHDDLRS)
        node_space.disk.disk_type.add(schema.DiskType.StandardSSDLRS)

        azure_capability = AzureCapability(
            location=location,
            vm_size=vm_size,
            estimated_cost=4,
            capability=node_space,
            resource_sku={},
        )

        node_space.name = f"{location}_{vm_size}"
        node_space.features = search_space.SetSpace[schema.FeatureSettings](
            is_allow_set=True
        )

        # all nodes support following features
        node_space.features.update(
            [
                schema.FeatureSettings.create(features.Nvme.name()),
                schema.FeatureSettings.create(features.Gpu.name()),
                schema.FeatureSettings.create(features.Sriov.name()),
                schema.FeatureSettings.create(features.StartStop.name()),
                schema.FeatureSettings.create(features.SerialConsole.name()),
            ]
        )

        return azure_capability

    def _generate_min_capability(
        self,
        requirement: schema.NodeSpace,
        azure_capability: AzureCapability,
        location: str,
    ) -> schema.NodeSpace:
        min_cap: schema.NodeSpace = requirement.generate_min_capability(
            azure_capability.capability
        )
        # Ppply azure specified values. They will pass into arm template
        azure_node_runbook = min_cap.get_extended_runbook(AzureNodeSchema, AZURE)
        if azure_node_runbook.location:
            assert azure_node_runbook.location == location, (
                f"predefined location [{azure_node_runbook.location}] "
                f"must be same as "
                f"cap location [{location}]"
            )
        # the location may not be set
        azure_node_runbook.location = location
        azure_node_runbook.vm_size = azure_capability.vm_size
        assert isinstance(min_cap.nic_count, int), f"actual: {min_cap.nic_count}"
        azure_node_runbook.nic_count = min_cap.nic_count

        assert min_cap.disk, "disk must exists"
        assert isinstance(
            min_cap.disk.data_disk_count, int
        ), f"actual: {min_cap.disk.data_disk_count}"
        azure_node_runbook.data_disk_count = min_cap.disk.data_disk_count
        assert isinstance(
            min_cap.disk.data_disk_caching_type, str
        ), f"actual: {min_cap.disk.data_disk_caching_type}"
        azure_node_runbook.data_disk_caching_type = min_cap.disk.data_disk_caching_type

        return min_cap

    def _get_deployable_vhd_path(
        self, vhd_path: str, location: str, log: Logger
    ) -> str:
        """
        The sas url is not able to create a vm directly, so this method check if
        the vhd_path is a sas url. If so, copy it to a location in current
        subscription, so it can be deployed.
        """
        matches = SAS_URL_PATTERN.match(vhd_path)
        if not matches:
            return vhd_path
        log.debug("found the vhd is a sas url, it needs to be copied...")

        original_vhd_path = vhd_path
        storage_name = get_storage_account_name(
            subscription_id=self.subscription_id, location=location, type="t"
        )
        container_client = get_or_create_storage_container(
            storage_name, SAS_COPIED_CONTAINER_NAME, self.credential
        )

        normalized_vhd_name = constants.NORMALIZE_PATTERN.sub("_", vhd_path)
        # use the expire date to generate the path. It's easy to identify when
        # the cache can be removed.
        vhd_path = (
            f"{matches['year']}{matches['month']}{matches['day']}/"
            f"{normalized_vhd_name}.vhd"
        )
        full_vhd_path = f"{container_client.url}/{vhd_path}"

        # lock here to prevent a vhd is copied in multi-thread
        global _global_sas_vhd_copy_lock
        with _global_sas_vhd_copy_lock:
            blobs = container_client.list_blobs(name_starts_with=vhd_path)
            for blob in blobs:
                if blob:
                    # if it exists, return the link, not to copy again.
                    log.debug("the sas url is copied already, use it directly.")
                    return full_vhd_path

            blob_client = container_client.get_blob_client(vhd_path)
            blob_client.start_copy_from_url(
                original_vhd_path, metadata=None, incremental_copy=False
            )

            wait_copy_blob(blob_client, vhd_path, log)

        return full_vhd_path

    def _generate_data_disks(
        self,
        node: Node,
        azure_node_runbook: AzureNodeSchema,
    ) -> List[DataDiskSchema]:
        data_disks: List[DataDiskSchema] = []
        assert node.capability.disk
        if azure_node_runbook.marketplace:
            marketplace = self._get_image_info(
                azure_node_runbook.location, azure_node_runbook.marketplace
            )
            # some images has data disks by default
            # e.g. microsoft-ads linux-data-science-vm linuxdsvm 21.05.27
            # we have to inject below part when dataDisks section added in
            #  arm template,
            # otherwise will see below exception:
            # deployment failed: InvalidParameter: StorageProfile.dataDisks.lun
            #  does not have required value(s) for image specified in
            #  storage profile.
            for default_data_disk in marketplace.data_disk_images:
                data_disks.append(
                    DataDiskSchema(
                        node.capability.disk.data_disk_caching_type,
                        default_data_disk.additional_properties["sizeInGb"],
                        azure_node_runbook.disk_type,
                        DataDiskCreateOption.DATADISK_CREATE_OPTION_TYPE_FROM_IMAGE,
                    )
                )
        assert isinstance(
            node.capability.disk.data_disk_count, int
        ), f"actual: {type(node.capability.disk.data_disk_count)}"
        for _ in range(node.capability.disk.data_disk_count):
            assert isinstance(node.capability.disk.data_disk_size, int)
            data_disks.append(
                DataDiskSchema(
                    node.capability.disk.data_disk_caching_type,
                    node.capability.disk.data_disk_size,
                    azure_node_runbook.disk_type,
                    DataDiskCreateOption.DATADISK_CREATE_OPTION_TYPE_EMPTY,
                )
            )
        return data_disks

    def _get_image_info(
        self, location: str, marketplace: Optional[AzureVmMarketplaceSchema]
    ) -> VirtualMachineImage:
        compute_client = get_compute_client(self)
        assert isinstance(marketplace, AzureVmMarketplaceSchema)
        image_info = compute_client.virtual_machine_images.get(
            location=location,
            publisher_name=marketplace.publisher,
            offer=marketplace.offer,
            skus=marketplace.sku,
            version=marketplace.version,
        )
        return image_info


def _convert_to_azure_node_space(node_space: schema.NodeSpace) -> None:
    if node_space:
        if node_space.features:
            new_settings = search_space.SetSpace[schema.FeatureSettings](
                is_allow_set=True
            )
            for current_settings in node_space.features:
                # reload to type specified settings
                settings_type = feature.get_feature_settings_type_by_name(
                    current_settings.type, AzurePlatform.supported_features()
                )
                new_settings.add(schema.load_by_type(settings_type, current_settings))
            node_space.features = new_settings
        if node_space.disk:
            node_space.disk = schema.load_by_type(
                features.AzureDiskOptionSettings, node_space.disk
            )
