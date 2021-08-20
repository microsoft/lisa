# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type

import requests
from assertpy import assert_that
from dataclasses_json import dataclass_json

from lisa import features, schema, search_space
from lisa.features.gpu import ComputeSDK
from lisa.node import Node
from lisa.operating_system import CentOs, Redhat, Suse, Ubuntu
from lisa.sut_orchestrator.azure.common import AZURE, AzureNodeSchema
from lisa.util import LisaException

if TYPE_CHECKING:
    from .platform_ import AzurePlatform

from .common import (
    get_compute_client,
    get_network_client,
    get_node_context,
    wait_operation,
)


class AzureFeatureMixin:
    def _initialize_information(self, node: Node) -> None:
        node_context = get_node_context(node)
        self._vm_name = node_context.vm_name
        self._resource_group_name = node_context.resource_group_name


class StartStop(AzureFeatureMixin, features.StartStop):
    def _stop(self, wait: bool = True) -> Any:
        return self._execute(wait, "begin_deallocate")

    def _start(self, wait: bool = True) -> Any:
        return self._execute(wait, "begin_start")

    def _restart(self, wait: bool = True) -> Any:
        return self._execute(wait, "begin_restart")

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)

    def _execute(self, wait: bool, operator: str) -> Any:
        platform: AzurePlatform = self._platform  # type: ignore
        # The latest version may not be deployed to server side, use specified version.
        compute_client = get_compute_client(platform, api_version="2020-06-01")
        operator_method = getattr(compute_client.virtual_machines, operator)
        result = operator_method(
            resource_group_name=self._resource_group_name, vm_name=self._vm_name
        )
        if wait:
            result = wait_operation(result)
        return result


class SerialConsole(AzureFeatureMixin, features.SerialConsole):
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)

    def _get_console_log(self, saved_path: Optional[Path]) -> bytes:
        platform: AzurePlatform = self._platform  # type: ignore
        compute_client = get_compute_client(platform)
        diagnostic_data = (
            compute_client.virtual_machines.retrieve_boot_diagnostics_data(
                resource_group_name=self._resource_group_name, vm_name=self._vm_name
            )
        )
        if saved_path:
            screenshot_name = saved_path.joinpath("serial_console.bmp")
            screenshot_response = requests.get(
                diagnostic_data.console_screenshot_blob_uri
            )
            with open(screenshot_name, mode="wb") as f:
                f.write(screenshot_response.content)

        log_response = requests.get(diagnostic_data.serial_console_log_blob_uri)

        return log_response.content


class Gpu(AzureFeatureMixin, features.Gpu):
    grid_supported_skus = ["Standard_NV"]
    cuda_supported_skus = ["Standard_NC", "Standard_ND"]

    def is_supported(self) -> bool:
        # TODO: more supportability can be defined here
        supported_distro = (CentOs, Redhat, Ubuntu, Suse)
        if isinstance(self._node.os, supported_distro):
            return True

        return False

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)

    def _get_supported_driver(self) -> List[ComputeSDK]:
        driver_list = []
        node_runbook = self._node.capability.get_extended_runbook(
            AzureNodeSchema, AZURE
        )
        if any(map((node_runbook.vm_size).__contains__, self.grid_supported_skus)):
            driver_list.append(ComputeSDK.GRID)
        if any(map((node_runbook.vm_size).__contains__, self.cuda_supported_skus)):
            driver_list.append(ComputeSDK.CUDA)

        if not driver_list:
            raise LisaException(
                "No valid Compute SDK found to install for the VM size -"
                f" {node_runbook.vm_size}."
            )
        return driver_list


class Sriov(AzureFeatureMixin, features.Sriov):
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)

    def _switch(self, enable: bool) -> None:
        azure_platform: AzurePlatform = self._platform  # type: ignore
        network_client = get_network_client(azure_platform)
        compute_client = get_compute_client(azure_platform)
        vm = compute_client.virtual_machines.get(
            self._resource_group_name, self._node.name
        )
        for nic in vm.network_profile.network_interfaces:
            # get nic name from nic id
            # /subscriptions/[subid]/resourceGroups/[rgname]/providers
            # /Microsoft.Network/networkInterfaces/[nicname]
            nic_name = nic.id.split("/")[-1]
            updated_nic = network_client.network_interfaces.get(
                self._resource_group_name, nic_name
            )
            if updated_nic.enable_accelerated_networking == enable:
                self._log.debug(
                    f"network interface {nic_name}'s accelerated networking default "
                    f"status [{updated_nic.enable_accelerated_networking}] is "
                    f"consistent with set status [{enable}], no need to update."
                )
            else:
                self._log.debug(
                    f"network interface {nic_name}'s accelerated networking default "
                    f"status [{updated_nic.enable_accelerated_networking}], "
                    f"now set its status into [{enable}]."
                )
                updated_nic.enable_accelerated_networking = enable
                network_client.network_interfaces.begin_create_or_update(
                    self._resource_group_name, updated_nic.name, updated_nic
                )
                updated_nic = network_client.network_interfaces.get(
                    self._resource_group_name, nic_name
                )
                assert_that(updated_nic.enable_accelerated_networking).described_as(
                    f"fail to set network interface {nic_name}'s accelerated "
                    f"networking into status [{enable}]"
                ).is_equal_to(enable)

    def enabled(self) -> bool:
        azure_platform: AzurePlatform = self._platform  # type: ignore
        network_client = get_network_client(azure_platform)
        compute_client = get_compute_client(azure_platform)
        sriov_enabled: bool = False
        vm = compute_client.virtual_machines.get(
            self._resource_group_name, self._node.name
        )
        found_primary = False
        for nic in vm.network_profile.network_interfaces:
            if nic.primary:
                found_primary = True
                break
        if not found_primary:
            raise LisaException(f"fail to find primary nic for vm {self._node.name}")
        nic_name = nic.id.split("/")[-1]
        primary_nic = network_client.network_interfaces.get(
            self._resource_group_name, nic_name
        )
        sriov_enabled = primary_nic.enable_accelerated_networking
        return sriov_enabled


class Nvme(AzureFeatureMixin, features.Nvme):
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)


# disk types are ordered by commonly and cost. The earlier is lower cost.
_ordered_disk_types: List[schema.DiskType] = [
    schema.DiskType.StandardHDDLRS,
    schema.DiskType.StandardSSDLRS,
    schema.DiskType.Ephemeral,
    schema.DiskType.PremiumLRS,
]


@dataclass_json()
@dataclass()
class AzureDiskOptionSettings(schema.DiskOptionSettings):
    def __hash__(self) -> int:
        return super().__hash__()

    # It uses to override requirement operations.
    def check(self, capability: Any) -> search_space.ResultReason:
        assert isinstance(
            capability, AzureDiskOptionSettings
        ), f"actual: {type(capability)}"
        result = super().check(capability)

        if self.disk_type is not None and (
            capability is None or capability.disk_type is None
        ):
            result.add_reason("capability doesn't have disk_type.")

        if self.disk_type:
            has_meet_disk_type = False
            if isinstance(self.disk_type, schema.DiskType):
                req_disk_types = search_space.SetSpace[schema.DiskType](
                    items=[self.disk_type]
                )
            else:
                req_disk_types = self.disk_type
            for req_disk_type in req_disk_types:
                if isinstance(capability.disk_type, schema.DiskType):
                    if req_disk_type == capability.disk_type:
                        has_meet_disk_type = True
                        break
                else:
                    assert isinstance(capability.disk_type, search_space.SetSpace)
                    if req_disk_type in capability.disk_type:
                        has_meet_disk_type = True
                        break
            if not has_meet_disk_type:
                result.add_reason(
                    f"no disk type supported in capability. "
                    f"requirement: {self.disk_type}, "
                    f"capability: {capability.disk_type}"
                )

        return result

    def _generate_min_capability(self, capability: Any) -> Any:
        assert isinstance(
            capability, AzureDiskOptionSettings
        ), f"actual: {type(capability)}"
        assert (
            capability.disk_type
        ), "capability should have at least one disk type, but it's None"
        cap_disk_type = capability.disk_type
        if isinstance(cap_disk_type, search_space.SetSpace):
            assert (
                len(cap_disk_type) > 0
            ), "capability should have at least one disk type, but it's empty"
        elif isinstance(cap_disk_type, schema.DiskType):
            cap_disk_type = search_space.SetSpace[schema.DiskType](
                is_allow_set=True, items=[cap_disk_type]
            )
        else:
            raise LisaException(
                f"unknown disk type on capability, type: {cap_disk_type}"
            )

        # if there is no requirement, copy capability to get min one.
        if self.disk_type is None:
            req_disk_type = capability.disk_type
        else:
            req_disk_type = self.disk_type

        # find the min disk type from the order by cost.
        min_disk_type: Optional[schema.DiskType] = None
        for expected_disk_type in _ordered_disk_types:
            if (
                expected_disk_type in req_disk_type
                and expected_disk_type in capability.disk_type
            ):
                min_disk_type = expected_disk_type
                break
        assert min_disk_type, (
            "Cannot find min capability on disk type, "
            f"requirement: {self.disk_type}"
            f"capability: {capability.disk_type}"
        )
        min_cap = AzureDiskOptionSettings(disk_type=min_disk_type)

        return min_cap


class Disk(AzureFeatureMixin, features.Disk):
    """
    This Disk feature is mainly to associate Azure disk options settings.
    """

    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return AzureDiskOptionSettings

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)


__disk_type_mapping: Dict[schema.DiskType, str] = {
    schema.DiskType.PremiumLRS: "Premium_LRS",
    schema.DiskType.Ephemeral: "Ephemeral",
    schema.DiskType.StandardHDDLRS: "Standard_LRS",
    schema.DiskType.StandardSSDLRS: "StandardSSD_LRS",
}


def get_azure_disk_type(disk_type: schema.DiskType) -> str:
    assert isinstance(disk_type, schema.DiskType), (
        f"the disk_type must be one value when calling get_disk_type. "
        f"But it's {disk_type}"
    )

    result = __disk_type_mapping.get(disk_type, None)
    assert result, f"unkonwn disk type: {disk_type}"

    return result
