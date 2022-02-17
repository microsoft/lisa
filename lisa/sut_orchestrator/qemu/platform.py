# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import io
import os
import random
import string
import tempfile
import time
import xml.etree.ElementTree as ET  # noqa: N817
from pathlib import PurePath
from typing import Any, List, Optional, Tuple, Type

import libvirt  # type: ignore
import pycdlib  # type: ignore
import yaml

from lisa import schema, search_space
from lisa.environment import Environment
from lisa.feature import Feature
from lisa.node import Node, RemoteNode, local_node_connect
from lisa.platform_ import Platform
from lisa.tools import QemuImg, Iptables
from lisa.util import LisaException, constants, get_public_key_data
from lisa.util.logger import Logger

from .. import QEMU
from . import libvirt_events_thread
from .console_logger import QemuConsoleLogger
from .context import get_environment_context, get_node_context
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

    qemu_platform_runbook: QemuPlatformSchema
    host_node: RemoteNode
    libvirt_conn_str: str

    def __init__(self, runbook: schema.Platform) -> None:
        super().__init__(runbook=runbook)

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
        self.libvirt_conn_str = "qemu:///system"

        if self.qemu_platform_runbook.is_host_remote():
            self.host_node = RemoteNode(schema.Node(name="qemu-host"), 0, "qemu-host")
            self.host_node.set_connection_info(
                address=self.qemu_platform_runbook.host.address,
                username=self.qemu_platform_runbook.host.username,
                private_key_file=self.qemu_platform_runbook.host.private_key_file
            )

            self.libvirt_conn_str = self._get_libvirt_conn_string()

    def _prepare_environment(self, environment: Environment, log: Logger) -> bool:
        self._configure_environment(environment, log)

        with libvirt.open(self.libvirt_conn_str) as qemu_conn:
            return self._configure_node_capabilities(environment, log, qemu_conn)

    def _deploy_environment(self, environment: Environment, log: Logger) -> None:
        local_node = local_node_connect(parent_logger=log)
        self._deploy_nodes(environment, log, local_node)

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

        nodes_requirement = []
        for node_space in environment.runbook.nodes_requirement:
            node_capabilities = self._create_node_capabilities(log, node_space)
            nodes_requirement.append(node_capabilities)

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

    # Check what capabilities can be provided for the node.
    def _create_node_capabilities(
        self,
        log: Logger,
        node_space: schema.NodeSpace,
    ) -> schema.NodeSpace:
        node_capabilities = schema.NodeSpace()
        node_capabilities.name = "QEMU"
        node_capabilities.node_count = 1
        node_capabilities.core_count = self._get_count_space_min(node_space.core_count)
        node_capabilities.memory_mb = self._get_count_space_min(node_space.memory_mb)
        node_capabilities.disk = schema.DiskOptionSettings()
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

        node_capabilities.set_extended_runbook(
            node_space.get_extended_runbook(QemuNodeSchema, type_name=QEMU)
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
            # Ensure host has enough CPU cores for the VM.
            # Note: The CPU scheduler can easily handle overprovisioning of CPU
            # cores.
            assert isinstance(node_requirements.core_count, int)
            if node_requirements.core_count > host_capabilities.core_count:
                log.error(
                    f"Node requires {node_requirements.core_count} CPU cores. "
                    f"Host only has {host_capabilities.core_count}."
                )
                return False

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

    def _deploy_nodes(
        self, environment: Environment, log: Logger, local_node: Node
    ) -> None:
        self._configure_nodes(environment, log, local_node)

        with libvirt.open(self.libvirt_conn_str) as qemu_conn:
            try:
                self._create_nodes(environment, log, qemu_conn, local_node)
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
    def _configure_nodes(
            self, environment: Environment, log: Logger, local_node: Node
    ) -> None:
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

            vm_disks_dir = os.path.dirname(qemu_node_runbook.qcow2)
            if self.qemu_platform_runbook.is_host_remote():
                vm_disks_dir = os.path.join(
                    "/home", self.qemu_platform_runbook.host.username, vm_name_prefix
                )
                self.host_node.shell.mkdir(vm_disks_dir)

            node = environment.create_node_from_requirement(node_space)
            node_context = get_node_context(node)

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
            node_context.os_disk_base_file_path = qemu_node_runbook.qcow2
            if self.qemu_platform_runbook.is_host_remote():
                host = self.qemu_platform_runbook.host
                new_os_disk_base_file_path = os.path.join(
                    "/home",
                    host.username,
                    vm_name_prefix,
                    os.path.basename(qemu_node_runbook.qcow2)
                )

                local_node.execute(
                    f"scp -i {host.private_key_file} "
                    f"{node_context.os_disk_base_file_path} "
                    f"scp://{host.address}/{new_os_disk_base_file_path}"
                )

                node_context.os_disk_base_file_path = new_os_disk_base_file_path

            node_context.os_disk_file_path = os.path.join(
                vm_disks_dir, f"{node_context.vm_name}-os.qcow2"
            )
            node_context.console_log_file_path = os.path.join(
                os.path.dirname(qemu_node_runbook.qcow2),
                f"{node_context.vm_name}-console.log"
            )
            node_context.console_logger = QemuConsoleLogger()

            if not node.name:
                node.name = node_context.vm_name

            # Read extra cloud-init data.
            if (
                qemu_node_runbook.cloud_init
                and qemu_node_runbook.cloud_init.extra_user_data
            ):
                extra_user_data_file_path = str(
                    constants.RUNBOOK_PATH.joinpath(
                        qemu_node_runbook.cloud_init.extra_user_data
                    )
                )
                with open(extra_user_data_file_path, "r") as file:
                    node_context.extra_cloud_init_user_data = yaml.safe_load(file)

    # Create all the VMs.
    def _create_nodes(
        self,
        environment: Environment,
        log: Logger,
        qemu_conn: libvirt.virConnect,
        local_node: Node,
    ) -> None:
        for node in environment.nodes.list():
            node_context = get_node_context(node)

            # Create cloud-init ISO file.
            self._create_node_cloud_init_iso(environment, log, node, local_node)

            # Create OS disk from the provided image.
            self._create_node_os_disk(environment, log, node, local_node)

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

            if self.qemu_platform_runbook.is_host_remote():
                vm_dir = os.path.dirname(node_context.os_disk_file_path)
                self.host_node.shell.remove(PurePath(vm_dir), True)
            else:
                # Delete the files created for the VM.
                try:
                    os.remove(node_context.os_disk_file_path)
                except Exception as ex:
                    log.warning(f"OS disk delete failed. {ex}")

                try:
                    os.remove(node_context.cloud_init_file_path)
                except Exception as ex:
                    log.warning(f"cloud-init ISO file delete failed. {ex}")

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

            node_addr = address
            node_port = 22
            if self.qemu_platform_runbook.is_host_remote():
                self.host_node.tools[Iptables].start_forwarding(10022, address, 22)

                node_addr = self.qemu_platform_runbook.host.address
                node_port = 10022

            # Set SSH connection info for the node.
            node.set_connection_info(
                address=node_addr,
                port=node_port,
                public_port=node_port,
                username=self.runbook.admin_username,
                private_key_file=self.runbook.admin_private_key_file,
            )

    # Create a cloud-init ISO for a VM.
    def _create_node_cloud_init_iso(
        self, environment: Environment, log: Logger, node: Node, local_node: Node
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

        if node_context.extra_cloud_init_user_data:
            user_data.update(node_context.extra_cloud_init_user_data)

        meta_data = {
            "local-hostname": node_context.vm_name,
        }

        # Note: cloud-init requires the user-data file to be prefixed with
        # `#cloud-config`.
        user_data_string = "#cloud-config\n" + yaml.safe_dump(user_data)
        meta_data_string = yaml.safe_dump(meta_data)

        iso_path = node_context.cloud_init_file_path
        tmp_dir = None
        if self.qemu_platform_runbook.is_host_remote():
            tmp_dir = tempfile.TemporaryDirectory()
            iso_path = os.path.join(tmp_dir.name, "cloud-init.iso")

        self._create_iso(
            iso_path,
            [("/user-data", user_data_string), ("/meta-data", meta_data_string)],
        )

        if self.qemu_platform_runbook.is_host_remote():
            host = self.qemu_platform_runbook.host
            local_node.execute(
                f"scp -i {host.private_key_file} "
                f"{iso_path} "
                f"scp://{host.address}/{node_context.cloud_init_file_path}"
            )
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
        self, environment: Environment, log: Logger, node: Node, local_node: Node
    ) -> None:
        node_context = get_node_context(node)

        if self.qemu_platform_runbook.is_host_remote():
            self.host_node.tools[QemuImg].createDiffQcow2(
                node_context.os_disk_file_path,
                node_context.os_disk_base_file_path
            )

            return

        # Create a new differencing image with the user provided image as the base.
        local_node.execute(
            f"qemu-img create -F qcow2 -f qcow2 -b "
            f'"{node_context.os_disk_base_file_path}" '
            f'"{node_context.os_disk_file_path}"',
            expected_exit_code=0,
        )

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

        cloud_init_disk = ET.SubElement(devices, "disk")
        cloud_init_disk.attrib["type"] = "file"
        cloud_init_disk.attrib["device"] = "cdrom"

        cloud_init_disk_driver = ET.SubElement(cloud_init_disk, "driver")
        cloud_init_disk_driver.attrib["name"] = "qemu"
        cloud_init_disk_driver.attrib["type"] = "raw"

        cloud_init_disk_target = ET.SubElement(cloud_init_disk, "target")
        cloud_init_disk_target.attrib["dev"] = "sda"
        cloud_init_disk_target.attrib["bus"] = "sata"

        cloud_init_disk_target = ET.SubElement(cloud_init_disk, "source")
        cloud_init_disk_target.attrib["file"] = node_context.cloud_init_file_path

        os_disk = ET.SubElement(devices, "disk")
        os_disk.attrib["type"] = "file"
        os_disk.attrib["device"] = "disk"

        os_disk_driver = ET.SubElement(os_disk, "driver")
        os_disk_driver.attrib["name"] = "qemu"
        os_disk_driver.attrib["type"] = "qcow2"

        os_disk_target = ET.SubElement(os_disk, "target")
        os_disk_target.attrib["dev"] = "sdb"
        os_disk_target.attrib["bus"] = "sata"

        os_disk_target = ET.SubElement(os_disk, "source")
        os_disk_target.attrib["file"] = node_context.os_disk_file_path

        xml = ET.tostring(domain, "unicode")
        return xml

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

    def _get_libvirt_conn_string(self) -> str:
        hypervisor = "qemu"
        host = self.qemu_platform_runbook.host

        host_addr = host.address if host is not None else ""
        transport = "+tcp" if host is not None else ""

        return f"{hypervisor}{transport}://{host_addr}/system"
