# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import time
from typing import Any, Dict, Optional, Tuple, Type, cast

from azure.core.exceptions import HttpResponseError
from azure.mgmt.compute.models import VirtualMachineExtension

from lisa import Environment, Logger, Node, schema, simple_requirement
from lisa.environment import EnvironmentStatus
from lisa.features import HibernationEnabled
from lisa.features.availability import AvailabilityTypeNoRedundancy
from lisa.operating_system import OperatingSystem, Windows
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    get_compute_client,
    get_node_context,
    wait_operation,
)
from lisa.sut_orchestrator.azure.features import ArchitectureSettings, AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.testsuite import TestCaseRequirement
from lisa.util import LisaException
from lisa.util.perf_timer import create_timer

from ..vm_extension_base import VmExtensionTestBase
from .hibernate_resume import HibernateResumeValidator

_TYPE_HANDLER_VERSION_PATTERN = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)" r"(?:\.(?P<patch>\d+)(?:\.(?P<revision>\d+))?)?$"
)
HIBERNATE_RESUME_TEST_TIMEOUT_SECONDS = 4 * 60 * 60


def _normalize_type_handler_version(version: str) -> Tuple[str, bool]:
    requested_version = version.strip()
    matched = _TYPE_HANDLER_VERSION_PATTERN.fullmatch(requested_version)
    if not matched:
        raise LisaException(
            "Invalid extension_version format. Expected 'Major.Minor', "
            "'Major.Minor.Patch', or 'Major.Minor.Patch.Revision', "
            f"got '{version}'."
        )
    return (
        f"{matched.group('major')}.{matched.group('minor')}",
        matched.group("patch") is not None,
    )


def _type_handler_versions_equal(expected_version: str, actual_version: str) -> bool:
    def normalize(version: str) -> Optional[Tuple[int, ...]]:
        parts = version.strip().split(".")
        if not parts or any(not part.isdigit() for part in parts):
            return None
        normalized = [int(part) for part in parts]
        while normalized and normalized[-1] == 0:
            normalized.pop()
        return tuple(normalized)

    expected = normalize(expected_version)
    actual = normalize(actual_version)
    return expected is not None and expected == actual


def _type_handler_version_matches_request(
    requested_version: str,
    installed_version: str,
) -> bool:
    requested_major_minor, exact_version_requested = _normalize_type_handler_version(
        requested_version
    )
    try:
        installed_major_minor, _ = _normalize_type_handler_version(installed_version)
    except LisaException:
        return False

    if exact_version_requested:
        return _type_handler_versions_equal(
            requested_version,
            installed_version,
        )
    return requested_major_minor == installed_major_minor


def hibernate_extension_requirement(
    supported_os: Type[OperatingSystem],
) -> TestCaseRequirement:
    return simple_requirement(
        environment_status=EnvironmentStatus.Deployed,
        remote_connection_required=False,
        min_os_disk_size=350,
        supported_features=[
            ArchitectureSettings(arch=schema.ArchitectureType.x64),
            HibernationEnabled(),
            AvailabilityTypeNoRedundancy(),
            AzureExtension,
        ],
        supported_platform_type=[AZURE],
        supported_os=[supported_os],
    )


class HibernateExtensionTestBase(VmExtensionTestBase):
    EXTENSION_RESOURCE_NAME: str = ""
    EXPECTED_INSTANCE_VIEW_TYPES: Tuple[str, ...] = ()
    EXPECTED_OS: Type[OperatingSystem] = OperatingSystem
    PLATFORM_MANAGED: bool = False

    @property
    def extension_name(self) -> str:
        if not self.EXTENSION_RESOURCE_NAME:
            raise LisaException("EXTENSION_RESOURCE_NAME must be configured.")
        return self.EXTENSION_RESOURCE_NAME

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        variables = cast(Dict[str, Any], kwargs["variables"])
        self._validate_extension_identity(variables)
        self._get_version(variables, use_default=False)

    def _validate_extension_identity(self, variables: Dict[str, Any]) -> None:
        expected_values = {
            "extension_publisher": self.PUBLISHER,
            "extension_type": self.EXTENSION_TYPE,
        }
        for variable_name, expected_value in expected_values.items():
            actual_value = str(variables.get(variable_name, "")).strip()
            if actual_value and actual_value.casefold() != expected_value.casefold():
                raise LisaException(
                    f"AzCertify supplied {variable_name}='{actual_value}', "
                    f"but this suite validates '{expected_value}'."
                )

    def _run_hibernate_resume_validation(
        self,
        node: Node,
        log: Logger,
        environment: Environment,
        variables: Dict[str, Any],
    ) -> None:
        installed_candidate = False
        if self.PLATFORM_MANAGED:
            extension_name = self._validate_platform_managed_candidate(
                node,
                log,
                environment,
                variables,
            )
        else:
            self._install_candidate(node, log, environment, variables)
            installed_candidate = True
            extension_name = self.extension_name

        try:
            HibernateResumeValidator(
                node=node,
                log=log,
                environment=environment,
                extension_name=extension_name,
                is_windows=issubclass(self.EXPECTED_OS, Windows),
            ).run()
        finally:
            if installed_candidate:
                self._delete_candidate(node, log, environment)

    def _install_candidate(
        self,
        node: Node,
        log: Logger,
        environment: Environment,
        variables: Dict[str, Any],
    ) -> None:
        _, compute_client = self._get_azure_context(environment)
        node_context = get_node_context(node)
        requested_version = self._get_version(variables, use_default=False)
        install_version, _ = _normalize_type_handler_version(requested_version)
        vm = compute_client.virtual_machines.get(
            resource_group_name=node_context.resource_group_name,
            vm_name=node_context.vm_name,
        )
        parameters = VirtualMachineExtension(
            name=self.extension_name,
            location=vm.location,
            publisher=self.PUBLISHER,
            type_properties_type=self.EXTENSION_TYPE,
            type_handler_version=install_version,
            auto_upgrade_minor_version=True,
            settings={},
        )
        log.info(
            f"Installing extension '{self.extension_name}' "
            f"({self.PUBLISHER}.{self.EXTENSION_TYPE}) version "
            f"'{requested_version}'."
        )
        try:
            create_or_update = (
                compute_client.virtual_machine_extensions.begin_create_or_update
            )
            operation = create_or_update(
                resource_group_name=node_context.resource_group_name,
                vm_name=node_context.vm_name,
                vm_extension_name=self.extension_name,
                extension_parameters=parameters,
            )
            wait_operation(
                operation,
                time_out=25 * 60,
                failure_identity=f"install extension '{self.extension_name}'",
            )
            extension = compute_client.virtual_machine_extensions.get(
                resource_group_name=node_context.resource_group_name,
                vm_name=node_context.vm_name,
                vm_extension_name=self.extension_name,
                expand="instanceView",
            )
            provisioning_state = str(getattr(extension, "provisioning_state", ""))
            if provisioning_state.casefold() != "succeeded":
                raise LisaException(
                    f"Extension '{self.extension_name}' provisioning state is "
                    f"'{provisioning_state}', expected 'Succeeded'."
                )
            instance_view = getattr(extension, "instance_view", None)
            installed_version = str(
                getattr(instance_view, "type_handler_version", "")
                or getattr(extension, "type_handler_version", "")
                or "unknown"
            )
            if not _type_handler_version_matches_request(
                requested_version,
                installed_version,
            ):
                raise LisaException(
                    f"Extension '{self.extension_name}' version mismatch: expected "
                    f"'{requested_version}', actual '{installed_version}'."
                )
            log.info(
                f"Installed extension '{self.extension_name}' version "
                f"'{installed_version}' successfully."
            )
        except Exception:
            self._delete_candidate(
                node,
                log,
                environment,
                ignore_not_found=True,
            )
            raise

    def _delete_candidate(
        self,
        node: Node,
        log: Logger,
        environment: Environment,
        ignore_not_found: bool = False,
    ) -> None:
        _, compute_client = self._get_azure_context(environment)
        node_context = get_node_context(node)
        log.info(f"Removing extension '{self.extension_name}'.")
        try:
            operation = compute_client.virtual_machine_extensions.begin_delete(
                resource_group_name=node_context.resource_group_name,
                vm_name=node_context.vm_name,
                vm_extension_name=self.extension_name,
            )
            wait_operation(
                operation,
                time_out=25 * 60,
                failure_identity=f"remove extension '{self.extension_name}'",
            )
        except HttpResponseError as error:
            if ignore_not_found and getattr(error, "status_code", None) == 404:
                return
            raise

    def _validate_platform_managed_candidate(
        self,
        node: Node,
        log: Logger,
        environment: Environment,
        variables: Dict[str, Any],
    ) -> str:
        requested_version = self._get_version(variables, use_default=False)
        _normalize_type_handler_version(requested_version)
        _, compute_client = self._get_azure_context(environment)
        node_context = get_node_context(node)
        timer = create_timer()
        timeout = 15 * 60
        last_state = ""

        while timer.elapsed(False) < timeout:
            vm = compute_client.virtual_machines.get(
                resource_group_name=node_context.resource_group_name,
                vm_name=node_context.vm_name,
                expand="instanceView",
            )
            instance_view = getattr(vm, "instance_view", None)
            for candidate in getattr(instance_view, "extensions", None) or []:
                extension_name = str(getattr(candidate, "name", ""))
                if extension_name.casefold() != self.extension_name.casefold():
                    continue

                statuses = getattr(candidate, "statuses", None) or []
                provisioning_succeeded = any(
                    str(getattr(status, "code", "")).casefold()
                    == "provisioningstate/succeeded"
                    for status in statuses
                )
                installed_version = str(
                    getattr(candidate, "type_handler_version", "unknown")
                )
                installed_type = str(getattr(candidate, "type", ""))
                last_state = (
                    f"name='{extension_name}', "
                    f"type='{installed_type}', "
                    f"version='{installed_version}', statuses='{statuses}'"
                )
                if not provisioning_succeeded:
                    continue

                if self.EXPECTED_INSTANCE_VIEW_TYPES and not any(
                    installed_type.casefold() == expected_type.casefold()
                    for expected_type in self.EXPECTED_INSTANCE_VIEW_TYPES
                ):
                    raise LisaException(
                        f"Platform-managed extension '{extension_name}' handler "
                        f"type mismatch: expected one of "
                        f"{self.EXPECTED_INSTANCE_VIEW_TYPES}, actual "
                        f"'{installed_type}'."
                    )

                if not _type_handler_version_matches_request(
                    requested_version,
                    installed_version,
                ):
                    raise LisaException(
                        f"Platform-managed extension '{extension_name}' version "
                        f"mismatch: expected '{requested_version}', actual "
                        f"'{installed_version}'."
                    )

                log.info(
                    f"Validated platform-managed extension '{extension_name}' "
                    f"({self.PUBLISHER}.{self.EXTENSION_TYPE}) version "
                    f"'{installed_version}'."
                )
                return extension_name

            time.sleep(10)

        raise LisaException(
            f"Platform-managed extension {self.PUBLISHER}.{self.EXTENSION_TYPE} "
            f"did not reach provisioning state Succeeded within {timeout} "
            f"seconds. Last observed state: {last_state or 'not found'}."
        )

    @staticmethod
    def _get_azure_context(environment: Environment) -> Tuple[AzurePlatform, Any]:
        if not environment.platform:
            raise LisaException("Azure platform is required.")
        platform = cast(AzurePlatform, environment.platform)
        if not isinstance(platform, AzurePlatform):
            raise LisaException("Hibernate extension validation requires Azure.")
        return platform, get_compute_client(platform)
