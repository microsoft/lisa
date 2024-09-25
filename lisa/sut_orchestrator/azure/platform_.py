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
from dataclasses import InitVar, dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from functools import lru_cache, partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Type, Union, cast

import requests
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute.models import (
    CommunityGalleryImage,
    CommunityGalleryImageVersion,
    GalleryImage,
    GalleryImageVersion,
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
from cachetools import TTLCache, cached
from dataclasses_json import dataclass_json
from marshmallow import validate
from msrestazure.azure_cloud import (  # type: ignore
    AZURE_CHINA_CLOUD,
    AZURE_GERMAN_CLOUD,
    AZURE_PUBLIC_CLOUD,
    AZURE_US_GOV_CLOUD,
    Cloud,
)
from packaging.version import parse
from retry import retry

from lisa import feature, schema, search_space
from lisa.environment import Environment
from lisa.features import Disk
from lisa.features.availability import AvailabilityType
from lisa.node import Node, RemoteNode, local
from lisa.platform_ import Platform
from lisa.secret import PATTERN_GUID, add_secret
from lisa.tools import Dmesg, Hostname, KernelConfig, Modinfo, Whoami
from lisa.tools.lsinitrd import Lsinitrd
from lisa.util import (
    KernelPanicException,
    LisaException,
    LisaTimeoutException,
    NotMeetRequirementException,
    ResourceAwaitableException,
    SkippedException,
    check_panic,
    constants,
    dump_file,
    field_metadata,
    generate_strong_password,
    get_datetime_path,
    get_first_combination,
    get_matched_str,
    get_or_generate_key_pairs,
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
    SAS_URL_PATTERN,
    AzureArmParameter,
    AzureCapability,
    AzureLocation,
    AzureNodeArmParameter,
    AzureNodeSchema,
    AzureVmMarketplaceSchema,
    AzureVmPurchasePlanSchema,
    CommunityGalleryImageSchema,
    DataDiskCreateOption,
    DataDiskSchema,
    SharedImageGallerySchema,
    check_or_create_resource_group,
    check_or_create_storage_account,
    convert_to_azure_node_space,
    get_compute_client,
    get_deployable_vhd_path,
    get_environment_context,
    get_marketplace_ordering_client,
    get_node_context,
    get_or_create_storage_container,
    get_primary_ip_addresses,
    get_resource_management_client,
    get_storage_account_name,
    get_vhd_details,
    get_vm,
    global_credential_access_lock,
    load_location_info_from_file,
    save_console_log,
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

KEY_HARDWARE_DISK_CONTROLLER_TYPE = "hardware_disk_controller_type"
KEY_HOST_VERSION = "host_version"
KEY_VM_GENERATION = "vm_generation"
KEY_KERNEL_VERSION = "kernel_version"
KEY_WALA_VERSION = "wala_version"
KEY_WALA_DISTRO_VERSION = "wala_distro"
KEY_HARDWARE_PLATFORM = "hardware_platform"
KEY_MANA_DRIVER_ENABLED = "mana_driver_enabled"
KEY_NVME_ENABLED = "nvme_enabled"
ATTRIBUTE_FEATURES = "features"

CLOUD: Dict[str, Dict[str, Any]] = {
    "azurecloud": AZURE_PUBLIC_CLOUD,
    "azurechinacloud": AZURE_CHINA_CLOUD,
    "azuregermancloud": AZURE_GERMAN_CLOUD,
    "azureusgovernment": AZURE_US_GOV_CLOUD,
}


@dataclass_json()
@dataclass
class CloudEndpointsSchema:
    management: str = ""
    resource_manager: str = ""
    sql_management: str = ""
    batch_resource_id: str = ""
    gallery: str = ""
    active_directory: str = ""
    active_directory_resource_id: str = ""
    active_directory_graph_resource_id: str = ""
    microsoft_graph_resource_id: str = ""


@dataclass_json()
@dataclass
class CloudSuffixesSchema:
    storage_endpoint: str = ""
    keyvault_dns: str = ""
    sql_server_hostname: str = ""
    azure_datalake_store_file_system_endpoint: str = ""
    azure_datalake_analytics_catalog_and_job_endpoint: str = ""


@dataclass_json()
@dataclass
class CloudSchema:
    name: str
    endpoints: CloudEndpointsSchema
    suffixes: CloudSuffixesSchema


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
    cloud_raw: Optional[Union[Dict[str, Any], str]] = field(
        default=None, metadata=field_metadata(data_key="cloud")
    )
    _cloud: InitVar[Cloud] = None

    shared_resource_group_name: str = AZURE_SHARED_RG_NAME
    resource_group_name: str = field(default="")
    # specify shared resource group location
    shared_resource_group_location: str = field(default=RESOURCE_GROUP_LOCATION)
    resource_group_managed_by: str = field(default="")
    # specify the locations which used to retrieve marketplace image information
    # example: westus, westus2
    marketplace_image_information_location: Optional[Union[str, List[str]]] = field(
        default=None
    )
    availability_set_tags: Optional[Dict[str, str]] = field(default=None)
    availability_set_properties: Optional[Dict[str, Any]] = field(default=None)
    availability_zones: Optional[List[int]] = field(default=None)
    availability_type: str = field(
        default=AvailabilityType.Default.value,
        metadata=field_metadata(
            validate=validate.OneOf([type.value for type in AvailabilityType])
        ),
    )
    vm_tags: Optional[Dict[str, Any]] = field(default=None)
    tags: Optional[Dict[str, Any]] = field(default=None)
    use_public_address: bool = field(default=True)

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
                "use_public_address",
            ],
        )

        if self.service_principal_tenant_id:
            add_secret(self.service_principal_tenant_id, mask=PATTERN_GUID)
        if self.subscription_id:
            add_secret(self.subscription_id, mask=PATTERN_GUID)
        if self.service_principal_key:
            add_secret(self.service_principal_key)
        if self.service_principal_client_id:
            add_secret(self.service_principal_client_id, mask=PATTERN_GUID)

    @property
    def cloud(self) -> Cloud:
        # this is a safe guard and prevent mypy error on typing
        if not hasattr(self, "_cloud"):
            self._cloud: Cloud = None
        cloud: Cloud = self._cloud
        if not cloud:
            # if pass str into cloud, it should be one of below values, case insensitive
            #  azurecloud
            #  azurechinacloud
            #  azuregermancloud
            #  azureusgovernment
            # example
            #   cloud: AzureCloud
            if isinstance(self.cloud_raw, str):
                cloud = CLOUD.get(self.cloud_raw.lower(), None)
                assert cloud, (
                    f"cannot find cloud type {self.cloud_raw},"
                    f" current support list is {list(CLOUD.keys())}"
                )
            # if pass dict to construct a cloud instance, the full example is
            #   cloud:
            #     name: AzureCloud
            #     endpoints:
            #       management: https://management.core.windows.net/
            #       resource_manager: https://management.azure.com/
            #       sql_management: https://management.core.windows.net:8443/
            #       batch_resource_id: https://batch.core.windows.net/
            #       gallery: https://gallery.azure.com/
            #       active_directory: https://login.microsoftonline.com
            #       active_directory_resource_id: https://management.core.windows.net/
            #       active_directory_graph_resource_id: https://graph.windows.net/
            #       microsoft_graph_resource_id: https://graph.microsoft.com/
            #     suffixes:
            #       storage_endpoint: core.windows.net
            #       keyvault_dns: .vault.azure.net
            #       sql_server_hostname: .database.windows.net
            #       azure_datalake_store_file_system_endpoint: azuredatalakestore.net
            #       azure_datalake_analytics_catalog_and_job_endpoint: azuredatalakeanalytics.net  # noqa: E501
            elif isinstance(self.cloud_raw, dict):
                cloud_schema = schema.load_by_type(CloudSchema, self.cloud_raw)
                cloud = Cloud(
                    cloud_schema.name, cloud_schema.endpoints, cloud_schema.suffixes
                )
            else:
                # by default use azure public cloud
                cloud = AZURE_PUBLIC_CLOUD
            self._cloud = cloud
        return cloud

    @cloud.setter
    def cloud(self, value: Optional[CloudSchema]) -> None:
        self._cloud = value
        if value is None:
            self.cloud_raw = None
        else:
            self.cloud_raw = value.to_dict()  # type: ignore


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
        self.cloud: Cloud

        # It has to be defined after the class definition is loaded. So it
        # cannot be a class level variable.
        self._environment_information_hooks = {
            KEY_HARDWARE_DISK_CONTROLLER_TYPE: self._get_disk_controller_type,
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
        # This list also determines the order of calls to on_before_deploy
        # Hibernation depends on Availability
        return [
            features.Disk,
            features.AzureExtension,
            features.AzureFileShare,
            features.Gpu,
            features.Nvme,
            features.NestedVirtualization,
            features.CVMNestedVirtualization,
            features.SerialConsole,
            features.NetworkInterface,
            features.PasswordExtension,
            features.Resize,
            features.StartStop,
            features.IaaS,
            features.SecurityProfile,
            features.ACC,
            features.IsolatedResource,
            features.VhdGeneration,
            features.Architecture,
            features.Nfs,
            features.Availability,
            features.Infiniband,
            features.Hibernation,
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
            self._set_image_features(req)

        is_success: bool = False

        # get eligible locations
        allowed_locations = _get_allowed_locations(nodes_requirement)
        log.debug(f"allowed locations: {allowed_locations}")

        # Any to wait for resource
        all_awaitable: bool = False
        errors: List[str] = []

        for location in allowed_locations:
            caps, error = self._get_azure_capabilities(
                location=location, nodes_requirement=nodes_requirement, log=log
            )

            if error:
                errors.append(error)

            # If returns non-zero length array, it means found either available
            # or awaitable for all nodes.
            if caps:
                all_awaitable = True

                # check to return value or raise WaitForMoreResource
                if all(isinstance(x, schema.NodeSpace) for x in caps):
                    # With above condition, all types are NodeSpace. Ignore the
                    # mypy check.
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
            if all_awaitable:
                raise ResourceAwaitableException(
                    "vm size", "No available quota, try to deploy later."
                )
            else:
                raise NotMeetRequirementException(
                    f"{errors}, runbook: {environment.runbook}."
                )

        # resolve Latest to specified version
        if is_success:
            self._resolve_marketplace_image_version(
                environment.runbook.nodes_requirement
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
            environment_context.resource_group_is_specified = True

        environment_context.resource_group_name = resource_group_name

        if self._azure_runbook.dry_run:
            log.info(f"dry_run: {self._azure_runbook.dry_run}")
        else:
            try:
                if (
                    not self._azure_runbook.deploy
                    and not self.runbook.admin_private_key_file
                    and not self.runbook.admin_password
                ):
                    raise LisaException(
                        "admin_private_key_file or admin_password must be "
                        "specified when use existing environment."
                    )

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
                        cloud=self.cloud,
                        resource_group_name=resource_group_name,
                        location=location,
                        log=log,
                        managed_by=self.resource_group_managed_by,
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

    def _save_console_log_and_check_panic(
        self,
        resource_group_name: str,
        environment: Environment,
        log: Logger,
        check_serial_console: bool = False,
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
            if check_serial_console is True:
                check_panic(log_response_content.decode("utf-8"), "provision", log)

    def _get_node_information(self, node: Node) -> Dict[str, str]:
        platform_runbook = cast(schema.Platform, self.runbook)
        information: Dict[str, Any] = {}
        if platform_runbook.capture_vm_information is False:
            return information
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
            if node.capture_kernel_config:
                node.log.debug("detecting mana driver enabled...")
                information[
                    KEY_MANA_DRIVER_ENABLED
                ] = node.nics.is_mana_driver_enabled()
                node.log.debug(f"mana enabled: {information[KEY_MANA_DRIVER_ENABLED]}")
                node.log.debug("detecting nvme driver enabled...")
                _has_nvme_core = node.tools[KernelConfig].is_built_in(
                    "CONFIG_NVME_CORE"
                ) or (
                    node.tools[KernelConfig].is_built_as_module("CONFIG_NVME_CORE")
                    and node.tools[Lsinitrd].has_module("nvme-core.ko")
                )
                _has_nvme = node.tools[KernelConfig].is_built_in(
                    "CONFIG_BLK_DEV_NVME"
                ) or (
                    node.tools[KernelConfig].is_built_as_module("CONFIG_BLK_DEV_NVME")
                    and node.tools[Lsinitrd].has_module("nvme.ko")
                )
                information[KEY_NVME_ENABLED] = _has_nvme_core and _has_nvme
                node.log.debug(f"nvme enabled: {information[KEY_NVME_ENABLED]}")

        node_runbook = node.capability.get_extended_runbook(AzureNodeSchema, AZURE)
        if node_runbook:
            information["location"] = node_runbook.location
            information["vmsize"] = node_runbook.vm_size
            information["image"] = node_runbook.get_image_name()
        information["platform"] = self.type_name()
        return information

    def _get_disk_controller_type(self, node: Node) -> str:
        result: str = ""
        try:
            result = node.features[Disk].get_hardware_disk_controller_type()
        except Exception as identifier:
            # it happens on some error vms. Those error should be caught earlier in
            # test cases not here. So ignore any error here to collect information only.
            node.log.debug(f"error on collecting disk controller type: {identifier}")
        return result

    def _get_kernel_version(self, node: Node) -> str:
        result: str = ""

        if node.is_connected and node.is_posix:
            linux_information = node.tools[Uname].get_linux_information()
            result = linux_information.kernel_version_raw
        elif not node.is_connected or node.is_posix:
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

        # skip for Windows
        if not node.is_connected or node.is_posix:
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

        if not node.is_connected or node.is_posix:
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

        information.update(self._get_platform_information(environment))

        if node:
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
        self.cloud = azure_runbook.cloud
        self.resource_group_managed_by = azure_runbook.resource_group_managed_by

        self._initialize_credential()

        check_or_create_resource_group(
            self.credential,
            self.subscription_id,
            self.cloud,
            azure_runbook.shared_resource_group_name,
            azure_runbook.shared_resource_group_location,
            self._log,
            azure_runbook.resource_group_managed_by,
        )

        self._rm_client = get_resource_management_client(
            self.credential, self.subscription_id, self.cloud
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

            credential = DefaultAzureCredential(
                authority=self.cloud.endpoints.active_directory,
            )

            with SubscriptionClient(
                credential,
                base_url=self.cloud.endpoints.resource_manager,
                credential_scopes=[self.cloud.endpoints.resource_manager + "/.default"],
            ) as self._sub_client:
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
            template_file_name = "autogen_arm_template.json"
            template_file_path = Path(__file__).parent / template_file_name
            with open(template_file_path, "r") as f:
                self._arm_template = json.load(f)
        return self._arm_template

    def get_location_info(self, location: str, log: Logger) -> AzureLocation:
        cached_file_name = constants.CACHE_PATH.joinpath(
            f"azure_locations_{location}.json"
        )
        should_refresh: bool = True
        key = self._get_location_key(location)
        location_data = self._locations_data_cache.get(key, None)
        if not location_data:
            location_data = load_location_info_from_file(
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
                filter=f"location eq '{location}'"
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
            "vm_tags",
            "tags",
        ]
        availability_copied_fields = [
            "availability_set_tags",
            "availability_set_properties",
            "availability_zones",
            "availability_type",
        ]
        set_filtered_fields(self._azure_runbook, arm_parameters, copied_fields)
        set_filtered_fields(
            self._azure_runbook,
            arm_parameters.availability_options,
            availability_copied_fields,
        )

        arm_parameters.virtual_network_resource_group = (
            self._azure_runbook.virtual_network_resource_group
        )
        arm_parameters.subnet_prefix = self._azure_runbook.subnet_prefix
        arm_parameters.virtual_network_name = self._azure_runbook.virtual_network_name

        is_windows: bool = False
        arm_parameters.admin_username = self.runbook.admin_username
        # if no key or password specified, generate the key pair
        if not self.runbook.admin_private_key_file and not self.runbook.admin_password:
            self.runbook.admin_private_key_file = get_or_generate_key_pairs(self._log)

        if self.runbook.admin_private_key_file:
            arm_parameters.admin_key_data = get_public_key_data(
                self.runbook.admin_private_key_file
            )
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

            arm_parameters.is_ultradisk = any(
                [
                    x
                    for x in nodes_parameters
                    if x.data_disk_type
                    == features.get_azure_disk_type(schema.DiskType.UltraSSDLRS)
                ]
            )
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
            node_context.location = arm_parameters.location
            node_context.subscription_id = self.subscription_id
            if azure_node_runbook.is_linux:
                node_context.password = arm_parameters.admin_password
            else:
                is_windows = True
                if not self.runbook.admin_password:
                    # password is required, if it doesn't present, generate one.
                    password = generate_strong_password()
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
        arm_parameters.vhd_storage_name = get_storage_account_name(
            self.subscription_id, arm_parameters.location, "t"
        )

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
        # Order of execution is guaranteed to match
        # the order of supported_features()
        for feature_type, setting in [
            (t, s)
            for t in self.supported_features()
            for s in features_settings.values()
            if t.name() == s.type
        ]:
            feature_type.on_before_deployment(
                arm_parameters=arm_parameters,
                template=template,
                settings=setting,
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
            vhd.vhd_path = get_deployable_vhd_path(
                self, vhd.vhd_path, azure_node_runbook.location, log
            )
            if vhd.vmgs_path:
                vhd.vmgs_path = get_deployable_vhd_path(
                    self, vhd.vmgs_path, azure_node_runbook.location, log
                )
            azure_node_runbook.vhd = vhd
            azure_node_runbook.marketplace = None
            azure_node_runbook.shared_gallery = None
            azure_node_runbook.community_gallery_image = None
            log.debug(
                f"current vhd generation is {azure_node_runbook.hyperv_generation}."
            )
        elif azure_node_runbook.shared_gallery:
            azure_node_runbook.marketplace = None
            azure_node_runbook.community_gallery_image = None
            azure_node_runbook.shared_gallery.resolve_version(self)
            azure_node_runbook.update_raw()
            azure_node_runbook.hyperv_generation = _get_gallery_image_generation(
                azure_node_runbook.shared_gallery.query_platform(self)
            )
        elif azure_node_runbook.community_gallery_image:
            azure_node_runbook.marketplace = None
            azure_node_runbook.community_gallery_image.resolve_version(self)
            azure_node_runbook.update_raw()
            azure_node_runbook.hyperv_generation = _get_gallery_image_generation(
                azure_node_runbook.community_gallery_image.query_platform(self)
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
            image_info = self.get_image_info(
                azure_node_runbook.location, azure_node_runbook.marketplace
            )
            # HyperVGenerationTypes return "V1"/"V2", so we need to strip "V"
            if image_info:
                azure_node_runbook.hyperv_generation = _get_vhd_generation(image_info)
                # retrieve the os type for arm template.
                if (
                    image_info.os_disk_image
                    and image_info.os_disk_image.operating_system == "Windows"
                ):
                    azure_node_runbook.is_linux = False

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
            vhd.vhd_path = get_deployable_vhd_path(
                self, vhd.vhd_path, arm_parameters.location, log
            )
            if vhd.vmgs_path:
                vhd.vmgs_path = get_deployable_vhd_path(
                    self, vhd.vmgs_path, arm_parameters.location, log
                )
            arm_parameters.vhd = vhd
            arm_parameters.osdisk_size_in_gb = max(
                arm_parameters.osdisk_size_in_gb,
                self._get_vhd_os_disk_size(arm_parameters.vhd.vhd_path),
            )
            # purchase plan is needed for vhds created using marketplace images with
            # purchase plans.
            if runbook.purchase_plan:
                arm_parameters.purchase_plan = runbook.purchase_plan
        elif arm_parameters.shared_gallery:
            arm_parameters.osdisk_size_in_gb = max(
                arm_parameters.osdisk_size_in_gb,
                self._get_sig_os_disk_size(arm_parameters.shared_gallery),
            )
        elif arm_parameters.community_gallery_image:
            arm_parameters.osdisk_size_in_gb = max(
                arm_parameters.osdisk_size_in_gb,
                self._get_cgi_os_disk_size(arm_parameters.community_gallery_image),
            )
        else:
            assert (
                arm_parameters.marketplace
            ), "not set one of marketplace, shared_gallery or vhd."
            image_info = self.get_image_info(
                arm_parameters.location, arm_parameters.marketplace
            )
            if image_info:
                assert (
                    image_info.os_disk_image
                ), "'image_info.os_disk_image' must not be 'None'"
                arm_parameters.osdisk_size_in_gb = max(
                    arm_parameters.osdisk_size_in_gb,
                    _get_disk_size_in_gb(
                        image_info.os_disk_image.additional_properties
                    ),
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
        assert isinstance(capability.disk.os_disk_type, schema.DiskType)
        arm_parameters.os_disk_type = features.get_azure_disk_type(
            capability.disk.os_disk_type
        )
        assert isinstance(capability.disk.data_disk_type, schema.DiskType)
        arm_parameters.data_disk_type = features.get_azure_disk_type(
            capability.disk.data_disk_type
        )
        assert isinstance(
            capability.disk.disk_controller_type, schema.DiskControllerType
        )
        if (
            arm_parameters.hyperv_generation == 1
            and capability.disk.disk_controller_type == schema.DiskControllerType.NVME
        ):
            raise SkippedException(
                "Gen 1 image cannot be set to NVMe Disk Controller Type"
            )
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

    @retry(exceptions=ResourceNotFoundError, tries=5, delay=2)
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

            # retry when encounter azure.core.exceptions.ResourceNotFoundError:
            # (ResourceGroupNotFound) Resource group 'lisa-xxxx' could not be found.
            if isinstance(identifier, ResourceNotFoundError) and identifier.error:
                raise identifier

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
            self.cloud,
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
                    self._save_console_log_and_check_panic(
                        resource_group_name, environment, log, False
                    )
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
                try:
                    self._save_console_log_and_check_panic(
                        resource_group_name, environment, log, True
                    )
                except KernelPanicException as ex:
                    if (
                        "OSProvisioningTimedOut: OS Provisioning for VM"
                        in error_message
                    ):
                        error_message = (
                            f"OSProvisioningTimedOut: {type(ex).__name__}: {ex}"
                        )
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
        compute_client = get_compute_client(self)

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
            node_context.use_public_address = self._azure_runbook.use_public_address
            assert isinstance(node, RemoteNode)
            node.set_connection_info(
                address=private_address,
                port=22,
                use_public_address=node_context.use_public_address,
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
        node_space.disk.os_disk_type = search_space.SetSpace[schema.DiskType](
            is_allow_set=True, items=[]
        )
        node_space.disk.data_disk_type = search_space.SetSpace[schema.DiskType](
            is_allow_set=True, items=[]
        )
        node_space.disk.disk_controller_type = search_space.SetSpace[
            schema.DiskControllerType
        ](is_allow_set=True, items=[])
        node_space.disk.data_disk_iops = search_space.IntRange(min=0)
        node_space.disk.data_disk_throughput = search_space.IntRange(min=0)
        node_space.disk.data_disk_size = search_space.IntRange(min=0)
        node_space.network_interface = schema.NetworkInterfaceOptionSettings()
        node_space.network_interface.data_path = search_space.SetSpace[
            schema.NetworkDataPath
        ](is_allow_set=True, items=[])

        # fill supported features
        azure_raw_capabilities: Dict[str, str] = {}
        # "locationInfo": [
        #     {
        #         "location": "southcentralus",
        #         "zoneDetails": [
        #         {
        #             //Represents the zones which support
        #             //the feature (UltraSSDAvailabile)
        #             "Name": [
        #             "3"
        #             ],
        #             "capabilities": [
        #             {
        #                 "name": "UltraSSDAvailable",
        #                 "value": "True"
        #             }
        #             ],
        #             "name": null
        #         }
        #         ],
        #         //Represents the zones which support
        #         //the SKU without any features
        #         "zones": [
        #         "2",
        #         "3",
        #         "1"
        #         ]
        #     }
        # ],
        if resource_sku.location_info:
            for location_info in resource_sku.location_info:
                # Default zones supported
                azure_raw_capabilities["availability_zones"] = location_info.zones
                for zone_details in location_info.zone_details:
                    for location_capability in zone_details.capabilities:
                        azure_raw_capabilities[
                            location_capability.name
                        ] = location_capability.value
                        # Zones supporting the feature
                        if zone_details.additional_properties["Name"]:
                            azure_raw_capabilities[
                                "availability_zones"
                            ] = zone_details.additional_properties["Name"]

        if resource_sku.capabilities:
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
            node_space.disk.os_disk_type.add(schema.DiskType.PremiumSSDLRS)
            node_space.disk.data_disk_type.add(schema.DiskType.PremiumSSDLRS)
            node_space.disk.data_disk_type.add(schema.DiskType.PremiumV2SSDLRS)

        if azure_raw_capabilities.get("UltraSSDAvailable", None) == "True":
            node_space.disk.data_disk_type.add(schema.DiskType.UltraSSDLRS)

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
            cached_disk_bytes_gb = int(int(cached_disk_bytes) / 1024 / 1024 / 1024)
            if cached_disk_bytes_gb >= 30:
                node_space.disk.os_disk_type.add(schema.DiskType.Ephemeral)
                node_space.disk.os_disk_size = cached_disk_bytes_gb

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
            assert resource_sku.family, "'resource_sku.family' must not be 'None'"
            if resource_sku.family.casefold() not in [
                "standarddcsv2family",
                "standardncsv2family",
                "standardncsv3family",
                "standardndsfamily",
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

        assert resource_sku.name, "'resource_sku.name' must not be 'None'"
        # for below vm sizes, there are 2 nics
        # but the accelerated networking can only be applied to a single NIC
        # there is no API to expose this information
        # so hardcode its max nic count to 1
        if (
            schema.NetworkDataPath.Sriov in node_space.network_interface.data_path
            and resource_sku.name
            in [
                "Standard_D2as_v5",
                "Standard_D2a_v4",
                "Standard_D2as_v4",
                "Standard_DS1_v2",
                "Standard_D1_v2",
                "Standard_D2als_v5",
                "Standard_D2ads_v5",
                "Standard_DC2ads_v5",
                "Standard_DC2as_v5",
                "Standard_D2_v3",
                "Standard_D2_v4",
                "Standard_D2s_v3",
                "Standard_D2s_v4",
                "Standard_D2ds_v4",
                "Standard_D2d_v4",
                "Standard_D2ds_v5",
                "Standard_E2s_v3",
                "Standard_E2s_v4",
                "Standard_E2as_v5",
                "Standard_E2d_v4",
                "Standard_E2ads_v5",
                "Standard_E2as_v4",
                "Standard_E2_v3",
                "Standard_E2a_v4",
                "Standard_E2_v5",
                "Standard_E2ds_v4",
                "Standard_EC2as_v5",
                "Standard_E2_v4",
                "Standard_EC2ads_v5",
                "Standard_F1",
                "Standard_F1s",
                "Standard_F2s_v2",
            ]
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

        node_space.disk.os_disk_type.add(schema.DiskType.StandardHDDLRS)
        node_space.disk.os_disk_type.add(schema.DiskType.StandardSSDLRS)
        node_space.disk.data_disk_type.add(schema.DiskType.StandardHDDLRS)
        node_space.disk.data_disk_type.add(schema.DiskType.StandardSSDLRS)
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
                try:
                    versioned_images = compute_client.virtual_machine_images.list(
                        location=location,
                        publisher_name=marketplace.publisher,
                        offer=marketplace.offer,
                        skus=marketplace.sku,
                    )
                    if 0 == len(versioned_images):
                        self._log.debug(
                            f"cannot find any version of image {marketplace.publisher} "
                            f"{marketplace.offer} {marketplace.sku} in {location}"
                        )
                    else:
                        # use the same sort approach as Az CLI.
                        versioned_images.sort(key=lambda x: parse(x.name), reverse=True)
                        new_marketplace.version = versioned_images[0].name
                except ResourceNotFoundError as e:
                    self._log.debug(
                        f"Cannot find any version of image {marketplace.publisher} "
                        f"{marketplace.offer} {marketplace.sku} in {location}:\n {e}"
                    )

        return new_marketplace

    @lru_cache(maxsize=10)  # noqa: B019
    def _process_marketplace_image_plan(
        self,
        marketplace: AzureVmMarketplaceSchema,
        plan_name: str,
        plan_product: str,
        plan_publisher: str,
    ) -> Optional[AzureVmPurchasePlanSchema]:
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
        node_space.disk.os_disk_type = search_space.SetSpace[schema.DiskType](
            is_allow_set=True, items=[]
        )
        node_space.disk.os_disk_type.add(schema.DiskType.PremiumSSDLRS)
        node_space.disk.os_disk_type.add(schema.DiskType.Ephemeral)
        node_space.disk.os_disk_type.add(schema.DiskType.StandardHDDLRS)
        node_space.disk.os_disk_type.add(schema.DiskType.StandardSSDLRS)
        node_space.disk.data_disk_type = search_space.SetSpace[schema.DiskType](
            is_allow_set=True, items=[]
        )
        node_space.disk.data_disk_type.add(schema.DiskType.UltraSSDLRS)
        node_space.disk.data_disk_type.add(schema.DiskType.PremiumV2SSDLRS)
        node_space.disk.data_disk_type.add(schema.DiskType.PremiumSSDLRS)
        node_space.disk.data_disk_type.add(schema.DiskType.StandardHDDLRS)
        node_space.disk.data_disk_type.add(schema.DiskType.StandardSSDLRS)
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
        convert_to_azure_node_space(node_space)

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

    def _generate_data_disks(
        self,
        node: Node,
        azure_node_runbook: AzureNodeArmParameter,
    ) -> List[DataDiskSchema]:
        data_disks: List[DataDiskSchema] = []
        assert node.capability.disk
        if azure_node_runbook.marketplace:
            marketplace = self.get_image_info(
                azure_node_runbook.location, azure_node_runbook.marketplace
            )
            # some images has data disks by default
            # e.g. microsoft-ads linux-data-science-vm linuxdsvm 21.05.27
            # we have to inject below part when dataDisks section added in
            # arm template, otherwise will see below exception:
            #   deployment failed: InvalidParameter: StorageProfile.dataDisks.lun
            #     does not have required value(s) for image specified in
            #     storage profile.
            if marketplace and marketplace.data_disk_images:
                for default_data_disk in marketplace.data_disk_images:
                    data_disks.append(
                        DataDiskSchema(
                            node.capability.disk.data_disk_caching_type,
                            _get_disk_size_in_gb(
                                default_data_disk.additional_properties
                            ),
                            0,
                            0,
                            azure_node_runbook.data_disk_type,
                            DataDiskCreateOption.DATADISK_CREATE_OPTION_TYPE_FROM_IMAGE,
                        )
                    )
        assert isinstance(
            node.capability.disk.data_disk_count, int
        ), f"actual: {type(node.capability.disk.data_disk_count)}"
        for _ in range(node.capability.disk.data_disk_count):
            assert isinstance(
                node.capability.disk.data_disk_size, int
            ), f"actual: {type(node.capability.disk.data_disk_size)}"
            assert isinstance(
                node.capability.disk.data_disk_iops, int
            ), f"actual: {type(node.capability.disk.data_disk_iops)}"
            assert isinstance(
                node.capability.disk.data_disk_throughput, int
            ), f"actual: {type(node.capability.disk.data_disk_throughput)}"
            data_disks.append(
                DataDiskSchema(
                    node.capability.disk.data_disk_caching_type,
                    node.capability.disk.data_disk_size,
                    node.capability.disk.data_disk_iops,
                    node.capability.disk.data_disk_throughput,
                    azure_node_runbook.data_disk_type,
                    DataDiskCreateOption.DATADISK_CREATE_OPTION_TYPE_EMPTY,
                )
            )
        runbook = node.capability.get_extended_runbook(AzureNodeSchema)
        if node.capability.disk and isinstance(
            node.capability.disk.max_data_disk_count, int
        ):
            max_data_disk_count = node.capability.disk.max_data_disk_count
            if len(data_disks) > max_data_disk_count:
                raise SkippedException(
                    f"image {runbook.get_image_name()} "
                    f"needs {len(data_disks)} data disks, "
                    f"current VM size {runbook.vm_size} "
                    f"only offers {node.capability.disk.max_data_disk_count} data disks"
                )
        return data_disks

    @lru_cache(maxsize=10)  # noqa: B019
    def get_image_info(
        self, location: str, marketplace: Optional[AzureVmMarketplaceSchema]
    ) -> Optional[VirtualMachineImage]:
        # resolve "latest" to specified version
        marketplace = self._resolve_marketplace_image(location, marketplace)

        compute_client = get_compute_client(self)
        assert isinstance(marketplace, AzureVmMarketplaceSchema)
        image_info = None
        with global_credential_access_lock:
            try:
                image_info = compute_client.virtual_machine_images.get(
                    location=location,
                    publisher_name=marketplace.publisher,
                    offer=marketplace.offer,
                    skus=marketplace.sku,
                    version=marketplace.version,
                )
            except HttpResponseError as e:
                # Code: ImageVersionDeprecated
                if "ImageVersionDeprecated" in str(e):
                    raise e
                self._log.debug(f"Could not find image info:\n {e}")
        return image_info

    def _get_location_key(self, location: str) -> str:
        return f"{self.subscription_id}_{location}"

    def _enable_ssh_on_windows(self, node: Node) -> None:
        runbook = node.capability.get_extended_runbook(AzureNodeSchema)
        if runbook.is_linux:
            return

        context = get_node_context(node)

        remote_node = cast(RemoteNode, node)

        node_ssh_port = remote_node.connection_info[
            constants.ENVIRONMENTS_NODES_REMOTE_PORT
        ]
        log = node.log
        log.debug(
            f"checking if SSH port {node_ssh_port} is reachable "
            f"on {remote_node.name}..."
        )

        connected, _ = wait_tcp_port_ready(
            address=remote_node.connection_info[
                constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS
            ],
            port=remote_node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_PORT],
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
        matches = SAS_URL_PATTERN.match(blob_url)
        if matches:
            response = requests.head(blob_url, timeout=60)
            if response and response.status_code == 200:
                size_in_bytes = int(response.headers["Content-Length"])
                vhd_os_disk_size = math.ceil(size_in_bytes / 1024 / 1024 / 1024)
                assert isinstance(
                    vhd_os_disk_size, int
                ), f"actual: {type(vhd_os_disk_size)}"
                return vhd_os_disk_size

        result_dict = get_vhd_details(self, blob_url)
        container_client = get_or_create_storage_container(
            credential=self.credential,
            cloud=self.cloud,
            account_name=result_dict["account_name"],
            container_name=result_dict["container_name"],
        )

        vhd_blob = container_client.get_blob_client(result_dict["blob_name"])
        properties = vhd_blob.get_blob_properties()
        assert properties.size, f"fail to get blob size of {blob_url}"
        # Azure requires only megabyte alignment of vhds, round size up
        # for cases where the size is megabyte aligned
        vhd_os_disk_size = math.ceil(properties.size / 1024 / 1024 / 1024)
        assert isinstance(vhd_os_disk_size, int), f"actual: {type(vhd_os_disk_size)}"
        return vhd_os_disk_size

    def _get_sig_version(
        self, shared_image: SharedImageGallerySchema
    ) -> GalleryImageVersion:
        compute_client = get_compute_client(
            self, subscription_id=shared_image.subscription_id
        )
        sig_version = compute_client.gallery_image_versions.get(
            resource_group_name=shared_image.resource_group_name,
            gallery_name=shared_image.image_gallery,
            gallery_image_name=shared_image.image_definition,
            gallery_image_version_name=shared_image.image_version,
            expand="ReplicationStatus",
        )
        assert isinstance(
            sig_version, GalleryImageVersion
        ), f"actual: {type(sig_version)}"
        return sig_version

    @lru_cache(maxsize=10)  # noqa: B019
    def _get_cgi_version(
        self, community_gallery_image: CommunityGalleryImageSchema
    ) -> CommunityGalleryImageVersion:
        compute_client = get_compute_client(self)
        cgi_version = compute_client.community_gallery_image_versions.get(
            location=community_gallery_image.location,
            public_gallery_name=community_gallery_image.image_gallery,
            gallery_image_name=community_gallery_image.image_definition,
            gallery_image_version_name=community_gallery_image.image_version,
        )
        assert isinstance(
            cgi_version, CommunityGalleryImageVersion
        ), f"actual: {type(cgi_version)}"
        return cgi_version

    @lru_cache(maxsize=10)  # noqa: B019
    def _get_cgi(
        self, community_gallery_image: CommunityGalleryImageSchema
    ) -> CommunityGalleryImage:
        compute_client = get_compute_client(self)
        cgi = compute_client.community_gallery_images.get(
            location=community_gallery_image.location,
            public_gallery_name=community_gallery_image.image_gallery,
            gallery_image_name=community_gallery_image.image_definition,
        )
        assert isinstance(cgi, CommunityGalleryImage), f"actual: {type(cgi)}"
        return cgi

    def _get_sig_os_disk_size(self, shared_image: SharedImageGallerySchema) -> int:
        found_image = self._get_sig_version(shared_image)
        assert found_image.storage_profile, "'storage_profile' must not be 'None'"
        assert (
            found_image.storage_profile.os_disk_image
        ), "'os_disk_image' must not be 'None'"
        assert (
            found_image.storage_profile.os_disk_image.size_in_gb
        ), "'size_in_gb' must not be 'None'"
        return int(found_image.storage_profile.os_disk_image.size_in_gb)

    def _get_cgi_os_disk_size(
        self, community_gallery_image: CommunityGalleryImageSchema
    ) -> int:
        found_image = self._get_cgi_version(community_gallery_image)
        storage_profile = found_image.storage_profile  # type: ignore
        assert storage_profile, "'storage_profile' must not be 'None'"
        assert storage_profile.os_disk_image, "'os_disk_image' must not be 'None'"
        assert (
            storage_profile.os_disk_image.disk_size_gb
        ), "'disk_size_gb' must not be 'None'"
        return int(storage_profile.os_disk_image.disk_size_gb)

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
                cap_features = caps[vm_size].capability.features
                # Azure platform offers SaaS, PaaS, IaaS.
                # VMs can only been created with the VM Skus which have IaaS capability.
                # Below exception will be thrown out
                # if the VM Sku doesn't provide IaaS capability.
                # BadRequest: Requested operation cannot be performed because VM size
                # XXX does not support IaaS deployments.
                if not cap_features or (
                    cap_features
                    and [x for x in cap_features if features.IaaS.name() == x.type]
                ):
                    candidate_caps.append(caps[vm_size])

        return candidate_caps

    def _get_meet_capabilities(
        self, item: Any
    ) -> Iterable[Union[schema.NodeSpace, bool]]:
        requirement, candidates = item

        # assertion for type checks
        assert isinstance(requirement, schema.NodeSpace)
        assert isinstance(candidates, list)

        # filter allowed vm sizes
        for azure_cap in candidates:
            check_result = requirement.check(azure_cap.capability)
            if check_result.result:
                min_cap = self._generate_min_capability(
                    requirement, azure_cap, azure_cap.location
                )
                yield min_cap

        return False

    def _get_azure_capabilities(
        self, location: str, nodes_requirement: List[schema.NodeSpace], log: Logger
    ) -> Tuple[List[Union[AzureCapability, bool]], str]:
        # one of errors for all requirements. It's enough for troubleshooting.
        error: str = ""

        # All candidates for each requirement. The values are node_requirement,
        # capabilities.
        available_candidates: List[Any] = []
        awaitable_candidates: List[Any] = []

        # get allowed vm sizes. Either it's from the runbook defined, or
        # from subscription supported.
        for req in nodes_requirement:
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
            ) = self._get_available_azure_capabilities(candidate_caps, log)

            # Sort available vm sizes to match. Awaitable doesn't need to be
            # sorted.
            available_capabilities = self.get_sorted_vm_sizes(
                available_capabilities, log
            )
            available_candidates.append([req, available_capabilities])
            awaitable_candidates.append(
                [req, available_capabilities + awaitable_capabilities]
            )

        results: List[Union[AzureCapability, bool]] = []

        # get available vm sizes
        found = get_first_combination(
            items=available_candidates,
            index=0,
            results=results,
            check=partial(
                self._check_environment_available, location=location, log=log
            ),
            next_value=self._get_meet_capabilities,
            can_early_stop=True,
        )

        if len(results) < len(nodes_requirement):
            # not found enough vm sizes, so mark it as not found
            results = []
            found = False

        # if no available vm size, get awaitable vm sizes, It doesn't need to
        # check quota again, because it's already checked in _get_meet_capabilities.
        if not found:
            found = get_first_combination(
                items=awaitable_candidates,
                index=0,
                results=results,
                check=lambda x: True,
                next_value=self._get_meet_capabilities,
                can_early_stop=True,
            )

            if found:
                # for awaitable resources, it returns true. So it can be different
                # with available resources in the caller.
                results = [True] * len(results)

        if len(results) < len(nodes_requirement):
            # not found enough vm sizes, so mark it as not found
            results = []
            found = False

        if not found:
            error = f"no available quota found on '{location}'."

        return results, error

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

    def _get_available_azure_capabilities(
        self, capabilities: List[AzureCapability], log: Logger
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
        for capability in capabilities:
            quota = self._get_vm_size_remaining_usage(
                location=location, vm_size=capability.vm_size, log=log
            )
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

    def _check_environment_available(
        self,
        capabilities: List[Union[schema.NodeSpace, bool]],
        location: str,
        log: Logger,
    ) -> bool:
        # Check if sum of the same capabilities over the cap. If so, mark
        # the overflow cap as True.
        if all(isinstance(x, schema.NodeSpace) for x in capabilities):
            cap_calculator: Dict[str, Tuple[int, int]] = {}
            for cap in capabilities:
                assert isinstance(cap, schema.NodeSpace), f"actual: {type(cap)}"
                azure_runbook = cap.get_extended_runbook(AzureNodeSchema, AZURE)
                vm_size = azure_runbook.vm_size
                if vm_size not in cap_calculator:
                    cap_calculator[vm_size] = self._get_vm_size_remaining_usage(
                        location, vm_size, log=log
                    )
                remaining, limit = cap_calculator[vm_size]
                remaining -= 1
                cap_calculator[vm_size] = (remaining, limit)
                if remaining < 0 and limit > 0:
                    return False

            return True

        # not all have the capability
        return False

    @cached(cache=TTLCache(maxsize=50, ttl=10))
    def _get_vm_family_remaining_usages(
        self, location: str
    ) -> Dict[str, Tuple[int, int]]:
        """
        The Dict item is: vm family name, Tuple(remaining cpu count, limited cpu count)
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

        for family, quota in quotas_map.items():
            # looking for quota for each vm size's family, and calculate
            # remaining and limit by core count of vm size.
            result[family] = ((quota.limit - quota.current_value), quota.limit)

        log.debug(
            f"found {len(result)} vm families with quota in location '{location}'."
        )

        return result

    def _get_vm_size_remaining_usage(
        self, location: str, vm_size: str, log: Logger
    ) -> Tuple[int, int]:
        """
        The format of return value refer to _get_remaining_usages
        """
        if is_unittest():
            return (sys.maxsize, sys.maxsize)

        family_usages = self._get_vm_family_remaining_usages(location)
        location_info = self.get_location_info(location=location, log=log)
        vm_size_info = location_info.capabilities.get(vm_size, None)
        if vm_size_info:
            family = vm_size_info.resource_sku["family"]
            family_usage = family_usages.get(family, (sys.maxsize, sys.maxsize))

            core_count = vm_size_info.capability.core_count
            assert isinstance(core_count, int), f"actual: {type(core_count)}"

            remaining = int(math.floor(family_usage[0] / core_count))
            limit = int(math.floor(family_usage[1] / core_count))
        else:
            # not trackable vm size, assume the capability is enough.
            remaining = sys.maxsize
            limit = sys.maxsize

        # The default value is to support force run for non-exists vm size.
        return (remaining, limit)

    def _resolve_marketplace_image_version(
        self, nodes_requirement: List[schema.NodeSpace]
    ) -> None:
        for req in nodes_requirement:
            node_runbook = req.get_extended_runbook(AzureNodeSchema, AZURE)
            if node_runbook.location and node_runbook.marketplace:
                node_runbook.marketplace = self._resolve_marketplace_image(
                    node_runbook.location, node_runbook.marketplace
                )

    def find_marketplace_image_location(self) -> List[str]:
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

        if self._azure_runbook.marketplace_image_information_location:
            if isinstance(
                self._azure_runbook.marketplace_image_information_location, str
            ):
                _marketplace_image_locations = [
                    self._azure_runbook.marketplace_image_information_location
                ]
            else:
                _marketplace_image_locations = (
                    self._azure_runbook.marketplace_image_information_location
                )
        return _marketplace_image_locations

    def _add_image_features(self, node_space: schema.NodeSpace) -> None:
        # Load image information, and add to requirements.

        if not node_space:
            return

        if not node_space.features:
            node_space.features = search_space.SetSpace[schema.FeatureSettings](
                is_allow_set=True
            )

        azure_runbook = node_space.get_extended_runbook(AzureNodeSchema, AZURE)
        image = azure_runbook.image
        if not image:
            return
        # Default to provided hyperv_generation,
        # but will be overrriden if the image is tagged
        image.hyperv_generation = azure_runbook.hyperv_generation
        image.load_from_platform(self)

        # Create Image requirements for each Feature
        for feat in self.supported_features():
            image_req = feat.create_image_requirement(image)
            if not image_req:
                continue
            # Merge with existing requirements
            node_cap = node_space._find_feature_by_type(
                image_req.type, node_space.features
            )
            if node_cap:
                node_space.features.remove(node_cap)
                node_space.features.add(node_cap.intersect(image_req))
            else:
                node_space.features.add(image_req)

        # Set Disk features
        if node_space.disk:
            self._set_disk_features(node_space, azure_runbook)

    def _set_disk_features(
        self, node_space: schema.NodeSpace, azure_runbook: AzureNodeSchema
    ) -> None:
        assert node_space.disk
        assert node_space.disk.os_disk_type
        assert azure_runbook.image
        if (
            isinstance(node_space.disk.os_disk_type, schema.DiskType)
            and schema.DiskType.Ephemeral == node_space.disk.os_disk_type
        ) or (
            isinstance(node_space.disk.os_disk_type, search_space.SetSpace)
            and node_space.disk.os_disk_type.isunique(schema.DiskType.Ephemeral)
        ):
            node_space.disk.os_disk_size = search_space.IntRange(
                min=self._get_os_disk_size(azure_runbook)
            )

        # Set Disk Controller Type based on image capabilities
        if isinstance(node_space.disk.disk_controller_type, schema.DiskControllerType):
            node_space.disk.disk_controller_type = search_space.SetSpace[
                schema.DiskControllerType
            ](is_allow_set=True, items=[node_space.disk.disk_controller_type])
        if isinstance(
            azure_runbook.image.disk_controller_type, schema.DiskControllerType
        ):
            azure_runbook.image.disk_controller_type = search_space.SetSpace[
                schema.DiskControllerType
            ](is_allow_set=True, items=[azure_runbook.image.disk_controller_type])

        allowed_types = azure_runbook.image.disk_controller_type
        if node_space.disk.disk_controller_type:
            allowed_types = search_space.intersect_setspace_by_priority(
                node_space.disk.disk_controller_type,  # type: ignore
                azure_runbook.image.disk_controller_type,  # type: ignore
                [],
            )
        node_space.disk.disk_controller_type = allowed_types

    def _get_os_disk_size(self, azure_runbook: AzureNodeSchema) -> int:
        assert azure_runbook
        if azure_runbook.marketplace:
            for location in self.find_marketplace_image_location():
                image_info = self.get_image_info(location, azure_runbook.marketplace)
                if image_info:
                    break
            if image_info and image_info.os_disk_image:
                return _get_disk_size_in_gb(
                    image_info.os_disk_image.additional_properties
                )
            else:
                # if no image info, use default size 30
                return 30
        elif azure_runbook.shared_gallery:
            azure_runbook.shared_gallery.resolve_version(self)
            azure_runbook.update_raw()
            return self._get_sig_os_disk_size(azure_runbook.shared_gallery)
        elif azure_runbook.community_gallery_image:
            azure_runbook.community_gallery_image.resolve_version(self)
            azure_runbook.update_raw()
            return self._get_cgi_os_disk_size(azure_runbook.community_gallery_image)
        else:
            assert azure_runbook.vhd
            assert azure_runbook.vhd.vhd_path
            return self._get_vhd_os_disk_size(azure_runbook.vhd.vhd_path)

    def _check_image_capability(self, node_space: schema.NodeSpace) -> None:
        azure_runbook = node_space.get_extended_runbook(AzureNodeSchema, AZURE)
        if azure_runbook.vhd:
            if node_space.network_interface:
                data_path = search_space.intersect_setspace_by_priority(  # type: ignore
                    node_space.network_interface.data_path,
                    azure_runbook.vhd.network_data_path,
                    [],
                )
                node_space.network_interface.data_path = data_path

    def _set_image_features(self, node_space: schema.NodeSpace) -> None:
        # This method does the same thing as convert_to_azure_node_space
        # method, and attach the additional features. The additional features
        # need Azure platform, so it needs to be in Azure Platform.
        convert_to_azure_node_space(node_space)
        self._add_image_features(node_space)
        self._check_image_capability(node_space)


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


def _get_gallery_image_generation(
    image: Union[GalleryImage, CommunityGalleryImage]
) -> int:
    assert (
        hasattr(image, "hyper_v_generation") and image.hyper_v_generation
    ), f"no hyper_v_generation property for image {image.name}"
    return int(image.hyper_v_generation.strip("V"))


def _get_disk_size_in_gb(additional_properties: Dict[str, int]) -> int:
    osdisk_size_in_gb = additional_properties.get("sizeInGb", 0)
    if not osdisk_size_in_gb:
        osdisk_size_in_gb = round(
            additional_properties.get("sizeInBytes", 0) / 1024 / 1024 / 1024
        )

    return osdisk_size_in_gb
