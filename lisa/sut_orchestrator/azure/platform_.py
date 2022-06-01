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
from functools import lru_cache, partial
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple, Type, Union, cast

from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute.models import (  # type: ignore
    PurchasePlan,
    ResourceSku,
    RunCommandInput,
    RunCommandInputParameter,
    VirtualMachine,
    VirtualMachineImage,
)
from azure.mgmt.marketplaceordering.models import AgreementTerms  # type: ignore
from azure.mgmt.network.models import NetworkInterface  # type: ignore
from azure.mgmt.resource import SubscriptionClient  # type: ignore
from azure.mgmt.resource.resources.models import (  # type: ignore
    Deployment,
    DeploymentMode,
    DeploymentProperties,
)
from azure.storage.blob import BlobClient
from dataclasses_json import dataclass_json
from marshmallow import fields, validate
from retry import retry

import lisa.features as base_features
from lisa import feature, schema, search_space
from lisa.environment import Environment
from lisa.features import NvmeSettings
from lisa.node import Node, RemoteNode, local
from lisa.platform_ import Platform
from lisa.secret import PATTERN_GUID, add_secret
from lisa.tools import Dmesg, Hostname, Modinfo, Whoami
from lisa.util import (
    LisaException,
    constants,
    dump_file,
    field_metadata,
    generate_random_chars,
    get_matched_str,
    get_public_key_data,
    plugin_manager,
    set_filtered_fields,
    strip_strs,
    truncate_keep_prefix,
)
from lisa.util.logger import Logger
from lisa.util.parallel import run_in_parallel
from lisa.util.shell import wait_tcp_port_ready

from .. import AZURE
from . import features
from .common import (
    AZURE_SHARED_RG_NAME,
    AzureArmParameter,
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
    global_credential_access_lock,
    wait_copy_blob,
    wait_operation,
)
from .tools import VmGeneration, Waagent

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
RESOURCE_ID_NIC_PATTERN = re.compile(r"(.+)-nic-0")
RESOURCE_ID_PUBLIC_IP_PATTERN = re.compile(r"(.+)-public-ip")

# Ubuntu 18.04:
# [    0.000000] Hyper-V Host Build:18362-10.0-3-0.3198
# FreeBSD 11.3:
# Hyper-V Version: 10.0.18362 [SP3]
# bitnami dreamfactory 1.7 1.7.8
# [    1.283478] hv_vmbus: Hyper-V Host Build:18362-10.0-3-0.3256; Vmbus version:3.0
# Ubuntu arm64 version:
# [    0.075800] Hyper-V: Host Build 10.0.22477.1022-1-0
HOST_VERSION_PATTERN = re.compile(
    r"Hyper-V:? (?:Host Build|Version)[\s|:][ ]?([^\r\n;]*)", re.M
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
KEY_WALA_DISTRO_VERSION = "wala_distro"
ATTRIBUTE_FEATURES = "features"

# https://abcdefg.blob.core.windows.net/abcdefg?sv=2020-08-04&
# st=2022-01-19T06%3A25%3A16Z&se=2022-01-19T06%3A25%3A00Z&sr=b&
# sp=r&sig=DdBu3FTHQr1%2BzIY%2FdS054IlsDQ1RdfjfL3FgRgexgeo%3D
# https://abcdefg.blob.storage.azure.net/1b33rftmpdhs/abcdefg?
# sv=2018-03-28&sr=b&si=11111111-feff-4312-bba2-3ca6eabf9b24&
# sig=xdZaRwJBwu3P2pYbQ3uEmymlovFwHrtQNVWDHyK48sg%3D
SAS_URL_PATTERN = re.compile(
    r"^https://.*?(?:\.blob\.core\.windows\.net|"
    r"blob\.storage\.azure\.net)/.*?\?sv=[^&]+?(?:&st=[^&]+)?"
    r"(?:&se=(?P<year>[\d]{4})-(?P<month>[\d]{2})-(?P<day>[\d]{2}).*?)|.*?&sig=.*?$"
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
        metadata=field_metadata(
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
class AzurePlatformSchema:
    service_principal_tenant_id: str = field(
        default="",
        metadata=field_metadata(
            validate=validate.Regexp(constants.GUID_REGEXP),
        ),
    )
    service_principal_client_id: str = field(
        default="",
        metadata=field_metadata(
            validate=validate.Regexp(constants.GUID_REGEXP),
        ),
    )
    service_principal_key: str = field(default="")
    subscription_id: str = field(
        default="",
        metadata=field_metadata(
            validate=validate.Regexp(constants.GUID_REGEXP),
        ),
    )

    shared_resource_group_name: str = AZURE_SHARED_RG_NAME
    resource_group_name: str = field(default="")
    availability_set_tags: Optional[Dict[str, str]] = field(default=None)
    availability_set_properties: Optional[Dict[str, Any]] = field(default=None)
    vm_tags: Optional[Dict[str, Any]] = field(default=None)
    locations: Optional[Union[str, List[str]]] = field(default=None)

    # Provisioning error causes by waagent is not ready or other reasons. In
    # smoke test, it can verify some points also. Other tests should use the
    # default False to raise errors to prevent unexpected behavior.
    ignore_provisioning_error: bool = False

    log_level: str = field(
        default=logging.getLevelName(logging.WARN),
        metadata=field_metadata(
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
        strip_strs(
            self,
            [
                "service_principal_tenant_id",
                "service_principal_client_id",
                "service_principal_key",
                "subscription_id",
                "shared_resource_group_name",
                "resource_group_name",
                "locations",
                "log_level",
            ],
        )

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
    _diagnostic_storage_container_pattern = re.compile(
        r"(https:\/\/)(?P<storage_name>.*)([.].*){4}\/" r"(?P<container_name>.*)\/",
        re.M,
    )
    _arm_template: Any = None

    _credentials: Dict[str, DefaultAzureCredential] = {}
    _locations_data_cache: Dict[str, AzureLocation] = {}
    _eligible_capabilities: Dict[str, List[AzureCapability]] = {}

    def __init__(self, runbook: schema.Platform) -> None:
        super().__init__(runbook=runbook)

        # for type detection
        self.credential: DefaultAzureCredential

        # It has to be defined after the class definition is loaded. So it
        # cannot be a class level variable.
        self._environment_information_hooks = {
            KEY_HOST_VERSION: self._get_host_version,
            KEY_KERNEL_VERSION: self._get_kernel_version,
            KEY_WALA_VERSION: self._get_wala_version,
            KEY_WALA_DISTRO_VERSION: self._get_wala_distro_version,
        }

    @classmethod
    def type_name(cls) -> str:
        return AZURE

    @classmethod
    def supported_features(cls) -> List[Type[feature.Feature]]:
        return [
            features.Disk,
            features.Gpu,
            base_features.Nvme,
            features.SerialConsole,
            features.NetworkInterface,
            features.Resize,
            features.StartStop,
            features.Infiniband,
            features.Hibernation,
            features.SecurityProfile,
            base_features.ACC,
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
                        # if any one has different location, raise an exception.
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
                        # If max capability is set, use the max capability,
                        # instead of the real capability. It needs to be in the
                        # loop, to find supported locations.
                        if node_runbook.maximize_capability:
                            matched_cap = self._generate_max_capability(
                                node_runbook.vm_size, location_name
                            )

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
                    mock_up_capability = self._generate_max_capability(
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
                location_caps = self.get_eligible_vm_sizes(location_name, log)
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

            for req in nodes_requirement:
                node_runbook = req.get_extended_runbook(AzureNodeSchema, AZURE)
                if node_runbook.location and node_runbook.marketplace:
                    # resolve Latest to specified version
                    node_runbook.marketplace = self._parse_marketplace_image(
                        node_runbook.location, node_runbook.marketplace
                    )
        return is_success

    def _deploy_environment(self, environment: Environment, log: Logger) -> None:
        assert self._rm_client
        assert self._azure_runbook

        environment_context = get_environment_context(environment=environment)
        if self._azure_runbook.resource_group_name:
            resource_group_name = self._azure_runbook.resource_group_name
        else:
            normalized_name = constants.NORMALIZE_PATTERN.sub("-", constants.RUN_NAME)
            # Take last chars to make sure the length is to exceed max 90 chars
            # allowed in resource group name.
            resource_group_name = truncate_keep_prefix(
                f"{normalized_name}-e{environment.id}", 80
            )
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
                    check_or_create_resource_group(
                        self.credential,
                        subscription_id=self.subscription_id,
                        resource_group_name=resource_group_name,
                        location=RESOURCE_GROUP_LOCATION,
                        log=log,
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
                self.initialize_environment(environment, log)
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
            az_rg_exists = self._rm_client.resource_groups.check_existence(
                resource_group_name
            )
            if not az_rg_exists:
                return
            log.info(
                f"deleting resource group: {resource_group_name}, "
                f"wait: {self._azure_runbook.wait_delete}"
            )
            try:
                self._delete_boot_diagnostic_container(resource_group_name, log)
            except Exception as identifier:
                log.debug(
                    f"exception on deleting boot diagnostic container: {identifier}"
                )
            delete_operation: Any = None
            try:
                delete_operation = self._rm_client.resource_groups.begin_delete(
                    resource_group_name
                )
            except Exception as identifier:
                log.debug(f"exception on delete resource group: {identifier}")
            if delete_operation and self._azure_runbook.wait_delete:
                wait_operation(
                    delete_operation, failure_identity="delete resource group"
                )
            else:
                log.debug("not wait deleting")

    def _delete_boot_diagnostic_container(
        self, resource_group_name: str, log: Logger
    ) -> None:
        compute_client = get_compute_client(self)
        vms = compute_client.virtual_machines.list(resource_group_name)
        for vm in vms:
            diagnostic_data = (
                compute_client.virtual_machines.retrieve_boot_diagnostics_data(
                    resource_group_name=resource_group_name, vm_name=vm.name
                )
            )
            if not diagnostic_data:
                continue

            # A sample url,
            # https://storageaccountname.blob.core.windows.net:443/
            # bootdiagnostics-node0-30779088-9b10-4074-8c27-98b91f1d8b70/
            # node-0.30779088-9b10-4074-8c27-98b91f1d8b70.serialconsole.log
            # ?sv=2018-03-28&sr=b&sig=mJEsvk9WunbKHfBs1lo1jcIBe4owq1brP8Kw3qXTQJA%3d&
            # se=2021-09-14T08%3a55%3a38Z&sp=r
            blob_uri = diagnostic_data.console_screenshot_blob_uri
            if blob_uri:
                matched = self._diagnostic_storage_container_pattern.match(blob_uri)
                assert matched
                # => storageaccountname
                storage_name = matched.group("storage_name")
                # => bootdiagnostics-node0-30779088-9b10-4074-8c27-98b91f1d8b70
                container_name = matched.group("container_name")
                container_client = get_or_create_storage_container(
                    credential=self.credential,
                    subscription_id=self.subscription_id,
                    account_name=storage_name,
                    container_name=container_name,
                    resource_group_name=self._azure_runbook.shared_resource_group_name,
                )
                log.debug(
                    f"deleting boot diagnostic container: {container_name}"
                    f" under storage account {storage_name} of vm {vm.name}"
                )
                try:
                    container_client.delete_container()
                except Exception as identifier:
                    log.debug(
                        f"exception on deleting boot diagnostic container:"
                        f" {identifier}"
                    )

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
                node.log.debug("detecting wala version from waagent...")
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

    def _get_wala_distro_version(self, node: Node) -> str:
        result = "Unknown"
        try:
            if node.is_connected and node.is_posix:
                waagent = node.tools[Waagent]
                result = waagent.get_distro_version()
        except Exception as identifier:
            # it happens on some error vms. Those error should be caught earlier in
            # test cases not here. So ignore any error here to collect information only.
            node.log.debug(f"error on get waagent distro version: {identifier}")

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
                        if value:
                            result[key] = value
        if azure_runbook.availability_set_tags:
            for key, value in azure_runbook.availability_set_tags.items():
                if value:
                    result[key] = value
        if azure_runbook.vm_tags:
            for key, value in azure_runbook.vm_tags.items():
                if value:
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

            for key, method in self._environment_information_hooks.items():
                node.log.debug(f"detecting {key} ...")
                try:
                    value = method(node)
                    if value:
                        information[key] = value
                except Exception as identifier:
                    node.log.exception(f"error on get {key}.", exc_info=identifier)

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

        self.subscription_id = azure_runbook.subscription_id
        self._initialize_credential()

        check_or_create_resource_group(
            self.credential,
            self.subscription_id,
            azure_runbook.shared_resource_group_name,
            RESOURCE_GROUP_LOCATION,
            self._log,
        )

        self._rm_client = get_resource_management_client(
            self.credential, self.subscription_id
        )

    def _initialize_credential(self) -> None:
        azure_runbook = self._azure_runbook

        credential_key = (
            f"{azure_runbook.service_principal_tenant_id}_"
            f"{azure_runbook.service_principal_client_id}"
        )
        credential = self._credentials.get(credential_key, None)
        if not credential:
            # set azure log to warn level only
            logging.getLogger("azure").setLevel(azure_runbook.log_level)

            if azure_runbook.service_principal_tenant_id:
                os.environ[
                    "AZURE_TENANT_ID"
                ] = azure_runbook.service_principal_tenant_id
            if azure_runbook.service_principal_client_id:
                os.environ[
                    "AZURE_CLIENT_ID"
                ] = azure_runbook.service_principal_client_id
            if azure_runbook.service_principal_key:
                os.environ["AZURE_CLIENT_SECRET"] = azure_runbook.service_principal_key
            credential = DefaultAzureCredential()

            with SubscriptionClient(credential) as self._sub_client:
                # suppress warning message by search for different credential types
                azure_identity_logger = logging.getLogger("azure.identity")
                azure_identity_logger.setLevel(logging.ERROR)
                with global_credential_access_lock:
                    subscription = self._sub_client.subscriptions.get(
                        self.subscription_id
                    )
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

            self._credentials[credential_key] = credential

        self.credential = credential

    def _load_template(self) -> Any:
        if self._arm_template is None:
            template_file_path = Path(__file__).parent / "arm_template.json"
            with open(template_file_path, "r") as f:
                self._arm_template = json.load(f)
        return self._arm_template

    @retry(tries=10, delay=1, jitter=(0.5, 1))
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
        key = self._get_location_key(location)
        location_data = self._locations_data_cache.get(key, None)
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
                    f"{key}: cache used: {location_data.updated_time}, "
                    f"sku count: {len(location_data.capabilities)}"
                )
            else:
                log.debug(
                    f"{key}: cache timeout: {location_data.updated_time},"
                    f"sku count: {len(location_data.capabilities)}"
                )
        else:
            log.debug(f"{key}: no cache found")
        if should_refresh:
            compute_client = get_compute_client(self)

            log.debug(f"{key}: querying")
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
            log.debug(f"{location}: saving to disk")
            with open(cached_file_name, "w") as f:
                json.dump(location_data.to_dict(), f)  # type: ignore
            log.debug(f"{key}: new data, " f"sku: {len(location_data.capabilities)}")

        assert location_data
        self._locations_data_cache[key] = location_data
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
            "vm_tags",
        ]
        set_filtered_fields(self._azure_runbook, arm_parameters, copied_fields)

        is_windows: bool = False
        arm_parameters.admin_username = self.runbook.admin_username
        if self.runbook.admin_private_key_file:
            arm_parameters.admin_key_data = get_public_key_data(
                self.runbook.admin_private_key_file
            )
        else:
            arm_parameters.admin_password = self.runbook.admin_password

        environment_context = get_environment_context(environment=environment)
        arm_parameters.vm_tags["RG"] = environment_context.resource_group_name

        # get local lisa environment
        arm_parameters.vm_tags["lisa_username"] = local().tools[Whoami].get_username()
        arm_parameters.vm_tags["lisa_hostname"] = local().tools[Hostname].get_hostname()

        nodes_parameters: List[AzureNodeSchema] = []
        features_settings: Dict[str, schema.FeatureSettings] = {}

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
                len(nodes_parameters), node_space, log, resource_group_name
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
            # ssh related information will be filled back once vm is created. If
            # it's Windows, fill in the password always. If it's Linux, the
            # private key has higher priority.
            node_context.username = arm_parameters.admin_username
            if azure_node_runbook.is_linux:
                node_context.password = arm_parameters.admin_password
            else:
                is_windows = True
                if not self.runbook.admin_password:
                    # password is required, if it doesn't present, generate one.
                    password = generate_random_chars()
                    add_secret(password)
                    self.runbook.admin_password = password

                node_context.password = self.runbook.admin_password
            node_context.private_key_file = self.runbook.admin_private_key_file

            # collect all features to handle special deployment logic. If one
            # node has this, it needs to run.
            if node.capability.features:
                for f in node.capability.features:
                    if f.type not in features_settings:
                        features_settings[f.type] = f

            log.info(f"vm setting: {azure_node_runbook}")

        if is_windows:
            # set password for windows any time.
            arm_parameters.admin_password = self.runbook.admin_password

        arm_parameters.nodes = nodes_parameters
        arm_parameters.storage_name = get_storage_account_name(
            self.subscription_id, arm_parameters.location
        )

        if (
            self._azure_runbook.availability_set_properties
            or self._azure_runbook.availability_set_tags
        ):
            arm_parameters.use_availability_sets = True

        # In Azure, each VM should have only one nic in one subnet. So calculate
        # the max nic count, and set to subnet count.
        arm_parameters.subnet_count = max(x.nic_count for x in arm_parameters.nodes)

        arm_parameters.shared_resource_group_name = (
            self._azure_runbook.shared_resource_group_name
        )

        # the arm template may be updated by the hooks, so make a copy to avoid
        # the original template is modified.
        template = deepcopy(self._load_template())
        plugin_manager.hook.azure_update_arm_template(
            template=template, environment=environment
        )

        # change deployment for each feature.
        for f in features_settings.values():
            feature_type = next(
                x for x in self.supported_features() if x.name() == f.type
            )
            feature_type.on_before_deployment(
                arm_parameters=arm_parameters,
                template=template,
                settings=f,
                environment=environment,
                log=log,
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
        name_prefix: str,
    ) -> AzureNodeSchema:
        azure_node_runbook = node_space.get_extended_runbook(
            AzureNodeSchema, type_name=AZURE
        )

        if not azure_node_runbook.name:
            # the max length of vm name is 64 chars. Below logic takes last 45
            # chars in resource group name and keep the leading 5 chars.
            # name_prefix can contain any of customized (existing) or
            # generated (starts with "lisa-") resource group name,
            # so, pass the first 5 chars as prefix to truncate_keep_prefix
            # to handle both cases
            node_name = f"{name_prefix}-n{index}"
            azure_node_runbook.name = truncate_keep_prefix(node_name, 50, node_name[:5])
        # It's used as computer name only. Windows doesn't support name more
        # than 15 chars
        azure_node_runbook.short_name = truncate_keep_prefix(
            azure_node_runbook.name, 15, azure_node_runbook.name[:5]
        )
        if not azure_node_runbook.vm_size:
            raise LisaException("vm_size is not detected before deploy")
        if not azure_node_runbook.location:
            raise LisaException("location is not detected before deploy")
        if azure_node_runbook.hyperv_generation not in [1, 2]:
            raise LisaException(
                "hyperv_generation need value 1 or 2, "
                f"but {azure_node_runbook.hyperv_generation}",
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

            image_info = self._get_image_info(
                azure_node_runbook.location, azure_node_runbook.marketplace
            )

            # HyperVGenerationTypes return "V1"/"V2", so we need to strip "V"
            if image_info.hyper_v_generation:
                azure_node_runbook.hyperv_generation = int(
                    image_info.hyper_v_generation.strip("V")
                )

            # retrieve the os type for arm template.
            if azure_node_runbook.is_linux is None:
                if image_info.os_disk_image.operating_system == "Windows":
                    azure_node_runbook.is_linux = False
                else:
                    azure_node_runbook.is_linux = True
            if not azure_node_runbook.purchase_plan and image_info.plan:
                # expand values for lru cache
                plan_name = image_info.plan.name
                plan_product = image_info.plan.product
                plan_publisher = image_info.plan.publisher
                # accept the default purchase plan automatically.
                azure_node_runbook.purchase_plan = self._process_marketplace_image_plan(
                    marketplace=azure_node_runbook.marketplace,
                    plan_name=plan_name,
                    plan_product=plan_product,
                    plan_publisher=plan_publisher,
                )

        if azure_node_runbook.is_linux is None:
            # fill it default value
            azure_node_runbook.is_linux = True

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

        assert node_space.network_interface
        assert isinstance(
            node_space.network_interface.nic_count, int
        ), f"actual: {node_space.network_interface.nic_count}"
        azure_node_runbook.nic_count = node_space.network_interface.nic_count
        assert isinstance(
            node_space.network_interface.data_path, schema.NetworkDataPath
        ), f"actual: {type(node_space.network_interface.data_path)}"
        if node_space.network_interface.data_path == schema.NetworkDataPath.Sriov:
            azure_node_runbook.enable_sriov = True

        return azure_node_runbook

    def _validate_template(
        self, deployment_parameters: Dict[str, Any], log: Logger
    ) -> None:
        log.debug("validating deployment")

        validate_operation: Any = None
        try:
            with global_credential_access_lock:
                validate_operation = self._rm_client.deployments.begin_validate(
                    **deployment_parameters
                )
            wait_operation(validate_operation, failure_identity="validation")
        except Exception as identifier:
            error_messages: List[str] = [str(identifier)]

            if isinstance(identifier, HttpResponseError) and identifier.error:
                # no validate_operation returned, the message may include
                # some errors, so check details
                error_messages = self._parse_detail_errors(identifier.error)

            raise LisaException("\n".join(error_messages))

    def _deploy(
        self, location: str, deployment_parameters: Dict[str, Any], log: Logger
    ) -> None:
        resource_group_name = deployment_parameters[AZURE_RG_NAME_KEY]
        storage_account_name = get_storage_account_name(self.subscription_id, location)
        check_or_create_storage_account(
            self.credential,
            self.subscription_id,
            storage_account_name,
            self._azure_runbook.shared_resource_group_name,
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
            wait_operation(deployment_operation, failure_identity="deploy")
        except HttpResponseError as identifier:
            # Some errors happens underlying, so there is no detail errors from API.
            # For example,
            # azure.core.exceptions.HttpResponseError:
            #    Operation returned an invalid status 'OK'
            assert identifier.error, f"HttpResponseError: {identifier}"

            error_message = "\n".join(self._parse_detail_errors(identifier.error))
            if (
                self._azure_runbook.ignore_provisioning_error
                and "OSProvisioningTimedOut: OS Provisioning for VM" in error_message
            ):
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
            elif self._azure_runbook.ignore_provisioning_error and get_matched_str(
                error_message, AZURE_INTERNAL_ERROR_PATTERN
            ):
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
    @retry(exceptions=LisaException, tries=150, delay=2)
    def _load_vms(
        self, environment: Environment, log: Logger
    ) -> Dict[str, VirtualMachine]:
        compute_client = get_compute_client(self, api_version="2020-06-01")
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

    # Use Exception, because there may be credential conflict error. Make it
    # retriable.
    @retry(exceptions=Exception, tries=150, delay=2)
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
            # nic name is like lisa-test-20220316-182126-985-e0-n0-nic-2, get vm
            # name part for later pick only find primary nic, which is ended by
            # -nic-0
            node_name_from_nic = RESOURCE_ID_NIC_PATTERN.findall(nic.name)
            if node_name_from_nic:
                name = node_name_from_nic[0]
                nics_map[name] = nic
                log.debug(f"  found nic '{nic.name}', and saved for next step.")
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

    @retry(exceptions=LisaException, tries=150, delay=2)
    def load_public_ips_from_resource_group(
        self, resource_group_name: str, log: Logger
    ) -> Dict[str, str]:
        network_client = get_network_client(self)
        log.debug(f"listing public ips in resource group '{resource_group_name}'")
        # get public IP
        public_ip_addresses = network_client.public_ip_addresses.list(
            resource_group_name
        )
        public_ips_map: Dict[str, str] = {}
        for ip_address in public_ip_addresses:
            # nic name is like node-0-nic-2, get vm name part for later pick
            # only find primary nic, which is ended by -nic-0
            node_name_from_public_ip = RESOURCE_ID_PUBLIC_IP_PATTERN.findall(
                ip_address.name
            )
            assert (
                ip_address
            ), f"public IP address cannot be empty, ip_address object: {ip_address}"
            if node_name_from_public_ip:
                name = node_name_from_public_ip[0]
                public_ips_map[name] = ip_address.ip_address
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
                f"from '{resource_group_name}'"
            )
        return public_ips_map

    def initialize_environment(self, environment: Environment, log: Logger) -> None:
        node_context_map: Dict[str, Node] = {}
        for node in environment.nodes.list():
            node_context = get_node_context(node)
            node_context_map[node_context.vm_name] = node

        vms_map: Dict[str, VirtualMachine] = self._load_vms(environment, log)
        nics_map: Dict[str, NetworkInterface] = self._load_nics(environment, log)
        environment_context = get_environment_context(environment=environment)
        public_ips_map: Dict[str, str] = self.load_public_ips_from_resource_group(
            environment_context.resource_group_name, log
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

            address = nic.ip_configurations[0].private_ip_address
            if not node.name:
                node.name = vm_name

            assert isinstance(node, RemoteNode)
            node.set_connection_info(
                address=address,
                port=22,
                public_address=public_ip,
                public_port=22,
                username=node_context.username,
                password=node_context.password,
                private_key_file=node_context.private_key_file,
            )

        # enable ssh for windows, if it's not Windows, or SSH reachable, it will
        # skip.
        run_in_parallel(
            [
                partial(self._enable_ssh_on_windows, node=x)
                for x in environment.nodes.list()
            ]
        )

    def _resource_sku_to_capability(  # noqa: C901
        self, location: str, resource_sku: ResourceSku
    ) -> schema.NodeSpace:
        # fill in default values, in case no capability meet.
        node_space = schema.NodeSpace(
            node_count=1,
            core_count=0,
            memory_mb=0,
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
        node_space.network_interface = schema.NetworkInterfaceOptionSettings()
        node_space.network_interface.data_path = search_space.SetSpace[
            schema.NetworkDataPath
        ](is_allow_set=True, items=[])
        vcpus = 0
        vcpus_available = 0
        for sku_capability in resource_sku.capabilities:
            name = sku_capability.name
            if name == "vCPUsAvailable":
                vcpus_available = int(sku_capability.value)
            elif name == "vCPUs":
                vcpus = int(sku_capability.value)
            elif name == "MaxDataDiskCount":
                node_space.disk.max_data_disk_count = int(sku_capability.value)
                node_space.disk.data_disk_count = search_space.IntRange(
                    max=node_space.disk.max_data_disk_count
                )
            elif name == "MemoryGB":
                node_space.memory_mb = int(float(sku_capability.value) * 1024)
            elif name == "MaxNetworkInterfaces":
                # set a min value for nic_count work around for an azure python sdk bug
                # nic_count is 0 when get capability for some sizes e.g. Standard_D8a_v3
                sku_nic_count = int(sku_capability.value)
                if sku_nic_count == 0:
                    sku_nic_count = 1
                node_space.network_interface.nic_count = search_space.IntRange(
                    min=1, max=sku_nic_count
                )
                node_space.network_interface.max_nic_count = sku_nic_count
            elif name == "GPUs":
                node_space.gpu_count = int(sku_capability.value)
                # update features list if gpu feature is supported
                node_space.features.add(
                    schema.FeatureSettings.create(features.Gpu.name())
                )
            elif name == "AcceleratedNetworkingEnabled":
                # refer https://docs.microsoft.com/en-us/azure/virtual-machines/dcv2-series#configuration # noqa: E501
                # https://docs.microsoft.com/en-us/azure/virtual-machines/ncv2-series
                # https://docs.microsoft.com/en-us/azure/virtual-machines/ncv3-series
                # https://docs.microsoft.com/en-us/azure/virtual-machines/nd-series
                # below VM size families don't support `Accelerated Networking`
                # but API return `True`, fix this issue temporarily
                # will revert it till bug fixed.
                if resource_sku.family in [
                    "standardDCSv2Family",
                    "standardNCSv2Family",
                    "standardNCSv3Family",
                    "standardNDSFamily",
                ]:
                    continue
                if eval(sku_capability.value) is True:
                    # update data path types if sriov feature is supported
                    node_space.network_interface.data_path.add(
                        schema.NetworkDataPath.Sriov
                    )
            elif name == "PremiumIO":
                if eval(sku_capability.value) is True:
                    node_space.disk.disk_type.add(schema.DiskType.PremiumSSDLRS)
            elif name == "EphemeralOSDiskSupported":
                if eval(sku_capability.value) is True:
                    node_space.disk.disk_type.add(schema.DiskType.Ephemeral)
            elif name == "RdmaEnabled":
                if eval(sku_capability.value) is True:
                    node_space.features.add(
                        schema.FeatureSettings.create(features.Infiniband.name())
                    )
            elif name == "HibernationSupported":
                if eval(sku_capability.value) is True:
                    node_space.features.add(
                        schema.FeatureSettings.create(features.Hibernation.name())
                    )
            elif name == "HyperVGenerations":
                if "V2" in str(sku_capability.value):
                    node_space.features.add(
                        schema.FeatureSettings.create(features.SecurityProfile.name())
                    )

        # Some vm sizes, like Standard_HC44rs, doesn't have vCPUsAvailable, so
        # use vcpus.
        if vcpus_available:
            node_space.core_count = vcpus_available
        else:
            node_space.core_count = vcpus

        # add acc feature if it's supported
        if resource_sku.family in ["standardDCSv2Family", "standardDCSv3Family"]:
            node_space.features.update(
                [
                    schema.FeatureSettings.create(base_features.ACC.name()),
                ]
            )

        if resource_sku.family in ["standardLSv2Family"]:
            # refer https://docs.microsoft.com/en-us/azure/virtual-machines/lsv2-series # noqa: E501
            # NVMe disk count = vCPU / 8
            nvme = NvmeSettings()
            assert isinstance(
                node_space.core_count, int
            ), f"actual: {node_space.core_count}"
            nvme.disk_count = int(node_space.core_count / 8)
            node_space.features.add(nvme)

        # for some new sizes, there is no MaxNetworkInterfaces capability
        # and we have to set a default value for max_nic_count
        if not node_space.network_interface.max_nic_count:
            node_space.network_interface.max_nic_count = 8

        # For Dp/Ep_v5 VM size, the `Accelerated Networking` is required. But the API
        # return `False`. Fix this issue temporarily and revert it till bug fixed
        if resource_sku.family in [
            "standardDPDSv5Family",
            "standardDPLDSv5Family",
            "standardDPLSv5Family",
            "standardDPSv5Family",
            "standardEPDSv5Family",
            "standardEPSv5Family",
        ]:
            node_space.network_interface.data_path.add(schema.NetworkDataPath.Sriov)

        # some vm size do not have resource disk present
        # https://docs.microsoft.com/en-us/azure/virtual-machines/azure-vms-no-temp-disk
        if resource_sku.family in [
            "standardDv4Family",
            "standardDSv4Family",
            "standardEv4Family",
            "standardESv4Family",
            "standardEASv4Family",
            "standardEASv5Family",
            "standardESv5Family",
            "standardEADSv5Family",
            "standardDASv5Family",
            "standardDSv5Family",
            "standardFSv2Family",
            "standardNCFamily",
            "standardESv3Family",
        ]:
            node_space.disk.has_resource_disk = False
        else:
            node_space.disk.has_resource_disk = True

        # all nodes support following features
        node_space.features.update(
            [
                schema.FeatureSettings.create(features.StartStop.name()),
                schema.FeatureSettings.create(features.SerialConsole.name()),
                schema.FeatureSettings.create(features.Resize.name()),
            ]
        )
        node_space.disk.disk_type.add(schema.DiskType.StandardHDDLRS)
        node_space.disk.disk_type.add(schema.DiskType.StandardSSDLRS)
        node_space.network_interface.data_path.add(schema.NetworkDataPath.Synthetic)

        return node_space

    def get_eligible_vm_sizes(
        self, location: str, log: Logger
    ) -> List[AzureCapability]:
        # load eligible vm sizes
        # 1. vm size supported in current location
        # 2. vm size match predefined pattern

        location_capabilities: List[AzureCapability] = []

        key = self._get_location_key(location)
        if key not in self._eligible_capabilities:
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
                    f"{key}, pattern '{fallback_pattern.pattern}'"
                    f" {len(level_capabilities)} candidates: "
                    f"{[x.vm_size for x in level_capabilities]}"
                )
                location_capabilities.extend(level_capabilities)
            self._eligible_capabilities[key] = location_capabilities
        return self._eligible_capabilities[key]

    def load_public_ip(self, node: Node, log: Logger) -> str:
        node_context = get_node_context(node)
        vm_name = node_context.vm_name
        resource_group_name = node_context.resource_group_name
        public_ips_map: Dict[str, str] = self.load_public_ips_from_resource_group(
            resource_group_name=resource_group_name, log=self._log
        )
        return public_ips_map[vm_name]

    @lru_cache(maxsize=10)  # noqa: B019
    def _parse_marketplace_image(
        self, location: str, marketplace: AzureVmMarketplaceSchema
    ) -> AzureVmMarketplaceSchema:
        new_marketplace = copy.copy(marketplace)
        # latest doesn't work, it needs a specified version.
        if marketplace.version.lower() == "latest":
            compute_client = get_compute_client(self)
            with global_credential_access_lock:
                versioned_images = compute_client.virtual_machine_images.list(
                    location=location,
                    publisher_name=marketplace.publisher,
                    offer=marketplace.offer,
                    skus=marketplace.sku,
                )
            # any one should be the same to get purchase plan
            new_marketplace.version = versioned_images[-1].name
        return new_marketplace

    @lru_cache(maxsize=10)  # noqa: B019
    def _process_marketplace_image_plan(
        self,
        marketplace: AzureVmMarketplaceSchema,
        plan_name: str,
        plan_product: str,
        plan_publisher: str,
    ) -> Optional[PurchasePlan]:
        """
        this method to fill plan, if a VM needs it. If don't fill it, the deployment
        will be failed.

        1. Get image_info to check if there is a plan.
        2. If there is a plan, it may need to check and accept terms.
        """
        plan: Optional[AzureVmPurchasePlanSchema] = None

        # if there is a plan, it may need to accept term.
        marketplace_client = get_marketplace_ordering_client(self)
        term: Optional[AgreementTerms] = None
        try:
            with global_credential_access_lock:
                term = marketplace_client.marketplace_agreements.get(
                    offer_type="virtualmachine",
                    publisher_id=marketplace.publisher,
                    offer_id=marketplace.offer,
                    plan_id=plan_name,
                )
        except Exception as identifier:
            raise LisaException(f"error on getting marketplace agreement: {identifier}")

        assert term
        if term.accepted is False:
            term.accepted = True
            marketplace_client.marketplace_agreements.create(
                offer_type="virtualmachine",
                publisher_id=marketplace.publisher,
                offer_id=marketplace.offer,
                plan_id=plan_name,
                parameters=term,
            )
        plan = AzureVmPurchasePlanSchema(
            name=plan_name,
            product=plan_product,
            publisher=plan_publisher,
        )

        return plan

    def _generate_max_capability(self, vm_size: str, location: str) -> AzureCapability:

        # some vm size cannot be queried from API, so use default capability to
        # run with best guess on capability.
        node_space = schema.NodeSpace(
            node_count=1,
            core_count=search_space.IntRange(min=1),
            memory_mb=search_space.IntRange(min=0),
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
        node_space.network_interface = schema.NetworkInterfaceOptionSettings()
        node_space.network_interface.data_path = search_space.SetSpace[
            schema.NetworkDataPath
        ](is_allow_set=True, items=[])
        node_space.network_interface.data_path.add(schema.NetworkDataPath.Synthetic)
        node_space.network_interface.data_path.add(schema.NetworkDataPath.Sriov)
        node_space.network_interface.nic_count = search_space.IntRange(min=1)
        # till now, the max nic number supported in Azure is 8
        node_space.network_interface.max_nic_count = 8

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
        all_features = self.supported_features()
        node_space.features.update(
            [schema.FeatureSettings.create(x.name()) for x in all_features]
        )
        _convert_to_azure_node_space(node_space)

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
        # Apply azure specified values. They will pass into arm template
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
        assert min_cap.network_interface
        assert isinstance(
            min_cap.network_interface.nic_count, int
        ), f"actual: {min_cap.network_interface.nic_count}"
        azure_node_runbook.nic_count = min_cap.network_interface.nic_count
        assert isinstance(
            min_cap.network_interface.data_path, schema.NetworkDataPath
        ), f"actual: {type(min_cap.network_interface.data_path)}"
        if min_cap.network_interface.data_path == schema.NetworkDataPath.Sriov:
            azure_node_runbook.enable_sriov = True

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

    @lru_cache(maxsize=10)  # noqa: B019
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
        log.debug("found the vhd is a sas url, it may need to be copied.")

        # get original vhd's hash key for comparing.
        original_key: Optional[bytearray] = None
        original_vhd_path = vhd_path
        original_blob_client = BlobClient.from_blob_url(original_vhd_path)
        properties = original_blob_client.get_blob_properties()
        if properties.content_settings:
            original_key = properties.content_settings.get(
                "content_md5", None
            )  # type: ignore

        storage_name = get_storage_account_name(
            subscription_id=self.subscription_id, location=location, type="t"
        )

        check_or_create_storage_account(
            self.credential,
            self.subscription_id,
            storage_name,
            self._azure_runbook.shared_resource_group_name,
            location,
            log,
        )
        container_client = get_or_create_storage_container(
            credential=self.credential,
            subscription_id=self.subscription_id,
            account_name=storage_name,
            container_name=SAS_COPIED_CONTAINER_NAME,
            resource_group_name=self._azure_runbook.shared_resource_group_name,
        )

        normalized_vhd_name = constants.NORMALIZE_PATTERN.sub("-", vhd_path)
        year = matches["year"] if matches["year"] else "9999"
        month = matches["month"] if matches["month"] else "01"
        day = matches["day"] if matches["day"] else "01"
        # use the expire date to generate the path. It's easy to identify when
        # the cache can be removed.
        vhd_path = f"{year}{month}{day}/{normalized_vhd_name}.vhd"
        full_vhd_path = f"{container_client.url}/{vhd_path}"

        # lock here to prevent a vhd is copied in multi-thread
        global _global_sas_vhd_copy_lock
        cached_key: Optional[bytearray] = None
        with _global_sas_vhd_copy_lock:
            blobs = container_client.list_blobs(name_starts_with=vhd_path)
            for blob in blobs:
                if blob:
                    # check if hash key matched with original key.
                    if blob.content_settings:
                        cached_key = blob.content_settings.get("content_md5", None)
                    if original_key == cached_key:
                        # if it exists, return the link, not to copy again.
                        log.debug("the sas url is copied already, use it directly.")
                        return full_vhd_path
                    else:
                        log.debug("found cached vhd, but the hash key mismatched.")

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

    @lru_cache(maxsize=10)  # noqa: B019
    def _get_image_info(
        self, location: str, marketplace: Optional[AzureVmMarketplaceSchema]
    ) -> VirtualMachineImage:
        compute_client = get_compute_client(self)
        assert isinstance(marketplace, AzureVmMarketplaceSchema)
        with global_credential_access_lock:
            image_info = compute_client.virtual_machine_images.get(
                location=location,
                publisher_name=marketplace.publisher,
                offer=marketplace.offer,
                skus=marketplace.sku,
                version=marketplace.version,
            )
        return image_info

    def _get_location_key(self, location: str) -> str:
        return f"{self.subscription_id}_{location}"

    def _enable_ssh_on_windows(self, node: Node) -> None:
        runbook = node.capability.get_extended_runbook(AzureNodeSchema)
        if runbook.is_linux:
            return

        context = get_node_context(node)

        remote_node = cast(RemoteNode, node)

        log = node.log
        log.debug(
            f"checking if SSH port {remote_node.public_port} is reachable "
            f"on {remote_node.name}..."
        )

        connected, _ = wait_tcp_port_ready(
            address=remote_node.public_address,
            port=remote_node.public_port,
            log=log,
            timeout=3,
        )
        if connected:
            log.debug("SSH port is reachable.")
            return

        log.debug("SSH port is not open, enabling ssh on Windows ...")
        # The SSH port is not opened, try to enable it.
        public_key_data = get_public_key_data(self.runbook.admin_private_key_file)
        with open(Path(__file__).parent / "Enable-SSH.ps1", "r") as f:
            script = f.read()

        parameters = RunCommandInputParameter(name="PublicKey", value=public_key_data)
        command = RunCommandInput(
            command_id="RunPowerShellScript",
            script=[script],
            parameters=[parameters],
        )

        compute_client = get_compute_client(self)
        operation = compute_client.virtual_machines.begin_run_command(
            resource_group_name=context.resource_group_name,
            vm_name=context.vm_name,
            parameters=command,
        )
        result = wait_operation(operation=operation, failure_identity="enable ssh")
        log.debug("SSH script result:")
        log.dump_json(logging.DEBUG, result)


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
        if node_space.network_interface:
            node_space.network_interface = schema.load_by_type(
                schema.NetworkInterfaceOptionSettings, node_space.network_interface
            )
