# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import faulthandler
import fnmatch
import io
import json
import os
import random
import string
import sys
import tempfile
import time
import xml.etree.ElementTree as ET  # noqa: N817
from pathlib import Path, PurePosixPath
from threading import Lock, Timer
from typing import Any, Dict, List, Optional, Tuple, Type, cast

import libvirt
import pycdlib
import yaml

from lisa import feature, schema, search_space
from lisa.environment import Environment
from lisa.feature import Feature
from lisa.node import Node, RemoteNode, local_node_connect
from lisa.operating_system import CBLMariner
from lisa.platform_ import Platform
from lisa.sut_orchestrator.libvirt.libvirt_device_pool import LibvirtDevicePool
from lisa.tools import (
    Cat,
    Chmod,
    Chown,
    Cp,
    Dmesg,
    Iptables,
    Journalctl,
    Ls,
    Mkdir,
    QemuImg,
    ResizePartition,
    Sed,
    Service,
    Uname,
    Whoami,
)
from lisa.util import (
    LisaException,
    NotMeetRequirementException,
    constants,
    get_public_key_data,
)
from lisa.util.logger import Logger, filter_ansi_escape, get_logger

from . import libvirt_events_thread
from .console_logger import QemuConsoleLogger
from .context import (
    DataDiskContext,
    InitSystem,
    NodeContext,
    get_environment_context,
    get_node_context,
)
from .features import SecurityProfile, SecurityProfileSettings
from .platform_interface import IBaseLibvirtPlatform
from .schema import (
    FIRMWARE_TYPE_BIOS,
    FIRMWARE_TYPE_UEFI,
    BaseLibvirtNodeSchema,
    BaseLibvirtPlatformSchema,
    DiskImageFormat,
)
from .serial_console import SerialConsole
from .start_stop import StartStop

# Host environment information fields
KEY_HOST_DISTRO = "host_distro"
KEY_HOST_KERNEL = "host_kernel_version"
KEY_LIBVIRT_VERSION = "libvirt_version"
KEY_VMM_VERSION = "vmm_version"


class _HostCapabilities:
    def __init__(self) -> None:
        self.core_count = 0
        self.free_memory_kib = 0


class BaseLibvirtPlatform(Platform, IBaseLibvirtPlatform):
    LIBVIRTD_CONF_PATH = PurePosixPath("/etc/libvirt/libvirtd.conf")
    LIBVIRT_DEBUG_LOG_PATH = PurePosixPath("/var/log/libvirt/libvirtd.log")
    # A marker that identifies lines added by lisa in a config file. This can be
    # appended as a comment and then used to identify the line to delete during
    # cleanup.
    CONFIG_FILE_MARKER = "lisa-libvirt-platform"

    _supported_features: List[Type[Feature]] = [
        SerialConsole,
        StartStop,
        SecurityProfile,
    ]

    def __init__(self, runbook: schema.Platform) -> None:
        super().__init__(runbook=runbook)
        self.libvirt_conn_str: str
        self.libvirt_conn: libvirt.virConnect
        self.platform_runbook: BaseLibvirtPlatformSchema
        self.host_node: Node
        self.vm_disks_dir: str

        # used for port forwarding in case of Remote Host
        self._next_available_port: int
        self._port_forwarding_lock: Lock

        # Lock used for scp-ing disk image to Remote host VM
        self._disk_img_copy_lock: Lock

        self._host_environment_information_hooks = {
            KEY_HOST_DISTRO: self._get_host_distro,
            KEY_HOST_KERNEL: self._get_host_kernel_version,
            KEY_LIBVIRT_VERSION: self._get_libvirt_version,
            KEY_VMM_VERSION: self._get_vmm_version,
        }

    @classmethod
    def type_name(cls) -> str:
        return ""

    @classmethod
    def supported_features(cls) -> List[Type[Feature]]:
        return BaseLibvirtPlatform._supported_features

    @classmethod
    def platform_runbook_type(cls) -> type:
        return BaseLibvirtPlatformSchema

    @classmethod
    def node_runbook_type(cls) -> type:
        return BaseLibvirtNodeSchema

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        libvirt_events_thread.init()

        # 49512 is the first available private port
        self._next_available_port = 49152
        self._port_forwarding_lock = Lock()

        self._disk_img_copy_lock = Lock()

        self.platform_runbook = self.runbook.get_extended_runbook(
            self.__platform_runbook_type(), type_name=type(self).type_name()
        )

        if len(self.platform_runbook.hosts) > 1:
            self._log.warning(
                "Multiple hosts are currently not supported. "
                "Only the first host will be used."
            )

        host = self.platform_runbook.hosts[0]
        if host.is_remote():
            assert host.address
            if not host.username:
                raise LisaException("Username must be provided for remote host")
            if not host.private_key_file:
                raise LisaException("Private key file must be provided for remote host")

            self.host_node = RemoteNode(
                runbook=schema.Node(name="libvirt-host"),
                index=-1,
                logger_name="libvirt-host",
                parent_logger=get_logger("libvirt-platform"),
            )

            self.host_node.set_connection_info(
                address=host.address,
                username=host.username,
                private_key_file=host.private_key_file,
            )
        else:
            self.host_node = local_node_connect(
                name="libvirt-host",
                parent_logger=get_logger("libvirt-platform"),
            )

        if self.platform_runbook.capture_libvirt_debug_logs:
            self._enable_libvirt_debug_log()

        self.__init_libvirt_conn_string()
        self.libvirt_conn = libvirt.open(self.libvirt_conn_str)

        self.device_pool = LibvirtDevicePool(self.host_node, self.platform_runbook)
        # If Device_passthrough is set in runbook,
        # Configure device passthrough params
        self.device_pool.configure_device_passthrough_pool(
            self.platform_runbook.device_pools,
        )

    def _prepare_environment(self, environment: Environment, log: Logger) -> bool:
        # Ensure environment log directory is created before connecting to any nodes.
        _ = environment.log_path

        self._configure_environment(environment, log)

        if environment.runbook.nodes_requirement:
            for node_space in environment.runbook.nodes_requirement:
                new_settings = search_space.SetSpace[schema.FeatureSettings](
                    is_allow_set=True
                )
                if node_space.features:
                    for current_settings in node_space.features.items:
                        # reload to type specified settings
                        try:
                            settings_type = feature.get_feature_settings_type_by_name(
                                current_settings.type,
                                BaseLibvirtPlatform.supported_features(),
                            )
                        except NotMeetRequirementException as e:
                            raise LisaException(
                                f"platform doesn't support all features. {e}"
                            )
                        new_setting = schema.load_by_type(
                            settings_type, current_settings
                        )
                        existing_setting = feature.get_feature_settings_by_name(
                            new_setting.type, new_settings, True
                        )
                        if existing_setting:
                            new_settings.remove(existing_setting)
                            new_setting = existing_setting.intersect(new_setting)

                        new_settings.add(new_setting)
                    node_space.features = new_settings

        return self._configure_node_capabilities(environment, log)

    def _deploy_environment(self, environment: Environment, log: Logger) -> None:
        self._deploy_nodes(environment, log)

    def _delete_environment(self, environment: Environment, log: Logger) -> None:
        self._delete_nodes(environment, log)

        if self.host_node.is_remote:
            self._stop_port_forwarding(environment, log)

    def _cleanup(self) -> None:
        if self.platform_runbook.capture_libvirt_debug_logs:
            self._disable_libvirt_debug_log()

        self._capture_libvirt_logs()

        if self.host_node.is_remote:
            dmesg_output = self.host_node.tools[Dmesg].get_output(force_run=True)
            dmesg_path = self.host_node.local_log_path / "dmesg.txt"
            with open(str(dmesg_path), "w") as f:
                f.write(dmesg_output)

    def _configure_environment(self, environment: Environment, log: Logger) -> None:
        environment_context = get_environment_context(environment)

        if self.platform_runbook.network_boot_timeout:
            environment_context.network_boot_timeout = (
                self.platform_runbook.network_boot_timeout
            )

        environment_context.ssh_public_key = get_public_key_data(
            self.runbook.admin_private_key_file
        )

    def _configure_node_capabilities(
        self, environment: Environment, log: Logger
    ) -> bool:
        if not environment.runbook.nodes_requirement:
            return True

        host_capabilities = self._get_host_capabilities(log)
        nodes_capabilities = self._create_node_capabilities(host_capabilities)

        nodes_requirement = []
        for node_space in environment.runbook.nodes_requirement:
            # Check that the general node capabilities are compatible with this node's
            # specific requirements.
            if not node_space.check(nodes_capabilities):
                return False

            # Rectify the general node capabilities with this node's specific
            # requirements.
            node_requirement = node_space.generate_min_capability(nodes_capabilities)
            nodes_requirement.append(node_requirement)

        if not self._check_host_capabilities(nodes_requirement, host_capabilities, log):
            return False

        environment.runbook.nodes_requirement = nodes_requirement
        return True

    def _get_host_capabilities(self, log: Logger) -> _HostCapabilities:
        host_capabilities = _HostCapabilities()

        capabilities_xml_str = self.libvirt_conn.getCapabilities()
        capabilities_xml = ET.fromstring(capabilities_xml_str)

        host_xml = capabilities_xml.find("host")
        assert host_xml

        topology_xml = host_xml.find("topology")
        assert topology_xml

        cells_xml = topology_xml.find("cells")
        assert cells_xml

        for cell in cells_xml.findall("cell"):
            cpus_xml = cell.find("cpus")
            assert cpus_xml

            host_capabilities.core_count += int(cpus_xml.attrib["num"])

        # Get free memory.
        # Include the disk cache size, as it will be freed if memory becomes limited.
        memory_stats = self.libvirt_conn.getMemoryStats(
            libvirt.VIR_NODE_MEMORY_STATS_ALL_CELLS
        )
        host_capabilities.free_memory_kib = (
            memory_stats[libvirt.VIR_NODE_MEMORY_STATS_FREE]
            + memory_stats[libvirt.VIR_NODE_MEMORY_STATS_CACHED]
        )

        log.debug(
            f"QEMU host: "
            f"CPU Cores = {host_capabilities.core_count}, "
            f"Free Memory = {host_capabilities.free_memory_kib} KiB"
        )

        return host_capabilities

    # Create the set of capabilities that are generally supported on QEMU nodes.
    def _create_node_capabilities(
        self, host_capabilities: _HostCapabilities
    ) -> schema.NodeSpace:
        node_capabilities = schema.NodeSpace()
        node_capabilities.name = "QEMU"
        node_capabilities.node_count = 1
        node_capabilities.core_count = search_space.IntRange(
            min=1, max=host_capabilities.core_count
        )
        node_capabilities.disk = schema.DiskOptionSettings(
            data_disk_count=search_space.IntRange(min=0),
            data_disk_size=search_space.IntRange(min=1),
        )
        node_capabilities.network_interface = schema.NetworkInterfaceOptionSettings()
        node_capabilities.network_interface.max_nic_count = 1
        node_capabilities.network_interface.nic_count = 1
        node_capabilities.gpu_count = 0
        security_profile_setting = SecurityProfileSettings()
        node_capabilities.features = search_space.SetSpace[schema.FeatureSettings](
            is_allow_set=True,
            items=[
                schema.FeatureSettings.create(SerialConsole.name()),
                security_profile_setting,
            ],
        )

        return node_capabilities

    # Check that the VM requirements can be fulfilled by the host.
    def _check_host_capabilities(
        self,
        nodes_requirements: List[schema.NodeSpace],
        host_capabilities: _HostCapabilities,
        log: Logger,
    ) -> bool:
        total_required_memory_mib = 0

        for node_requirements in nodes_requirements:
            # Calculate the total amount of memory required for all the VMs.
            assert isinstance(node_requirements.memory_mb, int)
            total_required_memory_mib += node_requirements.memory_mb

        # Ensure host has enough memory for all the VMs.
        total_required_memory_kib = total_required_memory_mib * 1024
        if total_required_memory_kib > host_capabilities.free_memory_kib:
            log.error(
                f"Nodes require a total of {total_required_memory_kib} KiB memory. "
                f"Host only has {host_capabilities.free_memory_kib} KiB free."
            )
            return False

        return True

    # Get the minimum value for a node requirement with an interger type.
    # Note: Unlike other orchestrators, we don't want to fill up the capacity of
    # the host in case the test is running on a dev box.
    def _get_count_space_min(self, count_space: search_space.CountSpace) -> int:
        return search_space.generate_min_capability_countspace(count_space, count_space)

    def _deploy_nodes(self, environment: Environment, log: Logger) -> None:
        self._configure_nodes(environment, log)

        try:
            self._create_nodes(environment, log)
            self._fill_nodes_metadata(environment, log)
            self._expand_nodes_os_partition(environment, log)

        except Exception as ex:
            assert environment.platform
            if (
                environment.platform.runbook.keep_environment
                == constants.ENVIRONMENT_KEEP_NO
            ):
                self._delete_nodes(environment, log)

            self._log.debug("Capturing libvirtd log from host...")
            journalctl = self.host_node.tools[Journalctl]
            journalctl.logs_for_unit(unit_name="libvirtd", sudo=True)
            cat = self.host_node.tools[Cat]
            cat.read(file="/var/log/libvirt/libvirtd.log", sudo=True)

            raise ex

    # Pre-determine all the nodes' properties, including the name of all the resouces
    # to be created. This makes it easier to cleanup everything after the test is
    # finished (or fails).
    def _configure_nodes(self, environment: Environment, log: Logger) -> None:
        # Generate a random name for the VMs.
        test_suffix = "".join(random.choice(string.ascii_uppercase) for _ in range(5))
        vm_name_prefix = f"lisa-{test_suffix}"

        self.vm_disks_dir = os.path.join(
            self.platform_runbook.hosts[0].lisa_working_dir, vm_name_prefix
        )

        assert environment.runbook.nodes_requirement
        for i, node_space in enumerate(environment.runbook.nodes_requirement):
            assert isinstance(
                node_space, schema.NodeSpace
            ), f"actual: {type(node_space)}"

            node_runbook: BaseLibvirtNodeSchema = node_space.get_extended_runbook(
                self.__node_runbook_type(), type_name=type(self).type_name()
            )

            if not os.path.exists(node_runbook.disk_img):
                raise LisaException(f"file does not exist: {node_runbook.disk_img}")

            node = environment.create_node_from_requirement(node_space)

            self._configure_node(
                node,
                i,
                node_space,
                node_runbook,
                vm_name_prefix,
            )

    def _configure_node(
        self,
        node: Node,
        node_idx: int,
        node_space: schema.NodeSpace,
        node_runbook: BaseLibvirtNodeSchema,
        vm_name_prefix: str,
    ) -> None:
        node_context = get_node_context(node)

        if node_runbook.ignition:
            node_context.init_system = InitSystem.IGNITION

        if (
            not node_runbook.firmware_type
            or node_runbook.firmware_type == FIRMWARE_TYPE_UEFI
        ):
            node_context.use_bios_firmware = False

        elif node_runbook.firmware_type == FIRMWARE_TYPE_BIOS:
            node_context.use_bios_firmware = True

            if node_runbook.enable_secure_boot:
                raise LisaException("Secure-boot requires UEFI firmware.")

        else:
            raise LisaException(
                f"Unknown node firmware type: {node_runbook.firmware_type}."
                f"Expecting either {FIRMWARE_TYPE_UEFI} or {FIRMWARE_TYPE_BIOS}."
            )

        node_context.machine_type = node_runbook.machine_type or None
        node_context.enable_secure_boot = node_runbook.enable_secure_boot

        node_context.vm_name = f"{vm_name_prefix}-{node_idx}"
        if not node.name:
            node.name = node_context.vm_name

        if node_context.init_system == InitSystem.CLOUD_INIT:
            node_context.cloud_init_file_path = os.path.join(
                self.vm_disks_dir, f"{node_context.vm_name}-cloud-init.iso"
            )
        else:
            node_context.ignition_file_path = os.path.join(
                self.vm_disks_dir, f"{node_context.vm_name}-ignition.json"
            )

        if self.host_node.is_remote:
            node_context.os_disk_source_file_path = node_runbook.disk_img
            host = self.platform_runbook.hosts[0]
            node_context.os_disk_base_file_path = os.path.join(
                host.lisa_working_dir, os.path.basename(node_runbook.disk_img)
            )
        else:
            node_context.os_disk_base_file_path = node_runbook.disk_img

        node_context.os_disk_base_file_fmt = DiskImageFormat(
            node_runbook.disk_img_format
        )

        if node_runbook.disk_img_resize_gib:
            node_context.os_disk_img_resize_gib = node_runbook.disk_img_resize_gib

        node_context.os_disk_file_path = os.path.join(
            self.vm_disks_dir, f"{node_context.vm_name}-os.qcow2"
        )

        node_context.console_log_file_path = str(
            node.local_log_path / "qemu-console.log"
        )

        # Read extra cloud-init data.
        extra_user_data = (
            node_runbook.cloud_init and node_runbook.cloud_init.extra_user_data
        )
        if extra_user_data:
            node_context.extra_cloud_init_user_data = []

            if isinstance(extra_user_data, str):
                extra_user_data = [extra_user_data]

            for relative_file_path in extra_user_data:
                if not relative_file_path:
                    continue

                file_path = constants.RUNBOOK_PATH.joinpath(relative_file_path)
                with open(file_path, "r") as file:
                    node_context.extra_cloud_init_user_data.append(yaml.safe_load(file))

        # Configure data disks.
        if node_space.disk:
            assert isinstance(
                node_space.disk.data_disk_count, int
            ), f"actual: {type(node_space.disk.data_disk_count)}"
            assert isinstance(
                node_space.disk.data_disk_size, int
            ), f"actual: {type(node_space.disk.data_disk_size)}"

            for i in range(node_space.disk.data_disk_count):
                data_disk = DataDiskContext()
                data_disk.file_path = os.path.join(
                    self.vm_disks_dir, f"{node_context.vm_name}-data-{i}.qcow2"
                )
                data_disk.size_gib = node_space.disk.data_disk_size

                node_context.data_disks.append(data_disk)

        self.device_pool._set_device_passthrough_node_context(
            node_context,
            node_runbook,
        )

    def restart_domain_and_attach_logger(self, node: Node) -> None:
        node_context = get_node_context(node)
        domain = node_context.domain
        assert domain

        if domain.isActive():
            # VM already running.
            return

        if node_context.console_logger is not None:
            node_context.console_logger.wait_for_close()
            node_context.console_logger = None

        self._create_domain_and_attach_logger(node_context)

    def _create_domain_and_attach_logger(
        self,
        node_context: NodeContext,
    ) -> None:
        # Start the VM in the paused state.
        # This gives the console logger a chance to connect before the VM starts
        # for real.
        assert node_context.domain
        node_context.domain.createWithFlags(libvirt.VIR_DOMAIN_START_PAUSED)

        # Attach the console logger
        node_context.console_logger = QemuConsoleLogger()
        node_context.console_logger.attach(
            node_context.domain, node_context.console_log_file_path
        )

        # Start the VM.
        node_context.domain.resume()

        # Once libvirt domain is created, check if driver attached to device
        # on the host is vfio-pci for PCI device passthrough to make sure if
        # pass-through for PCI device is happened properly or not
        self.device_pool._verify_device_passthrough_post_boot(
            node_context=node_context,
        )

    # Create all the VMs.
    def _create_nodes(
        self,
        environment: Environment,
        log: Logger,
    ) -> None:
        self.host_node.shell.mkdir(Path(self.vm_disks_dir), exist_ok=True)
        features_settings: Dict[str, schema.FeatureSettings] = {}

        # collect all the features to handle special deployment logic. If one
        # node has this, it needs to run.
        nodes_requirement = environment.runbook.nodes_requirement
        if nodes_requirement:
            for node_space in nodes_requirement:
                if not node_space.features:
                    continue
                for feature_setting in node_space.features:
                    if feature_setting.type not in features_settings:
                        features_settings[feature_setting.type] = feature_setting

        # change deployment for each feature.
        for feature_type, setting in [
            (t, s)
            for t in self.supported_features()
            for s in features_settings.values()
            if t.name() == s.type
        ]:
            feature_type.on_before_deployment(
                environment=environment,
                log=log,
                settings=setting,
            )

        for node in environment.nodes.list():
            node_context = get_node_context(node)
            self._create_node(
                node,
                node_context,
                environment,
                log,
            )

    def _create_node(
        self,
        node: Node,
        node_context: NodeContext,
        environment: Environment,
        log: Logger,
    ) -> None:
        # Create required directories and copy the required files to the host node.
        if node_context.os_disk_source_file_path:
            # use lock to avoid multiple environments scp disk img to same
            # os_disk_base_file_path.
            with self._disk_img_copy_lock:
                source_exists = self.host_node.tools[Ls].path_exists(
                    path=node_context.os_disk_base_file_path, sudo=True
                )
                if source_exists:
                    self.host_node.tools[Chmod].chmod(
                        node_context.os_disk_base_file_path, "a+r", sudo=True
                    )
                else:
                    self.host_node.shell.copy(
                        Path(node_context.os_disk_source_file_path),
                        Path(node_context.os_disk_base_file_path),
                    )

        if node_context.init_system == InitSystem.CLOUD_INIT:
            # Create cloud-init ISO file.
            self._create_node_cloud_init_iso(environment, log, node)
        else:
            # Prepate Ignition injection.
            self._create_node_ignition(environment, log, node)

        # Create OS disk from the provided image.
        self._create_node_os_disk(environment, log, node)

        # Create data disks
        self._create_node_data_disks(node)

        # Create libvirt domain (i.e. VM).
        xml = self._create_node_domain_xml(environment, log, node)
        log.debug(f"Domain xml for {node_context.vm_name} - {xml}")
        node_context.domain = self.libvirt_conn.defineXML(xml)

        log.debug(f"Creating libvirt domain - {node_context.vm_name}")
        self._create_domain_and_attach_logger(
            node_context,
        )

    # Delete all the VMs.
    def _delete_nodes(self, environment: Environment, log: Logger) -> None:
        # Delete nodes.
        for node in environment.nodes.list():
            self._delete_node(node, log)

        # Delete VM disks directory.
        try:
            self.host_node.shell.remove(Path(self.vm_disks_dir), True)
        except Exception as ex:
            log.warning(f"Failed to delete VM files directory: {ex}")

    def _delete_node_watchdog_callback(self) -> None:
        print("VM delete watchdog timer fired.\n", file=sys.__stderr__)
        faulthandler.dump_traceback(file=sys.__stderr__, all_threads=True)
        os._exit(1)

    def _delete_node(self, node: Node, log: Logger) -> None:
        node_context = get_node_context(node)

        watchdog = Timer(60.0, self._delete_node_watchdog_callback)
        watchdog.start()

        # Stop the VM.
        if node_context.domain:
            log.debug(f"Stop VM: {node_context.vm_name}")
            try:
                # In the libvirt API, "destroy" means "stop".
                node_context.domain.destroy()
            except libvirt.libvirtError as ex:
                log.warning(f"VM stop failed. {ex}")

        # Wait for console log to close.
        # Note: libvirt can deadlock if you try to undefine the VM while the stream
        # is trying to close.
        if node_context.console_logger:
            log.debug(f"Close VM console log: {node_context.vm_name}")
            node_context.console_logger.close()
            node_context.console_logger = None

        # Undefine the VM.
        if node_context.domain:
            log.debug(f"Delete VM: {node_context.vm_name}")
            try:
                node_context.domain.undefineFlags(self._get_domain_undefine_flags())
            except libvirt.libvirtError as ex:
                log.warning(f"VM delete failed. {ex}")

            node_context.domain = None

        watchdog.cancel()

        # Add passthrough device back in the
        # list of available device once domain is deleted
        self.device_pool.release_devices(node_context)

    def _get_domain_undefine_flags(self) -> int:
        return int(
            libvirt.VIR_DOMAIN_UNDEFINE_MANAGED_SAVE
            | libvirt.VIR_DOMAIN_UNDEFINE_SNAPSHOTS_METADATA
            | libvirt.VIR_DOMAIN_UNDEFINE_NVRAM
            | libvirt.VIR_DOMAIN_UNDEFINE_CHECKPOINTS_METADATA
        )

    def _stop_port_forwarding(self, environment: Environment, log: Logger) -> None:
        log.debug(f"Clearing port forwarding rules for environment {environment.name}")
        environment_context = get_environment_context(environment)
        for port, address in environment_context.port_forwarding_list:
            self.host_node.tools[Iptables].stop_forwarding(port, address, 22)

    # Retrieve the VMs' dynamic properties (e.g. IP address).
    def _fill_nodes_metadata(self, environment: Environment, log: Logger) -> None:
        environment_context = get_environment_context(environment)

        # Give all the VMs some time to boot and then acquire an IP address.
        timeout = time.time() + environment_context.network_boot_timeout
        address = ""
        if self.host_node.is_remote:
            remote_node = cast(RemoteNode, self.host_node)
            conn_info = remote_node.connection_info
            address = conn_info[constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS]

        for node in environment.nodes.list():
            assert isinstance(node, RemoteNode)

            # Get the VM's IP address.
            local_address = self._get_node_ip_address(environment, log, node, timeout)

            node_port = 22
            if self.host_node.is_remote:
                with self._port_forwarding_lock:
                    port_not_found = True
                    while port_not_found:
                        if self._next_available_port > 65535:
                            raise LisaException(
                                "No available ports on the host to forward"
                            )

                        # check if the port is already in use
                        output = self.host_node.execute(
                            f"nc -vz 127.0.0.1 {self._next_available_port}"
                        )
                        if output.exit_code == 1:  # port not in use
                            node_port = self._next_available_port
                            port_not_found = False
                        self._next_available_port += 1

                self.host_node.tools[Iptables].start_forwarding(
                    node_port, local_address, 22
                )

                environment_context.port_forwarding_list.append(
                    (node_port, local_address)
                )
            else:
                address = local_address

            # Set SSH connection info for the node.
            node.set_connection_info(
                address=local_address,
                public_address=address,
                public_port=node_port,
                username=self.runbook.admin_username,
                private_key_file=self.runbook.admin_private_key_file,
            )

            node_context = get_node_context(node)
            if node_context.init_system == InitSystem.CLOUD_INIT:
                # Ensure cloud-init completes its setup.
                node.execute(
                    "cloud-init status --wait",
                    sudo=True,
                    expected_exit_code=0,
                    expected_exit_code_failure_message="waiting on cloud-init",
                )

    # Setup Ignition for a VM.
    def _create_node_ignition(
        self, environment: Environment, log: Logger, node: Node
    ) -> None:
        environment_context = get_environment_context(environment)
        node_context = get_node_context(node)

        user_data = {
            "ignition": {
                "version": "3.3.0",
            },
            "passwd": {
                "users": [
                    {
                        "name": self.runbook.admin_username,
                        "sshAuthorizedKeys": [environment_context.ssh_public_key],
                    },
                ],
            },
        }

        tmp_dir = tempfile.TemporaryDirectory()
        try:
            ignition_path = os.path.join(tmp_dir.name, "ignition.json")
            with open(ignition_path, "w") as f:
                json.dump(user_data, f)

            self.host_node.shell.copy(
                Path(ignition_path), Path(node_context.ignition_file_path)
            )
        finally:
            tmp_dir.cleanup()

    # Create a cloud-init ISO for a VM.
    def _create_node_cloud_init_iso(
        self, environment: Environment, log: Logger, node: Node
    ) -> None:
        environment_context = get_environment_context(environment)
        node_context = get_node_context(node)

        user_data = {
            "users": [
                "default",
                {
                    "name": self.runbook.admin_username,
                    "shell": "/bin/bash",
                    "sudo": ["ALL=(ALL) NOPASSWD:ALL"],
                    "groups": ["sudo", "docker"],
                    "ssh_authorized_keys": [environment_context.ssh_public_key],
                },
            ],
        }

        # Iterate through all the top-level properties.
        for extra_user_data in node_context.extra_cloud_init_user_data:
            for key, value in extra_user_data.items():
                existing_value = user_data.get(key)
                if not existing_value:
                    # Property doesn't exist yet. So, add it.
                    user_data[key] = value

                elif isinstance(existing_value, dict) and isinstance(value, dict):
                    # Merge two dictionaries by adding properties from new value and
                    # replacing any existing properties.
                    # Examples: disk_setup, etc.
                    existing_value.update(value)

                elif isinstance(existing_value, list) and isinstance(value, list):
                    # Merge two lists by appending to the end of the existing list.
                    # Examples: write_files, runcmd, etc.
                    existing_value.extend(value)

                else:
                    # String, unknown type or mismatched type.
                    # Just replace the existing property.
                    user_data[key] = value

        meta_data = {
            "local-hostname": node_context.vm_name,
        }

        # Note: cloud-init requires the user-data file to be prefixed with
        # `#cloud-config`.
        user_data_string = "#cloud-config\n" + yaml.safe_dump(user_data)
        meta_data_string = yaml.safe_dump(meta_data)

        iso_path = node_context.cloud_init_file_path
        tmp_dir = tempfile.TemporaryDirectory()
        try:
            iso_path = os.path.join(tmp_dir.name, "cloud-init.iso")

            self._create_iso(
                iso_path,
                [("/user-data", user_data_string), ("/meta-data", meta_data_string)],
            )

            self.host_node.shell.copy(
                Path(iso_path), Path(node_context.cloud_init_file_path)
            )
        finally:
            tmp_dir.cleanup()

    # Create an ISO file.
    def _create_iso(self, file_path: str, files: List[Tuple[str, str]]) -> None:
        iso = pycdlib.PyCdlib()
        iso.new(joliet=3, vol_ident="cidata")

        for i, file in enumerate(files):
            path, contents = file
            contents_data = contents.encode()
            iso.add_fp(
                io.BytesIO(contents_data),
                len(contents_data),
                f"/{i}.;1",
                joliet_path=path,
            )

        iso.write(file_path)

    # Create the OS disk.
    def _create_node_os_disk(
        self, environment: Environment, log: Logger, node: Node
    ) -> None:
        raise NotImplementedError()

    def _create_node_data_disks(self, node: Node) -> None:
        node_context = get_node_context(node)
        qemu_img = self.host_node.tools[QemuImg]

        for disk in node_context.data_disks:
            qemu_img.create_new_qcow2(disk.file_path, disk.size_gib * 1024)

    # Create the XML definition for the VM.
    def _create_node_domain_xml(
        self,
        environment: Environment,
        log: Logger,
        node: Node,
    ) -> str:
        node_context = get_node_context(node)

        domain = ET.Element("domain")
        domain.attrib["type"] = "kvm"

        name = ET.SubElement(domain, "name")
        name.text = node_context.vm_name

        memory = ET.SubElement(domain, "memory")
        memory.attrib["unit"] = "MiB"
        assert isinstance(node.capability.memory_mb, int)
        memory.text = str(node.capability.memory_mb)

        vcpu = ET.SubElement(domain, "vcpu")
        assert isinstance(node.capability.core_count, int)
        vcpu.text = str(node.capability.core_count)

        os_tag = ET.SubElement(domain, "os")

        os_type = ET.SubElement(os_tag, "type")
        os_type.text = "hvm"

        if node_context.machine_type:
            os_type.attrib["machine"] = node_context.machine_type

        if not node_context.use_bios_firmware:
            # In an ideal world, we would use libvirt's firmware auto-selection feature.
            # Unfortunatley, it isn't possible to specify the secure-boot state until
            # libvirt v7.2.0 and Ubuntu 20.04 only has libvirt v6.0.0. Therefore, we
            # have to select the firmware manually.
            firmware_config = self._get_firmware_config(
                node_context.machine_type, node_context.enable_secure_boot
            )

            print(firmware_config)

            loader = ET.SubElement(os_tag, "loader")
            loader.attrib["readonly"] = "yes"
            loader.attrib["type"] = "pflash"
            loader.attrib["secure"] = "yes" if node_context.enable_secure_boot else "no"
            loader.text = firmware_config["mapping"]["executable"]["filename"]

            nvram = ET.SubElement(os_tag, "nvram")
            nvram.attrib["template"] = firmware_config["mapping"]["nvram-template"][
                "filename"
            ]

        features = ET.SubElement(domain, "features")

        ET.SubElement(features, "acpi")

        ET.SubElement(features, "apic")

        cpu = ET.SubElement(domain, "cpu")
        cpu.attrib["mode"] = "host-passthrough"

        clock = ET.SubElement(domain, "clock")
        clock.attrib["offset"] = "utc"

        on_poweroff = ET.SubElement(domain, "on_poweroff")
        on_poweroff.text = "destroy"

        on_reboot = ET.SubElement(domain, "on_reboot")
        on_reboot.text = "restart"

        on_crash = ET.SubElement(domain, "on_crash")
        on_crash.text = "destroy"

        devices = ET.SubElement(domain, "devices")
        if len(node_context.passthrough_devices) > 0:
            devices = self.device_pool._add_device_passthrough_xml(
                devices,
                node_context,
            )

        serial = ET.SubElement(devices, "serial")
        serial.attrib["type"] = "pty"

        serial_target = ET.SubElement(serial, "target")
        serial_target.attrib["type"] = "isa-serial"
        serial_target.attrib["port"] = "0"

        serial_target_model = ET.SubElement(serial_target, "model")
        serial_target_model.attrib["name"] = "isa-serial"

        console = ET.SubElement(devices, "console")
        console.attrib["type"] = "pty"

        console_target = ET.SubElement(console, "target")
        console_target.attrib["type"] = "serial"
        console_target.attrib["port"] = "0"

        video = ET.SubElement(devices, "video")

        video_model = ET.SubElement(video, "model")
        if isinstance(self.host_node.os, CBLMariner):
            video_model.attrib["type"] = "vga"
        else:
            video_model.attrib["type"] = "qxl"
            graphics = ET.SubElement(devices, "graphics")
            graphics.attrib["type"] = "spice"

        network_interface = ET.SubElement(devices, "interface")
        network_interface.attrib["type"] = "network"

        network_interface_source = ET.SubElement(network_interface, "source")
        network_interface_source.attrib["network"] = "default"

        network_interface_model = ET.SubElement(network_interface, "model")
        network_interface_model.attrib["type"] = "virtio"

        if node_context.init_system == InitSystem.CLOUD_INIT:
            self._add_disk_xml(
                node_context,
                devices,
                node_context.cloud_init_file_path,
                "cdrom",
                "raw",
                "sata",
            )
        else:
            sysinfo_tag = ET.SubElement(domain, "sysinfo")
            sysinfo_tag.attrib["type"] = "fwcfg"

            entry_tag = ET.SubElement(sysinfo_tag, "entry")
            entry_tag.attrib["name"] = "opt/org.flatcar-linux/config"
            entry_tag.attrib["file"] = node_context.ignition_file_path

        self._add_disk_xml(
            node_context,
            devices,
            node_context.os_disk_file_path,
            "disk",
            "qcow2",
            "virtio",
        )

        for data_disk in node_context.data_disks:
            self._add_disk_xml(
                node_context,
                devices,
                data_disk.file_path,
                "disk",
                "qcow2",
                "virtio",
            )

        xml = ET.tostring(domain, "unicode")
        return xml

    def _add_disk_xml(
        self,
        node_context: NodeContext,
        devices: ET.Element,
        file_path: str,
        device_type: str,
        image_type: str,
        bus_type: str,
    ) -> None:
        device_name = self._new_disk_device_name(node_context)

        disk = ET.SubElement(devices, "disk")
        disk.attrib["type"] = "file"
        disk.attrib["device"] = device_type

        disk_driver = ET.SubElement(disk, "driver")
        disk_driver.attrib["name"] = "qemu"
        disk_driver.attrib["type"] = image_type

        disk_target = ET.SubElement(disk, "target")
        disk_target.attrib["dev"] = device_name
        disk_target.attrib["bus"] = bus_type

        disk_source = ET.SubElement(disk, "source")
        disk_source.attrib["file"] = file_path

    def _add_virtio_disk_xml(
        self,
        node_context: NodeContext,
        devices: ET.Element,
        file_path: str,
        queues: int,
    ) -> None:
        device_name = self._new_disk_device_name(node_context, True)

        disk = ET.SubElement(devices, "disk")
        disk.attrib["type"] = "file"

        disk_driver = ET.SubElement(disk, "driver")
        disk_driver.attrib["if"] = "virtio"
        disk_driver.attrib["type"] = "raw"
        disk_driver.attrib["queues"] = str(queues)

        disk_target = ET.SubElement(disk, "target")
        disk_target.attrib["dev"] = device_name

        disk_source = ET.SubElement(disk, "source")
        disk_source.attrib["file"] = file_path

    def _new_disk_device_name(
        self,
        node_context: NodeContext,
        is_paravirtualized: bool = False,
    ) -> str:
        disk_index = node_context.next_disk_index
        node_context.next_disk_index += 1

        device_name = self._get_disk_device_name(disk_index, is_paravirtualized)
        return device_name

    def _get_disk_device_name(
        self, disk_index: int, is_paravirtualized: bool = False
    ) -> str:
        # The disk device name is required to follow the standard Linux device naming
        # scheme. That is: [ sda, sdb, ..., sdz, sdaa, sdab, ... ]. However, it is
        # unlikely that someone will ever need more than 26 disks. So, keep is simple
        # for now.
        if disk_index < 0 or disk_index > 25:
            raise LisaException(f"Unsupported disk index: {disk_index}.")

        prefix = "v" if is_paravirtualized else "s"
        suffix = chr(ord("a") + disk_index)
        return f"{prefix}d{suffix}"

    # Wait for the VM to boot and then get the IP address.
    def _get_node_ip_address(
        self,
        environment: Environment,
        log: Logger,
        node: Node,
        timeout: float,
    ) -> str:
        node_context = get_node_context(node)

        while True:
            addr = self._try_get_node_ip_address(environment, log, node)
            if addr:
                log.debug(f"VM {node_context.vm_name} booted with IP - {addr}")
                return addr

            if time.time() > timeout:
                raise LisaException(
                    f"no IP addresses found for {node_context.vm_name}."
                    " Guest OS might have failed to boot"
                )

    # Try to get the IP address of the VM.
    def _try_get_node_ip_address(
        self,
        environment: Environment,
        log: Logger,
        node: Node,
    ) -> Optional[str]:
        node_context = get_node_context(node)

        domain = self.libvirt_conn.lookupByName(node_context.vm_name)

        # Acquire IP address from libvirt's DHCP server.
        interfaces = domain.interfaceAddresses(
            libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE
        )
        if len(interfaces) < 1:
            return None

        interface_name = next(iter(interfaces))
        addrs = interfaces[interface_name]["addrs"]
        if len(addrs) < 1:
            return None

        addr = addrs[0]["addr"]
        assert isinstance(addr, str)
        return addr

    def _get_firmware_config(
        self,
        machine_type: Optional[str],
        enable_secure_boot: bool,
    ) -> Dict[str, Any]:
        # Resolve the machine type to its full name.
        domain_caps_str = self.libvirt_conn.getDomainCapabilities(
            machine=machine_type, virttype="kvm"
        )
        domain_caps = ET.fromstring(domain_caps_str)

        full_machine_type = domain_caps.findall("./machine")[0].text
        arch = domain_caps.findall("./arch")[0].text

        # Read the QEMU firmware config files.
        # Note: "/usr/share/qemu/firmware" is a well known location for these files.
        firmware_configs_str = self.host_node.execute(
            "cat /usr/share/qemu/firmware/*.json",
            shell=True,
            expected_exit_code=0,
            no_debug_log=True,
        ).stdout
        firmware_configs = self._read_concat_json_str(firmware_configs_str)

        # Filter on architecture.
        filtered_firmware_configs = list(
            filter(lambda f: f["targets"][0]["architecture"] == arch, firmware_configs)
        )

        filtered_firmware_configs = list(
            filter(
                lambda f: any(
                    fnmatch.fnmatch(full_machine_type, target_machine)
                    for target_machine in f["targets"][0]["machines"]
                ),
                filtered_firmware_configs,
            )
        )

        # Exclude Intel TDX and AMD SEV-ES firmwares.
        filtered_firmware_configs = list(
            filter(
                lambda f: "inteltdx" not in f["mapping"]["executable"]["filename"]
                and "amdsev" not in f["mapping"]["executable"]["filename"],
                filtered_firmware_configs,
            )
        )

        # Filter on secure boot.
        if enable_secure_boot:
            filtered_firmware_configs = list(
                filter(
                    lambda f: "secure-boot" in f["features"]
                    and "enrolled-keys" in f["features"],
                    filtered_firmware_configs,
                )
            )
        else:
            filtered_firmware_configs = list(
                filter(
                    lambda f: "secure-boot" not in f["features"],
                    filtered_firmware_configs,
                )
            )

        # Get first matching firmware.
        firmware_config = next(iter(filtered_firmware_configs), None)
        if firmware_config is None:
            raise LisaException(
                f"Could not find matching firmware for machine-type={machine_type} "
                f"({full_machine_type}) and secure-boot={enable_secure_boot}."
            )

        return firmware_config

    # Read a bunch of JSON files that have been concatenated together.
    def _read_concat_json_str(self, json_str: str) -> List[Dict[str, Any]]:
        objs = []

        # From: https://stackoverflow.com/a/42985887
        decoder = json.JSONDecoder()
        text = json_str.lstrip()  # decode hates leading whitespace
        while text:
            obj, index = decoder.raw_decode(text)
            text = text[index:].lstrip()

            objs.append(obj)

        return objs

    def _libvirt_uri_schema(self) -> str:
        raise NotImplementedError()

    def __init_libvirt_conn_string(self) -> None:
        hypervisor = self._libvirt_uri_schema()
        host = self.platform_runbook.hosts[0]

        host_addr = ""
        transport = ""
        params = ""
        if host.is_remote():
            assert host.address
            assert host.username
            host_addr = f"{host.username}@{host.address}"
            transport = "+ssh"
            params = f"?keyfile={host.private_key_file}"

        self.libvirt_conn_str = f"{hypervisor}{transport}://{host_addr}/system{params}"

    def __platform_runbook_type(self) -> type:
        platform_runbook_type: type = type(self).platform_runbook_type()
        assert issubclass(platform_runbook_type, BaseLibvirtPlatformSchema)
        return platform_runbook_type

    def __node_runbook_type(self) -> type:
        node_runbook_type: type = type(self).node_runbook_type()
        assert issubclass(node_runbook_type, BaseLibvirtNodeSchema)
        return node_runbook_type

    def _get_host_distro(self) -> str:
        result = self.host_node.os.information.full_version if self.host_node else ""
        return result

    def _get_host_kernel_version(self) -> str:
        result = ""
        if self.host_node:
            uname = self.host_node.tools[Uname]
            result = uname.get_linux_information().kernel_version_raw
        return result

    def _get_libvirt_version(self) -> str:
        result = ""
        if self.host_node:
            result = self.host_node.execute("libvirtd --version", shell=True).stdout
            result = filter_ansi_escape(result)
            # Libvirtd returns version info as "libvirtd (libvirt) 10.8.0"
            # From the return value, only return the version info
            result = result.split()[-1]
        return result

    def _get_vmm_version(self) -> str:
        return "Unknown"

    def _get_environment_information(self, environment: Environment) -> Dict[str, str]:
        information: Dict[str, str] = {}

        if self.host_node:
            node: Node = self.host_node
            for key, method in self._host_environment_information_hooks.items():
                node.log.debug(f"detecting {key} ...")
                try:
                    value = method()
                    if value:
                        information[key] = value
                except Exception as e:
                    node.log.exception(f"error on get {key}.", exc_info=e)

        return information

    def _enable_libvirt_debug_log(self) -> None:
        self.host_node.tools[Mkdir].create_directory(
            str(self.LIBVIRT_DEBUG_LOG_PATH.parent),
            sudo=True,
        )
        sed = self.host_node.tools[Sed]
        sed.append(
            f'log_outputs="1:file:{self.LIBVIRT_DEBUG_LOG_PATH} 3:syslog:libvirtd" '
            f"# {self.CONFIG_FILE_MARKER}",
            str(self.LIBVIRTD_CONF_PATH),
            sudo=True,
        )

        self.host_node.tools[Service].restart_service("libvirtd")

    def _disable_libvirt_debug_log(self) -> None:
        self.host_node.tools[Sed].delete_lines(
            self.CONFIG_FILE_MARKER,
            self.LIBVIRTD_CONF_PATH,
            sudo=True,
        )

    def _capture_libvirt_logs(self) -> None:
        libvirt_log_local_path = self.host_node.local_log_path / "libvirtd.log"

        if self.platform_runbook.capture_libvirt_debug_logs:
            libvirt_log_temp_path = self.host_node.working_path / "libvirtd.log"

            # Copy the log file to working_path, change ownership and then copy_back
            # to the local machine.
            self.host_node.tools[Cp].copy(
                self.LIBVIRT_DEBUG_LOG_PATH, libvirt_log_temp_path, sudo=True
            )
            user = self.host_node.tools[Whoami].get_username()
            self.host_node.tools[Chown].change_owner(libvirt_log_temp_path, user)
            self.host_node.shell.copy_back(
                libvirt_log_temp_path, libvirt_log_local_path
            )
        else:
            libvirt_log = self.host_node.tools[Journalctl].logs_for_unit(
                "libvirtd", sudo=self.host_node.is_remote
            )
            with open(str(libvirt_log_local_path), "w") as f:
                f.write(libvirt_log)

    def _expand_nodes_os_partition(self, environment: Environment, log: Logger) -> None:
        for node in environment.nodes.list():
            # In some cases, we observe that resize vhd resizes the entire disk
            # but fails to expand the partition size.
            log.debug(
                f"Expanding os parition for: node: {node.name}, os: {node.os.name}"
            )
            resize = node.tools[ResizePartition]
            resize.expand_os_partition()
