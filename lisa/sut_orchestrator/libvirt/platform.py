# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import faulthandler
import io
import os
import random
import string
import sys
import tempfile
import time
import xml.etree.ElementTree as ET  # noqa: N817
from pathlib import Path
from threading import Timer
from typing import Any, List, Optional, Tuple, Type, cast

import libvirt  # type: ignore
import pycdlib  # type: ignore
import yaml

from lisa import schema, search_space
from lisa.environment import Environment
from lisa.feature import Feature
from lisa.node import Node, RemoteNode, local_node_connect
from lisa.platform_ import Platform
from lisa.tools import Iptables, QemuImg
from lisa.util import LisaException, constants, get_public_key_data
from lisa.util.logger import Logger

from . import libvirt_events_thread
from .console_logger import QemuConsoleLogger
from .context import (
    DataDiskContext,
    NodeContext,
    get_environment_context,
    get_node_context,
)
from .schema import (
    FIRMWARE_TYPE_BIOS,
    FIRMWARE_TYPE_UEFI,
    BaseLibvirtNodeSchema,
    BaseLibvirtPlatformSchema,
    DiskImageFormat,
)
from .serial_console import SerialConsole


class _HostCapabilities:
    def __init__(self) -> None:
        self.core_count = 0
        self.free_memory_kib = 0


class BaseLibvirtPlatform(Platform):
    _supported_features: List[Type[Feature]] = [
        SerialConsole,
    ]

    def __init__(self, runbook: schema.Platform) -> None:
        super().__init__(runbook=runbook)
        self.libvirt_conn_str: str
        self.platform_runbook: BaseLibvirtPlatformSchema
        self.host_node: Node
        self.vm_disks_dir: str

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

        self.platform_runbook = self.runbook.get_extended_runbook(
            self.__platform_runbook_type(), type_name=type(self).type_name()
        )

    def _prepare_environment(self, environment: Environment, log: Logger) -> bool:
        # Ensure environment log directory is created before connecting to any nodes.
        _ = environment.log_path

        if len(self.platform_runbook.hosts) > 1:
            log.warning(
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
                base_part_path=environment.environment_part_path,
                parent_logger=log,
            )

            self.host_node.set_connection_info(
                address=host.address,
                username=host.username,
                private_key_file=host.private_key_file,
            )
        else:
            self.host_node = local_node_connect(
                name="libvirt-host",
                base_part_path=environment.environment_part_path,
                parent_logger=log,
            )

        self.__init_libvirt_conn_string()
        self._configure_environment(environment, log)

        with libvirt.open(self.libvirt_conn_str) as lv_conn:
            return self._configure_node_capabilities(environment, log, lv_conn)

    def _deploy_environment(self, environment: Environment, log: Logger) -> None:
        self._deploy_nodes(environment, log)

    def _delete_environment(self, environment: Environment, log: Logger) -> None:
        self._delete_nodes(environment, log)

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
        self, environment: Environment, log: Logger, lv_conn: libvirt.virConnect
    ) -> bool:
        if not environment.runbook.nodes_requirement:
            return True

        host_capabilities = self._get_host_capabilities(lv_conn, log)
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

    def _get_host_capabilities(
        self, lv_conn: libvirt.virConnect, log: Logger
    ) -> _HostCapabilities:
        host_capabilities = _HostCapabilities()

        capabilities_xml_str = lv_conn.getCapabilities()
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
        memory_stats = lv_conn.getMemoryStats(libvirt.VIR_NODE_MEMORY_STATS_ALL_CELLS)
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
        node_capabilities.features = search_space.SetSpace[schema.FeatureSettings](
            is_allow_set=True,
            items=[
                schema.FeatureSettings.create(SerialConsole.name()),
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

        with libvirt.open(self.libvirt_conn_str) as lv_conn:
            try:
                self._create_nodes(environment, log, lv_conn)
                self._fill_nodes_metadata(environment, log, lv_conn)

            except Exception as ex:
                assert environment.platform
                if (
                    environment.platform.runbook.keep_environment
                    == constants.ENVIRONMENT_KEEP_NO
                ):
                    self._delete_nodes(environment, log)

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

        if (
            not node_runbook.firmware_type
            or node_runbook.firmware_type == FIRMWARE_TYPE_UEFI
        ):
            node_context.use_bios_firmware = False
        elif node_runbook.firmware_type == FIRMWARE_TYPE_BIOS:
            node_context.use_bios_firmware = True
        else:
            raise LisaException(
                f"Unknown node firmware type: {node_runbook.firmware_type}."
                f"Expecting either {FIRMWARE_TYPE_UEFI} or {FIRMWARE_TYPE_BIOS}."
            )

        node_context.vm_name = f"{vm_name_prefix}-{node_idx}"
        if not node.name:
            node.name = node_context.vm_name

        node_context.cloud_init_file_path = os.path.join(
            self.vm_disks_dir, f"{node_context.vm_name}-cloud-init.iso"
        )

        if self.host_node.is_remote:
            node_context.os_disk_source_file_path = node_runbook.disk_img
            node_context.os_disk_base_file_path = os.path.join(
                self.vm_disks_dir, os.path.basename(node_runbook.disk_img)
            )
        else:
            node_context.os_disk_base_file_path = node_runbook.disk_img

        node_context.os_disk_base_file_fmt = DiskImageFormat(
            node_runbook.disk_img_format
        )

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

    def _create_domain_and_attach_logger(
        self,
        libvirt_conn: libvirt.virConnect,
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
            libvirt_conn, node_context.domain, node_context.console_log_file_path
        )

        # Start the VM.
        node_context.domain.resume()

    # Create all the VMs.
    def _create_nodes(
        self,
        environment: Environment,
        log: Logger,
        lv_conn: libvirt.virConnect,
    ) -> None:
        self.host_node.shell.mkdir(Path(self.vm_disks_dir), exist_ok=True)

        for node in environment.nodes.list():
            node_context = get_node_context(node)
            self._create_node(
                node,
                node_context,
                environment,
                log,
                lv_conn,
            )

    def _create_node(
        self,
        node: Node,
        node_context: NodeContext,
        environment: Environment,
        log: Logger,
        lv_conn: libvirt.virConnect,
    ) -> None:
        # Create required directories and copy the required files to the host
        # node.
        if node_context.os_disk_source_file_path:
            self.host_node.shell.copy(
                Path(node_context.os_disk_source_file_path),
                Path(node_context.os_disk_base_file_path),
            )

        # Create cloud-init ISO file.
        self._create_node_cloud_init_iso(environment, log, node)

        # Create OS disk from the provided image.
        self._create_node_os_disk(environment, log, node)

        # Create data disks
        self._create_node_data_disks(node)

        # Create libvirt domain (i.e. VM).
        xml = self._create_node_domain_xml(environment, log, node)
        node_context.domain = lv_conn.defineXML(xml)

        self._create_domain_and_attach_logger(
            lv_conn,
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

    def _get_domain_undefine_flags(self) -> int:
        return int(
            libvirt.VIR_DOMAIN_UNDEFINE_MANAGED_SAVE
            | libvirt.VIR_DOMAIN_UNDEFINE_SNAPSHOTS_METADATA
            | libvirt.VIR_DOMAIN_UNDEFINE_NVRAM
            | libvirt.VIR_DOMAIN_UNDEFINE_CHECKPOINTS_METADATA
        )

    # Retrieve the VMs' dynamic properties (e.g. IP address).
    def _fill_nodes_metadata(
        self, environment: Environment, log: Logger, lv_conn: libvirt.virConnect
    ) -> None:
        environment_context = get_environment_context(environment)

        # Give all the VMs some time to boot and then acquire an IP address.
        timeout = time.time() + environment_context.network_boot_timeout

        for node in environment.nodes.list():
            assert isinstance(node, RemoteNode)

            # Get the VM's IP address.
            address = self._get_node_ip_address(
                environment, log, lv_conn, node, timeout
            )

            node_port = 22
            if self.host_node.is_remote:
                self.host_node.tools[Iptables].start_forwarding(10022, address, 22)

                remote_node = cast(RemoteNode, self.host_node)
                conn_info = remote_node.connection_info

                address = conn_info[constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS]
                node_port = 10022

            # Set SSH connection info for the node.
            node.set_connection_info(
                address=address,
                port=node_port,
                public_port=node_port,
                username=self.runbook.admin_username,
                private_key_file=self.runbook.admin_private_key_file,
            )

            # Ensure cloud-init completes its setup.
            node.execute(
                "cloud-init status --wait",
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message="waiting on cloud-init",
            )

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
        self, environment: Environment, log: Logger, node: Node
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

        os = ET.SubElement(domain, "os")

        if not node_context.use_bios_firmware:
            os.attrib["firmware"] = "efi"

        os_type = ET.SubElement(os, "type")
        os_type.text = "hvm"

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
        video_model.attrib["type"] = "qxl"

        graphics = ET.SubElement(devices, "graphics")
        graphics.attrib["type"] = "spice"

        network_interface = ET.SubElement(devices, "interface")
        network_interface.attrib["type"] = "network"

        network_interface_source = ET.SubElement(network_interface, "source")
        network_interface_source.attrib["network"] = "default"

        network_interface_model = ET.SubElement(network_interface, "model")
        network_interface_model.attrib["type"] = "virtio"

        self._add_disk_xml(
            node_context,
            devices,
            node_context.cloud_init_file_path,
            "cdrom",
            "raw",
            "sata",
        )
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
        lv_conn: libvirt.virConnect,
        node: Node,
        timeout: float,
    ) -> str:
        node_context = get_node_context(node)

        while True:
            addr = self._try_get_node_ip_address(environment, log, lv_conn, node)
            if addr:
                return addr

            if time.time() > timeout:
                raise LisaException(f"no IP addresses found for {node_context.vm_name}")

    # Try to get the IP address of the VM.
    def _try_get_node_ip_address(
        self,
        environment: Environment,
        log: Logger,
        lv_conn: libvirt.virConnect,
        node: Node,
    ) -> Optional[str]:
        node_context = get_node_context(node)

        domain = lv_conn.lookupByName(node_context.vm_name)

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
