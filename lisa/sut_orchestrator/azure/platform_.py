# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import copy
import json
import logging
import math
import os
import re
import sys
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from functools import lru_cache, partial
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set, Tuple, Type, Union, cast

from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute.models import (  # type: ignore
    GalleryImage,
    GalleryImageVersion,
    PurchasePlan,
    ResourceSku,
    RunCommandInput,
    RunCommandInputParameter,
    VirtualMachine,
    VirtualMachineImage,
)
from azure.mgmt.marketplaceordering.models import AgreementTerms  # type: ignore
from azure.mgmt.resource import SubscriptionClient  # type: ignore
from azure.mgmt.resource.resources.models import (  # type: ignore
    Deployment,
    DeploymentMode,
    DeploymentProperties,
)
from azure.storage.blob import BlobClient
from cachetools import TTLCache, cached
from dataclasses_json import dataclass_json
from marshmallow import fields, validate
from retry import retry

from lisa import feature, schema, search_space
from lisa.environment import Environment
from lisa.node import Node, RemoteNode, local
from lisa.platform_ import Platform
from lisa.secret import PATTERN_GUID, add_secret
from lisa.tools import Dmesg, Hostname, Modinfo, Whoami
from lisa.util import (
    LisaException,
    LisaTimeoutException,
    NotMeetRequirementException,
    ResourceAwaitableException,
    constants,
    dump_file,
    field_metadata,
    generate_random_chars,
    get_datetime_path,
    get_matched_str,
    get_public_key_data,
    is_unittest,
    plugin_manager,
    set_filtered_fields,
    strip_strs,
    truncate_keep_prefix,
)
from lisa.util.logger import Logger, get_logger
from lisa.util.parallel import run_in_parallel
from lisa.util.perf_timer import create_timer
from lisa.util.shell import wait_tcp_port_ready

from .. import AZURE
from . import features
from .common import (
    AZURE_SHARED_RG_NAME,
    AZURE_SUBNET_PREFIX,
    AZURE_VIRTUAL_NETWORK_NAME,
    AzureArmParameter,
    AzureNodeArmParameter,
    AzureNodeSchema,
    AzureVmMarketplaceSchema,
    AzureVmPurchasePlanSchema,
    DataDiskCreateOption,
    DataDiskSchema,
    SharedImageGallerySchema,
    check_or_create_resource_group,
    check_or_create_storage_account,
    generate_sas_token,
    get_compute_client,
    get_environment_context,
    get_marketplace_ordering_client,
    get_node_context,
    get_or_create_storage_container,
    get_primary_ip_addresses,
    get_resource_management_client,
    get_storage_account_name,
    get_storage_client,
    get_vm,
    global_credential_access_lock,
    save_console_log,
    wait_copy_blob,
    wait_operation,
)
from .tools import Uname, VmGeneration, Waagent

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
    "westus3",
    "southeastasia",
    "eastus",
    "southcentralus",
    "northeurope",
    "westeurope",
    "brazilsouth",
    "australiaeast",
    "uksouth",
]
RESOURCE_GROUP_LOCATION = "westus3"

# names in arm template, they should be changed with template together.
RESOURCE_ID_PORT_POSTFIX = "-ssh"

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
KEY_HARDWARE_PLATFORM = "hardware_platform"
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

# /subscriptions/xxxx/resourceGroups/xxxx/providers/Microsoft.Compute/galleries/xxxx
# /subscriptions/xxxx/resourceGroups/xxxx/providers/Microsoft.Storage/storageAccounts/xxxx
RESOURCE_GROUP_PATTERN = re.compile(r"resourceGroups/(.*)/providers", re.M)
# https://sc.blob.core.windows.net/container/xxxx/xxxx/xxxx.vhd
STORAGE_CONTAINER_BLOB_PATTERN = re.compile(
    r"https://(?P<sc>.*)"
    r"(?:\.blob\.core\.windows\.net|blob\.storage\.azure\.net)"
    r"/(?P<container>[^/]+)/?/(?P<blob>.*)",
    re.M,
)

# The timeout hours of the blob with copy pending status
# If the blob is still copy pending status after the timeout hours, it can be deleted
BLOB_COPY_PENDING_TIMEOUT_HOURS = 6
_global_sas_vhd_copy_lock = Lock()


@dataclass_json()
@dataclass
class AzureCapability:
    location: str
    vm_size: str
    capability: schema.NodeSpace
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
    capabilities: Dict[str, AzureCapability] = field(default_factory=dict)


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
    # specify shared resource group location
    shared_resource_group_location: str = field(default=RESOURCE_GROUP_LOCATION)
    availability_set_tags: Optional[Dict[str, str]] = field(default=None)
    availability_set_properties: Optional[Dict[str, Any]] = field(default=None)
    vm_tags: Optional[Dict[str, Any]] = field(default=None)
    locations: Optional[Union[str, List[str]]] = field(default=None)

    virtual_network_resource_group: str = field(default="")
    virtual_network_name: str = field(default=AZURE_VIRTUAL_NETWORK_NAME)
    subnet_prefix: str = field(default=AZURE_SUBNET_PREFIX)

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
    # the AzCopy path can be specified if use this tool to copy blob
    azcopy_path: str = field(default="")

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
                "virtual_network_resource_group",
                "virtual_network_name",
                "subnet_prefix",
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
        r"(https:\/\/)(?P<storage_name>.*)([.].*){4}\/(?P<container_name>.*)\/",
        re.M,
    )
    _arm_template: Any = None

    _credentials: Dict[str, DefaultAzureCredential] = {}
    _locations_data_cache: Dict[str, AzureLocation] = {}

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
            KEY_HARDWARE_PLATFORM: self._get_hardware_platform,
        }

    @classmethod
    def type_name(cls) -> str:
        return AZURE

    @classmethod
    def supported_features(cls) -> List[Type[feature.Feature]]:
        return [
            features.Disk,
            features.AzureExtension,
            features.Gpu,
            features.Nvme,
            features.NestedVirtualization,
            features.SerialConsole,
            features.NetworkInterface,
            features.Resize,
            features.StartStop,
            features.Infiniband,
            features.Hibernation,
            features.SecurityProfile,
            features.ACC,
            features.IsolatedResource,
            features.VhdGeneration,
            features.Architecture,
            features.Nfs,
        ]

    def _prepare_environment(self, environment: Environment, log: Logger) -> bool:
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

        if not environment.runbook.nodes_requirement:
            return True

        # reload requirement to match
        environment.runbook.reload_requirements()
        nodes_requirement = environment.runbook.nodes_requirement

        # covert to azure node space, so the azure extensions can be loaded.
        for req in nodes_requirement:
            self._load_image_features(req)

        is_success: bool = False

        # get eligible locations
        allowed_locations = _get_allowed_locations(nodes_requirement)
        log.debug(f"allowed locations: {allowed_locations}")

        # Any to wait for resource
        any_wait_for_resource: bool = False
        errors: List[str] = []

        for location in allowed_locations:
            caps, error = self._get_matched_capabilities(
                location=location, nodes_requirement=nodes_requirement, log=log
            )

            if error:
                errors.append(error)

            self._analyze_environment_availability(location, caps)

            # set all awaitable flag if nothing is False
            if all(x for x in caps):
                any_wait_for_resource = True

            # check to return value or raise WaitForMoreResource
            if all(isinstance(x, schema.NodeSpace) for x in caps):
                # with above condition, all types are NodeSpace. Ignore the mypy check.
                environment.runbook.nodes_requirement = caps  # type: ignore
                environment.cost = sum(
                    x.cost for x in caps if isinstance(x, schema.NodeSpace)
                )
                is_success = True
                log.debug(
                    f"requirement meet, "
                    f"cost: {environment.cost}, "
                    f"cap: {environment.runbook.nodes_requirement}"
                )
                break

        if not is_success:
            if any_wait_for_resource:
                raise ResourceAwaitableException(
                    "vm size", "No available quota, try to deploy later."
                )
            else:
                raise NotMeetRequirementException(
                    f"{errors}, runbook: {environment.runbook}."
                )

        # resolve Latest to specified version
        if is_success:
            self._resolve_marketplace_image_version(nodes_requirement)

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
            environment_context.resource_group_is_specified = True

        environment_context.resource_group_name = resource_group_name

        if self._azure_runbook.dry_run:
            log.info(f"dry_run: {self._azure_runbook.dry_run}")
        else:
            try:
                location, deployment_parameters = self._create_deployment_parameters(
                    resource_group_name, environment, log
                )

                if self._azure_runbook.deploy:
                    log.info(
                        f"creating or updating resource group: [{resource_group_name}]"
                    )
                    check_or_create_resource_group(
                        self.credential,
                        subscription_id=self.subscription_id,
                        resource_group_name=resource_group_name,
                        location=location,
                        log=log,
                    )
                else:
                    log.info(f"reusing resource group: [{resource_group_name}]")

                if self._azure_runbook.deploy:
                    self._validate_template(deployment_parameters, log)
                    time = create_timer()
                    self._deploy(location, deployment_parameters, log, environment)
                    environment_context.provision_time = time.elapsed()
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

        if not environment_context.resource_group_is_specified:
            log.info(
                f"skipped to delete resource group: {resource_group_name}, "
                f"as it's specified in runbook."
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

    def _save_console_log(
        self, resource_group_name: str, environment: Environment, log: Logger
    ) -> None:
        compute_client = get_compute_client(self)
        vms = compute_client.virtual_machines.list(resource_group_name)
        saved_path = environment.log_path / f"{get_datetime_path()}_serial_log"
        saved_path.mkdir(parents=True, exist_ok=True)
        for vm in vms:
            log_response_content = save_console_log(
                resource_group_name,
                vm.name,
                self,
                log,
                saved_path,
                screenshot_file_name=f"{vm.name}_serial_console",
            )
            log_file_name = saved_path / f"{vm.name}_serial_console.log"
            log_file_name.write_bytes(log_response_content)

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
        for key, method in self._environment_information_hooks.items():
            node.log.debug(f"detecting {key} ...")
            try:
                value = method(node)
                if value:
                    information[key] = value
            except Exception as identifier:
                node.log.exception(f"error on get {key}.", exc_info=identifier)

        if node.is_connected and node.is_posix:
            node.log.debug("detecting lis version...")
            modinfo = node.tools[Modinfo]
            information["lis_version"] = modinfo.get_version("hv_vmbus")

            node.log.debug("detecting vm generation...")
            information[KEY_VM_GENERATION] = node.tools[VmGeneration].get_generation()
            node.log.debug(f"vm generation: {information[KEY_VM_GENERATION]}")

        node_runbook = node.capability.get_extended_runbook(AzureNodeSchema, AZURE)
        if node_runbook:
            information["location"] = node_runbook.location
            information["vmsize"] = node_runbook.vm_size
            information["image"] = node_runbook.get_image_name()
        information["platform"] = self.type_name()
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

    def _get_hardware_platform(self, node: Node) -> str:
        result: str = "Unknown"

        try:
            if node.is_connected and node.is_posix:
                node.log.debug("detecting hardware platform from uname...")
                uname_tool = node.tools[Uname]
                result = uname_tool.get_linux_information().hardware_platform
        except Exception as identifier:
            # it happens on some error vms. Those error should be caught earlier in
            # test cases not here. So ignore any error here to collect information only.
            node.log.debug(f"error on run uname: {identifier}")

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
            information.update(self._get_platform_information(environment))
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
            azure_runbook.shared_resource_group_location,
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

    def get_location_info(self, location: str, log: Logger) -> AzureLocation:
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
            all_skus: Dict[str, AzureCapability] = dict()
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
                            azure_capability = AzureCapability(
                                location=location,
                                vm_size=sku_obj.name,
                                capability=capability,
                                resource_sku=resource_sku,
                            )
                            all_skus[azure_capability.vm_size] = azure_capability
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

        arm_parameters.virtual_network_resource_group = (
            self._azure_runbook.virtual_network_resource_group
        )
        arm_parameters.subnet_prefix = self._azure_runbook.subnet_prefix
        arm_parameters.virtual_network_name = self._azure_runbook.virtual_network_name

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

        nodes_parameters: List[AzureNodeArmParameter] = []
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

            node_arm_parameters = self._create_node_arm_parameters(node.capability, log)
            nodes_parameters.append(node_arm_parameters)

            # Set data disk array
            arm_parameters.data_disks = self._generate_data_disks(
                node, node_arm_parameters
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
        arm_parameters.vhd_storage_name = get_storage_account_name(
            self.subscription_id, arm_parameters.location, "t"
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

        # if it is a new deployment
        #  azure_node_runbook.name will be generated in below way
        # if it is not a new deployment
        #  if user gives the vm name, azure_node_runbook.name stores the given user name
        #  if user doesn't give the vm name, it will be filled in initialize_environment
        if self._azure_runbook.deploy and not azure_node_runbook.name:
            # the max length of vm name is 64 chars. Below logic takes last 45
            # chars in resource group name and keep the leading 5 chars.
            # name_prefix can contain any of customized (existing) or
            # generated (starts with "lisa-") resource group name,
            # so, pass the first 5 chars as prefix to truncate_keep_prefix
            # to handle both cases
            node_name = f"{name_prefix}-n{index}"
            azure_node_runbook.name = truncate_keep_prefix(node_name, 50, node_name[:5])
        if azure_node_runbook.name:
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
        if azure_node_runbook.vhd and azure_node_runbook.vhd.vhd_path:
            # vhd is higher priority
            vhd = azure_node_runbook.vhd
            vhd.vhd_path = self._get_deployable_vhd_path(
                vhd.vhd_path, azure_node_runbook.location, log
            )
            if vhd.vmgs_path:
                vhd.vmgs_path = self._get_deployable_vhd_path(
                    vhd.vmgs_path, azure_node_runbook.location, log
                )
            azure_node_runbook.vhd = vhd
            azure_node_runbook.marketplace = None
            azure_node_runbook.shared_gallery = None
        elif azure_node_runbook.shared_gallery:
            azure_node_runbook.marketplace = None
            azure_node_runbook.shared_gallery = self._parse_shared_gallery_image(
                azure_node_runbook.shared_gallery
            )
        elif not azure_node_runbook.marketplace:
            # set to default marketplace, if nothing specified
            azure_node_runbook.marketplace = AzureVmMarketplaceSchema()
        else:
            # marketplace value is already set in runbook
            ...

        if azure_node_runbook.marketplace:
            # resolve "latest" to specified version
            azure_node_runbook.marketplace = self._resolve_marketplace_image(
                azure_node_runbook.location, azure_node_runbook.marketplace
            )
            image_info = self._get_image_info(
                azure_node_runbook.location, azure_node_runbook.marketplace
            )
            # HyperVGenerationTypes return "V1"/"V2", so we need to strip "V"
            azure_node_runbook.hyperv_generation = _get_vhd_generation(image_info)

            # retrieve the os type for arm template.
            if azure_node_runbook.is_linux is None:
                if image_info.os_disk_image.operating_system == "Windows":
                    azure_node_runbook.is_linux = False
                else:
                    azure_node_runbook.is_linux = True
        elif azure_node_runbook.shared_gallery:
            azure_node_runbook.hyperv_generation = _get_gallery_image_generation(
                self._get_detailed_sig(azure_node_runbook.shared_gallery)
            )
        else:
            log.debug(
                "there is no way to detect vhd generation, unless user provides it"
                f" current vhd generation is {azure_node_runbook.hyperv_generation}"
            )

        if azure_node_runbook.is_linux is None:
            # fill it default value
            azure_node_runbook.is_linux = True

        return azure_node_runbook

    def _create_node_arm_parameters(
        self, capability: schema.Capability, log: Logger
    ) -> AzureNodeArmParameter:
        runbook = capability.get_extended_runbook(AzureNodeSchema, type_name=AZURE)
        arm_parameters = AzureNodeArmParameter.from_node_runbook(runbook)

        if arm_parameters.vhd and arm_parameters.vhd.vhd_path:
            # vhd is higher priority
            vhd = arm_parameters.vhd
            vhd.vhd_path = self._get_deployable_vhd_path(
                vhd.vhd_path, arm_parameters.location, log
            )
            if vhd.vmgs_path:
                vhd.vmgs_path = self._get_deployable_vhd_path(
                    vhd.vmgs_path, arm_parameters.location, log
                )
            arm_parameters.vhd = vhd
            arm_parameters.osdisk_size_in_gb = max(
                arm_parameters.osdisk_size_in_gb,
                self._get_vhd_os_disk_size(arm_parameters.vhd.vhd_path),
            )
        elif arm_parameters.shared_gallery:
            arm_parameters.osdisk_size_in_gb = max(
                arm_parameters.osdisk_size_in_gb,
                self._get_sig_os_disk_size(arm_parameters.shared_gallery),
            )
        else:
            assert (
                arm_parameters.marketplace
            ), "not set one of marketplace, shared_gallery or vhd."
            image_info = self._get_image_info(
                arm_parameters.location, arm_parameters.marketplace
            )
            arm_parameters.osdisk_size_in_gb = max(
                arm_parameters.osdisk_size_in_gb,
                image_info.os_disk_image.additional_properties.get("sizeInGb", 0),
            )
            if not arm_parameters.purchase_plan and image_info.plan:
                # expand values for lru cache
                plan_name = image_info.plan.name
                plan_product = image_info.plan.product
                plan_publisher = image_info.plan.publisher
                # accept the default purchase plan automatically.
                arm_parameters.purchase_plan = self._process_marketplace_image_plan(
                    marketplace=arm_parameters.marketplace,
                    plan_name=plan_name,
                    plan_product=plan_product,
                    plan_publisher=plan_publisher,
                )

        # Set disk type
        assert capability.disk, "node space must have disk defined."
        assert isinstance(capability.disk.disk_type, schema.DiskType)
        arm_parameters.disk_type = features.get_azure_disk_type(
            capability.disk.disk_type
        )
        assert isinstance(
            capability.disk.disk_controller_type, schema.DiskControllerType
        )
        assert (
            arm_parameters.hyperv_generation == 2
            or capability.disk.disk_controller_type == schema.DiskControllerType.SCSI
        ), "Gen 1 images cannot be set to NVMe Disk Controller Type"
        arm_parameters.disk_controller_type = capability.disk.disk_controller_type.value

        assert capability.network_interface
        assert isinstance(
            capability.network_interface.nic_count, int
        ), f"actual: {capability.network_interface.nic_count}"
        arm_parameters.nic_count = capability.network_interface.nic_count
        assert isinstance(
            capability.network_interface.data_path, schema.NetworkDataPath
        ), f"actual: {type(capability.network_interface.data_path)}"
        if capability.network_interface.data_path == schema.NetworkDataPath.Sriov:
            arm_parameters.enable_sriov = True

        return arm_parameters

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

            error_message = "\n".join(error_messages)
            plugin_manager.hook.azure_deploy_failed(error_message=error_message)
            raise LisaException(error_message)

    def _deploy(
        self,
        location: str,
        deployment_parameters: Dict[str, Any],
        log: Logger,
        environment: Environment,
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
            while True:
                try:
                    wait_operation(
                        deployment_operation, time_out=300, failure_identity="deploy"
                    )
                except LisaTimeoutException:
                    self._save_console_log(resource_group_name, environment, log)
                    continue
                break
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
        self, resource_group_name: str, log: Logger
    ) -> Dict[str, VirtualMachine]:
        compute_client = get_compute_client(self, api_version="2020-06-01")

        log.debug(f"listing vm in resource group {resource_group_name}")
        vms_map: Dict[str, VirtualMachine] = {}
        vms = compute_client.virtual_machines.list(resource_group_name)
        for vm in vms:
            vms_map[vm.name] = vm
            log.debug(f"  found vm {vm.name}")
        if not vms_map:
            raise LisaException(
                "deployment succeeded, but VM not found in 5 minutes "
                f"from '{resource_group_name}'"
            )
        return vms_map

    def initialize_environment(self, environment: Environment, log: Logger) -> None:
        vms_map: Dict[str, VirtualMachine] = {}

        environment_context = get_environment_context(environment=environment)
        resource_group_name = environment_context.resource_group_name
        vms_map = self._load_vms(resource_group_name, log)

        vms_name_list = list(vms_map.keys())
        if len(vms_name_list) < len(environment.nodes):
            raise LisaException(
                f"{len(vms_name_list)} vms count is less than "
                f"requirement count {len(environment.nodes)}"
            )

        index = 0
        for node in environment.nodes.list():
            node_context = get_node_context(node)
            # when it is a new deployment or when vm name pass by user
            # node_context.vm_name is not empty
            if node_context.vm_name:
                vm_name = node_context.vm_name
                vm = get_vm(self, node)
            else:
                # when it is not a new deployment and vm name not passed by user
                # read the vms info from the given resource group name
                vm_name = vms_name_list[index]
                index = index + 1
                node_context.vm_name = vm_name
                vm = vms_map[vm_name]
            node.name = vm_name
            public_address, private_address = get_primary_ip_addresses(
                self, resource_group_name, vm
            )
            assert isinstance(node, RemoteNode)
            node.set_connection_info(
                address=private_address,
                port=22,
                public_address=public_address,
                public_port=22,
                username=node_context.username,
                password=node_context.password,
                private_key_file=node_context.private_key_file,
            )
            node.provision_time = environment_context.provision_time

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
        node_space.disk.disk_controller_type = search_space.SetSpace[
            schema.DiskControllerType
        ](is_allow_set=True, items=[])
        node_space.disk.data_disk_iops = search_space.IntRange(min=0)
        node_space.disk.data_disk_size = search_space.IntRange(min=0)
        node_space.network_interface = schema.NetworkInterfaceOptionSettings()
        node_space.network_interface.data_path = search_space.SetSpace[
            schema.NetworkDataPath
        ](is_allow_set=True, items=[])

        # fill supported features
        azure_raw_capabilities: Dict[str, str] = {}
        for sku_capability in resource_sku.capabilities:
            # prevent to loop in every feature
            azure_raw_capabilities[sku_capability.name] = sku_capability.value

        # calculate cpu count. Some vm sizes, like Standard_HC44rs, doesn't have
        # vCPUsAvailable, so use vCPUs.
        vcpus_available = int(azure_raw_capabilities.get("vCPUsAvailable", "0"))
        if vcpus_available:
            node_space.core_count = vcpus_available
        else:
            node_space.core_count = int(azure_raw_capabilities.get("vCPUs", "0"))

        memory_value = azure_raw_capabilities.get("MemoryGB", None)
        if memory_value:
            node_space.memory_mb = int(float(memory_value) * 1024)

        max_disk_count = azure_raw_capabilities.get("MaxDataDiskCount", None)
        if max_disk_count:
            node_space.disk.max_data_disk_count = int(max_disk_count)
            node_space.disk.data_disk_count = search_space.IntRange(
                max=node_space.disk.max_data_disk_count
            )

        max_nic_count = azure_raw_capabilities.get("MaxNetworkInterfaces", None)
        if max_nic_count:
            # set a min value for nic_count work around for an azure python sdk bug
            # nic_count is 0 when get capability for some sizes e.g. Standard_D8a_v3
            sku_nic_count = int(max_nic_count)
            if sku_nic_count == 0:
                sku_nic_count = 1
            node_space.network_interface.nic_count = search_space.IntRange(
                min=1, max=sku_nic_count
            )
            node_space.network_interface.max_nic_count = sku_nic_count

        if azure_raw_capabilities.get("PremiumIO", None) == "True":
            node_space.disk.disk_type.add(schema.DiskType.PremiumSSDLRS)

        disk_controller_types = azure_raw_capabilities.get("DiskControllerTypes", None)
        if disk_controller_types:
            for allowed_type in disk_controller_types.split(","):
                try:
                    node_space.disk.disk_controller_type.add(
                        schema.DiskControllerType(allowed_type)
                    )
                except ValueError:
                    self._log.error(
                        f"'{allowed_type}' is not a known Disk Controller Type "
                        f"({[x for x in schema.DiskControllerType]})"
                    )
        else:
            node_space.disk.disk_controller_type.add(schema.DiskControllerType.SCSI)

        if azure_raw_capabilities.get("EphemeralOSDiskSupported", None) == "True":
            # Check if CachedDiskBytes is greater than 30GB
            # We use diff disk as cache disk for ephemeral OS disk
            cached_disk_bytes = azure_raw_capabilities.get("CachedDiskBytes", 0)
            cached_disk_bytes_gb = int(cached_disk_bytes) / 1024 / 1024 / 1024
            if cached_disk_bytes_gb >= 30:
                node_space.disk.disk_type.add(schema.DiskType.Ephemeral)

        # set AN
        if azure_raw_capabilities.get("AcceleratedNetworkingEnabled", None) == "True":
            # refer
            # https://docs.microsoft.com/en-us/azure/virtual-machines/dcv2-series#configuration
            # https://docs.microsoft.com/en-us/azure/virtual-machines/ncv2-series
            # https://docs.microsoft.com/en-us/azure/virtual-machines/ncv3-series
            # https://docs.microsoft.com/en-us/azure/virtual-machines/nd-series
            # below VM size families don't support `Accelerated Networking` but
            # API return `True`, fix this issue temporarily will revert it till
            # bug fixed.
            if resource_sku.family not in [
                "standardDCSv2Family",
                "standardNCSv2Family",
                "standardNCSv3Family",
                "standardNDSFamily",
            ]:
                # update data path types if sriov feature is supported
                node_space.network_interface.data_path.add(schema.NetworkDataPath.Sriov)

        # for some new sizes, there is no MaxNetworkInterfaces capability
        # and we have to set a default value for max_nic_count
        if not node_space.network_interface.max_nic_count or not isinstance(
            node_space.network_interface.max_nic_count, int
        ):
            node_space.network_interface.max_nic_count = 1
            node_space.network_interface.nic_count = search_space.IntRange(min=1, max=1)

        # some vm size do not have resource disk present
        # https://docs.microsoft.com/en-us/azure/virtual-machines/azure-vms-no-temp-disk
        resource_disk_size = azure_raw_capabilities.get("MaxResourceVolumeMB", None)
        if resource_disk_size and int(resource_disk_size) > 0:
            node_space.disk.has_resource_disk = True
        else:
            node_space.disk.has_resource_disk = False

        for supported_feature in self.supported_features():
            if supported_feature.name() in [
                features.Disk.name(),
                features.NetworkInterface.name(),
            ]:
                # Skip the disk and network interfaces features. They will be
                # handled by node_space directly.
                continue

            feature_setting = supported_feature.create_setting(
                raw_capabilities=azure_raw_capabilities,
                resource_sku=resource_sku,
                node_space=node_space,
            )
            if feature_setting:
                node_space.features.add(feature_setting)

        node_space.disk.disk_type.add(schema.DiskType.StandardHDDLRS)
        node_space.disk.disk_type.add(schema.DiskType.StandardSSDLRS)
        node_space.network_interface.data_path.add(schema.NetworkDataPath.Synthetic)

        return node_space

    def get_sorted_vm_sizes(
        self, capabilities: List[AzureCapability], log: Logger
    ) -> List[AzureCapability]:
        # sort vm size by predefined pattern

        sorted_capabilities: List[AzureCapability] = []

        found_vm_sizes: Set[str] = set()
        # loop all fall back levels
        for fallback_pattern in VM_SIZE_FALLBACK_PATTERNS:
            level_capabilities: List[AzureCapability] = []

            # loop all capabilities
            for capability in capabilities:
                vm_size = capability.vm_size
                if fallback_pattern.match(vm_size) and vm_size not in found_vm_sizes:
                    level_capabilities.append(capability)
                    found_vm_sizes.add(vm_size)

            # sort by rough cost
            level_capabilities.sort(key=lambda x: (x.capability.cost))
            sorted_capabilities.extend(level_capabilities)
        return sorted_capabilities

    @lru_cache(maxsize=10)  # noqa: B019
    def _resolve_marketplace_image(
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
            if 0 == len(versioned_images):
                raise LisaException(
                    f"cannot find any version of image {marketplace.publisher} "
                    f"{marketplace.offer} {marketplace.sku} in {location}"
                )
            # any one should be the same to get purchase plan
            new_marketplace.version = versioned_images[-1].name
        return new_marketplace

    @lru_cache(maxsize=10)  # noqa: B019
    def _parse_shared_gallery_image(
        self, shared_image: SharedImageGallerySchema
    ) -> SharedImageGallerySchema:
        new_shared_image = copy.copy(shared_image)
        compute_client = get_compute_client(self)
        rg_name = shared_image.resource_group_name
        if not shared_image.resource_group_name:
            # /subscriptions/xxxx/resourceGroups/xxxx/providers/Microsoft.Compute/
            # galleries/xxxx
            rg_pattern = re.compile(r"resourceGroups/(.*)/providers", re.M)
            galleries = compute_client.galleries.list()
            for gallery in galleries:
                if gallery.name.lower() == shared_image.image_gallery:
                    rg_name = get_matched_str(gallery.id, rg_pattern)
                    break
            if not rg_name:
                raise LisaException(
                    f"not find matched gallery {shared_image.image_gallery}"
                )
        new_shared_image.resource_group_name = rg_name
        if shared_image.image_version.lower() == "latest":
            gallery_images = (
                compute_client.gallery_image_versions.list_by_gallery_image(
                    resource_group_name=new_shared_image.resource_group_name,
                    gallery_name=new_shared_image.image_gallery,
                    gallery_image_name=new_shared_image.image_definition,
                )
            )
            image: GalleryImageVersion = None
            time: Optional[datetime] = None
            for image in gallery_images:
                gallery_image = compute_client.gallery_image_versions.get(
                    resource_group_name=new_shared_image.resource_group_name,
                    gallery_name=new_shared_image.image_gallery,
                    gallery_image_name=new_shared_image.image_definition,
                    gallery_image_version_name=image.name,
                    expand="ReplicationStatus",
                )
                if not time:
                    time = gallery_image.publishing_profile.published_date
                    new_shared_image.image_version = image.name
                if gallery_image.publishing_profile.published_date > time:
                    time = gallery_image.publishing_profile.published_date
                    new_shared_image.image_version = image.name
        return new_shared_image

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
        node_space.disk.disk_controller_type = search_space.SetSpace[
            schema.DiskControllerType
        ](is_allow_set=True, items=[])
        node_space.disk.disk_controller_type.add(schema.DiskControllerType.SCSI)
        node_space.disk.disk_controller_type.add(schema.DiskControllerType.NVME)
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
            assert location in azure_node_runbook.location, (
                f"predefined location [{azure_node_runbook.location}] "
                f"must be same as "
                f"cap location [{location}]"
            )
        # the location may not be set
        azure_node_runbook.location = location
        azure_node_runbook.vm_size = azure_capability.vm_size

        return min_cap

    def _generate_sas_token(self, result_dict: Dict[str, str]) -> Any:
        sc_name = result_dict["account_name"]
        container_name = result_dict["container_name"]
        rg = result_dict["resource_group_name"]
        blob_name = result_dict["blob_name"]

        source_container_client = get_or_create_storage_container(
            credential=self.credential,
            subscription_id=self.subscription_id,
            account_name=sc_name,
            container_name=container_name,
            resource_group_name=rg,
        )
        source_blob = source_container_client.get_blob_client(blob_name)
        sas_token = generate_sas_token(
            credential=self.credential,
            subscription_id=self.subscription_id,
            account_name=sc_name,
            resource_group_name=rg,
        )
        source_url = source_blob.url + "?" + sas_token
        return source_url

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
            vhd_details = self._get_vhd_details(vhd_path)
            vhd_location = vhd_details["location"]
            if location == vhd_location:
                return vhd_path
            else:
                vhd_path = self._generate_sas_token(vhd_details)
                matches = SAS_URL_PATTERN.match(vhd_path)
                assert matches, f"fail to generate sas url for {vhd_path}"
                log.debug(
                    f"the vhd location {location} is not same with running case "
                    f"location {vhd_location}, generate a sas url for source vhd, "
                    f"it needs to be copied into location {location}."
                )
        else:
            log.debug("found the vhd is a sas url, it may need to be copied.")

        original_vhd_path = vhd_path

        storage_name = get_storage_account_name(
            subscription_id=self.subscription_id, location=location, type_="t"
        )

        check_or_create_storage_account(
            self.credential,
            self.subscription_id,
            storage_name,
            self._azure_runbook.shared_resource_group_name,
            location,
            log,
        )

        normalized_vhd_name = constants.NORMALIZE_PATTERN.sub("-", vhd_path)
        year = matches["year"] if matches["year"] else "9999"
        month = matches["month"] if matches["month"] else "01"
        day = matches["day"] if matches["day"] else "01"
        # use the expire date to generate the path. It's easy to identify when
        # the cache can be removed.
        vhd_path = f"{year}{month}{day}/{normalized_vhd_name}.vhd"
        full_vhd_path = self._copy_vhd_to_storage(
            storage_name, original_vhd_path, vhd_path, log
        )
        return full_vhd_path

    def _copy_vhd_to_storage(
        self, storage_name: str, src_vhd_sas_url: str, dst_vhd_name: str, log: Logger
    ) -> str:
        # get original vhd's hash key for comparing.
        original_key: Optional[bytearray] = None
        original_blob_client = BlobClient.from_blob_url(src_vhd_sas_url)
        properties = original_blob_client.get_blob_properties()
        if properties.content_settings:
            original_key = properties.content_settings.get(
                "content_md5", None
            )  # type: ignore

        container_client = get_or_create_storage_container(
            credential=self.credential,
            subscription_id=self.subscription_id,
            account_name=storage_name,
            container_name=SAS_COPIED_CONTAINER_NAME,
            resource_group_name=self._azure_runbook.shared_resource_group_name,
        )
        full_vhd_path = f"{container_client.url}/{dst_vhd_name}"

        # lock here to prevent a vhd is copied in multi-thread
        cached_key: Optional[bytearray] = None
        with _global_sas_vhd_copy_lock:
            blobs = container_client.list_blobs(name_starts_with=dst_vhd_name)
            blob_client = container_client.get_blob_client(dst_vhd_name)
            vhd_exists = False
            for blob in blobs:
                if blob:
                    # check if hash key matched with original key.
                    if blob.content_settings:
                        cached_key = blob.content_settings.get(
                            "content_md5", None
                        )  # type: ignore
                    if self._is_stuck_copying(blob_client, log):
                        # Delete the stuck vhd.
                        blob_client.delete_blob(delete_snapshots="include")
                    elif original_key and cached_key:
                        if original_key == cached_key:
                            log.debug("the sas url is copied already, use it directly.")
                            vhd_exists = True
                        else:
                            log.debug("found cached vhd, but the hash key mismatched.")
                    else:
                        log.debug(
                            "No md5 content either in original blob or current blob. "
                            "Then no need to check the hash key"
                        )
                        vhd_exists = True

            if not vhd_exists:
                azcopy_path = self._azure_runbook.azcopy_path
                if azcopy_path:
                    log.info(f"AzCopy path: {azcopy_path}")
                    if not os.path.exists(azcopy_path):
                        raise LisaException(f"{azcopy_path} does not exist")

                    sas_token = generate_sas_token(
                        credential=self.credential,
                        subscription_id=self.subscription_id,
                        account_name=storage_name,
                        resource_group_name=self._azure_runbook.shared_resource_group_name,  # noqa: E501
                        writable=True,
                    )
                    dst_vhd_sas_url = f"{full_vhd_path}?{sas_token}"
                    log.info(f"copying vhd by azcopy {dst_vhd_name}")
                    try:
                        local().execute(
                            f"{azcopy_path} copy {src_vhd_sas_url} {dst_vhd_sas_url} --recursive=true",  # noqa: E501
                            expected_exit_code=0,
                            expected_exit_code_failure_message=(
                                "Azcopy failed to copy the blob"
                            ),
                            timeout=60 * 60,
                        )
                    except Exception as identifier:
                        blob_client.delete_blob(delete_snapshots="include")
                        raise LisaException(f"{identifier}")

                    # Set metadata to mark the blob copied by AzCopy successfully
                    metadata = {"AzCopyStatus": "Success"}
                    blob_client.set_blob_metadata(metadata)
                else:
                    blob_client.start_copy_from_url(
                        src_vhd_sas_url, metadata=None, incremental_copy=False
                    )

            wait_copy_blob(blob_client, dst_vhd_name, log)

        return full_vhd_path

    def _is_stuck_copying(self, blob_client: BlobClient, log: Logger) -> bool:
        props = blob_client.get_blob_properties()
        copy_status = props.copy.status
        if copy_status == "pending":
            if props.creation_time:
                delta_hours = (
                    datetime.now(timezone.utc) - props.creation_time
                ).seconds / (60 * 60)
            else:
                delta_hours = 0

            if delta_hours > BLOB_COPY_PENDING_TIMEOUT_HOURS:
                log.debug(
                    "the blob is pending more than "
                    f"{BLOB_COPY_PENDING_TIMEOUT_HOURS} hours."
                )
                return True
        return False

    def _get_vhd_details(self, vhd_path: str) -> Any:
        matched = STORAGE_CONTAINER_BLOB_PATTERN.match(vhd_path)
        assert matched, f"fail to get matched info from {vhd_path}"
        sc_name = matched.group("sc")
        container_name = matched.group("container")
        blob_name = matched.group("blob")
        storage_client = get_storage_client(self.credential, self.subscription_id)
        # sometimes it will fail for below reason if list storage accounts like this way
        # [x for x in storage_client.storage_accounts.list() if x.name == sc_name]
        # failure - Message: Resource provider 'Microsoft.Storage' failed to return collection response for type 'storageAccounts'.  # noqa: E501
        sc_list = storage_client.storage_accounts.list()
        found_sc = None
        for sc in sc_list:
            if sc.name == sc_name:
                found_sc = sc
                break
        assert (
            found_sc
        ), f"storage account {sc_name} not found in subscription {self.subscription_id}"
        rg = get_matched_str(found_sc.id, RESOURCE_GROUP_PATTERN)
        return {
            "location": found_sc.location,
            "resource_group_name": rg,
            "account_name": sc_name,
            "container_name": container_name,
            "blob_name": blob_name,
        }

    def _generate_data_disks(
        self,
        node: Node,
        azure_node_runbook: AzureNodeArmParameter,
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
        # resolve "latest" to specified version
        marketplace = self._resolve_marketplace_image(location, marketplace)

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

    def _get_vhd_os_disk_size(self, blob_url: str) -> int:
        result_dict = self._get_vhd_details(blob_url)
        container_client = get_or_create_storage_container(
            credential=self.credential,
            subscription_id=self.subscription_id,
            account_name=result_dict["account_name"],
            container_name=result_dict["container_name"],
            resource_group_name=result_dict["resource_group_name"],
        )

        vhd_blob = container_client.get_blob_client(result_dict["blob_name"])
        properties = vhd_blob.get_blob_properties()
        assert properties.size, f"fail to get blob size of {blob_url}"
        # Azure requires only megabyte alignment of vhds, round size up
        # for cases where the size is megabyte aligned
        return math.ceil(properties.size / 1024 / 1024 / 1024)

    def _get_sig_info(
        self, shared_image: SharedImageGallerySchema
    ) -> GalleryImageVersion:
        compute_client = get_compute_client(self)
        return compute_client.gallery_image_versions.get(
            resource_group_name=shared_image.resource_group_name,
            gallery_name=shared_image.image_gallery,
            gallery_image_name=shared_image.image_definition,
            gallery_image_version_name=shared_image.image_version,
            expand="ReplicationStatus",
        )

    @lru_cache(maxsize=10)  # noqa: B019
    def _get_detailed_sig(self, shared_image: SharedImageGallerySchema) -> GalleryImage:
        compute_client = get_compute_client(self)
        return compute_client.gallery_images.get(
            resource_group_name=shared_image.resource_group_name,
            gallery_name=shared_image.image_gallery,
            gallery_image_name=shared_image.image_definition,
        )

    def _get_sig_os_disk_size(self, shared_image: SharedImageGallerySchema) -> int:
        found_image = self._get_sig_info(shared_image)
        assert found_image.storage_profile.os_disk_image.size_in_gb
        return int(found_image.storage_profile.os_disk_image.size_in_gb)

    def _get_normalized_vm_sizes(
        self, name: str, location: str, log: Logger
    ) -> List[str]:
        split_vm_sizes: List[str] = [x.strip() for x in name.split(",")]
        for index, vm_size in enumerate(split_vm_sizes):
            split_vm_sizes[index] = self._get_normalized_vm_size(vm_size, location, log)

        return [x for x in split_vm_sizes if x]

    def _get_normalized_vm_size(self, name: str, location: str, log: Logger) -> str:
        # find predefined vm size on all available's.
        location_info: AzureLocation = self.get_location_info(location, log)
        matched_score: float = 0
        matched_name: str = ""
        matcher = SequenceMatcher(None, name.lower(), "")
        for vm_size in location_info.capabilities:
            matcher.set_seq2(vm_size.lower())
            if name.lower() in vm_size.lower() and matched_score < matcher.ratio():
                matched_name = vm_size
                matched_score = matcher.ratio()

        return matched_name

    def _get_capabilities(
        self, vm_sizes: List[str], location: str, use_max_capability: bool, log: Logger
    ) -> List[AzureCapability]:
        candidate_caps: List[AzureCapability] = []
        caps = self.get_location_info(location, log).capabilities

        for vm_size in vm_sizes:
            # force to use max capability to run test cases as much as possible,
            # or force to support non-exists vm size.
            if use_max_capability:
                candidate_caps.append(self._generate_max_capability(vm_size, location))
                continue

            if vm_size in caps:
                candidate_caps.append(caps[vm_size])

        return candidate_caps

    def _get_matched_capability(
        self,
        requirement: schema.NodeSpace,
        candidate_capabilities: List[AzureCapability],
    ) -> Optional[schema.NodeSpace]:
        matched_cap: Optional[schema.NodeSpace] = None

        # filter allowed vm sizes
        for azure_cap in candidate_capabilities:
            check_result = requirement.check(azure_cap.capability)
            if check_result.result:
                min_cap = self._generate_min_capability(
                    requirement, azure_cap, azure_cap.location
                )

                matched_cap = min_cap
                break

        return matched_cap

    def _get_matched_capabilities(
        self, location: str, nodes_requirement: List[schema.NodeSpace], log: Logger
    ) -> Tuple[List[Union[schema.NodeSpace, bool]], str]:
        # capability or if it's able to wait.
        caps: List[Union[schema.NodeSpace, bool]] = [False] * len(nodes_requirement)
        # one of errors for all requirements. It's enough for troubleshooting.
        error: str = ""

        # get allowed vm sizes. Either it's from the runbook defined, or
        # from subscription supported .
        for req_index, req in enumerate(nodes_requirement):
            candidate_caps, sub_error = self._get_allowed_capabilities(
                req, location, log
            )
            if sub_error:
                # no candidate found, so try next one.
                error = sub_error
                continue

            # filter vm sizes and return two list. 1st is deployable, 2nd is
            # wait able for released resource.
            (
                available_capabilities,
                awaitable_capabilities,
            ) = self._parse_cap_availabilities(candidate_caps)

            # sort vm sizes to match
            available_capabilities = self.get_sorted_vm_sizes(
                available_capabilities, log
            )

            # match vm sizes by capability or use the predefined vm sizes.
            candidate_cap = self._get_matched_capability(req, available_capabilities)
            if candidate_cap:
                caps[req_index] = candidate_cap
            else:
                # the error will be overwritten, if there is vm sizes without
                # quota.
                error = f"no available vm size found on '{location}'."

            if not candidate_cap:
                # check if there is awaitable VMs
                candidate_cap = self._get_matched_capability(
                    req, awaitable_capabilities
                )
                if candidate_cap:
                    # True means awaitable.
                    caps[req_index] = True
                    error = f"no quota found on '{location}'"

        return caps, error

    def _get_allowed_capabilities(
        self, req: schema.NodeSpace, location: str, log: Logger
    ) -> Tuple[List[AzureCapability], str]:
        node_runbook = req.get_extended_runbook(AzureNodeSchema, AZURE)
        error: str = ""
        if node_runbook.vm_size:
            # find the vm_size
            allowed_vm_sizes = self._get_normalized_vm_sizes(
                name=node_runbook.vm_size, location=location, log=log
            )

            # Some preview vm size may not be queried from the list.
            # Force to add.
            if not allowed_vm_sizes:
                log.debug(
                    f"no vm size matched '{node_runbook.vm_size}' on location "
                    f"'{location}', using the raw string as vm size name."
                )
                allowed_vm_sizes = [node_runbook.vm_size]
        else:
            location_info = self.get_location_info(location, log)
            allowed_vm_sizes = [key for key, _ in location_info.capabilities.items()]

        # build the capability of vm sizes. The information is useful to
        # check quota.
        allowed_capabilities = self._get_capabilities(
            vm_sizes=allowed_vm_sizes,
            location=location,
            use_max_capability=node_runbook.maximize_capability,
            log=log,
        )

        if not allowed_capabilities:
            error = f"no vm size found in '{location}' for {allowed_vm_sizes}."

        return allowed_capabilities, error

    def _parse_cap_availabilities(
        self, capabilities: List[AzureCapability]
    ) -> Tuple[List[AzureCapability], List[AzureCapability]]:
        available_capabilities: List[AzureCapability] = []
        awaitable_capabilities: List[AzureCapability] = []

        if not capabilities:
            return ([], [])

        # skip because it needs call azure API.
        if is_unittest():
            return (capabilities, [])

        # assume all vm sizes are in the same location.
        location = capabilities[0].location
        quotas = self._get_quotas(location=location)
        for capability in capabilities:
            quota = quotas.get(capability.vm_size, None)
            if quota:
                remaining, limit = quota
                if limit == 0:
                    # no quota, doesn't need to wait
                    continue
                if remaining > 0:
                    available_capabilities.append(capability)
                else:
                    awaitable_capabilities.append(capability)
            else:
                # not trackable vm size, assume the capability is enough.
                available_capabilities.append(capability)

        return (available_capabilities, awaitable_capabilities)

    def _analyze_environment_availability(
        self, location: str, capabilities: List[Union[schema.NodeSpace, bool]]
    ) -> None:
        # Check if sum of the same capabilities over the cap. If so, mark
        # the overflow cap as True.
        if all(isinstance(x, schema.NodeSpace) for x in capabilities):
            cap_calculator: Dict[str, Tuple[int, int]] = {}
            for index, cap in enumerate(capabilities):
                assert isinstance(cap, schema.NodeSpace), f"actual: {type(cap)}"
                azure_runbook = cap.get_extended_runbook(AzureNodeSchema, AZURE)
                vm_size = azure_runbook.vm_size
                if vm_size not in cap_calculator:
                    cap_calculator[vm_size] = self._get_usage(location, vm_size)
                remaining, limit = cap_calculator[vm_size]
                remaining -= 1
                cap_calculator[vm_size] = (remaining, limit)
                if remaining < 0 and limit > 0:
                    capabilities[index] = True

    @cached(cache=TTLCache(maxsize=50, ttl=10))
    def _get_quotas(self, location: str) -> Dict[str, Tuple[int, int]]:
        """
        The Dict item is: vm size name, Tuple(remaining vm count, limited vm count)
        """
        result: Dict[str, Tuple[int, int]] = dict()

        client = get_compute_client(self)
        usages = client.usage.list(location=location)
        # named map
        quotas_map: Dict[str, Any] = {value.name.value: value for value in usages}

        # This method signature is used to generate cache. If pass in the log
        # object, it makes the cache doesn't work. So create a logger in the
        # method.
        log = get_logger("azure")
        location_info = self.get_location_info(location=location, log=log)
        capabilities = location_info.capabilities

        for vm_size, capability in capabilities.items():
            # looking for quota for each vm size's family, and calculate
            # remaining and limit by core count of vm size.
            quota = quotas_map.get(capability.resource_sku["family"], None)
            if quota:
                limit = math.floor(quota.limit / capability.capability.core_count)
                remaining = math.floor(
                    (quota.limit - quota.current_value)
                    / capability.capability.core_count
                )
                result[vm_size] = (remaining, limit)

        log.debug(f"found {len(result)} vm sizes with quota in location '{location}'.")

        return result

    def _get_usage(self, location: str, vm_size: str) -> Tuple[int, int]:
        """
        The format of return value refer to _get_usages
        """
        if is_unittest():
            return (sys.maxsize, sys.maxsize)

        usages = self._get_quotas(location)
        # The default value is to support force run for non-exists vm size.
        return usages.get(vm_size, (sys.maxsize, sys.maxsize))

    def _resolve_marketplace_image_version(
        self, nodes_requirement: List[schema.NodeSpace]
    ) -> None:
        for req in nodes_requirement:
            node_runbook = req.get_extended_runbook(AzureNodeSchema, AZURE)
            if node_runbook.location and node_runbook.marketplace:
                node_runbook.marketplace = self._resolve_marketplace_image(
                    node_runbook.location, node_runbook.marketplace
                )

    def _add_image_features(self, node_space: schema.NodeSpace) -> None:
        # Load image information, and add to requirements.

        # locations used to query marketplace image information. Some image is not
        # available in all locations, so try several of them.
        _marketplace_image_locations = [
            "westus3",
            "eastus",
            "westus2",
            "eastus2",
            "centraluseuap",
            "eastus2euap",
        ]

        if not node_space:
            return

        if not node_space.features:
            node_space.features = search_space.SetSpace[schema.FeatureSettings](
                is_allow_set=True
            )

        for feature_setting in node_space.features.items:
            if feature_setting.type == features.VhdGenerationSettings.type:
                # if requirement exists, not to add it.
                return

        azure_runbook = node_space.get_extended_runbook(AzureNodeSchema, AZURE)

        if azure_runbook.marketplace:
            for index, location in enumerate(_marketplace_image_locations):
                try:
                    image_info = self._get_image_info(
                        location, azure_runbook.marketplace
                    )
                    break
                except Exception as identifier:
                    # raise exception, if last location failed.
                    if index == len(_marketplace_image_locations) - 1:
                        raise identifier

            generation = _get_vhd_generation(image_info)
            node_space.features.add(features.VhdGenerationSettings(gen=generation))
            node_space.features.add(
                features.ArchitectureSettings(arch=image_info.architecture)
            )
        elif azure_runbook.shared_gallery:
            azure_runbook.shared_gallery = self._parse_shared_gallery_image(
                azure_runbook.shared_gallery
            )
            sig = self._get_detailed_sig(azure_runbook.shared_gallery)
            generation = _get_gallery_image_generation(sig)
            node_space.features.add(features.VhdGenerationSettings(gen=generation))
            node_space.features.add(
                features.ArchitectureSettings(arch=sig.architecture)
            )
        elif azure_runbook.vhd:
            node_space.features.add(
                features.VhdGenerationSettings(gen=azure_runbook.hyperv_generation)
            )
        else:
            ...

    def _load_image_features(self, node_space: schema.NodeSpace) -> None:
        # This method does the same thing as _convert_to_azure_node_space
        # method, and attach the additional features. The additional features
        # need Azure platform, so it needs to be in Azure Platform.
        _convert_to_azure_node_space(node_space)
        self._add_image_features(node_space)


def _convert_to_azure_node_space(node_space: schema.NodeSpace) -> None:
    if not node_space:
        return

    if node_space.features:
        new_settings = search_space.SetSpace[schema.FeatureSettings](is_allow_set=True)

        for current_settings in node_space.features.items:
            # reload to type specified settings
            try:
                settings_type = feature.get_feature_settings_type_by_name(
                    current_settings.type, AzurePlatform.supported_features()
                )
            except NotMeetRequirementException as identifier:
                raise LisaException(
                    f"platform doesn't support all features. {identifier}"
                )
            new_setting = schema.load_by_type(settings_type, current_settings)
            existing_setting = feature.get_feature_settings_by_name(
                new_setting.type, new_settings, True
            )
            if existing_setting:
                new_settings.remove(existing_setting)
                new_setting = existing_setting.intersect(new_setting)

            new_settings.add(new_setting)
        node_space.features = new_settings
    if node_space.disk:
        node_space.disk = schema.load_by_type(
            features.AzureDiskOptionSettings, node_space.disk
        )
    if node_space.network_interface:
        node_space.network_interface = schema.load_by_type(
            schema.NetworkInterfaceOptionSettings, node_space.network_interface
        )


def _get_allowed_locations(nodes_requirement: List[schema.NodeSpace]) -> List[str]:
    existing_locations_str: str = ""
    for req in nodes_requirement:
        # check locations
        # apply azure specified values
        # they will pass into arm template
        node_runbook: AzureNodeSchema = req.get_extended_runbook(AzureNodeSchema, AZURE)
        if node_runbook.location:
            if existing_locations_str:
                # if any one has different location, raise an exception.
                if existing_locations_str != node_runbook.location:
                    raise LisaException(
                        f"predefined node must be in same location, "
                        f"previous: {existing_locations_str}, "
                        f"found: {node_runbook.location}"
                    )
            else:
                existing_locations_str = node_runbook.location

    if existing_locations_str:
        existing_locations = existing_locations_str.split(",")
        existing_locations = [x.strip() for x in existing_locations]
    else:
        existing_locations = LOCATIONS[:]

    return existing_locations


def _get_vhd_generation(image_info: VirtualMachineImage) -> int:
    vhd_gen = 1
    if image_info.hyper_v_generation:
        vhd_gen = int(image_info.hyper_v_generation.strip("V"))

    return vhd_gen


def _get_gallery_image_generation(shared_image: GalleryImage) -> int:
    assert (
        shared_image.hyper_v_generation
    ), f"no hyper_v_generation property for image {shared_image.name}"
    return int(shared_image.hyper_v_generation.strip("V"))
