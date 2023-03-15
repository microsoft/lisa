# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import asyncio
import copy
import json
import re
import string
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from random import randint
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Type, Union, cast

import websockets
from assertpy import assert_that
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ResourceExistsError,
    ResourceNotFoundError,
    map_error,
)
from azure.mgmt.compute.models import (  # type: ignore
    DiskCreateOption,
    DiskCreateOptionTypes,
    HardwareProfile,
    NetworkInterfaceReference,
    VirtualMachineExtension,
    VirtualMachineUpdate,
)
from azure.mgmt.core.exceptions import ARMErrorFormat
from azure.mgmt.serialconsole import MicrosoftSerialConsoleClient  # type: ignore
from azure.mgmt.serialconsole.models import SerialPort, SerialPortState  # type: ignore
from azure.mgmt.serialconsole.operations import SerialPortsOperations  # type: ignore
from dataclasses_json import dataclass_json
from marshmallow import validate
from retry import retry

from lisa import Logger, features, schema, search_space
from lisa.feature import Feature
from lisa.features.gpu import ComputeSDK
from lisa.features.resize import ResizeAction
from lisa.features.security_profile import SecurityProfileType
from lisa.node import Node, RemoteNode
from lisa.operating_system import CentOs, Redhat, Suse, Ubuntu
from lisa.search_space import RequirementMethod
from lisa.tools import Curl, Dmesg, Ls, Lspci, Modprobe, Rm
from lisa.util import (
    LisaException,
    NotMeetRequirementException,
    SkippedException,
    UnsupportedOperationException,
    check_till_timeout,
    constants,
    field_metadata,
    find_patterns_in_lines,
    generate_random_chars,
    get_matched_str,
    set_filtered_fields,
)

if TYPE_CHECKING:
    from .platform_ import AzurePlatform, AzureCapability

from .. import AZURE
from .common import (
    AzureArmParameter,
    AzureNodeSchema,
    check_or_create_storage_account,
    create_update_private_dns_zone_groups,
    create_update_private_endpoints,
    create_update_private_zones,
    create_update_record_sets,
    create_update_virtual_network_links,
    delete_file_share,
    delete_private_dns_zone_groups,
    delete_private_endpoints,
    delete_private_zones,
    delete_record_sets,
    delete_storage_account,
    delete_virtual_network_links,
    find_by_name,
    get_compute_client,
    get_network_client,
    get_node_context,
    get_or_create_file_share,
    get_primary_ip_addresses,
    get_virtual_networks,
    get_vm,
    global_credential_access_lock,
    save_console_log,
    wait_operation,
)
from .tools import Waagent


class AzureFeatureMixin:
    def _initialize_information(self, node: Node) -> None:
        node_context = get_node_context(node)
        self._vm_name = node_context.vm_name
        self._resource_group_name = node_context.resource_group_name


class StartStop(AzureFeatureMixin, features.StartStop):
    @classmethod
    def create_setting(
        cls, *args: Any, **kwargs: Any
    ) -> Optional[schema.FeatureSettings]:
        return schema.FeatureSettings.create(cls.name())

    def _stop(
        self,
        wait: bool = True,
        state: features.StopState = features.StopState.Shutdown,
    ) -> None:
        if state == features.StopState.Hibernate:
            self._execute(wait, "begin_deallocate", hibernate=True)
        else:
            self._execute(wait, "begin_deallocate")

    def _start(self, wait: bool = True) -> None:
        self._execute(wait, "begin_start")
        # on the Azure platform, after stop, start vm
        # the public ip address will change, so reload here
        self._node = cast(RemoteNode, self._node)
        platform: AzurePlatform = self._platform  # type: ignore

        public_ip, _ = get_primary_ip_addresses(
            platform, self._resource_group_name, get_vm(platform, self._node)
        )
        node_info = self._node.connection_info
        node_info[constants.ENVIRONMENTS_NODES_REMOTE_PUBLIC_ADDRESS] = public_ip
        self._node.set_connection_info(**node_info)
        self._node._is_initialized = False
        self._node.initialize()

    def _restart(self, wait: bool = True) -> None:
        self._execute(wait, "begin_restart")

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)

    def _execute(self, wait: bool, operator: str, **kwargs: Any) -> None:
        platform: AzurePlatform = self._platform  # type: ignore
        # The latest version may not be deployed to server side, use specified version.
        compute_client = get_compute_client(platform, api_version="2021-07-01")
        operator_method = getattr(compute_client.virtual_machines, operator)
        operation = operator_method(
            resource_group_name=self._resource_group_name,
            vm_name=self._vm_name,
            **kwargs,
        )
        if wait:
            wait_operation(operation, failure_identity="Start/Stop")


class FixedSerialPortsOperations(SerialPortsOperations):  # type: ignore
    def connect(
        self,
        resource_group_name,  # type: str
        resource_provider_namespace,  # type: str
        parent_resource_type,  # type: str
        parent_resource,  # type: str
        serial_port,  # type: str
        **kwargs,  # type: Any
    ) -> Any:
        """Connect to serial port of the target resource.
        This class overrides the Serial Ports Operations class since this package
        is incorrectly sending the POST request. It's missing the "content-type"
        field.
        """
        cls = kwargs.pop("cls", None)
        error_map = {
            401: ClientAuthenticationError,
            404: ResourceNotFoundError,
            409: ResourceExistsError,
        }
        error_map.update(kwargs.pop("error_map", {}))
        api_version = "2018-05-01"
        accept = "application/json"
        content_type = accept

        # Construct URL
        url = self.connect.metadata["url"]  # type: ignore
        path_format_arguments = {
            "resourceGroupName": self._serialize.url(
                "resource_group_name", resource_group_name, "str"
            ),
            "resourceProviderNamespace": self._serialize.url(
                "resource_provider_namespace", resource_provider_namespace, "str"
            ),
            "parentResourceType": self._serialize.url(
                "parent_resource_type", parent_resource_type, "str", skip_quote=True
            ),
            "parentResource": self._serialize.url(
                "parent_resource", parent_resource, "str"
            ),
            "serialPort": self._serialize.url("serial_port", serial_port, "str"),
            "subscriptionId": self._serialize.url(
                "self._config.subscription_id", self._config.subscription_id, "str"
            ),
        }
        url = self._client.format_url(url, **path_format_arguments)

        # Construct parameters
        query_parameters: Dict[str, Any] = {}
        query_parameters["api-version"] = self._serialize.query(
            "api_version", api_version, "str"
        )

        # Construct headers
        header_parameters: Dict[str, Any] = {}

        # Fix SerialPortsOperations: Add Content-Type header
        header_parameters["Content-Type"] = self._serialize.header(
            "content_type", content_type, "str"
        )
        header_parameters["Accept"] = self._serialize.header("accept", accept, "str")

        request = self._client.post(url, query_parameters, header_parameters)
        pipeline_response = self._client._pipeline.run(request, stream=False, **kwargs)
        response = pipeline_response.http_response

        if response.status_code not in [200]:
            map_error(  # type: ignore
                status_code=response.status_code, response=response, error_map=error_map
            )
            raise HttpResponseError(
                response=response, error_format=ARMErrorFormat
            )  # type: ignore

        deserialized = self._deserialize("SerialPortConnectResult", pipeline_response)

        if cls:
            return cls(pipeline_response, deserialized, {})

        return deserialized

    connect.metadata = {  # type: ignore
        "url": (
            "/subscriptions/{subscriptionId}/"
            "resourcegroups/{resourceGroupName}/"
            "providers/{resourceProviderNamespace}/"
            "{parentResourceType}/{parentResource}/"
            "providers/Microsoft.SerialConsole/"
            "serialPorts/{serialPort}/connect"
        )
    }


class SerialConsole(AzureFeatureMixin, features.SerialConsole):
    RESOURCE_PROVIDER_NAMESPACE = "Microsoft.Compute"
    PARENT_RESOURCE_TYPE = "virtualMachines"
    DEFAULT_SERIAL_PORT_ID = 0

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)
        self._serial_console_initialized: bool = False

    @classmethod
    def create_setting(
        cls, *args: Any, **kwargs: Any
    ) -> Optional[schema.FeatureSettings]:
        return schema.FeatureSettings.create(cls.name())

    @retry(tries=3, delay=5)
    def write(self, data: str) -> None:
        # websocket connection is not stable, so we need to retry
        try:
            self._write(data)
            return
        except websockets.ConnectionClosed as e:  # type: ignore
            # If the connection is closed, we need to reconnect
            self._log.debug(f"Connection closed: {e}")
            self._ws = None
            self._get_connection()
            raise e

    @retry(tries=3, delay=5)
    def read(self) -> str:
        # websocket connection is not stable, so we need to retry
        try:
            # run command with timeout
            output = self._read()
            return output
        except websockets.ConnectionClosed as e:  # type: ignore
            # If the connection is closed, we need to reconnect
            self._log.debug(f"Connection closed: {e}")
            self._ws = None
            self._get_connection()
            raise e

    def _get_event_loop(self) -> asyncio.AbstractEventLoop:
        # create asyncio loop if it doesn't exist
        try:
            return asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop

    def _get_connection(self) -> Any:
        if self._ws is None:
            self._log.debug("Creating connection to serial console")
            connection_str = self._get_connection_string()

            # create websocket connection
            self._ws = self._get_event_loop().run_until_complete(
                websockets.connect(connection_str)  # type: ignore
            )

        return self._ws

    def _write(self, cmd: str) -> None:
        self._initialize_serial_console(port_id=self.DEFAULT_SERIAL_PORT_ID)

        # connect to websocket and send command
        ws = self._get_connection()
        self._get_event_loop().run_until_complete(ws.send(cmd))

    def _read(self) -> str:
        self._initialize_serial_console(port_id=self.DEFAULT_SERIAL_PORT_ID)

        # connect to websocket
        ws = self._get_connection()

        # read all the available messages
        output: str = ""
        while True:
            try:
                msg = self._get_event_loop().run_until_complete(
                    asyncio.wait_for(ws.recv(), timeout=10)
                )
                output += msg
            except asyncio.TimeoutError:
                # this implies that the buffer is empty
                break

        # assert isinstance(self._output_string, str)
        if self._output_string in output:
            # implies that the connection was reset
            diff = output[len(self._output_string) :]
            self._output_string: str = output
            return diff
        else:
            self._output_string += output

        return output

    def _get_console_log(self, saved_path: Optional[Path]) -> bytes:
        platform: AzurePlatform = self._platform  # type: ignore
        return save_console_log(
            resource_group_name=self._resource_group_name,
            vm_name=self._vm_name,
            platform=platform,
            log=self._log,
            saved_path=saved_path,
        )

    def _get_connection_string(self) -> str:
        # setup connection string
        platform: AzurePlatform = self._platform  # type: ignore
        connection = self._serial_port_operations.connect(
            resource_group_name=self._resource_group_name,
            resource_provider_namespace=self.RESOURCE_PROVIDER_NAMESPACE,
            parent_resource_type=self.PARENT_RESOURCE_TYPE,
            parent_resource=self._vm_name,
            serial_port=self._serial_port.name,
        )
        access_token = platform.credential.get_token(
            "https://management.core.windows.net/.default"
        ).token
        serial_port_connection_str = (
            f"{connection.connection_string}?authorization={access_token}"
        )

        return serial_port_connection_str

    def _initialize_serial_console(self, port_id: int) -> None:
        if self._serial_console_initialized:
            return

        platform: AzurePlatform = self._platform  # type: ignore
        with global_credential_access_lock:
            self._serial_console_client = MicrosoftSerialConsoleClient(
                credential=platform.credential, subscription_id=platform.subscription_id
            )
            self._serial_port_operations: FixedSerialPortsOperations = (
                FixedSerialPortsOperations(
                    self._serial_console_client._client,
                    self._serial_console_client._config,
                    self._serial_console_client._serialize,
                    self._serial_console_client._deserialize,
                )
            )

        # create serial port if not exists
        # list serial ports
        # https://docs.microsoft.com/en-us/python/api/azure-mgmt-serialconsole/azure.mgmt.serialconsole.operations.serialportsoperations?view=azure-python#azure-mgmt-serialconsole-operations-serialportsoperations-list
        serial_ports = self._serial_port_operations.list(
            resource_group_name=self._resource_group_name,
            resource_provider_namespace=self.RESOURCE_PROVIDER_NAMESPACE,
            parent_resource_type=self.PARENT_RESOURCE_TYPE,
            parent_resource=self._vm_name,
        )
        serial_port_ids = [int(port.name) for port in serial_ports.value]

        if port_id not in serial_port_ids:
            self._serial_port: SerialPort = self._serial_port_operations.create(
                resource_group_name=self._resource_group_name,
                resource_provider_namespace=self.RESOURCE_PROVIDER_NAMESPACE,
                parent_resource_type=self.PARENT_RESOURCE_TYPE,
                parent_resource=self._vm_name,
                serial_port=port_id,
                parameters=SerialPort(state=SerialPortState.ENABLED),
            )
        else:
            self._serial_port = [
                serialport
                for serialport in serial_ports.value
                if int(serialport.name) == port_id
            ][0]

        # setup shared web socket connection variable
        self._ws = None

        # setup output buffer
        self._output_string = ""

        # mark serial console as initialized
        self._serial_console_initialized = True


class Gpu(AzureFeatureMixin, features.Gpu):
    _grid_supported_skus = re.compile(r"^Standard_[^_]+(_v3)?$", re.I)
    _amd_supported_skus = re.compile(r"^Standard_[^_]+_v4$", re.I)
    _gpu_extension_template = """
        {
        "name": "[concat(parameters('nodes')[copyIndex('vmCopy')]['name'], '/gpu-extension')]",
        "type": "Microsoft.Compute/virtualMachines/extensions",
        "apiVersion": "2015-06-15",
        "location": "[parameters('nodes')[copyIndex('vmCopy')]['location']]",
        "copy": {
            "name": "vmCopy",
            "count": "[variables('node_count')]"
        },
        "dependsOn": [
            "[concat('Microsoft.Compute/virtualMachines/', parameters('nodes')[copyIndex('vmCopy')]['name'])]"
        ]
    }
    """  # noqa: E501
    _gpu_extension_nvidia_properties = json.loads(
        """
        {
            "publisher": "Microsoft.HpcCompute",
            "type": "NvidiaGpuDriverLinux",
            "typeHandlerVersion": "1.8",
            "autoUpgradeMinorVersion": true,
            "settings": {
            }
        }
    """
    )

    def is_supported(self) -> bool:
        # TODO: more supportability can be defined here
        node = self._node
        supported = False
        if isinstance(node.os, Redhat):
            supported = node.os.information.version >= "7.0.0"
        elif isinstance(node.os, Ubuntu):
            supported = node.os.information.version >= "16.0.0"
        elif isinstance(node.os, Suse):
            supported = node.os.information.version >= "15.0.0"

        return supported

    def get_supported_driver(self) -> List[ComputeSDK]:
        driver_list = []
        node_runbook = self._node.capability.get_extended_runbook(
            AzureNodeSchema, AZURE
        )
        if re.match(self._grid_supported_skus, node_runbook.vm_size):
            driver_list.append(ComputeSDK.GRID)
        elif re.match(self._amd_supported_skus, node_runbook.vm_size):
            driver_list.append(ComputeSDK.AMD)
            self._is_nvidia: bool = False
        else:
            driver_list.append(ComputeSDK.CUDA)

        if not driver_list:
            raise LisaException(
                "No valid Compute SDK found to install for the VM size -"
                f" {node_runbook.vm_size}."
            )
        return driver_list

    @classmethod
    def create_setting(
        cls, *args: Any, **kwargs: Any
    ) -> Optional[schema.FeatureSettings]:
        raw_capabilities: Any = kwargs.get("raw_capabilities")
        node_space = kwargs.get("node_space")

        assert isinstance(node_space, schema.NodeSpace), f"actual: {type(node_space)}"

        value = raw_capabilities.get("GPUs", None)
        if value:
            node_space.gpu_count = int(value)
            return schema.FeatureSettings.create(cls.name())

        return None

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)
        self._is_nvidia = True

    def _install_driver_using_platform_feature(self) -> None:
        supported_versions: Dict[Any, List[str]] = {
            Redhat: ["7.3", "7.4", "7.5", "7.6", "7.7", "7.8"],
            Ubuntu: ["16.04", "18.04", "20.04"],
            CentOs: ["7.3", "7.4", "7.5", "7.6", "7.7", "7.8"],
        }
        release = self._node.os.information.release
        if release not in supported_versions.get(type(self._node.os), []):
            raise UnsupportedOperationException("GPU Extension not supported")
        extension = self._node.features[AzureExtension]
        result = extension.create_or_update(
            type_="NvidiaGpuDriverLinux",
            publisher="Microsoft.HpcCompute",
            type_handler_version="1.6",
            auto_upgrade_minor_version=True,
            settings={},
        )
        if result["provisioning_state"] == "Succeeded":
            return
        else:
            raise LisaException("GPU Extension Provisioning Failed")


class Infiniband(AzureFeatureMixin, features.Infiniband):
    @classmethod
    def on_before_deployment(cls, *args: Any, **kwargs: Any) -> None:
        arm_parameters: AzureArmParameter = kwargs.pop("arm_parameters")

        arm_parameters.availability_set_properties["platformFaultDomainCount"] = 1
        arm_parameters.availability_set_properties["platformUpdateDomainCount"] = 1
        arm_parameters.use_availability_sets = True

    @classmethod
    def create_setting(
        cls, *args: Any, **kwargs: Any
    ) -> Optional[schema.FeatureSettings]:
        raw_capabilities: Any = kwargs.get("raw_capabilities")

        if raw_capabilities.get("RdmaEnabled", None) == "True":
            return schema.FeatureSettings.create(cls.name())

        return None

    def is_over_sriov(self) -> bool:
        lspci = self._node.tools[Lspci]
        device_list = lspci.get_devices()
        return any("Virtual Function" in device.device_info for device in device_list)

    # nd stands for network direct
    # example SKU: Standard_H16mr
    def is_over_nd(self) -> bool:
        dmesg = self._node.tools[Dmesg]
        return "hvnd_try_bind_nic" in dmesg.get_output()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)


class NetworkInterface(AzureFeatureMixin, features.NetworkInterface):
    """
    This Network interface feature is mainly to associate Azure
    network interface options settings.
    """

    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return schema.NetworkInterfaceOptionSettings

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)
        all_nics = self._get_all_nics()
        # store extra synthetic and sriov nics count
        # in order to restore nics status after testing which needs change nics
        # extra synthetic nics count before testing
        self.origin_extra_synthetic_nics_count = len(
            [
                x
                for x in all_nics
                if x.primary is False and x.enable_accelerated_networking is False
            ]
        )
        # extra sriov nics count before testing
        self.origin_extra_sriov_nics_count = (
            len(all_nics) - self.origin_extra_synthetic_nics_count - 1
        )

    def switch_sriov(
        self, enable: bool, wait: bool = True, reset_connections: bool = True
    ) -> None:
        azure_platform: AzurePlatform = self._platform  # type: ignore
        network_client = get_network_client(azure_platform)
        vm = get_vm(azure_platform, self._node)
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

        # wait settings effective
        if wait:
            self._check_sriov_enabled(enable, reset_connections)

    def is_enabled_sriov(self) -> bool:
        azure_platform: AzurePlatform = self._platform  # type: ignore
        network_client = get_network_client(azure_platform)
        sriov_enabled: bool = False
        vm = get_vm(azure_platform, self._node)
        nic = self._get_primary(vm.network_profile.network_interfaces)
        nic_name = nic.id.split("/")[-1]
        primary_nic = network_client.network_interfaces.get(
            self._resource_group_name, nic_name
        )
        sriov_enabled = primary_nic.enable_accelerated_networking
        return sriov_enabled

    def attach_nics(
        self, extra_nic_count: int, enable_accelerated_networking: bool = True
    ) -> None:
        if 0 == extra_nic_count:
            return
        azure_platform: AzurePlatform = self._platform  # type: ignore
        network_client = get_network_client(azure_platform)
        compute_client = get_compute_client(azure_platform)
        vm = get_vm(azure_platform, self._node)
        current_nic_count = len(vm.network_profile.network_interfaces)
        nic_count_after_add_extra = extra_nic_count + current_nic_count
        assert (
            self._node.capability.network_interface
            and self._node.capability.network_interface.max_nic_count
        )
        assert isinstance(
            self._node.capability.network_interface.max_nic_count, int
        ), f"actual: {type(self._node.capability.network_interface.max_nic_count)}"
        node_capability_nic_count = (
            self._node.capability.network_interface.max_nic_count
        )
        if nic_count_after_add_extra > node_capability_nic_count:
            raise LisaException(
                f"nic count after add extra nics is {nic_count_after_add_extra},"
                f" it exceeds the vm size's capability {node_capability_nic_count}."
            )
        nic = self._get_primary(vm.network_profile.network_interfaces)
        nic_name = nic.id.split("/")[-1]
        primary_nic = network_client.network_interfaces.get(
            self._resource_group_name, nic_name
        )

        startstop = self._node.features[StartStop]
        startstop.stop()

        network_interfaces_section = []
        index = 0
        while index < current_nic_count + extra_nic_count - 1:
            extra_nic_name = f"{self._node.name}-extra-{index}"
            self._log.debug(f"start to create the nic {extra_nic_name}.")
            params = {
                "location": vm.location,
                "enable_accelerated_networking": enable_accelerated_networking,
                "ip_configurations": [
                    {
                        "name": extra_nic_name,
                        "subnet": {"id": primary_nic.ip_configurations[0].subnet.id},
                        "primary": False,
                    }
                ],
            }
            network_client.network_interfaces.begin_create_or_update(
                resource_group_name=self._resource_group_name,
                network_interface_name=extra_nic_name,
                parameters=params,
            )
            self._log.debug(f"create the nic {extra_nic_name} successfully.")
            extra_nic = network_client.network_interfaces.get(
                network_interface_name=extra_nic_name,
                resource_group_name=self._resource_group_name,
            )

            network_interfaces_section.append({"id": extra_nic.id, "primary": False})
            index += 1
        network_interfaces_section.append({"id": primary_nic.id, "primary": True})

        self._log.debug(f"start to attach the nics into VM {self._node.name}.")
        compute_client.virtual_machines.begin_update(
            resource_group_name=self._resource_group_name,
            vm_name=self._node.name,
            parameters={
                "network_profile": {"network_interfaces": network_interfaces_section},
            },
        )
        self._log.debug(f"attach the nics into VM {self._node.name} successfully.")
        startstop.start()

    def get_nic_count(self, is_sriov_enabled: bool = True) -> int:
        return len(
            [
                x
                for x in self._get_all_nics()
                if x.enable_accelerated_networking == is_sriov_enabled
            ]
        )

    def remove_extra_nics(self) -> None:
        azure_platform: AzurePlatform = self._platform  # type: ignore
        network_client = get_network_client(azure_platform)
        compute_client = get_compute_client(azure_platform)
        vm = get_vm(azure_platform, self._node)
        if len(vm.network_profile.network_interfaces) == 1:
            self._log.debug("No existed extra nics can be disassociated.")
            return
        nic = self._get_primary(vm.network_profile.network_interfaces)
        nic_name = nic.id.split("/")[-1]
        primary_nic = network_client.network_interfaces.get(
            self._resource_group_name, nic_name
        )
        network_interfaces_section = []
        network_interfaces_section.append({"id": primary_nic.id, "primary": True})
        startstop = self._node.features[StartStop]
        startstop.stop()
        compute_client.virtual_machines.begin_update(
            resource_group_name=self._resource_group_name,
            vm_name=self._node.name,
            parameters={
                "network_profile": {"network_interfaces": network_interfaces_section},
            },
        )
        self._log.debug(
            f"Only associated nic {primary_nic.id} into VM {self._node.name}."
        )
        startstop.start()

    def reload_module(self) -> None:
        modprobe_tool = self._node.tools[Modprobe]
        modprobe_tool.reload(["hv_netvsc"])

    @retry(tries=60, delay=10)
    def _check_sriov_enabled(
        self, enabled: bool, reset_connections: bool = True
    ) -> None:
        if reset_connections:
            self._node.close()
        self._node.nics.reload()
        default_nic = self._node.nics.get_nic_by_index(0)

        if enabled and not default_nic.lower:
            raise LisaException("SRIOV is enabled, but VF is not found.")
        elif not enabled and default_nic.lower:
            raise LisaException("SRIOV is disabled, but VF exists.")
        else:
            # the enabled flag is consistent with VF presents.
            ...

    def _get_primary(
        self, nics: List[NetworkInterfaceReference]
    ) -> NetworkInterfaceReference:
        for nic in nics:
            if nic.primary:
                return nic

        raise LisaException(f"failed to find primary nic for vm {self._node.name}")

    def _get_all_nics(self) -> Any:
        azure_platform: AzurePlatform = self._platform  # type: ignore
        network_client = get_network_client(azure_platform)
        vm = get_vm(azure_platform, self._node)
        all_nics = []
        for nic in vm.network_profile.network_interfaces:
            # get nic name from nic id
            # /subscriptions/[subid]/resourceGroups/[rgname]/providers
            # /Microsoft.Network/networkInterfaces/[nicname]
            nic_name = nic.id.split("/")[-1]
            all_nics.append(
                network_client.network_interfaces.get(
                    self._resource_group_name, nic_name
                )
            )
        return all_nics


# Tuple: (IOPS, Disk Size)
_disk_size_iops_map: Dict[schema.DiskType, List[Tuple[int, int]]] = {
    schema.DiskType.PremiumSSDLRS: [
        (120, 4),
        (240, 64),
        (500, 128),
        (1100, 256),
        (2300, 512),
        (5000, 1024),
        (7500, 2048),
        (16000, 8192),
        (18000, 16384),
        (20000, 32767),
    ],
    schema.DiskType.StandardHDDLRS: [
        (500, 32),
        (1300, 8192),
        (2000, 16384),
    ],
    schema.DiskType.StandardSSDLRS: [
        (500, 4),
        (2000, 8192),
        (4000, 16384),
        (6000, 32767),
    ],
}


@dataclass_json()
@dataclass()
class AzureDiskOptionSettings(schema.DiskOptionSettings):
    has_resource_disk: Optional[bool] = None

    def __hash__(self) -> int:
        return super().__hash__()

    def __str__(self) -> str:
        return self.__repr__()

    def __repr__(self) -> str:
        return f"has_resource_disk: {self.has_resource_disk},{super().__repr__()}"

    def __eq__(self, o: object) -> bool:
        if not super().__eq__(o):
            return False

        assert isinstance(o, AzureDiskOptionSettings), f"actual: {type(o)}"
        return self.has_resource_disk == o.has_resource_disk and super().__eq__(o)

    # It uses to override requirement operations.
    def check(self, capability: Any) -> search_space.ResultReason:
        assert isinstance(
            capability, AzureDiskOptionSettings
        ), f"actual: {type(capability)}"
        result = super().check(capability)

        result.merge(
            search_space.check_setspace(self.disk_type, capability.disk_type),
            "disk_type",
        )
        result.merge(
            search_space.check_countspace(
                self.data_disk_count, capability.data_disk_count
            ),
            "data_disk_count",
        )
        result.merge(
            search_space.check_countspace(
                self.data_disk_iops, capability.data_disk_iops
            ),
            "data_disk_iops",
        )
        result.merge(
            search_space.check_countspace(
                self.data_disk_size, capability.data_disk_size
            ),
            "data_disk_size",
        )
        result.merge(
            self._check_has_resource_disk(
                self.has_resource_disk, capability.has_resource_disk
            ),
            "has_resource_disk",
        )
        result.merge(
            search_space.check_countspace(
                self.max_data_disk_count, capability.max_data_disk_count
            ),
            "max_data_disk_count",
        )
        result.merge(
            search_space.check_setspace(
                self.disk_controller_type, capability.disk_controller_type
            ),
            "disk_controller_type",
        )

        return result

    def _call_requirement_method(self, method_name: str, capability: Any) -> Any:
        assert isinstance(
            capability, AzureDiskOptionSettings
        ), f"actual: {type(capability)}"

        assert (
            capability.disk_type
        ), "capability should have at least one disk type, but it's None"
        assert (
            capability.disk_controller_type
        ), "capability should have at least one disk controller type, but it's None"
        value = AzureDiskOptionSettings()
        super_value = schema.DiskOptionSettings._call_requirement_method(
            self, method_name, capability
        )
        set_filtered_fields(super_value, value, ["data_disk_count"])

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

        value.disk_type = getattr(search_space, f"{method_name}_setspace_by_priority")(
            self.disk_type, capability.disk_type, schema.disk_type_priority
        )

        cap_disk_controller_type = capability.disk_controller_type
        if isinstance(cap_disk_controller_type, search_space.SetSpace):
            assert len(cap_disk_controller_type) > 0, (
                "capability should have at least one "
                "disk controller type, but it's empty"
            )
        elif isinstance(cap_disk_controller_type, schema.DiskControllerType):
            cap_disk_controller_type = search_space.SetSpace[schema.DiskControllerType](
                is_allow_set=True, items=[cap_disk_controller_type]
            )
        else:
            raise LisaException(
                "unknown disk controller type "
                f"on capability, type: {cap_disk_controller_type}"
            )

        value.disk_controller_type = getattr(
            search_space, f"{method_name}_setspace_by_priority"
        )(
            self.disk_controller_type,
            capability.disk_controller_type,
            schema.disk_controller_type_priority,
        )

        # below values affect data disk only.
        if self.data_disk_count is not None or capability.data_disk_count is not None:
            value.data_disk_count = getattr(search_space, f"{method_name}_countspace")(
                self.data_disk_count, capability.data_disk_count
            )

        if (
            self.max_data_disk_count is not None
            or capability.max_data_disk_count is not None
        ):
            value.max_data_disk_count = getattr(
                search_space, f"{method_name}_countspace"
            )(self.max_data_disk_count, capability.max_data_disk_count)

        # The Ephemeral doesn't support data disk, but it needs a value. And it
        # doesn't need to calculate on intersect
        value.data_disk_iops = 0
        value.data_disk_size = 0

        if method_name == RequirementMethod.generate_min_capability:
            assert isinstance(
                value.disk_type, schema.DiskType
            ), f"actual: {type(value.disk_type)}"
            disk_type_iops = _disk_size_iops_map.get(value.disk_type, None)
            # ignore unsupported disk type like Ephemeral. It supports only os
            # disk. Calculate for iops, if it has value. If not, try disk size
            if disk_type_iops:
                if isinstance(self.data_disk_iops, int) or (
                    self.data_disk_iops != search_space.IntRange(min=0)
                ):
                    req_disk_iops = search_space.count_space_to_int_range(
                        self.data_disk_iops
                    )
                    cap_disk_iops = search_space.count_space_to_int_range(
                        capability.data_disk_iops
                    )
                    min_iops = max(req_disk_iops.min, cap_disk_iops.min)
                    max_iops = min(req_disk_iops.max, cap_disk_iops.max)

                    value.data_disk_iops = min(
                        iops
                        for iops, _ in disk_type_iops
                        if iops >= min_iops and iops <= max_iops
                    )
                    value.data_disk_size = self._get_disk_size_from_iops(
                        value.data_disk_iops, disk_type_iops
                    )
                elif self.data_disk_size:
                    req_disk_size = search_space.count_space_to_int_range(
                        self.data_disk_size
                    )
                    cap_disk_size = search_space.count_space_to_int_range(
                        capability.data_disk_size
                    )
                    min_size = max(req_disk_size.min, cap_disk_size.min)
                    max_size = min(req_disk_size.max, cap_disk_size.max)

                    value.data_disk_iops = min(
                        iops
                        for iops, disk_size in disk_type_iops
                        if disk_size >= min_size and disk_size <= max_size
                    )
                    value.data_disk_size = self._get_disk_size_from_iops(
                        value.data_disk_iops, disk_type_iops
                    )
                else:
                    # if req is not specified, query minimum value.
                    cap_disk_size = search_space.count_space_to_int_range(
                        capability.data_disk_size
                    )
                    value.data_disk_iops = min(
                        iops
                        for iops, _ in disk_type_iops
                        if iops >= cap_disk_size.min and iops <= cap_disk_size.max
                    )
                    value.data_disk_size = self._get_disk_size_from_iops(
                        value.data_disk_iops, disk_type_iops
                    )
        elif method_name == RequirementMethod.intersect:
            value.data_disk_iops = search_space.intersect_countspace(
                self.data_disk_iops, capability.data_disk_iops
            )
            value.data_disk_size = search_space.intersect_countspace(
                self.data_disk_size, capability.data_disk_size
            )

        # all caching types are supported, so just take the value from requirement.
        value.data_disk_caching_type = self.data_disk_caching_type

        check_result = self._check_has_resource_disk(
            self.has_resource_disk, capability.has_resource_disk
        )
        if not check_result.result:
            raise NotMeetRequirementException("capability doesn't support requirement")
        value.has_resource_disk = capability.has_resource_disk

        return value

    def _get_disk_size_from_iops(
        self, data_disk_iops: int, disk_type_iops: List[Tuple[int, int]]
    ) -> int:
        return next(
            disk_size for iops, disk_size in disk_type_iops if iops == data_disk_iops
        )

    def _check_has_resource_disk(
        self, requirement: Optional[bool], capability: Optional[bool]
    ) -> search_space.ResultReason:
        result = search_space.ResultReason()
        # if requirement is none, capability can be either of True or False
        # else requirement should match capability
        if requirement is not None:
            if capability is None:
                result.add_reason(
                    "if requirements isn't None, capability shouldn't be None"
                )
            else:
                if requirement != capability:
                    result.add_reason(
                        "requirement is a truth value, capability should be exact "
                        f"match, requirement: {requirement}, "
                        f"capability: {capability}"
                    )

        return result

    def _get_key(self) -> str:
        return f"{super()._get_key()}/{self.has_resource_disk}"


class Disk(AzureFeatureMixin, features.Disk):
    """
    This Disk feature is mainly to associate Azure disk options settings.
    """

    # /dev/disk/azure/scsi1/lun0
    # /dev/disk/azure/scsi1/lun63
    SCSI_PATTERN = re.compile(r"/dev/disk/azure/scsi[0-9]/lun[0-9][0-9]?$", re.M)
    UN_SUPPORT_SETTLE = re.compile(r"trigger: unrecognized option '--settle'", re.M)

    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return AzureDiskOptionSettings

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)

    def get_raw_data_disks(self) -> List[str]:
        # refer here to get data disks from folder /dev/disk/azure/scsi1
        # https://docs.microsoft.com/en-us/troubleshoot/azure/virtual-machines/troubleshoot-device-names-problems#identify-disk-luns  # noqa: E501
        # /dev/disk/azure/scsi1/lun0
        ls_tools = self._node.tools[Ls]
        files = ls_tools.list("/dev/disk/azure/scsi1", sudo=True)

        if len(files) == 0:
            os = self._node.os
            # there are known issues on ubuntu 16.04 and rhel 9.0
            # try to workaround it
            if (isinstance(os, Ubuntu) and os.information.release <= "16.04") or (
                isinstance(os, Redhat) and os.information.release >= "9.0"
            ):
                self._log.debug(
                    "download udev rules to construct a set of symbolic links "
                    "under the /dev/disk/azure path"
                )
                if ls_tools.is_file(
                    self._node.get_pure_path("/dev/disk/azure"), sudo=True
                ):
                    self._node.tools[Rm].remove_file("/dev/disk/azure", sudo=True)
                self._node.tools[Curl].fetch(
                    arg="-o /etc/udev/rules.d/66-azure-storage.rules",
                    execute_arg="",
                    url="https://raw.githubusercontent.com/Azure/WALinuxAgent/master/config/66-azure-storage.rules",  # noqa: E501
                    sudo=True,
                    cwd=self._node.get_pure_path("/etc/udev/rules.d/"),
                )
                cmd_result = self._node.execute(
                    "udevadm trigger --settle --subsystem-match=block", sudo=True
                )
                if get_matched_str(cmd_result.stdout, self.UN_SUPPORT_SETTLE):
                    self._node.execute(
                        "udevadm trigger --subsystem-match=block", sudo=True
                    )
                check_till_timeout(
                    lambda: len(ls_tools.list("/dev/disk/azure/scsi1", sudo=True)) > 0,
                    timeout_message="wait for dev rule take effect",
                )
                files = ls_tools.list("/dev/disk/azure/scsi1", sudo=True)

        assert_that(len(files)).described_as(
            "no data disks info found under /dev/disk/azure/scsi1"
        ).is_greater_than(0)
        matched = [x for x in files if get_matched_str(x, self.SCSI_PATTERN) != ""]
        # https://docs.microsoft.com/en-us/troubleshoot/azure/virtual-machines/troubleshoot-device-names-problems#get-the-latest-azure-storage-rules  # noqa: E501
        assert matched, "not find data disks"
        disk_array: List[str] = [""] * len(matched)
        for disk in matched:
            # readlink -f /dev/disk/azure/scsi1/lun0
            # /dev/sdc
            cmd_result = self._node.execute(
                f"readlink -f {disk}", shell=True, sudo=True
            )
            disk_array[int(disk.split("/")[-1].replace("lun", ""))] = cmd_result.stdout
        return disk_array

    def get_all_disks(self) -> List[str]:
        # /sys/block/sda = > sda
        # /sys/block/sdb = > sdb
        disk_label_pattern = re.compile(r"/sys/block/(?P<label>sd\w*)", re.M)
        cmd_result = self._node.execute("ls -d /sys/block/sd*", shell=True, sudo=True)
        matched = find_patterns_in_lines(cmd_result.stdout, [disk_label_pattern])
        assert matched[0], "not found the matched disk label"
        return list(set(matched[0]))

    def add_data_disk(
        self,
        count: int,
        disk_type: schema.DiskType = schema.DiskType.StandardHDDLRS,
        size_in_gb: int = 20,
    ) -> List[str]:
        disk_sku = _disk_type_mapping.get(disk_type, None)
        assert disk_sku
        assert self._node.capability.disk
        assert isinstance(self._node.capability.disk.data_disk_count, int)
        current_disk_count = self._node.capability.disk.data_disk_count
        platform: AzurePlatform = self._platform  # type: ignore
        compute_client = get_compute_client(platform)
        node_context = self._node.capability.get_extended_runbook(AzureNodeSchema)

        # create managed disk
        managed_disks = []
        for i in range(count):
            name = f"lisa_data_disk_{i+current_disk_count}"
            async_disk_update = compute_client.disks.begin_create_or_update(
                self._resource_group_name,
                name,
                {
                    "location": node_context.location,
                    "disk_size_gb": size_in_gb,
                    "sku": {"name": disk_sku},
                    "creation_data": {"create_option": DiskCreateOption.empty},
                },
            )
            managed_disks.append(async_disk_update.result())

        # attach managed disk
        azure_platform: AzurePlatform = self._platform  # type: ignore
        vm = get_vm(azure_platform, self._node)
        for i, managed_disk in enumerate(managed_disks):
            lun = str(i + current_disk_count)
            vm.storage_profile.data_disks.append(
                {
                    "lun": lun,
                    "name": managed_disk.name,
                    "create_option": DiskCreateOptionTypes.attach,
                    "managed_disk": {"id": managed_disk.id},
                }
            )

        # update vm
        async_vm_update = compute_client.virtual_machines.begin_create_or_update(
            self._resource_group_name,
            vm.name,
            vm,
        )
        async_vm_update.wait()

        # update data disk count
        add_disk_names = [managed_disk.name for managed_disk in managed_disks]
        self.disks += add_disk_names
        self._node.capability.disk.data_disk_count += len(managed_disks)

        return add_disk_names

    def remove_data_disk(self, names: Optional[List[str]] = None) -> None:
        assert self._node.capability.disk
        platform: AzurePlatform = self._platform  # type: ignore
        compute_client = get_compute_client(platform)

        # if names is None, remove all data disks
        if names is None:
            names = self.disks

        # detach managed disk
        azure_platform: AzurePlatform = self._platform  # type: ignore
        vm = get_vm(azure_platform, self._node)

        # remove managed disk
        data_disks = vm.storage_profile.data_disks
        data_disks[:] = [disk for disk in data_disks if disk.name not in names]

        # update vm
        async_vm_update = compute_client.virtual_machines.begin_create_or_update(
            self._resource_group_name,
            vm.name,
            vm,
        )
        async_vm_update.wait()

        # delete managed disk
        for name in names:
            async_disk_delete = compute_client.disks.begin_delete(
                self._resource_group_name, name
            )
            async_disk_delete.wait()

        # update data disk count
        assert isinstance(self._node.capability.disk.data_disk_count, int)
        self.disks = [name for name in self.disks if name not in names]
        self._node.capability.disk.data_disk_count -= len(names)
        self._node.close()

    def get_resource_disk_mount_point(self) -> str:
        # by default, cloudinit will use /mnt as mount point of resource disk
        # in CentOS, cloud.cfg.d/91-azure_datasource.cfg customize mount point as
        # /mnt/resource
        if (
            not isinstance(self._node.os, CentOs)
            and self._node.shell.exists(
                self._node.get_pure_path("/var/log/cloud-init.log")
            )
            and self._node.shell.exists(
                self._node.get_pure_path("/var/lib/cloud/instance")
            )
        ):
            self._log.debug("Disk handled by cloud-init.")
            mount_point = "/mnt"
        else:
            self._log.debug("Disk handled by waagent.")
            mount_point = self._node.tools[Waagent].get_resource_disk_mount_point()
        return mount_point


def get_azure_disk_type(disk_type: schema.DiskType) -> str:
    assert isinstance(disk_type, schema.DiskType), (
        "the disk_type must be one value when calling get_disk_type. "
        f"But it's {disk_type}"
    )

    result = _disk_type_mapping.get(disk_type, None)
    assert result, f"unknown disk type: {disk_type}"

    return result


_disk_type_mapping: Dict[schema.DiskType, str] = {
    schema.DiskType.PremiumSSDLRS: "Premium_LRS",
    schema.DiskType.Ephemeral: "Ephemeral",
    schema.DiskType.StandardHDDLRS: "Standard_LRS",
    schema.DiskType.StandardSSDLRS: "StandardSSD_LRS",
}


class Resize(AzureFeatureMixin, features.Resize):
    @classmethod
    def create_setting(
        cls, *args: Any, **kwargs: Any
    ) -> Optional[schema.FeatureSettings]:
        return schema.FeatureSettings.create(cls.name())

    def resize(
        self, resize_action: ResizeAction = ResizeAction.IncreaseCoreCount
    ) -> Tuple[schema.NodeSpace, str, str]:
        platform: AzurePlatform = self._platform  # type: ignore
        compute_client = get_compute_client(platform)
        node_context = get_node_context(self._node)
        origin_vm_size, new_vm_size_info = self._select_vm_size(resize_action)

        # Creating parameter for VM Operations API call
        hardware_profile = HardwareProfile(vm_size=new_vm_size_info.vm_size)
        vm_update = VirtualMachineUpdate(hardware_profile=hardware_profile)

        # Resizing with new Vm Size
        lro_poller = compute_client.virtual_machines.begin_update(
            resource_group_name=node_context.resource_group_name,
            vm_name=node_context.vm_name,
            parameters=vm_update,
        )

        # Waiting for the Long Running Operation to finish
        wait_operation(lro_poller, time_out=1200)

        self._node.close()
        new_capability = copy.deepcopy(new_vm_size_info.capability)
        self._node.capability = cast(schema.Capability, new_capability)
        return new_capability, origin_vm_size, new_vm_size_info.vm_size

    def _select_vm_size(
        self, resize_action: ResizeAction = ResizeAction.IncreaseCoreCount
    ) -> Tuple[str, "AzureCapability"]:
        platform: AzurePlatform = self._platform  # type: ignore
        compute_client = get_compute_client(platform)
        node_context = get_node_context(self._node)
        node_runbook = self._node.capability.get_extended_runbook(AzureNodeSchema)

        # Get list of vm sizes that the current resource group can use
        available_sizes = compute_client.virtual_machines.list_available_sizes(
            node_context.resource_group_name, node_context.vm_name
        )
        # Get list of vm sizes available in the current location
        location_info = platform.get_location_info(node_runbook.location, self._log)
        capabilities = [value for _, value in location_info.capabilities.items()]
        sorted_sizes = platform.get_sorted_vm_sizes(capabilities, self._log)

        current_vm_size = next(
            (x for x in sorted_sizes if x.vm_size == node_runbook.vm_size),
            None,
        )
        assert current_vm_size, "cannot find current vm size in eligible list"

        # Intersection of available_sizes and eligible_sizes
        avail_eligible_intersect: List[AzureCapability] = []
        # Populating avail_eligible_intersect with vm sizes that are available in the
        # current location and that are available for the current vm size to resize to
        for size in available_sizes:
            vm_size_name = size.as_dict()["name"]
            # Getting eligible vm sizes and their capability data
            new_vm_size = next(
                (x for x in sorted_sizes if x.vm_size == vm_size_name), None
            )
            if not new_vm_size:
                continue

            avail_eligible_intersect.append(new_vm_size)

        current_network_interface = current_vm_size.capability.network_interface
        assert_that(current_network_interface).described_as(
            "current_network_interface is not of type NetworkInterfaceOptionSettings."
        ).is_instance_of(schema.NetworkInterfaceOptionSettings)
        current_data_path = current_network_interface.data_path  # type: ignore
        current_core_count = current_vm_size.capability.core_count
        assert_that(current_core_count).described_as(
            "Didn't return an integer to represent the current VM size core count."
        ).is_instance_of(int)
        assert current_vm_size.capability.features
        current_arch = [
            feature
            for feature in current_vm_size.capability.features
            if feature.type == ArchitectureSettings.type
        ]
        current_gen = [
            feature
            for feature in current_vm_size.capability.features
            if feature.type == VhdGenerationSettings.type
        ]
        # Loop removes candidate vm sizes if they can't be resized to or if the
        # change in cores resulting from the resize is undesired
        for candidate_size in avail_eligible_intersect[:]:
            assert candidate_size.capability.features
            candidate_arch = [
                feature
                for feature in candidate_size.capability.features
                if feature.type == ArchitectureSettings.type
            ]
            # Removing vm size from candidate list if the candidate architecture is
            # different with current vm size
            if isinstance(current_arch[0], ArchitectureSettings) and isinstance(
                candidate_arch[0], ArchitectureSettings
            ):
                if candidate_arch[0].arch != current_arch[0].arch:
                    avail_eligible_intersect.remove(candidate_size)
                    continue

            candidate_gen = [
                feature
                for feature in candidate_size.capability.features
                if feature.type == VhdGenerationSettings.type
            ]
            if isinstance(current_gen[0], VhdGenerationSettings) and isinstance(
                candidate_gen[0], VhdGenerationSettings
            ):
                result = search_space.check_setspace(
                    current_gen[0].gen, candidate_gen[0].gen
                )
                # Removing vm size from candidate list if the candidate vhd gen type is
                # different with current vm size gen type
                if not result.result:
                    avail_eligible_intersect.remove(candidate_size)
                    continue
            candidate_network_interface = candidate_size.capability.network_interface
            assert_that(candidate_network_interface).described_as(
                "candidate_network_interface is not of type "
                "NetworkInterfaceOptionSettings."
            ).is_instance_of(schema.NetworkInterfaceOptionSettings)
            candidate_data_path = candidate_network_interface.data_path  # type: ignore
            # Can't resize from an accelerated networking enabled size to a size where
            # accelerated networking isn't enabled
            if (
                schema.NetworkDataPath.Sriov in current_data_path  # type: ignore
                and schema.NetworkDataPath.Sriov not in candidate_data_path  # type: ignore # noqa: E501
            ):
                # Removing sizes without accelerated networking capabilities
                # if original size has it enabled
                avail_eligible_intersect.remove(candidate_size)
                continue

            candidate_core_count = candidate_size.capability.core_count
            assert_that(candidate_core_count).described_as(
                "Didn't return an integer to represent the "
                "candidate VM size core count."
            ).is_instance_of(int)
            # Removing vm size from candidate list if the change in core count
            # doesn't align with the ResizeAction passed into this function
            if (
                resize_action == ResizeAction.IncreaseCoreCount
                and candidate_core_count < current_core_count  # type: ignore
                or resize_action == ResizeAction.DecreaseCoreCount
                and candidate_core_count > current_core_count  # type: ignore
            ):
                avail_eligible_intersect.remove(candidate_size)

        if not avail_eligible_intersect:
            raise LisaException(
                f"current vm size: {current_vm_size.vm_size},"
                f" no available size for resizing with {resize_action} setting."
            )

        # Choose random size from the list to resize to
        index = randint(0, len(avail_eligible_intersect) - 1)
        resize_vm_size_info = avail_eligible_intersect[index]
        origin_vm_size = node_runbook.vm_size
        node_runbook.vm_size = resize_vm_size_info.vm_size
        node_runbook.location = resize_vm_size_info.location
        resize_vm_size_info.capability.set_extended_runbook(node_runbook)
        self._log.info(f"New vm size: {resize_vm_size_info.vm_size}")
        return origin_vm_size, resize_vm_size_info


class Hibernation(AzureFeatureMixin, features.Hibernation):
    _hibernation_properties = """
        {
            "additionalCapabilities": {
                "hibernationEnabled": "true"
            }
        }
        """

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)

    @classmethod
    def create_setting(
        cls, *args: Any, **kwargs: Any
    ) -> Optional[schema.FeatureSettings]:
        raw_capabilities: Any = kwargs.get("raw_capabilities")

        if raw_capabilities.get("HibernationSupported", None) == "True":
            return schema.FeatureSettings.create(cls.name())

        return None

    @classmethod
    def _enable_hibernation(cls, *args: Any, **kwargs: Any) -> None:
        parameters: Any = kwargs.get("arm_parameters")
        if parameters.use_availability_sets:
            raise SkippedException(
                "Hibernation cannot be enabled on Virtual Machines created in an"
                " Availability Set."
            )
        template: Any = kwargs.get("template")
        log = cast(Logger, kwargs.get("log"))
        log.debug("updating arm template to support vm hibernation.")
        resources = template["resources"]
        virtual_machines = find_by_name(resources, "Microsoft.Compute/virtualMachines")
        virtual_machines["properties"].update(json.loads(cls._hibernation_properties))


@dataclass_json()
@dataclass()
class SecurityProfileSettings(features.SecurityProfileSettings):
    disk_encryption_set_id: str = field(
        default="",
        metadata=field_metadata(
            required=False,
        ),
    )

    def __hash__(self) -> int:
        return hash(self._get_key())

    def _get_key(self) -> str:
        return (
            f"{self.type}/{self.security_profile}/"
            f"{self.encrypt_disk}/{self.disk_encryption_set_id}"
        )

    def _call_requirement_method(self, method_name: str, capability: Any) -> Any:
        super_value: SecurityProfileSettings = super()._call_requirement_method(
            method_name, capability
        )
        value = SecurityProfileSettings()
        value.security_profile = super_value.security_profile
        value.encrypt_disk = super_value.encrypt_disk

        if self.disk_encryption_set_id:
            value.disk_encryption_set_id = self.disk_encryption_set_id
        else:
            value.disk_encryption_set_id = capability.disk_encryption_set_id

        return value


class SecurityProfile(AzureFeatureMixin, features.SecurityProfile):
    _both_enabled_properties = """
        {
            "securityProfile": {
                "uefiSettings": {
                    "secureBootEnabled": "true",
                    "vTpmEnabled": "true"
                },
                "securityType": "%s"
            }
        }
        """

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)

    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return SecurityProfileSettings

    @classmethod
    def create_setting(
        cls, *args: Any, **kwargs: Any
    ) -> Optional[schema.FeatureSettings]:
        raw_capabilities: Any = kwargs.get("raw_capabilities")
        resource_sku: Any = kwargs.get("resource_sku")
        capabilities: List[SecurityProfileType] = [SecurityProfileType.Standard]

        gen_value = raw_capabilities.get("HyperVGenerations", None)
        cvm_value = raw_capabilities.get("ConfidentialComputingType", None)
        # https://learn.microsoft.com/en-us/azure/virtual-machines/trusted-launch#limitations # noqa: E501
        if resource_sku.family not in [
            "standardMSFamily",
            "standardMDSMediumMemoryv2Family",
            "standardMSMediumMemoryv2Family",
            "standardMSv2Family",
        ]:
            # https://learn.microsoft.com/en-us/azure/virtual-machines/trusted-launch#how-can-i-find-vm-sizes-that-support-trusted-launch # noqa: E501
            if (
                gen_value
                and ("V2" in str(gen_value))
                and raw_capabilities.get("TrustedLaunchDisabled", "False") == "False"
            ):
                capabilities.append(SecurityProfileType.SecureBoot)
        # https://learn.microsoft.com/en-us/azure/confidential-computing/confidential-vm-overview # noqa: E501
        if cvm_value and resource_sku.family in [
            "standardDCASv5Family",
            "standardDCADSv5Family",
            "standardECASv5Family",
            "standardECADSv5Family",
        ]:
            capabilities.append(SecurityProfileType.CVM)

        return SecurityProfileSettings(
            security_profile=search_space.SetSpace(True, capabilities)
        )

    @classmethod
    def on_before_deployment(cls, *args: Any, **kwargs: Any) -> None:
        settings = cast(SecurityProfileSettings, kwargs.get("settings"))
        if SecurityProfileType.Standard != settings.security_profile:
            parameters: Any = kwargs.get("arm_parameters")
            if 1 == parameters.nodes[0].hyperv_generation:
                raise SkippedException(
                    f"{settings.security_profile} can only be set on gen2 image/vhd."
                )
            cls._enable_secure_boot(*args, **kwargs)

    @classmethod
    def _enable_secure_boot(cls, *args: Any, **kwargs: Any) -> None:
        settings: Any = kwargs.get("settings")
        template: Any = kwargs.get("template")
        log = cast(Logger, kwargs.get("log"))
        resources = template["resources"]
        virtual_machines = find_by_name(resources, "Microsoft.Compute/virtualMachines")
        if SecurityProfileType.Standard == settings.security_profile:
            log.debug("Security profile set to none. Arm template will not be updated.")
            return
        elif SecurityProfileType.SecureBoot == settings.security_profile:
            log.debug("Security Profile set to secure boot. Updating arm template.")
            security_type = "TrustedLaunch"
        elif SecurityProfileType.CVM == settings.security_profile:
            log.debug("Security Profile set to CVM. Updating arm template.")
            security_type = "ConfidentialVM"

            security_encryption_type = (
                "DiskWithVMGuestState" if settings.encrypt_disk else "VMGuestStateOnly"
            )

            if settings.disk_encryption_set_id:
                disk_encryption_set = (
                    ',"diskEncryptionSet":{"id":"'
                    f"{settings.disk_encryption_set_id}"
                    '"}'
                )
            else:
                disk_encryption_set = ""

            template["functions"][0]["members"]["getOSImage"]["output"]["value"][
                "managedDisk"
            ] = (
                "[if(not(equals(parameters('node')['disk_type'], 'Ephemeral')), "
                'json(concat(\'{"storageAccountType": "\','
                "parameters('node')['disk_type'],"
                '\'","securityProfile":{"securityEncryptionType": "'
                f'{security_encryption_type}"'
                f"{disk_encryption_set}"
                "}}')), json('null'))]"
            )
        else:
            raise LisaException(
                "Security profile: not all requirements could be met. "
                "Please check VM SKU capabilities, test requirements, "
                "and runbook requirements."
            )

        virtual_machines["properties"].update(
            json.loads(
                cls._both_enabled_properties % security_type,
            )
        )


class IsolatedResource(AzureFeatureMixin, features.IsolatedResource):
    # From https://docs.microsoft.com/en-us/azure/security/fundamentals/isolation-choices#compute-isolation # noqa: E501
    supported_vm_sizes = set(
        [
            "Standard_E80ids_v4",
            "Standard_E80is_v4",
            "Standard_E104i_v5",
            "Standard_E104is_v5",
            "Standard_E104id_v5",
            "Standard_E104ids_v5",
            "Standard_M192is_v2",
            "Standard_M192ims_v2",
            "Standard_M192ids_v2",
            "Standard_M192idms_v2",
            "Standard_F72s_v2",
            "Standard_M128ms",
            # add custom vm sizes below,
        ]
    )

    @classmethod
    def create_setting(
        cls, *args: Any, **kwargs: Any
    ) -> Optional[schema.FeatureSettings]:
        resource_sku: Any = kwargs.get("resource_sku")

        if resource_sku.name in cls.supported_vm_sizes:
            return schema.FeatureSettings.create(cls.name())

        return None


class ACC(AzureFeatureMixin, features.ACC):
    @classmethod
    def create_setting(
        cls, *args: Any, **kwargs: Any
    ) -> Optional[schema.FeatureSettings]:
        resource_sku: Any = kwargs.get("resource_sku")

        if resource_sku.family in ["standardDCSv2Family", "standardDCSv3Family"]:
            return schema.FeatureSettings.create(cls.name())
        return None


class NestedVirtualization(AzureFeatureMixin, features.NestedVirtualization):
    @classmethod
    def create_setting(
        cls, *args: Any, **kwargs: Any
    ) -> Optional[schema.FeatureSettings]:
        resource_sku: Any = kwargs.get("resource_sku")

        # add vm which support nested virtualization
        # https://docs.microsoft.com/en-us/azure/virtual-machines/acu
        if resource_sku.family in [
            "standardDDSv5Family",
            "standardDDv4Family",
            "standardDDv5Family",
            "standardDSv3Family",
            "standardDSv4Family",
            "standardDSv5Family",
            "standardDv3Family",
            "standardDv4Family",
            "standardDv5Family",
            "standardDADSv5Family",
            "standardDASv5Family",
            "standardDDSv4Family",
            "standardEIv5Family",
            "standardEADSv5Family",
            "standardEASv5Family",
            "standardEDSv4Family",
            "standardEDSv5Family",
            "standardESv3Family",
            "standardESv4Family",
            "standardESv5Family",
            "standardEBDSv5Family",
            "standardEBSv5Family",
            "standardEDv4Family",
            "standardEv4Family",
            "standardEDv5Family",
            "standardEv3Family",
            "standardEv5Family",
            "standardXEIDSv4Family",
            "standardXEISv4Family",
            "standardFSv2Family",
            "standardFXMDVSFamily",
            "standardLASv3Family",
            "standardLSv3Family",
            "standardMSFamily",
            "standardMSMediumMemoryv2Family",
        ]:
            return schema.FeatureSettings.create(cls.name())
        return None


class Nvme(AzureFeatureMixin, features.Nvme):
    @classmethod
    def create_setting(
        cls, *args: Any, **kwargs: Any
    ) -> Optional[schema.FeatureSettings]:
        resource_sku: Any = kwargs.get("resource_sku")
        node_space: Any = kwargs.get("node_space")

        assert isinstance(node_space, schema.NodeSpace), f"actual: {type(node_space)}"
        # add vm which support nested virtualization
        # https://docs.microsoft.com/en-us/azure/virtual-machines/acu
        if resource_sku.family in [
            "standardLSv2Family",
        ]:
            # refer https://docs.microsoft.com/en-us/azure/virtual-machines/lsv2-series # noqa: E501
            # NVMe disk count = vCPU / 8
            nvme = features.NvmeSettings()
            assert isinstance(
                node_space.core_count, int
            ), f"actual: {node_space.core_count}"
            nvme.disk_count = int(node_space.core_count / 8)
            return nvme

        return None


class Nfs(AzureFeatureMixin, features.Nfs):
    @classmethod
    def create_setting(
        cls, *args: Any, **kwargs: Any
    ) -> Optional[schema.FeatureSettings]:
        return schema.FeatureSettings.create(cls.name())

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)
        self.storage_account_name: str = ""
        self.file_share_name: str = ""

    def create_share(self) -> None:
        platform: AzurePlatform = self._platform  # type: ignore
        node_context = self._node.capability.get_extended_runbook(AzureNodeSchema)
        location = node_context.location
        resource_group_name = self._resource_group_name
        random_str = generate_random_chars(string.ascii_lowercase + string.digits, 10)
        self.storage_account_name = f"lisasc{random_str}"
        self.file_share_name = f"lisa{random_str}fs"

        # create storage account and file share
        check_or_create_storage_account(
            credential=platform.credential,
            subscription_id=platform.subscription_id,
            account_name=self.storage_account_name,
            resource_group_name=resource_group_name,
            location=location,
            log=self._log,
            sku="Premium_LRS",
            kind="FileStorage",
            enable_https_traffic_only=False,
        )
        get_or_create_file_share(
            credential=platform.credential,
            subscription_id=platform.subscription_id,
            account_name=self.storage_account_name,
            file_share_name=self.file_share_name,
            resource_group_name=resource_group_name,
            protocols="NFS",
            log=self._log,
        )

        storage_account_resource_id = (
            f"/subscriptions/{platform.subscription_id}/resourceGroups/"
            f"{resource_group_name}/providers/Microsoft.Storage/storageAccounts"
            f"/{self.storage_account_name}"
        )
        # get vnet and subnet id
        virtual_networks_dict: Dict[str, List[str]] = get_virtual_networks(
            platform, resource_group_name
        )
        virtual_networks_id = ""
        subnet_id = ""
        for vnet_id, subnet_ids in virtual_networks_dict.items():
            virtual_networks_id = vnet_id
            subnet_id = subnet_ids[0]
            break

        # create private endpoints
        ipv4_address = create_update_private_endpoints(
            platform,
            resource_group_name,
            location,
            subnet_id,
            storage_account_resource_id,
            ["file"],
            self._log,
        )
        # create private zone
        private_dns_zone_id = create_update_private_zones(
            platform, resource_group_name, self._log
        )
        # create records sets
        create_update_record_sets(
            platform, resource_group_name, str(ipv4_address), self._log
        )
        # create virtual network links for the private zone
        create_update_virtual_network_links(
            platform, resource_group_name, virtual_networks_id, self._log
        )
        # create private dns zone groups
        create_update_private_dns_zone_groups(
            platform=platform,
            resource_group_name=resource_group_name,
            private_dns_zone_id=str(private_dns_zone_id),
            log=self._log,
        )

    def delete_share(self) -> None:
        platform: AzurePlatform = self._platform  # type: ignore
        resource_group_name = self._resource_group_name
        delete_private_dns_zone_groups(platform, resource_group_name, self._log)
        delete_virtual_network_links(platform, resource_group_name, self._log)
        delete_record_sets(platform, resource_group_name, self._log)
        delete_private_zones(platform, resource_group_name, self._log)
        delete_private_endpoints(platform, resource_group_name, self._log)
        delete_file_share(
            platform.credential,
            platform.subscription_id,
            self.storage_account_name,
            self.file_share_name,
            resource_group_name,
            self._log,
        )
        delete_storage_account(
            platform.credential,
            platform.subscription_id,
            self.storage_account_name,
            resource_group_name,
            self._log,
        )


class AzureExtension(AzureFeatureMixin, Feature):
    RESOURCE_NOT_FOUND = re.compile(r"ResourceNotFound", re.M)

    @classmethod
    def create_setting(
        cls, *args: Any, **kwargs: Any
    ) -> Optional[schema.FeatureSettings]:
        return schema.FeatureSettings.create(cls.name())

    def create_or_update(
        self,
        type_: str,
        name: str = "",
        tags: Optional[Dict[str, str]] = None,
        publisher: str = "Microsoft.Azure.Extensions",
        type_handler_version: str = "2.1",
        auto_upgrade_minor_version: Optional[bool] = None,
        enable_automatic_upgrade: Optional[bool] = None,
        force_update_tag: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
        protected_settings: Any = None,
        suppress_failures: Optional[bool] = None,
        timeout: int = 60 * 25,
    ) -> Any:
        platform: AzurePlatform = self._platform  # type: ignore
        compute_client = get_compute_client(platform)
        if not name:
            name = f"ext-{generate_random_chars()}"

        extension_parameters = VirtualMachineExtension(
            tags=tags,
            name=name,
            location=self._location,
            force_update_tag=force_update_tag,
            publisher=publisher,
            auto_upgrade_minor_version=auto_upgrade_minor_version,
            type_properties_type=type_,
            type_handler_version=type_handler_version,
            enable_automatic_upgrade=enable_automatic_upgrade,
            settings=settings,
            protected_settings=protected_settings,
            suppress_failures=suppress_failures,
        )

        self._log.debug(f"extension_parameters: {extension_parameters.as_dict()}")

        operation = compute_client.virtual_machine_extensions.begin_create_or_update(
            resource_group_name=self._resource_group_name,
            vm_name=self._vm_name,
            vm_extension_name=name,
            extension_parameters=extension_parameters,
        )
        result = wait_operation(operation, timeout)

        return result

    def delete(
        self,
        name: str = "",
        timeout: int = 60 * 25,
    ) -> None:
        platform: AzurePlatform = self._platform  # type: ignore
        compute_client = get_compute_client(platform)
        self._log.debug(f"uninstall extension: {name}")

        operation = compute_client.virtual_machine_extensions.begin_delete(
            resource_group_name=self._resource_group_name,
            vm_name=self._vm_name,
            vm_extension_name=name,
        )
        # no return for this operation
        wait_operation(operation, timeout)

    def list_all(self) -> Any:
        platform: AzurePlatform = self._platform  # type: ignore
        compute_client = get_compute_client(platform)
        self._log.debug(f"list all extensions in rg: {self._resource_group_name}")

        return_list = compute_client.virtual_machine_extensions.list(
            resource_group_name=self._resource_group_name,
            vm_name=self._vm_name,
        )
        return return_list.value

    def check_exist(self, name: str) -> bool:
        platform: AzurePlatform = self._platform  # type: ignore
        compute_client = get_compute_client(platform)
        try:
            compute_client.virtual_machine_extensions.get(
                resource_group_name=self._resource_group_name,
                vm_name=self._vm_name,
                vm_extension_name=name,
            )
            self._log.debug(f"the extension {name} has been installed")
            return True
        except Exception as ex:
            if find_patterns_in_lines(str(ex), [self.RESOURCE_NOT_FOUND]):
                self._log.debug(f"not found the extension {name}")
                return False
            else:
                raise ex

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)

        node_runbook = self._node.capability.get_extended_runbook(
            AzureNodeSchema, AZURE
        )
        self._location = node_runbook.location


@dataclass_json()
@dataclass()
class VhdGenerationSettings(schema.FeatureSettings):
    type: str = "VhdGeneration"
    # vhd generation in hyper-v
    gen: Optional[Union[search_space.SetSpace[int], int]] = field(  # type:ignore
        default_factory=partial(
            search_space.SetSpace,
            items=[1, 2],
        ),
        metadata=field_metadata(
            decoder=partial(search_space.decode_set_space_by_type, base_type=int)
        ),
    )

    def __eq__(self, o: object) -> bool:
        if not super().__eq__(o):
            return False

        assert isinstance(o, VhdGenerationSettings), f"actual: {type(o)}"
        return self.type == o.type and self.gen == o.gen

    def __repr__(self) -> str:
        return f"gen:{self.gen}"

    def __str__(self) -> str:
        return self.__repr__()

    def __hash__(self) -> int:
        return super().__hash__()

    def _get_key(self) -> str:
        return f"{super()._get_key()}/{self.gen}"

    def check(self, capability: Any) -> search_space.ResultReason:
        assert isinstance(
            capability, VhdGenerationSettings
        ), f"actual: {type(capability)}"
        result = super().check(capability)

        result.merge(
            search_space.check_setspace(self.gen, capability.gen),
            "vhd generation",
        )

        return result

    def _call_requirement_method(self, method_name: str, capability: Any) -> Any:
        assert isinstance(
            capability, VhdGenerationSettings
        ), f"actual: {type(capability)}"

        value = VhdGenerationSettings()
        if self.gen or capability.gen:
            value.gen = getattr(search_space, f"{method_name}_setspace_by_priority")(
                self.gen, capability.gen, [1, 2]
            )
        return value


class VhdGeneration(AzureFeatureMixin, Feature):
    @classmethod
    def create_setting(
        cls, *args: Any, **kwargs: Any
    ) -> Optional[schema.FeatureSettings]:
        raw_capabilities: Any = kwargs.get("raw_capabilities")

        # regard missed value as both to maximize the test scope.
        value: str = raw_capabilities.get("HyperVGenerations", "V1,V2")
        versions = value.split(",")
        gens: List[int] = []
        if "V1" in versions:
            gens.append(1)
        if "V2" in versions:
            gens.append(2)

        settings = VhdGenerationSettings(gen=search_space.SetSpace(items=gens))

        return settings

    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return VhdGenerationSettings

    @classmethod
    def can_disable(cls) -> bool:
        return True

    def enabled(self) -> bool:
        return True


@dataclass_json()
@dataclass()
class ArchitectureSettings(schema.FeatureSettings):
    type: str = "Architecture"
    # Architecture in hyper-v
    arch: str = field(
        default="x64",
        metadata=field_metadata(
            validate=validate.OneOf(["x64", "Arm64"]),
        ),
    )

    def __eq__(self, o: object) -> bool:
        if not super().__eq__(o):
            return False

        assert isinstance(o, ArchitectureSettings), f"actual: {type(o)}"
        return self.type == o.type and self.arch == o.arch

    def __repr__(self) -> str:
        return f"arch:{self.arch}"

    def __str__(self) -> str:
        return self.__repr__()

    def __hash__(self) -> int:
        return super().__hash__()

    def _get_key(self) -> str:
        return f"{super()._get_key()}/{self.arch}"

    def check(self, capability: Any) -> search_space.ResultReason:
        assert isinstance(
            capability, ArchitectureSettings
        ), f"actual: {type(capability)}"
        result = super().check(capability)
        if self.arch != capability.arch:
            result.result = False
            result.reasons.append(
                f"image arch {self.arch} should be consistent with"
                f" vm size arch {capability.arch}"
            )

        return result

    def _call_requirement_method(self, method_name: str, capability: Any) -> Any:
        assert isinstance(
            capability, ArchitectureSettings
        ), f"actual: {type(capability)}"

        assert_that(self.arch).described_as(
            "req and capability should be the same"
        ).is_equal_to(capability.arch)

        value = ArchitectureSettings()
        value.arch = self.arch
        return value


class Architecture(AzureFeatureMixin, Feature):
    @classmethod
    def create_setting(
        cls, *args: Any, **kwargs: Any
    ) -> Optional[schema.FeatureSettings]:
        raw_capabilities: Any = kwargs.get("raw_capabilities")
        return ArchitectureSettings(
            arch=raw_capabilities.get("CpuArchitectureType", "x64")
        )

    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return ArchitectureSettings

    @classmethod
    def can_disable(cls) -> bool:
        return True

    def enabled(self) -> bool:
        return True
