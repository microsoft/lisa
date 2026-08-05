# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
import os
import re
import secrets
import shutil
import xml.etree.ElementTree as ET  # noqa: N817
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Tuple, Type, cast

import libvirt

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
from lisa.tools import Chown, Cp, Ls, QemuImg, Whoami
from lisa.util import LisaException, SkippedException, parse_version
from lisa.util.logger import Logger, filter_ansi_escape

from .. import CLOUD_HYPERVISOR
from .console_logger import QemuConsoleLogger
from .schema import BaseLibvirtNodeSchema, CloudHypervisorNodeSchema, DiskImageFormat

CH_VERSION_PATTERN = re.compile(r"cloud-hypervisor (?P<ch_version>.+)")

# Directory where the libvirt Cloud Hypervisor (ch) driver writes the per-domain
# CH log/stderr. libvirt removes/overwrites these when it cleans up a domain that
# exits during start, so they must be captured before that cleanup runs.
CH_DOMAIN_LOG_DIR = PurePosixPath("/var/log/libvirt/ch")

# Artifact name prefixes for diagnostics preserved into the LISA per-node log path.
CH_DOMAIN_LOG_ARTIFACT_PREFIX = "ch-domain-"
DOMAIN_START_ERROR_ARTIFACT_PREFIX = "domain-start-error-"
DOMAIN_XML_ARTIFACT_PREFIX = "domain-"
DOMAIN_START_EVIDENCE_ARTIFACT_PREFIX = "domain-start-evidence-"

# Expected exceptions while collecting best-effort diagnostics. These are caught
# and logged so that diagnostic collection never masks the original libvirt error,
# while genuine programming errors (e.g. AttributeError/TypeError) still surface.
# AssertionError is included because LISA tools (e.g. Cp/Chown) raise it to signal
# an underlying host command failure.
_DIAGNOSTIC_EXCEPTIONS = (
    OSError,
    AssertionError,
    libvirt.libvirtError,
    LisaException,
)

# Exact captured Cloud Hypervisor signature indicating the guest VM configuration
# is not supported on this host. Only a "VmCreate" failure paired with an
# EINVAL / "Invalid argument" / "os error 22" on the same line is treated as
# unsupported; any other deployment error keeps its normal failure behavior.
CH_UNSUPPORTED_VMCREATE_PATTERN = re.compile(
    r"VmCreate\b[^\n]*?(?:invalid argument|os error 22|einval)",
    re.IGNORECASE,
)


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

        try:
            self._run_libvirt_operation_with_reconnect(
                operation=start_domain_and_attach_logger,
                retry_operation=retry_start_domain_and_attach_logger,
                operation_description="domain start and console attach",
                vm_name=node_context.vm_name,
                log=self._log,
            )
        except libvirt.libvirtError as ex:
            # The domain may have exited during createWithFlags before it ever
            # became active. Only a genuine start failure (domain inactive) is
            # eligible for diagnostics/skip classification; a failure raised
            # after the domain became active (e.g. console attach/openConsole)
            # is re-raised unchanged.
            self._handle_domain_start_failure(node_context, ex)
            raise

        if len(node_context.passthrough_devices) > 0:
            # Once libvirt domain is created, check if driver attached to device
            # on the host is vfio-pci for PCI device passthrough to make sure if
            # pass-through for PCI device is happened properly or not
            self.device_pool._verify_device_passthrough_post_boot(
                node_context=node_context,
            )

    def _is_domain_active(self, node_context: NodeContext) -> bool:
        domain = node_context.domain
        if domain is None:
            return False
        try:
            return bool(cast(Any, domain).isActive())
        except libvirt.libvirtError:
            return False

    def _handle_domain_start_failure(
        self,
        node_context: NodeContext,
        error: libvirt.libvirtError,
    ) -> None:
        """
        Preserve domain-start diagnostics for artifact publication and, only for
        a Confidential VM (CVM) guest whose captured Cloud Hypervisor log matches
        the exact unsupported-VmCreate signature, raise SkippedException.
        Otherwise return so the original deployment error keeps its normal
        failure behavior.
        """
        if self._is_domain_active(node_context):
            # The domain is active, so the failure originated from console
            # attach/openConsole rather than starting the guest. This is not a
            # start failure and must not be classified as unsupported.
            self._log.debug(
                f"Domain {node_context.vm_name} is active; treating '{error}' as "
                "a console-attach failure, not a start failure."
            )
            return

        try:
            (
                artifacts,
                evidence,
                ch_log_content,
            ) = self._preserve_domain_start_diagnostics(node_context, error, self._log)
        except _DIAGNOSTIC_EXCEPTIONS as ex:
            # Diagnostic collection must never mask the original libvirt error.
            self._log.warning(
                f"Failed to collect domain-start diagnostics for "
                f"{node_context.vm_name}: {ex}"
            )
            return

        # Only a Confidential VM guest with the exact CH VmCreate/EINVAL signature
        # is classified as an unsupported configuration.
        if node_context.guest_vm_type is not GuestVmType.ConfidentialVM:
            return

        match = CH_UNSUPPORTED_VMCREATE_PATTERN.search(ch_log_content)
        if not match:
            return

        signature = match.group(0).strip()
        artifact_names = (
            ", ".join(sorted(path.name for path in artifacts.values())) or "<none>"
        )
        evidence_summary = (
            "; ".join(f"{key}={value}" for key, value in evidence.items())
            or "<unavailable>"
        )
        raise SkippedException(
            "Cloud Hypervisor reported the Confidential VM (CVM) guest "
            "configuration is not supported on this host (captured signature: "
            f"'{signature}'). Runtime evidence: {evidence_summary}. Preserved "
            f"artifacts: {artifact_names}."
        ) from error

    def _preserve_domain_start_diagnostics(
        self,
        node_context: NodeContext,
        error: Exception,
        log: Logger,
    ) -> Tuple[Dict[str, Path], Dict[str, str], str]:
        """
        Preserve auditable domain-start diagnostics into the node's LISA log
        directory before libvirt cleanup removes them. Collects, best-effort:
        the per-domain Cloud Hypervisor log/stderr, the domain XML, the
        domain-start error, and runtime evidence (CH, kernel and libvirt
        versions). Works even when the domain never became active and no console
        is available.

        Returns the map of preserved artifact name -> local path, the collected
        runtime evidence, and the CH log text content (used to classify the
        failure).
        """
        vm_name = node_context.vm_name
        artifacts: Dict[str, Path] = {}
        evidence: Dict[str, str] = {}
        ch_log_content = ""

        # Derive the node's LISA log directory from the console log path so the
        # diagnostics land next to the other per-node artifacts (e.g.
        # ch-console.log). Fall back to the host node's log path if unset.
        if node_context.console_log_file_path:
            local_log_dir = Path(node_context.console_log_file_path).parent
        else:
            local_log_dir = self.host_node.local_log_path

        try:
            local_log_dir.mkdir(parents=True, exist_ok=True)
        except _DIAGNOSTIC_EXCEPTIONS as e:
            log.warning(f"Failed to create log directory {local_log_dir}: {e}")
            return artifacts, evidence, ch_log_content

        # Collect runtime evidence where safely obtainable.
        evidence = self._collect_runtime_evidence(log)

        # Record the domain-start error itself, even if the CH log or XML are gone.
        start_error_path = (
            local_log_dir / f"{DOMAIN_START_ERROR_ARTIFACT_PREFIX}{vm_name}.log"
        )
        try:
            start_error_path.write_text(
                f"Domain '{vm_name}' failed to start during createWithFlags "
                f"before becoming active:\n{error}\n",
                encoding="utf-8",
            )
            artifacts["start_error"] = start_error_path
        except _DIAGNOSTIC_EXCEPTIONS as e:
            log.warning(f"Failed to write domain-start error log: {e}")

        # Record the collected runtime evidence as an auditable artifact.
        evidence_path = (
            local_log_dir / f"{DOMAIN_START_EVIDENCE_ARTIFACT_PREFIX}{vm_name}.txt"
        )
        try:
            evidence_path.write_text(
                "\n".join(f"{key}: {value}" for key, value in evidence.items()) + "\n",
                encoding="utf-8",
            )
            artifacts["evidence"] = evidence_path
        except _DIAGNOSTIC_EXCEPTIONS as e:
            log.warning(f"Failed to write domain-start evidence log: {e}")

        # Preserve the domain XML so the exact configuration is auditable.
        self._preserve_domain_xml(node_context, local_log_dir, artifacts, log)

        # Preserve the per-domain CH log/stderr before libvirt removes it.
        ch_log_content = self._preserve_ch_domain_log(
            node_context, local_log_dir, artifacts, log
        )

        return artifacts, evidence, ch_log_content

    def _collect_runtime_evidence(self, log: Logger) -> Dict[str, str]:
        evidence: Dict[str, str] = {}
        getters = (
            ("cloud_hypervisor_version", self._get_vmm_version),
            ("kernel_version", self._get_host_kernel_version),
            ("libvirt_version", self._get_libvirt_version),
        )
        for key, getter in getters:
            try:
                value = getter()
            except _DIAGNOSTIC_EXCEPTIONS + (IndexError, ValueError) as e:
                # IndexError/ValueError guard against empty/malformed version
                # output while parsing so evidence collection never masks the
                # original libvirt failure.
                log.warning(f"Failed to collect {key}: {e}")
                value = "<unavailable>"
            evidence[key] = value or "<unknown>"
        return evidence

    def _preserve_domain_xml(
        self,
        node_context: NodeContext,
        local_log_dir: Path,
        artifacts: Dict[str, Path],
        log: Logger,
    ) -> None:
        domain = node_context.domain
        if domain is None:
            return
        try:
            xml_text = cast(str, cast(Any, domain).XMLDesc(0))
        except libvirt.libvirtError as e:
            log.warning(f"Failed to read domain XML for {node_context.vm_name}: {e}")
            return
        if not xml_text:
            return
        xml_path = (
            local_log_dir / f"{DOMAIN_XML_ARTIFACT_PREFIX}{node_context.vm_name}.xml"
        )
        try:
            xml_path.write_text(xml_text, encoding="utf-8")
            artifacts["domain_xml"] = xml_path
        except _DIAGNOSTIC_EXCEPTIONS as e:
            log.warning(f"Failed to write domain XML artifact: {e}")

    def _preserve_ch_domain_log(
        self,
        node_context: NodeContext,
        local_log_dir: Path,
        artifacts: Dict[str, Path],
        log: Logger,
    ) -> str:
        vm_name = node_context.vm_name
        ch_log_content = ""
        host_ch_log = CH_DOMAIN_LOG_DIR / f"{vm_name}.log"
        try:
            if not self.host_node.tools[Ls].path_exists(str(host_ch_log), sudo=True):
                log.debug(f"No CH domain log found at {host_ch_log} for {vm_name}")
                return ch_log_content

            dst = local_log_dir / f"{CH_DOMAIN_LOG_ARTIFACT_PREFIX}{vm_name}.log"
            # Stage the root-owned CH log into the host working path with sudo,
            # fix ownership, then copy back so this works for both local and
            # remote hosts (same pattern as _capture_libvirt_logs).
            temp_path = self.host_node.working_path / f"{vm_name}-ch.log"
            try:
                self.host_node.tools[Cp].copy(host_ch_log, temp_path, sudo=True)
                user = self.host_node.tools[Whoami].get_username()
                self.host_node.tools[Chown].change_owner(temp_path, user)
                self.host_node.shell.copy_back(temp_path, dst)
                artifacts["ch_log"] = dst
                ch_log_content = dst.read_text(encoding="utf-8", errors="replace")
                log.debug(f"Preserved CH domain log for {vm_name} to {dst}")
            finally:
                # Remove the staged temp copy from the host working path.
                try:
                    self.host_node.shell.remove(temp_path)
                except _DIAGNOSTIC_EXCEPTIONS as e:
                    log.warning(f"Failed to remove staged CH log temp {temp_path}: {e}")
        except _DIAGNOSTIC_EXCEPTIONS as e:
            log.warning(f"Failed to preserve CH domain log for {vm_name}: {e}")

        return ch_log_content

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
