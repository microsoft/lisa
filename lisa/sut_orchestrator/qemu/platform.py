# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import io
import os
import random
import string
import subprocess
import time
import xml.etree.ElementTree as ET  # noqa: N817
from typing import List, Optional, Tuple, Type

import libvirt  # type: ignore
import pycdlib  # type: ignore
import yaml

from lisa import schema
from lisa.environment import Environment
from lisa.feature import Feature
from lisa.node import Node, RemoteNode
from lisa.platform_ import Platform
from lisa.util import LisaException, constants, get_public_key_data
from lisa.util.logger import Logger

from .. import QEMU
from . import libvirt_events_thread
from .console_logger import QemuConsoleLogger
from .context import get_environment_context, get_node_context
from .schema import QemuNodeSchema
from .serial_console import SerialConsole


class QemuPlatform(Platform):
    _supported_features: List[Type[Feature]] = [
        SerialConsole,
    ]

    def __init__(self, runbook: schema.Platform) -> None:
        super().__init__(runbook=runbook)

    @classmethod
    def type_name(cls) -> str:
        return QEMU

    @classmethod
    def supported_features(cls) -> List[Type[Feature]]:
        return QemuPlatform._supported_features

    def _prepare_environment(self, environment: Environment, log: Logger) -> bool:
        return True

    def _deploy_environment(self, environment: Environment, log: Logger) -> None:
        self._deploy_nodes(environment, log)

    def _delete_environment(self, environment: Environment, log: Logger) -> None:
        with libvirt.open("qemu:///system") as qemu_conn:
            self._delete_nodes(environment, log, qemu_conn)

    def _deploy_nodes(self, environment: Environment, log: Logger) -> None:
        libvirt_events_thread.init()

        self._configure_nodes(environment, log)

        with libvirt.open("qemu:///system") as qemu_conn:
            try:
                self._create_nodes(environment, log, qemu_conn)
                self._fill_nodes_metadata(environment, log, qemu_conn)

            except Exception as ex:
                self._delete_nodes(environment, log, qemu_conn)
                raise ex

    # Pre-determine all the nodes' properties, including the name of all the resouces
    # to be created. This makes it easier to cleanup everything after the test is
    # finished (or fails).
    def _configure_nodes(self, environment: Environment, log: Logger) -> None:
        environment_context = get_environment_context(environment)

        # Generate a random name for the VMs.
        test_suffix = "".join(random.choice(string.ascii_uppercase) for i in range(5))
        vm_name_prefix = f"lisa-{test_suffix}"

        environment_context.ssh_public_key = get_public_key_data(
            self.runbook.admin_private_key_file
        )

        assert environment.runbook.nodes_requirement
        for i, node_space in enumerate(environment.runbook.nodes_requirement):
            assert isinstance(
                node_space, schema.NodeSpace
            ), f"actual: {type(node_space)}"

            qemu_node_runbook: QemuNodeSchema = node_space.get_extended_runbook(
                QemuNodeSchema, type_name=QEMU
            )

            vm_disks_dir = os.path.dirname(qemu_node_runbook.qcow2)

            node = environment.create_node_from_requirement(node_space)
            node_context = get_node_context(node)

            node_context.vm_name = f"{vm_name_prefix}-{i}"
            node_context.cloud_init_file_path = os.path.join(
                vm_disks_dir, f"{node_context.vm_name}-cloud-init.iso"
            )
            node_context.os_disk_base_file_path = qemu_node_runbook.qcow2
            node_context.os_disk_file_path = os.path.join(
                vm_disks_dir, f"{node_context.vm_name}-os.qcow2"
            )
            node_context.console_log_file_path = os.path.join(
                vm_disks_dir, f"{node_context.vm_name}-console.log"
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
        self, environment: Environment, log: Logger, qemu_conn: libvirt.virConnect
    ) -> None:
        for node in environment.nodes.list():
            node_context = get_node_context(node)

            # Create cloud-init ISO file.
            self._create_node_cloud_init_iso(environment, log, node)

            # Create OS disk from the provided image.
            self._create_node_os_disk(environment, log, node)

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
        # Give all the VMs some time to boot and then acquire an IP address.
        timeout = time.time() + 30  # seconds

        for node in environment.nodes.list():
            assert isinstance(node, RemoteNode)

            # Get the VM's IP address.
            address = self._get_node_ip_address(
                environment, log, qemu_conn, node, timeout
            )

            # Set SSH connection info for the node.
            node.set_connection_info(
                address=address,
                username=self.runbook.admin_username,
                private_key_file=self.runbook.admin_private_key_file,
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

        if node_context.extra_cloud_init_user_data:
            user_data.update(node_context.extra_cloud_init_user_data)

        meta_data = {
            "local-hostname": node_context.vm_name,
        }

        # Note: cloud-init requires the user-data file to be prefixed with
        # `#cloud-config`.
        user_data_string = "#cloud-config\n" + yaml.safe_dump(user_data)
        meta_data_string = yaml.safe_dump(meta_data)

        self._create_iso(
            node_context.cloud_init_file_path,
            [("/user-data", user_data_string), ("/meta-data", meta_data_string)],
        )

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

        # Create a new differencing image with the user provided image as the base.
        subprocess.run(
            [
                "qemu-img",
                "create",
                "-F",
                "qcow2",
                "-f",
                "qcow2",
                "-b",
                node_context.os_disk_base_file_path,
                node_context.os_disk_file_path,
            ],
            check=True,
            capture_output=True,
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
        memory.attrib["unit"] = "GiB"
        memory.text = "4"

        vcpu = ET.SubElement(domain, "vcpu")
        vcpu.text = "2"

        os = ET.SubElement(domain, "os")
        os.attrib["firmware"] = "efi"

        os_type = ET.SubElement(os, "type")
        os_type.text = "hvm"

        features = ET.SubElement(domain, "features")

        acpi = ET.SubElement(features, "acpi")  # noqa: F841

        apic = ET.SubElement(features, "apic")  # noqa: F841

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
