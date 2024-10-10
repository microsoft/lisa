# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import asyncio
import copy
import json
import re
import string
import time
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
from azure.mgmt.compute.models import (
    DiskCreateOption,
    DiskCreateOptionTypes,
    HardwareProfile,
    NetworkInterfaceReference,
    VirtualMachineExtension,
    VirtualMachineUpdate,
)
from azure.mgmt.core.exceptions import ARMErrorFormat
from azure.mgmt.network.models import RouteTable  # type: ignore
from azure.mgmt.serialconsole import MicrosoftSerialConsoleClient  # type: ignore
from azure.mgmt.serialconsole.models import SerialPort, SerialPortState  # type: ignore
from azure.mgmt.serialconsole.operations import SerialPortsOperations  # type: ignore
from dataclasses_json import dataclass_json
from retry import retry

from lisa import Logger, features, schema, search_space
from lisa.environment import Environment
from lisa.feature import Feature
from lisa.features.availability import AvailabilityType
from lisa.features.gpu import ComputeSDK
from lisa.features.hibernation import HibernationSettings
from lisa.features.resize import ResizeAction
from lisa.features.security_profile import (
    FEATURE_NAME_SECURITY_PROFILE,
    SecurityProfileType,
)
from lisa.features.startstop import VMStatus
from lisa.node import Node, RemoteNode
from lisa.operating_system import BSD, CBLMariner, CentOs, Redhat, Suse, Ubuntu
from lisa.search_space import RequirementMethod
from lisa.secret import add_secret
from lisa.tools import (
    Cat,
    Curl,
    Dmesg,
    Find,
    IpInfo,
    LisDriver,
    Ls,
    Lsblk,
    Lspci,
    Modprobe,
    Rm,
    Sed,
)
from lisa.tools.echo import Echo
from lisa.tools.kernel_config import KernelConfig
from lisa.tools.lsblk import DiskInfo
from lisa.util import (
    LisaException,
    LisaTimeoutException,
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
    from .platform_ import AzurePlatform

from lisa.util.perf_timer import create_timer

from .. import AZURE
from .common import (
    AvailabilityArmParameter,
    AzureArmParameter,
    AzureCapability,
    AzureImageSchema,
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
    get_storage_credential,
    get_virtual_networks,
    get_vm,
    global_credential_access_lock,
    is_cloud_init_enabled,
    save_console_log,
    wait_operation,
)
from .tools import Waagent

HTTP_TOO_MANY_REQUESTS = 429


class AzureFeatureMixin:
    def _initialize_information(self, node: Node) -> None:
        node_context = get_node_context(node)
        self._vm_name = node_context.vm_name
        self._resource_group_name = node_context.resource_group_name


class StartStop(AzureFeatureMixin, features.StartStop):
    azure_vm_status_map = {
        "VM deallocated": VMStatus.Deallocated,
        "VM running": VMStatus.Running,
        "Provisioning succeeded": VMStatus.ProvisionSucceeded,
        # Add more Azure-specific mappings as needed
    }

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

        public_ip, private_ip = get_primary_ip_addresses(
            platform, self._resource_group_name, get_vm(platform, self._node)
        )
        node_info = self._node.connection_info
        node_info[constants.ENVIRONMENTS_NODES_REMOTE_PUBLIC_ADDRESS] = public_ip
        node_info[constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS] = private_ip
        node_info[
            constants.ENVIRONMENTS_NODES_REMOTE_USE_PUBLIC_ADDRESS
        ] = platform._azure_runbook.use_public_address
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

    def get_status(self) -> VMStatus:
        try:
            platform: AzurePlatform = self._platform  # type: ignore
            compute_client = get_compute_client(platform)
            status = (
                compute_client.virtual_machines.get(
                    self._resource_group_name, self._vm_name, expand="instanceView"
                )
                .instance_view.statuses[1]
                .display_status
            )
            assert isinstance(status, str), f"actual: {type(status)}"
            assert self.azure_vm_status_map.get(status) is not None, "unknown vm status"
            return cast(VMStatus, self.azure_vm_status_map.get(status))
        except Exception as e:
            raise LisaException(f"fail to get status of vm {self._vm_name}") from e


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
            map_error(
                status_code=response.status_code, response=response, error_map=error_map
            )
            raise HttpResponseError(response=response, error_format=ARMErrorFormat)

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
            self._log.debug(f"Connection closed on read serial console: {e}")
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
            self._log.debug(f"Connection closed on read serial console: {e}")
            self._ws = None
            self._get_connection()
            raise e

    def close(self) -> None:
        if self._ws is not None:
            self._log.debug("Closing connection to serial console")
            self._get_event_loop().run_until_complete(self._ws.close())
            self._ws = None

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
            ws = self._get_event_loop().run_until_complete(
                websockets.connect(connection_str)  # type: ignore
            )

            token = self._get_access_token()
            # add to secret in case it's echo back.
            add_secret(token)
            # send token to auth
            self._get_event_loop().run_until_complete(ws.send(token))

            self._ws = ws

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

    def _get_access_token(self) -> str:
        platform: AzurePlatform = self._platform  # type: ignore
        access_token = platform.credential.get_token(
            "https://management.core.windows.net/.default"
        ).token

        return access_token

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
        connection = self._serial_port_operations.connect(
            resource_group_name=self._resource_group_name,
            resource_provider_namespace=self.RESOURCE_PROVIDER_NAMESPACE,
            parent_resource_type=self.PARENT_RESOURCE_TYPE,
            parent_resource=self._vm_name,
            serial_port=self._serial_port.name,
        )
        return str(connection.connection_string)

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

        self._log.debug(f"Serial port {port_id} is enabled: {self._serial_port}")

        # setup shared web socket connection variable
        self._ws = None

        # setup output buffer
        self._output_string = ""

        # mark serial console as initialized
        self._serial_console_initialized = True


class Gpu(AzureFeatureMixin, features.Gpu):
    # refer https://learn.microsoft.com/en-us/azure/virtual-machines/linux/n-series-driver-setup#nvidia-grid-drivers # noqa: E501
    # grid vm sizes NV, NVv3, NCasT4v3, NVadsA10 v5
    _grid_supported_skus = re.compile(
        r"^(Standard_NV[\d]+(s_v3)?$|Standard_NC[\d]+as_T4_v3|"
        r"Standard_NV[\d]+ad(ms|s)_A10_v5)",
        re.I,
    )
    # refer https://learn.microsoft.com/en-us/azure/virtual-machines/windows/n-series-amd-driver-setup # noqa: E501
    # - NGads V620 Series: Standard_NG[^_]+_V620_v[0-9]+
    # - NVv4 Series: Standard_NV[^_]+_v4
    _amd_supported_skus = re.compile(
        r"^(Standard_NG[^_]+_V620_v[0-9]+|Standard_NV[^_]+_v4)$", re.I
    )

    _grid_supported_distros: Dict[Any, List[str]] = {
        Redhat: ["7.9.0", "8.6.0", "8.8.0"],
        Ubuntu: ["20.4.0", "22.4.0"],
    }
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
        elif isinstance(node.os, CBLMariner):
            supported = node.os.information.version >= "2.0.0"

        return supported

    def get_supported_driver(self) -> List[ComputeSDK]:
        driver_list = []
        node_runbook = self._node.capability.get_extended_runbook(
            AzureNodeSchema, AZURE
        )
        if (
            re.match(self._grid_supported_skus, node_runbook.vm_size)
            and self.is_grid_supported_os()
        ):
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

    # GRID driver is supported on a limited number of distros.
    # https://learn.microsoft.com/en-us/azure/virtual-machines/linux/n-series-driver-setup#nvidia-grid-drivers # noqa: E501
    def is_grid_supported_os(self) -> bool:
        distro = type(self._node.os)
        if distro not in self._grid_supported_distros:
            return False
        else:
            version = str(self._node.os.information.version)
            return version in self._grid_supported_distros[distro]

    @classmethod
    def create_setting(
        cls, *args: Any, **kwargs: Any
    ) -> Optional[schema.FeatureSettings]:
        raw_capabilities: Any = kwargs.get("raw_capabilities")
        node_space = kwargs.get("node_space")
        resource_sku: Any = kwargs.get("resource_sku")

        assert isinstance(node_space, schema.NodeSpace), f"actual: {type(node_space)}"

        value = raw_capabilities.get("GPUs", None)
        # refer https://learn.microsoft.com/en-us/azure/virtual-machines/sizes-gpu
        # NVv4 VMs currently support only Windows guest operating system.
        if value and resource_sku.family.casefold() not in ["standardnvsv4family"]:
            node_space.gpu_count = int(value)
            return schema.FeatureSettings.create(cls.name())

        return None

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)
        self._is_nvidia = True

    def _install_driver_using_platform_feature(self) -> None:
        # https://learn.microsoft.com/en-us/azure/virtual-machines/extensions/hpccompute-gpu-linux
        supported_versions: Dict[Any, List[str]] = {
            Redhat: ["7.9"],
            Ubuntu: ["20.04"],
            CentOs: ["7.3", "7.4", "7.5", "7.6", "7.7", "7.8"],
        }
        release = self._node.os.information.release
        if release not in supported_versions.get(type(self._node.os), []):
            raise UnsupportedOperationException("GPU Extension not supported")
        if type(self._node.os) == Redhat:
            self._node.os.handle_rhui_issue()
        extension = self._node.features[AzureExtension]
        try:
            result = extension.create_or_update(
                type_="NvidiaGpuDriverLinux",
                publisher="Microsoft.HpcCompute",
                type_handler_version="1.6",
                auto_upgrade_minor_version=True,
                settings={},
            )
        except Exception as e:
            if (
                "'Microsoft.HpcCompute.NvidiaGpuDriverLinux' already added"
                " or specified in input" in str(e)
            ):
                self._log.info("GPU Extension is already added")
                return
            else:
                raise e

        if result["provisioning_state"] == "Succeeded":
            # Close the connection because the extension takes long time
            # to install and ssh connection may get timeout.
            self._node.close()
            return
        else:
            raise LisaException("GPU Extension Provisioning Failed")

    def install_compute_sdk(self, version: str = "") -> None:
        try:
            # install LIS driver if required and not already installed.
            self._node.tools[LisDriver]
        except Exception as identifier:
            self._log.debug(
                f"LisDriver is not installed. It might not be required. {identifier}"
            )
        super().install_compute_sdk(version)


class Infiniband(AzureFeatureMixin, features.Infiniband):
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

    def setup_rdma(self) -> None:
        if self._node.tools[Ls].path_exists("/opt/azurehpc/component_versions.txt"):
            self.is_hpc_image = True
        super().setup_rdma()
        waagent = self._node.tools[Waagent]
        devices = self._get_ib_device_names()
        if len(devices) > 1:
            # upgrade waagent to latest version to resolve
            # multiple ib devices not getting ip address issue

            # Upgrade to v2.9.0.4 since the latest v2.9.1.1 version
            # does not successfully assign IP over the IB interface
            waagent.upgrade_from_source("v2.9.0.4")

            # Mark the node as dirty
            self._node.mark_dirty()
        # Update waagent.conf
        sed = self._node.tools[Sed]
        rdma_config = "OS.EnableRDMA=y"
        waagent_config_path = "/etc/waagent.conf"

        # CBLMariner's waagent configuration does not specify OS.EnableRDMA
        # and thus need to manually append it for RDMA support
        if isinstance(self._node.os, CBLMariner):
            # Check whether OS.EnableRDMA=y is already specified
            cat = self._node.tools[Cat]
            if rdma_config not in cat.read(waagent_config_path, sudo=True):
                sed.append(
                    text=rdma_config,
                    file=waagent_config_path,
                    sudo=True,
                )

        sed.substitute(
            regexp=f"# {rdma_config}",
            replacement=rdma_config,
            file=waagent_config_path,
            sudo=True,
        )
        sed.substitute(
            regexp="# AutoUpdate.Enabled=y",
            replacement="AutoUpdate.Enabled=y",
            file=waagent_config_path,
            sudo=True,
        )

        # For systems using the Mellanox inbox driver, need to make sure
        # the following kernel modules are loaded in order to successfully
        # make WALinuxAgent enable RDMA support
        modprobe = self._node.tools[Modprobe]
        for module in ["ib_uverbs", "ib_umad", "rdma_ucm", "ib_ipoib"]:
            if modprobe.module_exists(module):
                modprobe.load(module)

        waagent.restart()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)


class NetworkInterface(AzureFeatureMixin, features.NetworkInterface):
    """
    This Network interface feature is mainly to associate Azure
    network interface options settings.
    """

    # ex: 1.1.1.0/24 or 1.2.3.4/32 or 4.0.0.0/8
    __ipv4_mask_check_regex = re.compile(
        r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}/([012][0-9]?|3[012])"
    )

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

    def create_route_table(
        self,
        nic_name: str,
        route_name: str,
        subnet_mask: str,
        dest_hop: str,
        em_first_hop: str = "",
        next_hop_type: str = "",
    ) -> None:
        # some quick checks that the subnet mask looks correct
        check_mask = self.__ipv4_mask_check_regex.match(subnet_mask)
        assert_that(check_mask).described_as(
            "subnet mask should be prefix format X.X.X.X/YY"
        ).is_not_none()

        azure_platform: AzurePlatform = self._platform  # type: ignore
        # Step 1: create the route table, apply comes later.
        route_table = self._do_create_route_table(
            em_first_hop,
            subnet_mask=subnet_mask,
            nic_name=nic_name,
            route_name=route_name,
            next_hop_type=next_hop_type,
            dest_hop=dest_hop,
        )
        # Step 2: Get the virtual networks in the resource group.
        vnets: Dict[str, List[str]] = get_virtual_networks(
            azure_platform, self._resource_group_name
        )
        # get the subnets in the virtual network
        vnet_id = ""
        subnet_ids: List[str] = []
        assert_that(vnets.items()).described_as(
            "There is more than one virtual network in this RG!"
            " This RG is setup is unexpected, test cannot infer which VNET to use."
            "Check if LISA has changed it's test setup logic, verify if the "
            "DPDK test suite needs to be modified."
        ).is_length(1)

        # get the subnets for the virtual network in the test RG.
        # dict will have a single entry, lisa is only creating one vnet per test vm.
        vnet_items: List[Tuple[str, List[str]]] = list(vnets.items())
        vnet_id, subnet_ids = vnet_items[0]
        self._log.debug(f"Found vnet/subnet info: {vnet_id} {subnet_ids}")

        # get the az resource name for the virtual network
        # ex /subscriptions/[sub_id]/resourceGroups/rg_name/providers/...
        #        .../Microsoft.Network/virtualNetworks/lisa-virtualNetwork
        virtual_network_name = vnet_id.split("/")[-1]

        # Step 3: Look for the subnet we'll assign this routing table entry to.
        for subnet in subnet_ids:
            # get the az resource name for the subnet
            # ex /subscriptions/[sub_id]/resourceGroups/rg_name/providers/...
            #     .../subnet_resource_name
            subnet_name = subnet.split("/")[-1]
            # update the subnet, there will only be one since they cannot
            # share address spaces.
            if self._do_update_subnet(
                virtual_network_name=virtual_network_name,
                subnet_name=subnet_name,
                subnet_mask=subnet_mask,
                route_table=route_table,
            ):
                return
        # if we're through the loop and didn't find the subnet, fail
        raise LisaException(
            "routing table was not assigned to any subnet! "
            f"targeted subnet: {subnet_mask} with route table: {route_table}"
        )

    def switch_ip_forwarding(self, enable: bool, private_ip_addr: str = "") -> None:
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
            # Since the VM nic and the Azure NIC names won't always match,
            # allow selection by private_ip_address to resolve a NIC in the VM
            # to an azure network interface resource.
            if private_ip_addr and not any(
                [
                    x.private_ip_address == private_ip_addr
                    for x in updated_nic.ip_configurations
                ]
            ):
                # if ip is provided, skip resource which don't match.
                self._log.debug(f"Skipping enable ip forwarding on nic {nic_name}...")
                continue
            if updated_nic.enable_ip_forwarding == enable:
                self._log.debug(
                    f"network interface {nic_name}'s ip forwarding default "
                    f"status [{updated_nic.enable_ip_forwarding}] is "
                    f"consistent with set status [{enable}], no need to update."
                )
            else:
                self._log.debug(
                    f"network interface {nic_name}'s ip forwarding default "
                    f"status [{updated_nic.enable_ip_forwarding}], "
                    f"now set its status into [{enable}]."
                )
                updated_nic.enable_ip_forwarding = enable
                network_client.network_interfaces.begin_create_or_update(
                    self._resource_group_name, updated_nic.name, updated_nic
                )
                updated_nic = network_client.network_interfaces.get(
                    self._resource_group_name, nic_name
                )
                assert_that(updated_nic.enable_ip_forwarding).described_as(
                    f"fail to set network interface {nic_name}'s ip forwarding "
                    f"into status [{enable}]"
                ).is_equal_to(enable)

    def switch_sriov(
        self, enable: bool, wait: bool = True, reset_connections: bool = True
    ) -> None:
        azure_platform: AzurePlatform = self._platform  # type: ignore
        network_client = get_network_client(azure_platform)
        vm = get_vm(azure_platform, self._node)
        status_changed = False
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
                status_changed = True

        # wait settings effective
        if wait and status_changed:
            self._check_sriov_enabled(enable, reset_connections)

    def is_enabled_sriov(self) -> bool:
        azure_platform: AzurePlatform = self._platform  # type: ignore
        network_client = get_network_client(azure_platform)
        sriov_enabled: bool = False
        vm = get_vm(azure_platform, self._node)
        nic = self._get_primary(vm.network_profile.network_interfaces)
        assert nic.id, "'nic.id' must not be 'None'"
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
        assert nic.id, "'nic.id' must not be 'None'"
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
        assert nic.id, "'nic.id' must not be 'None'"
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

    # Subroutine for applying route table to subnet.
    # We don't want to retry the entire routine if we
    # catch an exception in this section.
    @retry(HttpResponseError, tries=5, delay=1, backoff=1.3)
    def _do_update_subnet(
        self,
        virtual_network_name: str,
        subnet_name: str,
        subnet_mask: str,
        route_table: RouteTable,
    ) -> bool:
        platform: AzurePlatform = self._platform  # type: ignore
        network_client = get_network_client(platform)
        subnet_az = network_client.subnets.get(
            resource_group_name=self._resource_group_name,
            virtual_network_name=virtual_network_name,
            subnet_name=subnet_name,
        )
        self._log.debug(f"Checking subnet: {subnet_az.address_prefix} == {subnet_mask}")
        # Step 4: once we find the matching subnet, assign the routing table to it.
        if subnet_az.address_prefix == subnet_mask:
            subnet_az.route_table = route_table
            result = network_client.subnets.begin_create_or_update(
                resource_group_name=self._resource_group_name,
                virtual_network_name=virtual_network_name,
                subnet_name=subnet_name,
                subnet_parameters=subnet_az,
            ).result()
            # log the subnets we're finding along the way...
            self._log.info(
                f'Assigned routing table "{route_table}" to subnet: "{subnet_az}"'
                f' with result: "{result}"'
            )
            return True
        return False

    # Subroutine to create the route table,
    # seperated because the create/apply process has multiple potential timeouts.
    # We don't want to restart the entire process if one step fails.
    @retry(HttpResponseError, tries=5, delay=1, backoff=1.3)
    def _do_create_route_table(
        self,
        em_first_hop: str,
        subnet_mask: str,
        nic_name: str,
        route_name: str,
        next_hop_type: str,
        dest_hop: str,
    ) -> RouteTable:
        platform: AzurePlatform = self._platform  # type: ignore
        network_client = get_network_client(platform)
        vm = get_vm(platform, self._node)

        # Set up first hop routing rule.
        # If no exact match first hop is provided:
        # assume the rule is to be applied to all traffic on the subnet.
        # Otherwise allow an arbitrary 'first hop' address
        if not em_first_hop:
            address_prefix = subnet_mask
        else:
            address_prefix = em_first_hop

        # NOTE: Next Hop Types
        # 'None' is for dropping all traffic
        # 'VirtualAppliance' is common for sending all traffic on a subnet
        # to a VM (or NetVirtualApplicate aka NVA ) to filter it before forarding.
        # There are other next hop types, see:
        # https://learn.microsoft.com/en-us/azure/virtual-network/virtual-networks-udr-overview#user-defined

        # Step 1: Create the routing table entry, it will be assigned to a subnet later.
        route_table_name = f"{nic_name}-{route_name}-route_table"
        route_table: RouteTable = network_client.route_tables.begin_create_or_update(
            resource_group_name=self._resource_group_name,
            route_table_name=f"{nic_name}-{route_name}-route_table",
            parameters={
                "location": vm.location,
                "properties": {
                    "disableBgpRoutePropagation": False,
                    "routes": [
                        {
                            "name": route_table_name,
                            "properties": {
                                "addressPrefix": address_prefix,
                                "nextHopType": next_hop_type,
                                "nextHopIpAddress": dest_hop,
                            },
                        },
                    ],
                },
            },
        ).result()
        self._log.debug(f"Created routing table:{route_table}")

        return route_table

    @retry(tries=60, delay=10)
    def _check_sriov_enabled(
        self, enabled: bool, reset_connections: bool = True
    ) -> None:
        if reset_connections:
            self._node.close()
        self._node.nics.check_pci_enabled(enabled)

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

    def get_all_primary_nics_ip_info(self) -> List[IpInfo]:
        interfaces_info_list: List[IpInfo] = []
        for interface in self._get_all_nics():
            interfaces_info_list.append(
                IpInfo(
                    interface.name,
                    ":".join(interface.mac_address.lower().split("-")),
                    [
                        x.private_ip_address
                        for x in interface.ip_configurations
                        if x.primary
                    ][0],
                )
            )
        return interfaces_info_list

    def get_all_nics_ip_info(self) -> List[IpInfo]:
        interfaces_info_list: List[IpInfo] = []
        for interface in self._get_all_nics():
            interfaces_info_list.append(
                IpInfo(
                    interface.name,
                    ":".join(interface.mac_address.lower().split("-")),
                    [x.private_ip_address for x in interface.ip_configurations][0],
                )
            )
        return interfaces_info_list


# Tuple: (Disk Size, IOPS, Throughput)
_disk_size_performance_map: Dict[schema.DiskType, List[Tuple[int, int, int]]] = {
    schema.DiskType.PremiumSSDLRS: [
        (4, 120, 25),
        (64, 240, 50),
        (128, 500, 100),
        (256, 1100, 125),
        (512, 2300, 150),
        (1024, 5000, 200),
        (2048, 7500, 250),
        (8192, 16000, 500),
        (16384, 18000, 750),
        (32767, 20000, 900),
    ],
    schema.DiskType.PremiumV2SSDLRS: [
        (4, 1200, 300),
        (8, 2400, 600),
        (16, 4800, 1200),
        (32, 9600, 2400),
        (64, 19200, 4000),
        (128, 38400, 4000),
        (256, 76800, 4000),
        (512, 153600, 4000),
        (1024, 160000, 4000),
    ],
    schema.DiskType.StandardHDDLRS: [
        (32, 500, 60),
        (8192, 1300, 300),
        (16384, 2000, 500),
    ],
    schema.DiskType.StandardSSDLRS: [
        (4, 500, 60),
        (8192, 2000, 400),
        (16384, 4000, 600),
        (32767, 6000, 750),
    ],
    schema.DiskType.UltraSSDLRS: [
        (4, 1200, 300),
        (8, 2400, 600),
        (16, 4800, 1200),
        (32, 9600, 2400),
        (64, 19200, 4000),
        (128, 38400, 4000),
        (256, 76800, 4000),
        (512, 153600, 4000),
        (1024, 160000, 4000),
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
            search_space.check_setspace(self.os_disk_type, capability.os_disk_type),
            "os_disk_type",
        )
        result.merge(
            search_space.check_countspace(self.os_disk_size, capability.os_disk_size),
            "os_disk_size",
        )
        result.merge(
            search_space.check_setspace(self.data_disk_type, capability.data_disk_type),
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
                self.data_disk_throughput, capability.data_disk_throughput
            ),
            "data_disk_throughput",
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

    def _call_requirement_method(
        self, method: RequirementMethod, capability: Any
    ) -> Any:
        assert isinstance(
            capability, AzureDiskOptionSettings
        ), f"actual: {type(capability)}"

        assert (
            capability.os_disk_type
        ), "capability should have at least one OS disk type, but it's None"
        assert (
            capability.data_disk_type
        ), "capability should have at least one disk type, but it's None"
        assert (
            capability.disk_controller_type
        ), "capability should have at least one disk controller type, but it's None"
        value = AzureDiskOptionSettings()
        super_value = schema.DiskOptionSettings._call_requirement_method(
            self, method, capability
        )
        set_filtered_fields(super_value, value, ["data_disk_count"])

        cap_os_disk_type = capability.os_disk_type
        if isinstance(cap_os_disk_type, search_space.SetSpace):
            assert (
                len(cap_os_disk_type) > 0
            ), "capability should have at least one disk type, but it's empty"
        elif isinstance(cap_os_disk_type, schema.DiskType):
            cap_os_disk_type = search_space.SetSpace[schema.DiskType](
                is_allow_set=True, items=[cap_os_disk_type]
            )
        else:
            raise LisaException(
                f"unknown OS disk type on capability, type: {cap_os_disk_type}"
            )

        value.os_disk_type = getattr(
            search_space, f"{method.value}_setspace_by_priority"
        )(self.os_disk_type, capability.os_disk_type, schema.disk_type_priority)

        cap_disk_type = capability.data_disk_type
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

        if self.os_disk_size is not None or capability.os_disk_size is not None:
            value.os_disk_size = getattr(search_space, f"{method.value}_countspace")(
                self.os_disk_size, capability.os_disk_size
            )

        value.data_disk_type = getattr(
            search_space, f"{method.value}_setspace_by_priority"
        )(self.data_disk_type, capability.data_disk_type, schema.disk_type_priority)

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
            search_space, f"{method.value}_setspace_by_priority"
        )(
            self.disk_controller_type,
            capability.disk_controller_type,
            schema.disk_controller_type_priority,
        )

        # below values affect data disk only.
        if self.data_disk_count is not None or capability.data_disk_count is not None:
            value.data_disk_count = getattr(search_space, f"{method.value}_countspace")(
                self.data_disk_count, capability.data_disk_count
            )

        if (
            self.max_data_disk_count is not None
            or capability.max_data_disk_count is not None
        ):
            value.max_data_disk_count = getattr(
                search_space, f"{method.value}_countspace"
            )(self.max_data_disk_count, capability.max_data_disk_count)

        # The Ephemeral doesn't support data disk, but it needs a value. And it
        # doesn't need to calculate on intersect
        value.data_disk_iops = 0
        value.data_disk_throughput = 0
        value.data_disk_size = 0

        if method == RequirementMethod.generate_min_capability:
            assert isinstance(
                value.data_disk_type, schema.DiskType
            ), f"actual: {type(value.data_disk_type)}"
            disk_type_performance = _disk_size_performance_map.get(
                value.data_disk_type, None
            )
            # ignore unsupported disk type like Ephemeral. It supports only os
            # disk. Calculate for iops, if it has value. If not, try disk size
            if disk_type_performance:
                req_disk_iops = search_space.count_space_to_int_range(
                    self.data_disk_iops
                )
                cap_disk_iops = search_space.count_space_to_int_range(
                    capability.data_disk_iops
                )
                min_iops = max(req_disk_iops.min, cap_disk_iops.min)
                max_iops = min(req_disk_iops.max, cap_disk_iops.max)

                req_disk_throughput = search_space.count_space_to_int_range(
                    self.data_disk_throughput
                )
                cap_disk_throughput = search_space.count_space_to_int_range(
                    capability.data_disk_throughput
                )
                min_throughput = max(req_disk_throughput.min, cap_disk_throughput.min)
                max_throughput = min(req_disk_throughput.max, cap_disk_throughput.max)

                req_disk_size = search_space.count_space_to_int_range(
                    self.data_disk_size
                )
                cap_disk_size = search_space.count_space_to_int_range(
                    capability.data_disk_size
                )
                min_size = max(req_disk_size.min, cap_disk_size.min)
                max_size = min(req_disk_size.max, cap_disk_size.max)

                value.data_disk_size = min(
                    size
                    for size, iops, throughput in disk_type_performance
                    if iops >= min_iops
                    and iops <= max_iops
                    and throughput >= min_throughput
                    and throughput <= max_throughput
                    and size >= min_size
                    and size <= max_size
                )

                (
                    value.data_disk_iops,
                    value.data_disk_throughput,
                ) = self._get_disk_performance_from_size(
                    value.data_disk_size, disk_type_performance
                )

        elif method == RequirementMethod.intersect:
            value.data_disk_iops = search_space.intersect_countspace(
                self.data_disk_iops, capability.data_disk_iops
            )
            value.data_disk_throughput = search_space.intersect_countspace(
                self.data_disk_throughput, capability.data_disk_throughput
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

    def _get_disk_performance_from_size(
        self, data_disk_size: int, disk_type_performance: List[Tuple[int, int, int]]
    ) -> Tuple[int, int]:
        return next(
            (iops, throughput)
            for size, iops, throughput in disk_type_performance
            if size == data_disk_size
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

    # /sys/block/sda = > sda
    # /sys/block/sdb = > sdb
    DISK_LABEL_PATTERN = re.compile(r"/sys/block/(?P<label>sd\w*)", re.M)

    # =>       40  369098672  da1  GPT  (176G)
    DISK_LABEL_PATTERN_BSD = re.compile(
        r"^=>\s+\d+\s+\d+\s+(?P<label>\w*)\s+\w+\s+\(\w+\)", re.M
    )

    # mounts:
    #   - [ ephemeral0, /mnt/resource ]
    EPHEMERAL_DISK_PATTERN = re.compile(
        r"^(?!\s*#)\s*mounts:\s+-\s*\[\s*ephemeral[0-9]+,\s*([^,\s]+)\s*\]", re.M
    )

    # /dev/nvme0n1p15 -> /dev/nvme0n1
    NVME_NAMESPACE_PATTERN = re.compile(r"/dev/nvme[0-9]+n[0-9]+", re.M)

    # /dev/nvme0n1p15 -> /dev/nvme0
    NVME_CONTROLLER_PATTERN = re.compile(r"/dev/nvme[0-9]+", re.M)

    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return AzureDiskOptionSettings

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)

    def get_hardware_disk_controller_type(self) -> Any:
        azure_platform: AzurePlatform = self._platform  # type: ignore
        vm = get_vm(azure_platform, self._node)
        return vm.storage_profile.disk_controller_type

    def _get_scsi_data_disks(self) -> List[str]:
        # This method restuns azure data disks attached to you given VM.
        # refer here to get data disks from folder /dev/disk/azure/scsi1
        # Example: /dev/disk/azure/scsi1/lun0
        # https://docs.microsoft.com/en-us/troubleshoot/azure/virtual-machines/troubleshoot-device-names-problems#identify-disk-luns  # noqa: E501
        ls_tools = self._node.tools[Ls]
        files = ls_tools.list("/dev/disk/azure/scsi1", sudo=True)

        azure_scsi_disks = []
        assert self._node.capability.disk
        assert isinstance(self._node.capability.disk.max_data_disk_count, int)
        if len(files) == 0 and self._node.capability.disk.data_disk_count != 0:
            os = self._node.os
            # https://docs.microsoft.com/en-us/troubleshoot/azure/virtual-machines/troubleshoot-device-names-problems#get-the-latest-azure-storage-rules  # noqa: E501
            # there are known issues on ubuntu 16.04, rhel 9.0 and mariner 3.0
            # try to workaround it
            if (
                (isinstance(os, Ubuntu) and os.information.release <= "16.04")
                or (isinstance(os, Redhat) and os.information.release >= "9.0")
                or isinstance(os, CBLMariner)
            ):
                self._log.debug(
                    "download udev rules to construct a set of "
                    "symbolic links under the /dev/disk/azure path"
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
        azure_scsi_disks = [
            x for x in files if get_matched_str(x, self.SCSI_PATTERN) != ""
        ]
        return azure_scsi_disks

    def get_luns(self) -> Dict[str, int]:
        # disk_controller_type == SCSI
        # get azure scsi attached disks
        azure_scsi_disks = self._get_scsi_data_disks()
        device_luns = {}
        lun_number_pattern = re.compile(r"[0-9]+$", re.M)
        for disk in azure_scsi_disks:
            # /dev/disk/azure/scsi1/lun20 -> 20
            device_lun = int(get_matched_str(disk, lun_number_pattern))
            # readlink -f /dev/disk/azure/scsi1/lun0
            # /dev/sdc
            cmd_result = self._node.execute(
                f"readlink -f {disk}", shell=True, sudo=True
            )
            device_luns.update({cmd_result.stdout: device_lun})
        return device_luns

    def get_raw_data_disks(self) -> List[str]:
        # Handle BSD case
        if isinstance(self._node.os, BSD):
            return self._get_raw_data_disks_bsd()

        # disk_controller_type == NVME
        node_disk = self._node.features[Disk]
        if node_disk.get_os_disk_controller_type() == schema.DiskControllerType.NVME:
            # Getting OS disk nvme namespace and disk controller used by OS disk.
            # Sample os_boot_partition:
            # name: /dev/nvme0n1p15, disk: nvme, mount_point: /boot/efi, type: vfat
            os_boot_partition = node_disk.get_os_boot_partition()
            if os_boot_partition:
                os_disk_namespace = get_matched_str(
                    os_boot_partition.name,
                    self.NVME_NAMESPACE_PATTERN,
                )
                os_disk_controller = get_matched_str(
                    os_boot_partition.name,
                    self.NVME_CONTROLLER_PATTERN,
                )

            # With NVMe disk controller type, all remote SCSI disks are connected to
            # same NVMe controller. The same controller is used by OS disk.
            # This loop collects all the SCSI remote disks except OS disk.
            nvme = self._node.features[Nvme]
            nvme_namespaces = nvme.get_namespaces()
            disk_array = []
            for name_space in nvme_namespaces:
                if (
                    name_space.startswith(os_disk_controller)
                    and name_space != os_disk_namespace
                ):
                    disk_array.append(name_space)
            return disk_array

        # disk_controller_type == SCSI

        # get azure scsi attached disks
        azure_scsi_disks = self._get_scsi_data_disks()
        assert_that(len(azure_scsi_disks)).described_as(
            "no data disks info found under /dev/disk/azure/scsi1"
        ).is_greater_than(0)
        assert azure_scsi_disks, "not find data disks"
        disk_array = [""] * len(azure_scsi_disks)
        for disk in azure_scsi_disks:
            # readlink -f /dev/disk/azure/scsi1/lun0
            # /dev/sdc
            cmd_result = self._node.execute(
                f"readlink -f {disk}", shell=True, sudo=True
            )
            disk_array[int(disk.split("/")[-1].replace("lun", ""))] = cmd_result.stdout
        return disk_array

    def get_all_disks(self) -> List[str]:
        if isinstance(self._node.os, BSD):
            disk_label_pattern = self.DISK_LABEL_PATTERN_BSD
            cmd_result = self._node.execute("gpart show", shell=True, sudo=True)
        else:
            disk_label_pattern = self.DISK_LABEL_PATTERN
            cmd_result = self._node.execute(
                "ls -d /sys/block/sd*", shell=True, sudo=True
            )
        matched = find_patterns_in_lines(cmd_result.stdout, [disk_label_pattern])
        assert matched[0], "not found the matched disk label"
        return list(set(matched[0]))

    def add_data_disk(
        self,
        count: int,
        disk_type: schema.DiskType = schema.DiskType.StandardHDDLRS,
        size_in_gb: int = 20,
        lun: int = -1,
    ) -> List[str]:
        if lun != -1:
            assert_that(
                count,
                "Data disk add count should be equal to 1"
                " when 'lun' number is passed by the caller",
            ).is_equal_to(1)
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
            name = f"lisa_data_disk_{i+current_disk_count}_{self._node.name}"
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
            if lun != -1:
                lun_temp = lun
            else:
                lun_temp = i + current_disk_count
            self._log.debug(f"attaching disk {managed_disk.name} at lun #{lun_temp}")
            vm.storage_profile.data_disks.append(
                {
                    "lun": lun_temp,
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
        # get customize mount point from cloud-init configuration file from /etc/cloud/
        # if not found, use default mount point /mnt for cloud-init
        if is_cloud_init_enabled(self._node):
            self._log.debug("Disk handled by cloud-init.")
            # get mount point from cloud-init config files
            find_tool = self._node.tools[Find]
            file_list = find_tool.find_files(
                self._node.get_pure_path("/etc/cloud/"),
                "*.cfg",
                sudo=True,
                ignore_not_exist=True,
                file_type="f",
            )
            conf_content = ""
            for found_file in file_list:
                conf_content = conf_content + self._node.tools[Cat].read(
                    str(found_file), sudo=True, no_debug_log=True
                )
            match = self.EPHEMERAL_DISK_PATTERN.search(conf_content)

            if match:
                mount_point = match.group(1)
                self._log.debug(
                    f"Found mount point {mount_point} from "
                    "cloud-init configuration file."
                )
            else:
                mount_point = "/mnt"
                self._log.debug(
                    "No mount point found from cloud-init configuration file. Use /mnt."
                )
        else:
            self._log.debug("Disk handled by waagent.")
            mount_point = self._node.tools[Waagent].get_resource_disk_mount_point()
        return mount_point

    def _is_resource_disk(self, disk: DiskInfo) -> bool:
        # check if the disk is a resource disk
        if disk.mountpoint == "/mnt/resource":
            return True

        return any(
            partition.mountpoint == "/mnt/resource" for partition in disk.partitions
        )

    def _get_raw_data_disks_bsd(self) -> List[str]:
        disks = self._node.tools[Lsblk].get_disks()

        # Remove os disk and resource disk
        data_disks = [
            disk.device_name
            for disk in disks
            if not disk.is_os_disk and not self._is_resource_disk(disk)
        ]

        return data_disks


def get_azure_disk_type(disk_type: schema.DiskType) -> str:
    assert isinstance(disk_type, schema.DiskType), (
        "the disk_type must be one value when calling get_disk_type. "
        f"But it's {disk_type}"
    )

    result = _disk_type_mapping.get(disk_type, None)
    assert result, f"unknown disk type: {disk_type}"

    return result


_disk_type_mapping: Dict[schema.DiskType, str] = {
    schema.DiskType.Ephemeral: "Ephemeral",
    schema.DiskType.PremiumSSDLRS: "Premium_LRS",
    schema.DiskType.PremiumV2SSDLRS: "PremiumV2_LRS",
    schema.DiskType.StandardHDDLRS: "Standard_LRS",
    schema.DiskType.StandardSSDLRS: "StandardSSD_LRS",
    schema.DiskType.UltraSSDLRS: "UltraSSD_LRS",
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
        filter_capabilities = []
        # Filter out the vm sizes that are not available for IaaS deployment
        for capability in capabilities:
            if any(
                cap
                for cap in capability.resource_sku["capabilities"]
                if cap["name"] == "VMDeploymentTypes" and "IaaS" in cap["value"]
            ):
                filter_capabilities.append(capability)
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
            if vm_size_name.startswith(("Standard_", "Basic_")):
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
        resource_sku: Any = kwargs.get("resource_sku")

        if (
            resource_sku.family.casefold()
            in [
                "standarddsv5family",
                "standardddsv5family",
                "standarddasv5family",
                "standarddadsv5family",
                "standardebdsv5family",
                "standardesv5family",
                "standardBsv2Family",
            ]
            or raw_capabilities.get("HibernationSupported", None) == "True"
        ):
            return HibernationSettings()

        return None

    @classmethod
    def _enable_hibernation(cls, *args: Any, **kwargs: Any) -> None:
        parameters = cast(AzureArmParameter, kwargs.get("arm_parameters"))
        if (
            parameters.availability_options.availability_type
            == AvailabilityType.AvailabilitySet
        ):
            raise SkippedException(
                "Hibernation cannot be enabled on Virtual Machines created in an"
                " Availability Set."
            )
        template: Any = kwargs.get("template")
        log = cast(Logger, kwargs.get("log"))
        log.debug("updating arm template to support vm hibernation.")
        resources = template["resources"]
        if isinstance(resources, dict):
            resources = list(resources.values())
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

    def _call_requirement_method(
        self, method: RequirementMethod, capability: Any
    ) -> Any:
        super_value: SecurityProfileSettings = super()._call_requirement_method(
            method, capability
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
    # Convert Security Profile Setting to Arm Parameter Value
    _security_profile_mapping = {
        SecurityProfileType.Standard: "",
        SecurityProfileType.SecureBoot: "TrustedLaunch",
        SecurityProfileType.CVM: "ConfidentialVM",
        SecurityProfileType.Stateless: "ConfidentialVM",
    }

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
        if resource_sku.family.casefold() not in [
            "standardmsfamily",
            "standardmdsmediummemoryv2family",
            "standardmsmediummemoryv2family",
            "standardmsv2family",
        ]:
            # https://learn.microsoft.com/en-us/azure/virtual-machines/trusted-launch#how-can-i-find-vm-sizes-that-support-trusted-launch # noqa: E501
            if (
                gen_value
                and ("V2" in str(gen_value))
                and raw_capabilities.get("TrustedLaunchDisabled", "False") == "False"
            ):
                capabilities.append(SecurityProfileType.SecureBoot)
        # https://learn.microsoft.com/en-us/azure/confidential-computing/confidential-vm-overview # noqa: E501
        if cvm_value and resource_sku.family.casefold() in [
            "standarddcasv5family",
            "standarddcadsv5family",
            "standardecasv5family",
            "standardecadsv5family",
            "standarddcev5family",
            "standarddcedv5family",
            "standardecev5family",
            "standardecedv5family",
        ]:
            capabilities.append(SecurityProfileType.CVM)

        if cvm_value == "TDX" and resource_sku.family.casefold() in [
            "standarddcev5family",
            "standarddcedv5family",
            "standardecev5family",
            "standardecedv5family",
        ]:
            capabilities.append(SecurityProfileType.Stateless)

        return SecurityProfileSettings(
            security_profile=search_space.SetSpace(True, capabilities)
        )

    @classmethod
    def create_image_requirement(
        cls, image: schema.ImageSchema
    ) -> Optional[schema.FeatureSettings]:
        assert isinstance(image, AzureImageSchema), f"actual: {type(image)}"
        return SecurityProfileSettings(security_profile=image.security_profile)

    @classmethod
    def on_before_deployment(cls, *args: Any, **kwargs: Any) -> None:
        environment = cast(Environment, kwargs.get("environment"))
        arm_parameters = cast(AzureArmParameter, kwargs.get("arm_parameters"))

        assert len(environment.nodes._list) == len(arm_parameters.nodes)
        for node, node_parameters in zip(environment.nodes._list, arm_parameters.nodes):
            assert node.capability.features
            security_profile = [
                feature_setting
                for feature_setting in node.capability.features.items
                if feature_setting.type == FEATURE_NAME_SECURITY_PROFILE
            ]
            if security_profile:
                settings = security_profile[0]
                assert isinstance(settings, SecurityProfileSettings)
                assert isinstance(settings.security_profile, SecurityProfileType)
                node_parameters.security_profile[
                    "security_type"
                ] = cls._security_profile_mapping[settings.security_profile]
                if settings.security_profile == SecurityProfileType.Stateless:
                    node_parameters.security_profile["secure_boot"] = False
                    node_parameters.security_profile[
                        "encryption_type"
                    ] = "NonPersistedTPM"
                else:
                    node_parameters.security_profile["secure_boot"] = True
                    node_parameters.security_profile["encryption_type"] = (
                        "DiskWithVMGuestState"
                        if settings.encrypt_disk
                        else "VMGuestStateOnly"
                    )
                node_parameters.security_profile[
                    "disk_encryption_set_id"
                ] = settings.disk_encryption_set_id

                if node_parameters.security_profile["security_type"] == "":
                    node_parameters.security_profile.clear()
                elif 1 == node_parameters.hyperv_generation:
                    raise SkippedException(
                        f"{settings.security_profile} "
                        "can only be set on gen2 image/vhd."
                    )


availability_type_priority: List[AvailabilityType] = [
    AvailabilityType.NoRedundancy,
    AvailabilityType.AvailabilitySet,
    AvailabilityType.AvailabilityZone,
]


class AvailabilitySettings(features.AvailabilitySettings):
    def _resolve_availability_type_by_priority(
        self, arm_parameters: Optional[AvailabilityArmParameter] = None
    ) -> AvailabilityType:
        if isinstance(self.availability_type, AvailabilityType):
            return self.availability_type
        if arm_parameters:
            if (
                arm_parameters.availability_set_properties
                or arm_parameters.availability_set_tags
            ) and AvailabilityType.AvailabilitySet in self.availability_type:
                return AvailabilityType.AvailabilitySet
            elif (
                arm_parameters.availability_zones
                and AvailabilityType.AvailabilityZone in self.availability_type
            ):
                return AvailabilityType.AvailabilityZone
        for option in availability_type_priority:
            if option in self.availability_type:
                return option
        raise LisaException(
            "Could not resolve availability option."
            f"Availability Options: {self.availability_type}"
        )


class Availability(AzureFeatureMixin, features.Availability):
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)

    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return AvailabilitySettings

    @classmethod
    def create_setting(
        cls, *args: Any, **kwargs: Any
    ) -> Optional[schema.FeatureSettings]:
        raw_capabilities: Any = kwargs.get("raw_capabilities")
        availability_settings: AvailabilitySettings = AvailabilitySettings()
        availability_settings.availability_type = search_space.SetSpace(
            True,
            [
                AvailabilityType.NoRedundancy,
                AvailabilityType.AvailabilitySet,
            ],
        )

        availability_zones = raw_capabilities.get("availability_zones", None)
        if availability_zones:
            availability_settings.availability_type.add(
                AvailabilityType.AvailabilityZone
            )
            availability_settings.availability_zones = search_space.SetSpace(
                is_allow_set=True, items=availability_zones
            )

        return availability_settings

    @classmethod
    def on_before_deployment(cls, *args: Any, **kwargs: Any) -> None:
        environment = cast(Environment, kwargs.get("environment"))
        arm_parameters = cast(AzureArmParameter, kwargs.get("arm_parameters"))
        settings = cast(AvailabilitySettings, kwargs.get("settings"))
        params = arm_parameters.availability_options

        try:
            assert environment.runbook.nodes_requirement
            assert environment.runbook.nodes_requirement[0].extended_schemas
            is_maximize_capability = environment.runbook.nodes_requirement[
                0
            ].extended_schemas["azure"]["maximize_capability"]
        except (KeyError, IndexError, AssertionError):
            is_maximize_capability = False

        if not is_maximize_capability:
            assert isinstance(settings.availability_type, search_space.SetSpace)

            # Ultra Disk does not support Availability Sets
            assert environment.capability.nodes
            assert environment.capability.nodes[0].disk
            is_ultra_disk = (
                environment.capability.nodes[0].disk.data_disk_type
                == schema.DiskType.UltraSSDLRS
            )
            if is_ultra_disk:
                settings.availability_type.discard(AvailabilityType.AvailabilitySet)
                # If a region supports Ultra Disk in availability zones,
                # then availability zones must be used
                if AvailabilityType.AvailabilityZone in settings.availability_type:
                    settings.availability_type.discard(AvailabilityType.NoRedundancy)

            # Set ARM parameters based on min capability
            if params.availability_type == AvailabilityType.Default:
                params.availability_type = (
                    settings._resolve_availability_type_by_priority(params).value
                )
            if (
                params.availability_zones
                and params.availability_type == AvailabilityType.AvailabilityZone
            ):
                params.availability_zones = [
                    zone
                    for zone in params.availability_zones
                    if zone in settings.availability_zones
                ]
                assert params.availability_zones, (
                    "Invalid zones provided. "
                    "This SKU in this location supports zones: "
                    f"{settings.availability_zones}. "
                )
            elif settings.availability_zones:
                params.availability_zones = [settings.availability_zones.items[0]]

            assert params.availability_type in [
                type.value for type in AvailabilityType
            ], ("Not a valid Availability Type: " f"{params.availability_type}")

            assert (
                AvailabilityType(params.availability_type) in settings.availability_type
            ), (
                f"Availability Type "
                f"'{params.availability_type}' "
                "is not supported in the current configuration. Please select one of "
                f"{[type.value for type in settings.availability_type.items]}. "
                "Or consider changing the disk type or location."
            )

        # If the availability_type is still set to Default, then
        # resolve the default without considering capabilities
        if params.availability_type == AvailabilityType.Default:
            params.availability_type = (
                AvailabilityType.AvailabilitySet.value
                if params.availability_set_tags or params.availability_set_properties
                else AvailabilityType.NoRedundancy.value
            )

        # Once the availability type has been determined, clear the unecessary
        # fields for clarity
        if params.availability_type == AvailabilityType.AvailabilitySet:
            params.availability_zones.clear()
            if "platformFaultDomainCount" not in params.availability_set_properties:
                params.availability_set_properties["platformFaultDomainCount"] = 1
            if "platformUpdateDomainCount" not in params.availability_set_properties:
                params.availability_set_properties["platformUpdateDomainCount"] = 1
        elif params.availability_type == AvailabilityType.AvailabilityZone:
            assert (
                params.availability_zones
            ), "Availability Zone is selected, but no zone was provided."
            params.availability_zones = [params.availability_zones[0]]
            params.availability_set_tags.clear()
            params.availability_set_properties.clear()
        else:
            params.availability_set_tags.clear()
            params.availability_set_properties.clear()
            params.availability_zones.clear()


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

        if resource_sku.family.casefold() in [
            "standarddcsv2family",
            "standarddcsv3family",
        ]:
            return schema.FeatureSettings.create(cls.name())
        return None


class CVMNestedVirtualization(AzureFeatureMixin, features.CVMNestedVirtualization):
    @classmethod
    def create_setting(
        cls, *args: Any, **kwargs: Any
    ) -> Optional[schema.FeatureSettings]:
        resource_sku: Any = kwargs.get("resource_sku")

        # add vm which support nested confidential virtualization
        # https://learn.microsoft.com/en-us/azure/virtual-machines/dcasccv5-dcadsccv5-series
        # https://learn.microsoft.com/en-us/azure/virtual-machines/ecasccv5-ecadsccv5-series
        if resource_sku.family.casefold() in [
            "standarddcaccv5family",
            "standardecaccv5family",
            "standarddcadccv5family",
            "standardecadccv5family",
        ]:
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
        if resource_sku.family.casefold() in [
            "standardddsv5family",
            "standardddv4family",
            "standardddv5family",
            "standarddsv3family",
            "standarddsv4family",
            "standarddsv5family",
            "standarddv3family",
            "standarddv4family",
            "standarddv5family",
            "standarddadsv5family",
            "standarddasv5family",
            "standardddsv4family",
            "standardeiv5family",
            "standardeadsv5family",
            "standardeasv5family",
            "standardedsv4family",
            "standardedsv5family",
            "standardesv3family",
            "standardesv4family",
            "standardesv5family",
            "standardebdsv5family",
            "standardebsv5family",
            "standardedv4family",
            "standardev4family",
            "standardedv5family",
            "standardev3family",
            "standardev5family",
            "standardxeidsv4family",
            "standardxeisv4family",
            "standardfsv2family",
            "standardfxmdvsfamily",
            "standardlasv3family",
            "standardlsv3family",
            "standardmsfamily",
            "standardmsmediummemoryv2family",
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
        if resource_sku.family.casefold() in [
            "standardlsv2family",
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
            cloud=platform.cloud,
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
            cloud=platform.cloud,
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
            platform.cloud,
            self.storage_account_name,
            self.file_share_name,
            resource_group_name,
            self._log,
        )
        delete_storage_account(
            platform.credential,
            platform.subscription_id,
            platform.cloud,
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

    def get(
        self,
        name: str = "",
    ) -> Any:
        platform: AzurePlatform = self._platform  # type: ignore
        compute_client = get_compute_client(platform)
        extension = compute_client.virtual_machine_extensions.get(
            resource_group_name=self._resource_group_name,
            vm_name=self._vm_name,
            vm_extension_name=name,
            expand="instanceView",
        )
        return extension

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

        if protected_settings:
            add_secret(
                str(extension_parameters.protected_settings),
                sub="***REDACTED***",
            )

        self._log.debug(f"extension_parameters: {extension_parameters.as_dict()}")

        operations = compute_client.virtual_machine_extensions.begin_create_or_update(
            resource_group_name=self._resource_group_name,
            vm_name=self._vm_name,
            vm_extension_name=name,
            extension_parameters=extension_parameters,
        )

        interval = 10
        timer = create_timer()
        while timeout >= timer.elapsed(False):
            extension = self.get(name=name)
            provisioning_state = str(extension.provisioning_state)

            if provisioning_state.lower() in ["failed", "succeeded"]:
                self._log.debug(
                    f"Extension '{name}' provision status is '{provisioning_state}'."
                    " Exiting loop."
                )
                break

            self._log.debug(
                f"Extension '{name}' is still '{provisioning_state}'."
                f" Waiting {interval} seconds..."
            )
            time.sleep(interval)
        if timeout < timer.elapsed():
            raise LisaTimeoutException(
                f"Azure operation failed: timeout after {timeout} seconds."
            )

        result = operations.result()
        result_dict = result.as_dict() if result else None
        if result_dict:
            result_dict["provisioning_state"] = provisioning_state

        return result_dict

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
        if hasattr(self._node, "os"):
            self._node.tools[Waagent].enable_configuration("Extensions.Enabled")


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

    def _call_requirement_method(
        self, method: RequirementMethod, capability: Any
    ) -> Any:
        assert isinstance(
            capability, VhdGenerationSettings
        ), f"actual: {type(capability)}"

        value = VhdGenerationSettings()
        if self.gen or capability.gen:
            value.gen = getattr(search_space, f"{method.value}_setspace_by_priority")(
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
    def create_image_requirement(
        cls, image: schema.ImageSchema
    ) -> Optional[schema.FeatureSettings]:
        assert isinstance(image, AzureImageSchema), f"actual: {type(image)}"
        return VhdGenerationSettings(gen=image.hyperv_generation)

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
    arch: Union[
        schema.ArchitectureType, search_space.SetSpace[schema.ArchitectureType]
    ] = field(  # type: ignore
        default_factory=partial(
            search_space.SetSpace,
            items=[schema.ArchitectureType.x64, schema.ArchitectureType.Arm64],
        ),
        metadata=field_metadata(
            decoder=partial(
                search_space.decode_nullable_set_space,
                base_type=schema.ArchitectureType,
                default_values=[
                    schema.ArchitectureType.x64,
                    schema.ArchitectureType.Arm64,
                ],
            )
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
        result.merge(
            search_space.check_setspace(self.arch, capability.arch),
            "architecture type",
        )

        return result

    def _call_requirement_method(
        self, method: RequirementMethod, capability: Any
    ) -> Any:
        assert isinstance(
            capability, ArchitectureSettings
        ), f"actual: {type(capability)}"

        value = ArchitectureSettings()
        value.arch = getattr(search_space, f"{method.value}_setspace_by_priority")(
            self.arch,
            capability.arch,
            [schema.ArchitectureType.x64, schema.ArchitectureType.Arm64],
        )
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
    def create_image_requirement(
        cls, image: schema.ImageSchema
    ) -> Optional[schema.FeatureSettings]:
        assert isinstance(image, AzureImageSchema), f"actual: {type(image)}"
        return ArchitectureSettings(arch=image.architecture)

    @classmethod
    def settings_type(cls) -> Type[schema.FeatureSettings]:
        return ArchitectureSettings

    @classmethod
    def can_disable(cls) -> bool:
        return True

    def enabled(self) -> bool:
        return True


class IaaS(AzureFeatureMixin, Feature):
    @classmethod
    def create_setting(
        cls, *args: Any, **kwargs: Any
    ) -> Optional[schema.FeatureSettings]:
        raw_capabilities: Any = kwargs.get("raw_capabilities")
        deployment_types = raw_capabilities.get("VMDeploymentTypes", None)
        if deployment_types and "IaaS" in deployment_types:
            return schema.FeatureSettings.create(cls.name())

        return None


class PasswordExtension(AzureFeatureMixin, features.PasswordExtension):
    @classmethod
    def create_setting(
        cls, *args: Any, **kwargs: Any
    ) -> Optional[schema.FeatureSettings]:
        return schema.FeatureSettings.create(cls.name())

    def reset_password(self, username: str, password: str) -> None:
        # This uses the VMAccessForLinux extension to reset the credentials for an
        # existing user or create a new user with sudo privileges.
        # https://learn.microsoft.com/en-us/azure/virtual-machines/extensions/vmaccess
        reset_user_password = {"username": username, "password": password}
        extension = self._node.features[AzureExtension]
        result = extension.create_or_update(
            name="VMAccessForLinux",
            publisher="Microsoft.OSTCExtensions",
            type_="VMAccessForLinux",
            type_handler_version="1.5",
            auto_upgrade_minor_version=True,
            protected_settings=reset_user_password,
        )
        assert_that(result["provisioning_state"]).described_as(
            "Expected the extension to succeed"
        ).is_equal_to("Succeeded")


class AzureFileShare(AzureFeatureMixin, Feature):
    @classmethod
    def create_setting(
        cls, *args: Any, **kwargs: Any
    ) -> Optional[schema.FeatureSettings]:
        return schema.FeatureSettings.create(cls.name())

    def get_smb_version(self) -> str:
        if self._node.tools[KernelConfig].is_enabled("CONFIG_CIFS_SMB311"):
            version = "3.1.1"
        else:
            version = "3.0"
        return version

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._initialize_information(self._node)
        self._initialize_fileshare_information()

    def _initialize_fileshare_information(self) -> None:
        random_str = generate_random_chars(string.ascii_lowercase + string.digits, 10)
        self._storage_account_name = f"lisasc{random_str}"
        self._fstab_info = (
            f"nofail,vers={self.get_smb_version()},"
            "credentials=/etc/smbcredentials/lisa.cred"
            ",dir_mode=0777,file_mode=0777,serverino"
        )

    def create_file_share(
        self,
        file_share_names: List[str],
        environment: Environment,
        allow_shared_key_access: bool = False,
        sku: str = "Standard_LRS",
        kind: str = "StorageV2",
        enable_https_traffic_only: bool = True,
        enable_private_endpoint: bool = False,
    ) -> Dict[str, str]:
        platform: AzurePlatform = self._platform  # type: ignore
        information = environment.get_information()
        resource_group_name = self._resource_group_name
        location = information["location"]
        storage_account_name = self._storage_account_name

        fs_url_dict: Dict[str, str] = {}

        check_or_create_storage_account(
            credential=platform.credential,
            subscription_id=platform.subscription_id,
            cloud=platform.cloud,
            account_name=storage_account_name,
            resource_group_name=resource_group_name,
            location=location,
            log=self._log,
            sku=sku,
            kind=kind,
            enable_https_traffic_only=enable_https_traffic_only,
            allow_shared_key_access=allow_shared_key_access,
        )
        # If enable_private_endpoint is true, SMB share endpoint
        # will dns resolve to <share>.privatelink.file.core.windows.net
        # No changes need to be done in code calling function
        for share_name in file_share_names:
            fs_url_dict[share_name] = get_or_create_file_share(
                credential=platform.credential,
                subscription_id=platform.subscription_id,
                cloud=platform.cloud,
                account_name=storage_account_name,
                file_share_name=share_name,
                resource_group_name=resource_group_name,
                log=self._log,
            )
        # Create file private endpoint, always after all shares have been created
        # There is a known issue in API preventing access to data plane
        # once private endpoint is created. Observed in Terraform provider as well
        if enable_private_endpoint:
            storage_account_resource_id = (
                f"/subscriptions/{platform.subscription_id}/resourceGroups/"
                f"{resource_group_name}/providers/Microsoft.Storage/storageAccounts"
                f"/{storage_account_name}"
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

            # Create Private endpoint
            ipv4_address = create_update_private_endpoints(
                platform,
                resource_group_name,
                location,
                subnet_id,
                storage_account_resource_id,
                ["file"],
                self._log,
            )
            # Create private zone
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

        return fs_url_dict

    def create_fileshare_folders(self, test_folders_share_dict: Dict[str, str]) -> None:
        """
        test_folders_share_dict is of the form
            {
            "foldername": "fileshareurl",
            "foldername2": "fileshareurl2",
            }
        """
        platform: AzurePlatform = self._platform  # type: ignore
        account_credential = get_storage_credential(
            credential=platform.credential,
            subscription_id=platform.subscription_id,
            cloud=platform.cloud,
            account_name=self._storage_account_name,
            resource_group_name=self._resource_group_name,
        )
        self._prepare_azure_file_share(
            self._node,
            account_credential,
            test_folders_share_dict,
            self._fstab_info,
        )

    def delete_azure_fileshare(self, file_share_names: List[str]) -> None:
        resource_group_name = self._resource_group_name
        storage_account_name = self._storage_account_name
        platform: AzurePlatform = self._platform  # type: ignore
        for share_name in file_share_names:
            delete_file_share(
                credential=platform.credential,
                subscription_id=platform.subscription_id,
                cloud=platform.cloud,
                account_name=storage_account_name,
                file_share_name=share_name,
                resource_group_name=resource_group_name,
                log=self._log,
            )
        delete_storage_account(
            credential=platform.credential,
            subscription_id=platform.subscription_id,
            cloud=platform.cloud,
            account_name=storage_account_name,
            resource_group_name=resource_group_name,
            log=self._log,
        )
        # revert file into original status after testing.
        self._node.execute("cp -f /etc/fstab_cifs /etc/fstab", sudo=True)

    def _prepare_azure_file_share(
        self,
        node: Node,
        account_credential: Dict[str, str],
        test_folders_share_dict: Dict[str, str],
        fstab_info: str,
    ) -> None:
        folder_path = node.get_pure_path("/etc/smbcredentials")
        if node.shell.exists(folder_path):
            node.execute(f"rm -rf {folder_path}", sudo=True)
        node.shell.mkdir(folder_path)
        file_path = node.get_pure_path("/etc/smbcredentials/lisa.cred")
        echo = node.tools[Echo]
        username = account_credential["account_name"]
        password = account_credential["account_key"]
        add_secret(password)
        echo.write_to_file(f"username={username}", file_path, sudo=True, append=True)
        echo.write_to_file(f"password={password}", file_path, sudo=True, append=True)
        node.execute("cp -f /etc/fstab /etc/fstab_cifs", sudo=True)
        for folder_name, share in test_folders_share_dict.items():
            node.execute(f"mkdir {folder_name}", sudo=True)
            echo.write_to_file(
                f"{share} {folder_name} cifs {fstab_info}",
                node.get_pure_path("/etc/fstab"),
                sudo=True,
                append=True,
            )
