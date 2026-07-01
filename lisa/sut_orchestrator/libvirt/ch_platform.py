# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
import os
import re
import secrets
import shutil
import xml.etree.ElementTree as ET  # noqa: N817
from pathlib import Path
from typing import Any, List, Tuple, Type, cast

from lisa import schema
from lisa.environment import Environment
from lisa.feature import Feature
from lisa.node import Node
from lisa.sut_orchestrator.libvirt.context import (
    GuestVmType,
    NodeContext,
    get_node_context,
)
from lisa.sut_orchestrator.libvirt.platform import BaseLibvirtPlatform
from lisa.tools import Ls, QemuImg
from lisa.util import LisaException, parse_version
from lisa.util.logger import Logger, filter_ansi_escape

from .. import CLOUD_HYPERVISOR
from .console_logger import QemuConsoleLogger
from .schema import BaseLibvirtNodeSchema, CloudHypervisorNodeSchema, DiskImageFormat

CH_VERSION_PATTERN = re.compile(r"cloud-hypervisor (?P<ch_version>.+)")


class CloudHypervisorPlatform(BaseLibvirtPlatform):
    @classmethod
    def type_name(cls) -> str:
        return CLOUD_HYPERVISOR

    @classmethod
    def supported_features(cls) -> List[Type[Feature]]:
        return BaseLibvirtPlatform._supported_features

    @classmethod
    def node_runbook_type(cls) -> type:
        return CloudHypervisorNodeSchema

    def _libvirt_uri_schema(self) -> str:
        return "ch"

    def _configure_node(
        self,
        node: Node,
        node_idx: int,
        node_space: schema.NodeSpace,
        node_runbook: BaseLibvirtNodeSchema,
        vm_name_prefix: str,
    ) -> None:
        super()._configure_node(
            node,
            node_idx,
            node_space,
            node_runbook,
            vm_name_prefix,
        )

        assert isinstance(node_runbook, CloudHypervisorNodeSchema)
        node_context = get_node_context(node)
        assert node_runbook.kernel, "Kernel parameter is required for clh platform"
        if self.host_node.is_remote and not node_runbook.kernel.is_remote_path:
            node_context.kernel_source_path = node_runbook.kernel.path
            node_context.kernel_path = os.path.join(
                self.vm_disks_dir, os.path.basename(node_runbook.kernel.path)
            )
        else:
            node_context.kernel_path = node_runbook.kernel.path
        node_context.guest_kernel_boot_parameters = (
            node_runbook.kernel_boot_parameters.strip()
        )
        libvirt_version = self._get_libvirt_version()
        assert libvirt_version, "Can not get libvirt version"

        if parse_version(libvirt_version) >= "10.5.0":
            en = "utf-8"
            token = secrets.token_hex(16)
            node_context.host_data = base64.b64encode(token.encode(en)).decode(en)
            node_context.is_host_data_base64 = True
        else:
            node_context.host_data = secrets.token_hex(32)

    def _create_node(
        self,
        node: Node,
        node_context: NodeContext,
        environment: Environment,
        log: Logger,
    ) -> None:
        if node_context.kernel_source_path:
            self.host_node.shell.copy(
                Path(node_context.kernel_source_path),
                Path(node_context.kernel_path),
            )

        super()._create_node(
            node,
            node_context,
            environment,
            log,
        )

    def _create_node_domain_xml(
        self,
        environment: Environment,
        log: Logger,
        node: Node,
    ) -> str:
        node_context = get_node_context(node)

        domain = ET.Element("domain")

        libvirt_version = self._get_libvirt_version()
        if parse_version(libvirt_version) > "10.0.2":
            if self.host_node.tools[Ls].path_exists("/dev/mshv", sudo=True):
                domain.attrib["type"] = "hyperv"
            elif self.host_node.tools[Ls].path_exists("/dev/kvm", sudo=True):
                domain.attrib["type"] = "kvm"
            else:
                raise LisaException(
                    "kvm, mshv are the only supported \
                                    hypervsiors. Both are missing on the host"
                )

        else:
            domain.attrib["type"] = "ch"

        name = ET.SubElement(domain, "name")
        name.text = node_context.vm_name

        memory = ET.SubElement(domain, "memory")
        memory.attrib["unit"] = "MiB"
        assert isinstance(node.capability.memory_mb, int)
        memory.text = str(node.capability.memory_mb)

        vcpu = ET.SubElement(domain, "vcpu")
        assert isinstance(node.capability.core_count, int)
        vcpu_count = node.capability.core_count
        vcpu.text = str(vcpu_count)

        os = ET.SubElement(domain, "os")

        os_type = ET.SubElement(os, "type")
        os_type.text = "hvm"
        os_kernel = ET.SubElement(os, "kernel")
        os_kernel.text = node_context.kernel_path

        # Ensure kernel logs go to UART (ttyS0) on first boot
        # - console=ttyS0,115200  : log to the ISA UART
        # - ignore_loglevel       : show all kernel messages
        # - printk.time=1         : add timestamps to kernel messages
        # Additional guest kernel boot parameters can be supplied through runbook.
        os_cmdline = ET.SubElement(os, "cmdline")
        os_cmdline.text = "console=ttyS0,115200 ignore_loglevel printk.time=1"
        if node_context.guest_kernel_boot_parameters:
            os_cmdline.text = (
                f"{os_cmdline.text} {node_context.guest_kernel_boot_parameters}"
            )
        if node_context.guest_vm_type is GuestVmType.ConfidentialVM:
            attrb_type = "sev"
            attrb_host_data = "host_data"
            if parse_version(libvirt_version) >= "10.5.0":
                attrb_type = "sev-snp"
                attrb_host_data = "hostData"

            launch_sec = ET.SubElement(domain, "launchSecurity")
            launch_sec.attrib["type"] = attrb_type
            cbitpos = ET.SubElement(launch_sec, "cbitpos")
            cbitpos.text = "0"
            reducedphysbits = ET.SubElement(launch_sec, "reducedPhysBits")
            reducedphysbits.text = "0"
            policy = ET.SubElement(launch_sec, "policy")
            policy.text = "0"
            host_data = ET.SubElement(launch_sec, attrb_host_data)
            host_data.text = node_context.host_data

        devices = ET.SubElement(domain, "devices")
        if len(node_context.passthrough_devices) > 0:
            devices = self.device_pool._add_device_passthrough_xml(
                devices,
                node_context,
            )

        # Provide a PTY-backed ISA UART so guest sees /dev/ttyS0
        # virDomainOpenConsole(devname=None) will attach to this serial by default
        serial = ET.SubElement(devices, "serial")
        serial.attrib["type"] = "pty"

        serial_target = ET.SubElement(serial, "target")
        serial_target.attrib["port"] = "0"

        network_interface = ET.SubElement(devices, "interface")
        network_interface.attrib["type"] = "network"

        network_interface_source = ET.SubElement(network_interface, "source")
        network_interface_source.attrib["network"] = "default"

        network_model = ET.SubElement(network_interface, "model")
        network_model.attrib["type"] = "virtio"

        network_driver = ET.SubElement(network_interface, "driver")
        network_driver.attrib["queues"] = str(vcpu_count)
        network_driver.attrib["iommu"] = "on"

        self._add_virtio_disk_xml(
            node_context,
            devices,
            node_context.os_disk_file_path,
            vcpu_count,
        )

        self._add_virtio_disk_xml(
            node_context,
            devices,
            node_context.cloud_init_file_path,
            vcpu_count,
        )

        xml = ET.tostring(domain, "unicode")
        return xml

    def _get_domain_undefine_flags(self) -> int:
        return 0

    def _create_domain_and_attach_logger(
        self,
        node_context: NodeContext,
    ) -> None:
        assert node_context.domain

        def start_domain_and_attach_logger() -> None:
            domain = cast(Any, node_context.domain)
            assert domain is not None
            if not domain.isActive():
                domain.createWithFlags(0)
            self._attach_console_logger(node_context)

        def retry_start_domain_and_attach_logger() -> None:
            node_context.domain = self._lookup_domain(
                node_context.vm_name,
                self._log,
            )
            start_domain_and_attach_logger()

        self._run_libvirt_operation_with_reconnect(
            operation=start_domain_and_attach_logger,
            retry_operation=retry_start_domain_and_attach_logger,
            operation_description="domain start and console attach",
            vm_name=node_context.vm_name,
            log=self._log,
        )

        if len(node_context.passthrough_devices) > 0:
            # Once libvirt domain is created, check if driver attached to device
            # on the host is vfio-pci for PCI device passthrough to make sure if
            # pass-through for PCI device is happened properly or not
            self.device_pool._verify_device_passthrough_post_boot(
                node_context=node_context,
            )

    def _attach_console_logger(self, node_context: NodeContext) -> None:
        domain = cast(Any, node_context.domain)
        assert domain is not None
        if node_context.console_logger is not None:
            node_context.console_logger.close()
            node_context.console_logger = None

        console_logger = QemuConsoleLogger()
        node_context.console_logger = console_logger
        console_logger.attach(
            domain,
            node_context.console_log_file_path,
        )

    def _delete_node(self, node: Node, log: Logger) -> None:
        """
        Override to preserve console log for every test run (not just failures).
        """
        node_context = get_node_context(node)

        self._capture_node_debug_artifacts(node, node_context, log)

        # Copy console log to node's log directory before closing it
        # This ensures we capture console output for ALL tests, not just failures
        if node_context.console_log_file_path:
            try:
                src = Path(node_context.console_log_file_path)
                if src.exists():
                    dst = node.local_log_path / "ch-console.log"
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    log.debug(
                        f"Copied console log from {src} to {dst} "
                        f"(size: {dst.stat().st_size} bytes)"
                    )
            except Exception as e:
                log.warning(f"Failed to preserve console log for {node.name}: {e}")

        # Call parent implementation to handle cleanup
        super()._delete_node(node, log)

    def _capture_node_debug_artifacts(
        self,
        node: Node,
        node_context: NodeContext,
        log: Logger,
    ) -> None:
        node.local_log_path.mkdir(parents=True, exist_ok=True)
        vm_name = node_context.vm_name
        domain_commands: List[Tuple[str, str, bool]] = [
            (
                "ch-virsh-domain.txt",
                "set -x; "
                f"virsh -c ch:///system domstate {vm_name}; "
                f"virsh -c ch:///system dominfo {vm_name}; "
                f"virsh -c ch:///system domblklist {vm_name} --details; "
                f"virsh -c ch:///system domiflist {vm_name}; "
                f"virsh -c ch:///system dommemstat {vm_name}; "
                f"virsh -c ch:///system domstats {vm_name} --state --cpu-total "
                "--vcpu --balloon --block --interface",
                False,
            ),
            (
                "ch-domain.xml",
                f"virsh -c ch:///system dumpxml {vm_name}",
                False,
            ),
        ]
        host_commands: List[Tuple[str, str, bool]] = [
            (
                "ch-host-processes.txt",
                "set -x; "
                "ps -eo pid,ppid,stat,etime,pcpu,pmem,args "
                "| grep -E 'cloud-hypervisor|libvirt|virt(ch|qemu|log)d' "
                "| grep -v grep || true; "
                "pgrep -af cloud-hypervisor || true; "
                "ss -tanp 2>/dev/null | grep -E 'ssh|:22|cloud-hypervisor|libvirt' "
                "|| true; "
                "free -m || true; "
                "cat /proc/meminfo || true",
                True,
            ),
            (
                "ch-host-kernel.txt",
                "set -x; dmesg -T | tail -n 1000; "
                "journalctl -k --no-pager -n 1000",
                True,
            ),
            (
                "ch-host-libvirt-journal.txt",
                "journalctl -u libvirtd -u virtchd -u virtlogd -u virtqemud "
                "--no-pager -n 1000",
                True,
            ),
            (
                "ch-host-libvirt-files.txt",
                "set -x; "
                "ls -lR /var/log/libvirt /var/run/libvirt 2>&1 || true; "
                "for f in /var/log/libvirt/ch/* /var/log/libvirt/qemu/* "
                "/var/log/libvirt/libvirtd.log; do "
                '[ -f "$f" ] && echo "===== $f =====" && tail -n 500 "$f"; '
                "done",
                True,
            ),
        ]

        for file_name, command, sudo in domain_commands:
            self._capture_host_command_output(
                node=node,
                log=log,
                file_name=file_name,
                command=command,
                sudo=sudo,
            )

        if getattr(self, "_ch_host_debug_artifacts_captured", False):
            return
        setattr(self, "_ch_host_debug_artifacts_captured", True)

        for file_name, command, sudo in host_commands:
            self._capture_host_command_output(
                node=node,
                log=log,
                file_name=file_name,
                command=command,
                sudo=sudo,
            )

    def _capture_host_command_output(
        self,
        node: Node,
        log: Logger,
        file_name: str,
        command: str,
        sudo: bool,
    ) -> None:
        try:
            result = self.host_node.execute(
                command,
                shell=True,
                sudo=sudo,
                timeout=120,
                expected_exit_code=None,
                no_error_log=True,
            )
            output_path = node.local_log_path / file_name
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(f"$ {command}\n")
                f.write(f"exit_code: {result.exit_code}\n\n")
                f.write("===== stdout =====\n")
                f.write(result.stdout)
                f.write("\n===== stderr =====\n")
                f.write(result.stderr)
        except Exception as e:
            log.warning(f"Failed to capture CH debug artifact {file_name}: {e}")

    # Create the OS disk.
    def _create_node_os_disk(
        self, environment: Environment, log: Logger, node: Node
    ) -> None:
        node_context = get_node_context(node)

        if node_context.os_disk_base_file_fmt == DiskImageFormat.QCOW2:
            self.host_node.tools[QemuImg].convert(
                "qcow2",
                node_context.os_disk_base_file_path,
                "raw",
                node_context.os_disk_file_path,
            )
        else:
            self.host_node.execute(
                f"cp {node_context.os_disk_base_file_path}"
                f" {node_context.os_disk_file_path}",
                expected_exit_code=0,
                expected_exit_code_failure_message="Failed to copy os disk image",
            )

        if node_context.os_disk_img_resize_gib:
            self.host_node.tools[QemuImg].resize(
                src_file=node_context.os_disk_file_path,
                size_gib=node_context.os_disk_img_resize_gib,
            )

    def _get_vmm_version(self) -> str:
        result = "Unknown"
        if self.host_node:
            output = self.host_node.execute(
                "cloud-hypervisor --version",
                shell=True,
            ).stdout
            output = filter_ansi_escape(output)
            match = re.search(CH_VERSION_PATTERN, output.strip())
            if match:
                result = match.group("ch_version")
        return result
