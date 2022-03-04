# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import io
import os
import random
import string
import tempfile
import time
import xml.etree.ElementTree as ET  # noqa: N817
from pathlib import Path
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

from .. import QEMU
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
    QemuNodeSchema,
    QemuPlatformSchema,
)
from .serial_console import SerialConsole


class _HostCapabilities:
    def __init__(self) -> None:
        self.core_count = 0
        self.free_memory_kib = 0


class QemuPlatform(Platform):
    _supported_features: List[Type[Feature]] = [
        SerialConsole,
    ]

    def __init__(self, runbook: schema.Platform) -> None:
        super().__init__(runbook=runbook)
        self.libvirt_conn_str: str
        self.qemu_platform_runbook: QemuPlatformSchema
        self.host_node: Node

    @classmethod
    def type_name(cls) -> str:
        return QEMU

    @classmethod
    def supported_features(cls) -> List[Type[Feature]]:
        return QemuPlatform._supported_features

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        libvirt_events_thread.init()

        self.qemu_platform_runbook = self.runbook.get_extended_runbook(
            QemuPlatformSchema, type_name=QEMU
        )

    def _prepare_environment(self, environment: Environment, log: Logger) -> bool:
        if len(self.qemu_platform_runbook.hosts) > 1:
            log.warning(
                "Multiple hosts are currently not supported. "
                "Only the first host will be used."
            )

        host = self.qemu_platform_runbook.hosts[0]
        if host.is_remote():
            assert host.address
            if not host.username:
                raise LisaException("Username must be provided for remote host")
            if not host.private_key_file:
                raise LisaException("Private key file must be provided for remote host")

            self.host_node = RemoteNode(
                runbook=schema.Node(name="qemu-host"),
                index=-1,
                logger_name="qemu-host",
                parent_logger=log,
            )

            self.host_node.set_connection_info(
                address=host.address,
                username=host.username,
                private_key_file=host.private_key_file,
            )
        else:
            self.host_node = local_node_connect(parent_logger=log)

        self._init_libvirt_conn_string()
        self._configure_environment(environment, log)

        with libvirt.open(self.libvirt_conn_str) as qemu_conn:
            return self._configure_node_capabilities(environment, log, qemu_conn)

    def _deploy_environment(self, environment: Environment, log: Logger) -> None:
        self._deploy_nodes(environment, log)

    def _delete_environment(self, environment: Environment, log: Logger) -> None:
        with libvirt.open(self.libvirt_conn_str) as qemu_conn:
            self._delete_nodes(environment, log, qemu_conn)

    def _configure_environment(self, environment: Environment, log: Logger) -> None:
        environment_context = get_environment_context(environment)

        if self.qemu_platform_runbook.network_boot_timeout:
            environment_context.network_boot_timeout = (
                self.qemu_platform_runbook.network_boot_timeout
            )

        environment_context.ssh_public_key = get_public_key_data(
            self.runbook.admin_private_key_file
        )

    def _configure_node_capabilities(
        self, environment: Environment, log: Logger, qemu_conn: libvirt.virConnect
    ) -> bool:
        if not environment.runbook.nodes_requirement:
            return True

        host_capabilities = self._get_host_capabilities(qemu_conn, log)
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
        self, qemu_conn: libvirt.virConnect, log: Logger
    ) -> _HostCapabilities:
        host_capabilities = _HostCapabilities()

        capabilities_xml_str = qemu_conn.getCapabilities()
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
        memory_stats = qemu_conn.getMemoryStats(libvirt.VIR_NODE_MEMORY_STATS_ALL_CELLS)
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

        with libvirt.open(self.libvirt_conn_str) as qemu_conn:
            try:
                self._create_nodes(environment, log, qemu_conn)
                self._fill_nodes_metadata(environment, log, qemu_conn)

            except Exception as ex:
                assert environment.platform
                if (
                    environment.platform.runbook.keep_environment
                    == constants.ENVIRONMENT_KEEP_NO
                ):
                    self._delete_nodes(environment, log, qemu_conn)

                raise ex

    # Pre-determine all the nodes' properties, including the name of all the resouces
    # to be created. This makes it easier to cleanup everything after the test is
    # finished (or fails).
    def _configure_nodes(self, environment: Environment, log: Logger) -> None:
        # Generate a random name for the VMs.
        test_suffix = "".join(random.choice(string.ascii_uppercase) for _ in range(5))
        vm_name_prefix = f"lisa-{test_suffix}"

        assert environment.runbook.nodes_requirement
        for i, node_space in enumerate(environment.runbook.nodes_requirement):
            assert isinstance(
                node_space, schema.NodeSpace
            ), f"actual: {type(node_space)}"

            qemu_node_runbook: QemuNodeSchema = node_space.get_extended_runbook(
                QemuNodeSchema, type_name=QEMU
            )

            if not os.path.exists(qemu_node_runbook.qcow2):
                raise LisaException(f"file does not exist: {qemu_node_runbook.qcow2}")

            node = environment.create_node_from_requirement(node_space)
            node_context = get_node_context(node)

            vm_disks_dir = os.path.join(
                self.qemu_platform_runbook.hosts[0].lisa_working_dir, vm_name_prefix
            )
            node_context.vm_disks_dir = vm_disks_dir

            if (
                not qemu_node_runbook.firmware_type
                or qemu_node_runbook.firmware_type == FIRMWARE_TYPE_UEFI
            ):
                node_context.use_bios_firmware = False
            elif qemu_node_runbook.firmware_type == FIRMWARE_TYPE_BIOS:
                node_context.use_bios_firmware = True
            else:
                raise LisaException(
                    f"Unknown node firmware type: {qemu_node_runbook.firmware_type}."
                    f"Expecting either {FIRMWARE_TYPE_UEFI} or {FIRMWARE_TYPE_BIOS}."
                )

            node_context.vm_name = f"{vm_name_prefix}-{i}"
            node_context.cloud_init_file_path = os.path.join(
                vm_disks_dir, f"{node_context.vm_name}-cloud-init.iso"
            )

            if self.host_node.is_remote:
                node_context.os_disk_source_file_path = qemu_node_runbook.qcow2
                node_context.os_disk_base_file_path = os.path.join(
                    vm_disks_dir, os.path.basename(qemu_node_runbook.qcow2)
                )
            else:
                node_context.os_disk_base_file_path = qemu_node_runbook.qcow2

            node_context.os_disk_file_path = os.path.join(
                vm_disks_dir, f"{node_context.vm_name}-os.qcow2"
            )
            node_context.console_log_file_path = os.path.join(
                os.path.dirname(qemu_node_runbook.qcow2),
                f"{node_context.vm_name}-console.log",
            )
            node_context.console_logger = QemuConsoleLogger()

            if not node.name:
                node.name = node_context.vm_name

            # Read extra cloud-init data.
            extra_user_data = (
                qemu_node_runbook.cloud_init
                and qemu_node_runbook.cloud_init.extra_user_data
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
                        node_context.extra_cloud_init_user_data.append(
                            yaml.safe_load(file)
                        )

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
                        vm_disks_dir, f"{node_context.vm_name}-data-{i}.qcow2"
                    )
                    data_disk.size_gib = node_space.disk.data_disk_size

                    node_context.data_disks.append(data_disk)

    # Create all the VMs.
    def _create_nodes(
        self,
        environment: Environment,
        log: Logger,
        qemu_conn: libvirt.virConnect,
    ) -> None:
        for node in environment.nodes.list():
            node_context = get_node_context(node)

            # Create required directories and copy the required files to the host
            # node.
            self.host_node.shell.mkdir(Path(node_context.vm_disks_dir), exist_ok=True)
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
            domain = qemu_conn.defineXML(xml)

            # Start the VM in the paused state.
            # This gives the console logger a chance to connect before the VM starts
            # for real.
            domain.createWithFlags(libvirt.VIR_DOMAIN_START_PAUSED)

            # Attach the console logger
            assert node_context.console_logger
            node_context.console_logger.attach(
                qemu_conn, domain, node_context.console_log_file_path
            )

            # Start the VM.
            domain.resume()

    # Delete all the VMs.
    def _delete_nodes(
        self, environment: Environment, log: Logger, qemu_conn: libvirt.virConnect
    ) -> None:
        for node in environment.nodes.list():
            node_context = get_node_context(node)
            log.debug(f"Delete VM: {node_context.vm_name}")

            # Shutdown and delete the VM.
            self._stop_and_delete_vm(environment, log, qemu_conn, node)

            assert node_context.console_logger
            node_context.console_logger.close()

            # Delete console log file
            try:
                os.remove(node_context.console_log_file_path)
            except Exception as ex:
                log.warning(f"console log delete failed. {ex}")

            try:
                self.host_node.shell.remove(Path(node_context.vm_disks_dir), True)
            except Exception as ex:
                log.warning(f"Failed to delete VM files directory: {ex}")

    # Delete a VM.
    def _stop_and_delete_vm(
        self,
        environment: Environment,
        log: Logger,
        qemu_conn: libvirt.virConnect,
        node: Node,
    ) -> None:
        node_context = get_node_context(node)

        # Find the VM.
        try:
            domain = qemu_conn.lookupByName(node_context.vm_name)
        except libvirt.libvirtError as ex:
            log.warning(f"VM delete failed. Can't find domain. {ex}")
            return

        # Stop the VM.
        try:
            # In the libvirt API, "destroy" means "stop".
            domain.destroy()
        except libvirt.libvirtError as ex:
            log.warning(f"VM stop failed. {ex}")

        # Undefine the VM.
        try:
            domain.undefineFlags(
                libvirt.VIR_DOMAIN_UNDEFINE_MANAGED_SAVE
                | libvirt.VIR_DOMAIN_UNDEFINE_SNAPSHOTS_METADATA
                | libvirt.VIR_DOMAIN_UNDEFINE_NVRAM
                | libvirt.VIR_DOMAIN_UNDEFINE_CHECKPOINTS_METADATA
            )
        except libvirt.libvirtError as ex:
            log.warning(f"VM delete failed. {ex}")

    # Retrieve the VMs' dynamic properties (e.g. IP address).
    def _fill_nodes_metadata(
        self, environment: Environment, log: Logger, qemu_conn: libvirt.virConnect
    ) -> None:
        environment_context = get_environment_context(environment)

        # Give all the VMs some time to boot and then acquire an IP address.
        timeout = time.time() + environment_context.network_boot_timeout

        for node in environment.nodes.list():
            assert isinstance(node, RemoteNode)

            # Get the VM's IP address.
            address = self._get_node_ip_address(
                environment, log, qemu_conn, node, timeout
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
        node_context = get_node_context(node)
        self.host_node.tools[QemuImg].create_diff_qcow2(
            node_context.os_disk_file_path, node_context.os_disk_base_file_path
        )

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

        self._add_disk_xml(
            node_context,
            devices,
            node_context.cloud_init_file_path,
            "cdrom",
            "raw",
        )
        self._add_disk_xml(
            node_context,
            devices,
            node_context.os_disk_file_path,
            "disk",
            "qcow2",
        )

        for data_disk in node_context.data_disks:
            self._add_disk_xml(
                node_context,
                devices,
                data_disk.file_path,
                "disk",
                "qcow2",
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
        disk_target.attrib["bus"] = "sata"

        disk_source = ET.SubElement(disk, "source")
        disk_source.attrib["file"] = file_path

    def _new_disk_device_name(self, node_context: NodeContext) -> str:
        disk_index = node_context.next_disk_index
        node_context.next_disk_index += 1

        device_name = self._get_disk_device_name(disk_index)
        return device_name

    def _get_disk_device_name(self, disk_index: int) -> str:
        # The disk device name is required to follow the standard Linux device naming
        # scheme. That is: [ sda, sdb, ..., sdz, sdaa, sdab, ... ]. However, it is
        # unlikely that someone will ever need more than 26 disks. So, keep is simple
        # for now.
        if disk_index < 0 or disk_index > 25:
            raise LisaException(f"Unsupported disk index: {disk_index}.")

        suffix = chr(ord("a") + disk_index)
        return f"sd{suffix}"

    # Wait for the VM to boot and then get the IP address.
    def _get_node_ip_address(
        self,
        environment: Environment,
        log: Logger,
        qemu_conn: libvirt.virConnect,
        node: Node,
        timeout: float,
    ) -> str:
        node_context = get_node_context(node)

        while True:
            addr = self._try_get_node_ip_address(environment, log, qemu_conn, node)
            if addr:
                return addr

            if time.time() > timeout:
                raise LisaException(f"no IP addresses found for {node_context.vm_name}")

    # Try to get the IP address of the VM.
    def _try_get_node_ip_address(
        self,
        environment: Environment,
        log: Logger,
        qemu_conn: libvirt.virConnect,
        node: Node,
    ) -> Optional[str]:
        node_context = get_node_context(node)

        domain = qemu_conn.lookupByName(node_context.vm_name)

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

    def _init_libvirt_conn_string(self) -> None:
        hypervisor = "qemu"
        host = self.qemu_platform_runbook.hosts[0]

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
