# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
import os
import re
import secrets
import shutil
import xml.etree.ElementTree as ET  # noqa: N817
from pathlib import Path
from typing import List, Type

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
        os_cmdline = ET.SubElement(os, "cmdline")
        os_cmdline.text = "console=ttyS0,115200 ignore_loglevel printk.time=1"
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
        attach_path = node_context.console_log_file_path
        self._log.info(
            f"[DEBUG ATTACH] VM: {node_context.vm_name}"
        )
        self._log.info(
            f"[DEBUG ATTACH] Console log path: {attach_path}"
        )
        self._log.info(
            f"[DEBUG ATTACH] Resolved path: {Path(attach_path).resolve()}"
        )
        
        node_context.domain.createWithFlags(0)

        node_context.console_logger = QemuConsoleLogger()
        try:
            node_context.console_logger.attach(
                node_context.domain, attach_path
            )
            self._log.info(
                f"[DEBUG ATTACH] Console logger attached successfully"
            )
            
            # IMMEDIATE size check - baseline should be 0
            log_path = Path(attach_path)
            if log_path.exists():
                size = log_path.stat().st_size
                self._log.info(
                    f"[DEBUG ATTACH] File exists immediately after attach, size: {size} bytes (baseline)"
                )
            else:
                self._log.warning(
                    f"[DEBUG ATTACH] File NOT FOUND after attachment: {log_path}"
                )
            
            # Wait a moment for initial boot messages, then check again
            import time
            time.sleep(2)
            if log_path.exists():
                size_after = log_path.stat().st_size
                logger_stats = node_context.console_logger.get_stats()
                self._log.info(
                    f"[DEBUG ATTACH] Size after 2s: {size_after} bytes, "
                    f"logger reports {logger_stats['bytes_written']} bytes written"
                )
                if size_after == 0:
                    self._log.warning(
                        f"[DEBUG ATTACH] Still 0 bytes after 2s - VM may not be outputting to serial console"
                    )
            
        except Exception as e:
            self._log.error(
                f"[DEBUG ATTACH] Failed to attach console logger: {e}", exc_info=True
            )

        if len(node_context.passthrough_devices) > 0:
            # Once libvirt domain is created, check if driver attached to device
            # on the host is vfio-pci for PCI device passthrough to make sure if
            # pass-through for PCI device is happened properly or not
            self.device_pool._verify_device_passthrough_post_boot(
                node_context=node_context,
            )

    def _delete_node(self, node: Node, log: Logger) -> None:
        """
        Override to preserve console log for every test run (not just failures).
        """
        node_context = get_node_context(node)

        # Copy console log to node's log directory before closing it
        # This ensures we capture console output for ALL tests, not just failures
        if node_context.console_log_file_path:
            try:
                src = Path(node_context.console_log_file_path)
                log.info(
                    f"[DEBUG DELETE] VM: {node_context.vm_name}"
                )
                log.info(
                    f"[DEBUG DELETE] Console log path from context: {node_context.console_log_file_path}"
                )
                log.info(
                    f"[DEBUG DELETE] Resolved path: {src.resolve()}"
                )
                
                # Get logger stats before closing
                if node_context.console_logger:
                    logger_stats = node_context.console_logger.get_stats()
                    log.info(
                        f"[DEBUG DELETE] Logger stats: "
                        f"path={logger_stats['log_file_path']}, "
                        f"bytes_written={logger_stats['bytes_written']}, "
                        f"completed={logger_stats['stream_completed']}"
                    )
                    
                    # Check if paths match
                    if logger_stats['log_file_path'] != str(src):
                        log.error(
                            f"[DEBUG DELETE] PATH MISMATCH! "
                            f"Logger wrote to: {logger_stats['log_file_path']}, "
                            f"But we're trying to copy from: {src}"
                        )
                
                log.info(
                    f"[DEBUG DELETE] File exists: {src.exists()}"
                )
                
                if src.exists():
                    src_size = src.stat().st_size
                    log.info(f"[DEBUG DELETE] Source console log size: {src_size} bytes")
                    
                    # Also check if there's a file at the actual location
                    parent_dir = src.parent
                    log.info(f"[DEBUG DELETE] Parent directory: {parent_dir}")
                    if parent_dir.exists():
                        all_logs = list(parent_dir.glob("*console*.log"))
                        log.info(f"[DEBUG DELETE] All console logs in directory:")
                        for f in all_logs:
                            log.info(f"[DEBUG DELETE]   - {f.name}: {f.stat().st_size} bytes")
                    
                    dst = node.local_log_path / "ch-console.log"
                    log.info(f"[DEBUG DELETE] Destination path: {dst}")
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    dst_size = dst.stat().st_size
                    log.info(
                        f"[DEBUG DELETE] Copied console log (src: {src_size} bytes, dst: {dst_size} bytes)"
                    )
                    
                    if src_size == 0:
                        log.warning(
                            f"[DEBUG DELETE] Console log file is EMPTY (0 bytes). "
                            f"Logger reports {logger_stats['bytes_written'] if node_context.console_logger else 'N/A'} bytes written. "
                            f"This suggests either: 1) VM not outputting to serial, or 2) logger stream not receiving data."
                        )
                else:
                    log.warning(
                        f"[DEBUG DELETE] Console log file does not exist: {src}"
                    )
            except Exception as e:
                log.warning(f"Failed to preserve console log for {node.name}: {e}", exc_info=True)

        # Call parent implementation to handle cleanup
        super()._delete_node(node, log)

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
