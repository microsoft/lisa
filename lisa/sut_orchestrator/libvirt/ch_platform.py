# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
import os
import re
import secrets
import shlex
import shutil
import time
import xml.etree.ElementTree as ET  # noqa: N817
from pathlib import Path
from typing import Any, List, Type, cast

from lisa import schema
from lisa.environment import Environment
from lisa.feature import Feature
from lisa.node import Node
from lisa.sut_orchestrator.libvirt.context import (
    GuestVmType,
    NodeContext,
    get_environment_context,
    get_node_context,
)
from lisa.sut_orchestrator.libvirt.platform import (
    BaseLibvirtPlatform,
    GuestBootTimeoutError,
)
from lisa.tools import Ls, QemuImg
from lisa.util import LisaException, parse_version
from lisa.util.logger import Logger, filter_ansi_escape
from lisa.util.process import ExecutableResult

from .. import CLOUD_HYPERVISOR
from .console_logger import QemuConsoleLogger
from .schema import BaseLibvirtNodeSchema, CloudHypervisorNodeSchema, DiskImageFormat

CH_VERSION_PATTERN = re.compile(r"cloud-hypervisor (?P<ch_version>.+)")
CH_STATE_DIRECTORY = "/run/libvirt/ch"
DOMAIN_STOP_TIMEOUT_SECONDS = 30
DOMAIN_STOP_KILL_TIMEOUT_SECONDS = 5
DOMAIN_PROCESS_EXIT_TIMEOUT_SECONDS = 15
CONSOLE_CLOSE_TIMEOUT_SECONDS = 15
PASSTHROUGH_BOOT_RETRY_COUNT = 4


class CloudHypervisorDomainStopError(LisaException):
    pass


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
        node_runbook = node.capability.get_extended_runbook(
            CloudHypervisorNodeSchema, CLOUD_HYPERVISOR
        )
        network_queue_count = (
            node_runbook.network_queue_count
            if node_runbook.network_queue_count is not None
            else vcpu_count
        )
        disk_queue_count = (
            node_runbook.disk_queue_count
            if node_runbook.disk_queue_count is not None
            else vcpu_count
        )

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
        network_driver.attrib["queues"] = str(network_queue_count)
        network_driver.attrib["iommu"] = "on" if node_runbook.enable_iommu else "off"

        self._add_virtio_disk_xml(
            node_context,
            devices,
            node_context.os_disk_file_path,
            disk_queue_count,
        )

        self._add_virtio_disk_xml(
            node_context,
            devices,
            node_context.cloud_init_file_path,
            disk_queue_count,
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

    def _stop_domain(self, node_context: NodeContext, log: Logger) -> None:
        if not node_context.passthrough_devices:
            super()._stop_domain(node_context, log)
            return

        if node_context.domain_stop_failed is True:
            raise CloudHypervisorDomainStopError(
                f"Cloud Hypervisor domain {node_context.vm_name} previously "
                "failed its bounded stop and cannot be safely reused."
            )

        assert node_context.domain is not None
        process_id = self._find_domain_process_id(node_context.vm_name)

        stop_result = self._run_bounded_domain_stop(node_context.vm_name)
        if self._domain_stop_succeeded(stop_result):
            node_context.domain_stop_failed = False
            return
        if not self._domain_stop_timed_out(stop_result):
            raise CloudHypervisorDomainStopError(
                self._domain_stop_error_message(node_context.vm_name, stop_result)
            )

        log.warning(
            f"Timed out stopping Cloud Hypervisor domain {node_context.vm_name}; "
            f"capturing diagnostics and targeting only process {process_id}"
        )
        self._capture_domain_process_diagnostics(
            node_context.vm_name,
            process_id,
            log,
        )
        if process_id <= 1:
            node_context.domain_stop_failed = True
            raise CloudHypervisorDomainStopError(
                f"Cloud Hypervisor domain {node_context.vm_name} did not stop and "
                f"libvirt returned invalid process ID {process_id}."
            )

        kill_result = self._force_kill_domain_process(
            node_context.vm_name,
            process_id,
        )
        if kill_result.exit_code != 0:
            if kill_result.exit_code == 124:
                self._capture_domain_process_diagnostics(
                    node_context.vm_name,
                    process_id,
                    log,
                )
            node_context.domain_stop_failed = True
            raise CloudHypervisorDomainStopError(
                f"Exact-process termination failed for Cloud Hypervisor domain "
                f"{node_context.vm_name}, process {process_id} "
                f"(exit code {kill_result.exit_code})."
            )

        # Let the timed-out libvirt destroy job reap the process and release its
        # host devices before checking the domain state again.
        time.sleep(1)
        cleanup_result = self._run_bounded_domain_stop(node_context.vm_name)
        if not self._domain_stop_succeeded(cleanup_result):
            node_context.domain_stop_failed = True
            raise CloudHypervisorDomainStopError(
                self._domain_stop_error_message(
                    node_context.vm_name,
                    cleanup_result,
                )
            )
        node_context.domain_stop_failed = False
        node_context.domain = self._lookup_domain(node_context.vm_name, log)

    def _find_domain_process_id(self, vm_name: str) -> int:
        event_monitor_argument = shlex.quote(
            f"path={CH_STATE_DIRECTORY}/{vm_name}-event-monitor-fifo"
        )
        command = (
            "for cmdline in /proc/[0-9]*/cmdline; do "
            '[ -r "$cmdline" ] || continue; '
            f"tr '\\0' '\\n' < \"$cmdline\" "
            f"| grep -Fqx -- {event_monitor_argument} || continue; "
            'pid="${cmdline#/proc/}"; pid="${pid%/cmdline}"; '
            'executable="$(readlink -f "/proc/$pid/exe")" || continue; '
            '[ "${executable##*/}" = "cloud-hypervisor" ] || continue; '
            'printf "%s\\n" "$pid"; '
            "done"
        )
        result = self.host_node.execute(
            command,
            sudo=True,
            shell=True,
            timeout=15,
        )
        process_ids = [
            int(line) for line in result.stdout.splitlines() if line.strip().isdigit()
        ]
        if len(process_ids) > 1:
            raise CloudHypervisorDomainStopError(
                f"Found multiple Cloud Hypervisor processes for domain {vm_name}: "
                f"{process_ids}"
            )
        return process_ids[0] if process_ids else -1

    def _run_bounded_domain_stop(self, vm_name: str) -> ExecutableResult:
        command = (
            "LC_ALL=C timeout "
            f"--kill-after={DOMAIN_STOP_KILL_TIMEOUT_SECONDS}s "
            f"{DOMAIN_STOP_TIMEOUT_SECONDS}s "
            "virsh --connect ch:///system destroy "
            f"{shlex.quote(vm_name)}"
        )
        return self.host_node.execute(
            command,
            sudo=True,
            shell=True,
            timeout=(
                DOMAIN_STOP_TIMEOUT_SECONDS + DOMAIN_STOP_KILL_TIMEOUT_SECONDS + 10
            ),
        )

    def _force_kill_domain_process(
        self,
        vm_name: str,
        process_id: int,
    ) -> ExecutableResult:
        event_monitor_argument = shlex.quote(
            f"path={CH_STATE_DIRECTORY}/{vm_name}-event-monitor-fifo"
        )
        command = (
            f"if [ ! -d /proc/{process_id} ]; then exit 0; fi; "
            f'executable="$(readlink -f /proc/{process_id}/exe)" || exit 126; '
            '[ "${executable##*/}" = "cloud-hypervisor" ] || exit 125; '
            f"tr '\\0' '\\n' < /proc/{process_id}/cmdline "
            f"| grep -Fqx -- {event_monitor_argument} || exit 125; "
            f"kill -KILL {process_id}; "
            f"remaining={DOMAIN_PROCESS_EXIT_TIMEOUT_SECONDS}; "
            f"while kill -0 {process_id} 2>/dev/null; do "
            '[ "$remaining" -le 0 ] && exit 124; '
            "remaining=$((remaining - 1)); "
            "sleep 1; "
            "done"
        )
        return self.host_node.execute(
            command,
            sudo=True,
            shell=True,
            timeout=DOMAIN_PROCESS_EXIT_TIMEOUT_SECONDS + 10,
        )

    def _capture_domain_process_diagnostics(
        self,
        vm_name: str,
        process_id: int,
        log: Logger,
    ) -> None:
        diagnostic_header = shlex.quote(f"domain={vm_name} pid={process_id}")
        command = (
            f"if [ ! -d /proc/{process_id} ]; then "
            f"echo 'process {process_id} no longer exists'; exit 0; fi; "
            f"echo {diagnostic_header}; "
            f"grep -E '^(Name|State|Pid|PPid|Threads):' /proc/{process_id}/status "
            "|| true; "
            f"ps -L -p {process_id} -o pid=,tid=,stat=,wchan:32=,comm= || true; "
            f"for task in /proc/{process_id}/task/[0-9]*; do "
            'tid="${task##*/}"; '
            "printf '\\nthread=%s wchan=' \"$tid\"; "
            'cat "$task/wchan" 2>/dev/null || true; '
            'cat "$task/stack" 2>/dev/null || true; '
            "done; "
            "echo 'recent mshv/vfio kernel messages:'; "
            "dmesg | grep -Ei 'mshv|vfio|iommu|cloud.?hypervisor' "
            "| tail -n 80 || true"
        )
        process = self.host_node.execute_async(
            command,
            sudo=True,
            shell=True,
            no_error_log=True,
        )
        result = process.wait_result(timeout=30, raise_on_timeout=False)
        output = "\n".join(
            part for part in (result.stdout, result.stderr) if part.strip()
        )
        if len(output) > 32768:
            output = output[-32768:]
        log.warning(
            f"Cloud Hypervisor stop diagnostics for {vm_name}:\n"
            f"{output or '<no diagnostics returned>'}"
        )

    @staticmethod
    def _domain_stop_succeeded(result: ExecutableResult) -> bool:
        output = f"{result.stdout}\n{result.stderr}".lower()
        return result.exit_code == 0 or any(
            message in output
            for message in (
                "domain is not running",
                "domain is not active",
            )
        )

    @staticmethod
    def _domain_stop_timed_out(result: ExecutableResult) -> bool:
        return result.is_timeout or result.exit_code in (124, 137, 143)

    @staticmethod
    def _domain_stop_error_message(
        vm_name: str,
        result: ExecutableResult,
    ) -> str:
        output = (result.stderr or result.stdout).strip()
        if len(output) > 2048:
            output = output[-2048:]
        return (
            f"Failed to stop Cloud Hypervisor domain {vm_name} with exit code "
            f"{result.exit_code}: {output or '<no command output>'}"
        )

    def restart_domain_and_attach_logger(self, node: Node) -> None:
        node_context = get_node_context(node)
        domain = cast(Any, node_context.domain)
        assert domain is not None

        if domain.isActive():
            return

        if node_context.console_logger is not None:
            if not node_context.console_logger.wait_for_close(
                CONSOLE_CLOSE_TIMEOUT_SECONDS
            ) and not node_context.console_logger.close(
                timeout=CONSOLE_CLOSE_TIMEOUT_SECONDS
            ):
                raise CloudHypervisorDomainStopError(
                    f"Console stream for {node_context.vm_name} did not close "
                    "after the Cloud Hypervisor domain stopped."
                )
            node_context.console_logger = None

        self._create_domain_and_attach_logger(node_context)

    def _get_node_ip_address(
        self,
        environment: Environment,
        log: Logger,
        node: Node,
        timeout: float,
    ) -> str:
        node_context = get_node_context(node)
        restart_count = 0
        current_timeout = timeout
        while True:
            try:
                return super()._get_node_ip_address(
                    environment,
                    log,
                    node,
                    current_timeout,
                )
            except GuestBootTimeoutError:
                if (
                    not node_context.passthrough_devices
                    or restart_count >= PASSTHROUGH_BOOT_RETRY_COUNT
                ):
                    raise

            restart_count += 1
            log.warning(
                f"VM {node_context.vm_name} did not acquire an IP address before "
                "the boot timeout; restarting the Cloud Hypervisor passthrough "
                f"domain (attempt {restart_count} of "
                f"{PASSTHROUGH_BOOT_RETRY_COUNT})"
            )
            self._stop_domain(node_context, log)
            self.restart_domain_and_attach_logger(node)
            current_timeout = (
                time.time() + get_environment_context(environment).network_boot_timeout
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
