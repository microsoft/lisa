# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import shlex
from dataclasses import dataclass, field, replace
from pathlib import PurePath
from typing import List, Optional

from lisa.executable import Tool
from lisa.util import LisaException

VERSION_PATTERN = re.compile(r"openvmm(?:\.exe)?\s+(?P<version>.+)")

OPENVMM_NETWORK_BACKEND_CONSOMME = "consomme"
OPENVMM_DEFAULT_SCSI_CONTROLLER = "lisa_scsi0"
OPENVMM_DISK_DEVICE_SCSI = "scsi"
OPENVMM_DISK_DEVICE_VIRTIO_BLK = "virtio-blk"
OPENVMM_IOMMU_AMD = "amd-iommu"
OPENVMM_IOMMU_INTEL = "intel-vtd"
OPENVMM_IOMMU_NONE = "none"
OPENVMM_NETWORK_DEVICE_SYNTHETIC = "synthetic"
OPENVMM_NETWORK_DEVICE_VIRTIO = "virtio"
OPENVMM_SMT_AUTO = "auto"
OPENVMM_SMT_FORCE = "force"
OPENVMM_SMT_OFF = "off"
OPENVMM_VIRTIO_ROOT_COMPLEX = "lisa_virtio_rc0"
OPENVMM_VIRTIO_DISK_PORT = "lisa_virtio_disk"
OPENVMM_VIRTIO_NETWORK_PORT = "lisa_virtio_net"
OPENVMM_GUEST_RESET_EXIT_CODE = 42
OPENVMM_MAX_GUEST_RESET_RESTARTS = 8

_COMMAND_NOT_FOUND_MARKERS = (
    "command not found",
    "no such file or directory",
    "is not recognized as an internal or external command",
)


def _new_str_list() -> List[str]:
    return []


def is_missing_command_output(output: str) -> bool:
    normalized_output = output.lower()
    return any(marker in normalized_output for marker in _COMMAND_NOT_FOUND_MARKERS)


@dataclass
class OpenVmmLaunchConfig:
    uefi_firmware_path: str
    with_hv: bool = True
    hypervisor: str = "mshv"
    vmgs_path: str = ""
    create_vmgs: bool = False
    exit_on_guest_reset: bool = False
    auto_restart_on_guest_reset: bool = False
    guest_reset_exit_code: int = OPENVMM_GUEST_RESET_EXIT_CODE
    max_guest_reset_restarts: int = OPENVMM_MAX_GUEST_RESET_RESTARTS
    disk_img_path: str = ""
    disk_device: str = OPENVMM_DISK_DEVICE_SCSI
    iommu: str = OPENVMM_IOMMU_NONE
    dvd_disk_paths: List[str] = field(default_factory=_new_str_list)
    processors: int = 1
    vps_per_socket: Optional[int] = None
    smt: str = ""
    memory_mb: int = 1024
    network_mode: str = "user"
    network_device: str = OPENVMM_NETWORK_DEVICE_SYNTHETIC
    network_queue_count: Optional[int] = None
    tap_name: str = ""
    network_cidr: str = ""
    serial_mode: str = "file"
    serial_path: str = ""
    extra_args: List[str] = field(default_factory=_new_str_list)
    stdout_path: str = ""
    stderr_path: str = ""
    use_pci_devices: bool = False


class OpenVmm(Tool):
    @property
    def command(self) -> str:
        return self._command

    @property
    def can_install(self) -> bool:
        return False

    def _initialize(self, *args: object, **kwargs: object) -> None:
        self._command = "openvmm"

    def set_binary_path(self, path: str) -> None:
        self._command = path or "openvmm"
        self._exists = None

    def get_version(self) -> str:
        attempts = [
            f"{shlex.quote(self.command)} --version",
            f"{shlex.quote(self.command)} --help",
        ]
        for attempt in attempts:
            result = self.node.execute(
                attempt,
                shell=True,
                no_info_log=True,
                no_error_log=True,
                expected_exit_code=None,
            )
            stdout_output = result.stdout.strip()
            stderr_output = result.stderr.strip()
            output = stdout_output or stderr_output
            if not output:
                continue
            normalized_output = output.lower()
            if is_missing_command_output(output):
                continue
            match = VERSION_PATTERN.search(output)
            if match:
                return match.group("version").strip()
            if result.exit_code == 0 or ("usage:" in normalized_output):
                return output.splitlines()[0].strip()
        return "Unknown"

    def build_command(self, config: OpenVmmLaunchConfig) -> str:
        args: List[str] = [self.command]
        if config.with_hv:
            args.append("--hv")
        if config.hypervisor:
            args.extend(["--hypervisor", config.hypervisor])
        self._validate_processor_topology(config)
        args.extend(["--processors", str(config.processors)])
        if config.vps_per_socket is not None:
            args.extend(["--vps-per-socket", str(config.vps_per_socket)])
        if config.smt:
            args.extend(["--smt", config.smt])
        args.extend(["--memory", f"{config.memory_mb}MB"])

        if not config.uefi_firmware_path:
            raise LisaException("uefi_firmware_path must be provided for UEFI boot")
        args.append("--uefi")
        args.extend(["--uefi-firmware", config.uefi_firmware_path])
        args.extend(["--uefi-console-mode", "com1"])
        if config.vmgs_path:
            vmgs_disk = f"file:{config.vmgs_path}"
            if config.create_vmgs:
                vmgs_disk = f"{vmgs_disk};create=VMGS_DEFAULT"
            args.extend(
                [
                    "--vmgs",
                    f"{vmgs_disk},fmt-on-fail",
                ]
            )
        if config.auto_restart_on_guest_reset:
            if not 0 <= config.guest_reset_exit_code <= 255:
                raise LisaException("guest_reset_exit_code must be between 0 and 255")
            if config.max_guest_reset_restarts <= 0:
                raise LisaException("max_guest_reset_restarts must be greater than 0")
            args.extend(
                [
                    "--guest-reset-action",
                    f"exit:{config.guest_reset_exit_code}",
                    "--guest-shutdown-action",
                    "exit",
                ]
            )
        elif config.exit_on_guest_reset:
            args.extend(["--guest-reset-action", "exit"])

        network_backend = self._get_network_backend(config)

        if config.use_pci_devices:
            root_complex = "rc0"
            root_disk_port = "disk"
            network_port = "net"
            dvd_ports = [f"dvd{index}" for index, _ in enumerate(config.dvd_disk_paths)]

            args.append("--no-vmbus")
            args.extend(["--pcie-root-complex", root_complex])
            if config.disk_img_path:
                args.extend(["--pcie-root-port", f"{root_complex}:{root_disk_port}"])
            for dvd_port in dvd_ports:
                args.extend(["--pcie-root-port", f"{root_complex}:{dvd_port}"])
            args.extend(["--pcie-root-port", f"{root_complex}:{network_port}"])

            if config.disk_img_path:
                args.extend(
                    [
                        "--nvme-pci",
                        f"id=nvme-disk,pcie_port={root_disk_port}",
                        "--disk",
                        f"file:{config.disk_img_path},on=nvme-disk",
                    ]
                )
            for dvd_disk_path, dvd_port in zip(config.dvd_disk_paths, dvd_ports):
                args.extend(
                    [
                        "--virtio-blk",
                        f"file:{dvd_disk_path},ro,pcie_port={dvd_port}",
                    ]
                )
            args.extend(
                [
                    "--virtio-net",
                    f"pcie_port={network_port}:{network_backend}",
                    "--default-boot-always-attempt",
                ]
            )
        else:
            self._validate_device_types(config)
            self._add_pcie_args(args, config)
            self._add_disk_args(args, config)
            self._add_network_args(args, config, network_backend)

        if config.serial_mode == "stderr":
            args.extend(["--com1", "stderr"])
        elif config.serial_mode == "file":
            if not config.serial_path:
                raise LisaException("serial_path must be provided for file serial mode")
            args.extend(["--com1", f"file={config.serial_path}"])
        else:
            raise LisaException(f"Unsupported serial mode: {config.serial_mode}")

        args.extend(config.extra_args)
        return " ".join(shlex.quote(arg) for arg in args)

    def _validate_processor_topology(self, config: OpenVmmLaunchConfig) -> None:
        if config.vps_per_socket is not None and config.vps_per_socket < 1:
            raise LisaException(
                "OpenVMM vps_per_socket must be at least 1. "
                "Set it to the number of virtual processors in each socket."
            )
        if config.smt and config.smt not in [
            OPENVMM_SMT_AUTO,
            OPENVMM_SMT_FORCE,
            OPENVMM_SMT_OFF,
        ]:
            raise LisaException(
                f"OpenVMM SMT mode '{config.smt}' is not supported. "
                f"Use {OPENVMM_SMT_AUTO}, {OPENVMM_SMT_FORCE}, or "
                f"{OPENVMM_SMT_OFF}."
            )

    def _validate_device_types(self, config: OpenVmmLaunchConfig) -> None:
        if config.disk_device not in [
            OPENVMM_DISK_DEVICE_SCSI,
            OPENVMM_DISK_DEVICE_VIRTIO_BLK,
        ]:
            raise LisaException(
                f"Unsupported OpenVMM disk device: {config.disk_device}"
            )
        if config.network_device not in [
            OPENVMM_NETWORK_DEVICE_SYNTHETIC,
            OPENVMM_NETWORK_DEVICE_VIRTIO,
        ]:
            raise LisaException(
                f"Unsupported OpenVMM network device: {config.network_device}"
            )
        if config.network_queue_count is not None and not (
            1 <= config.network_queue_count <= 65535
        ):
            raise LisaException(
                "OpenVMM network queue count must be between 1 and 65535. "
                "Set network.queue_count to a supported positive value."
            )
        if config.iommu not in [
            OPENVMM_IOMMU_NONE,
            OPENVMM_IOMMU_INTEL,
            OPENVMM_IOMMU_AMD,
        ]:
            raise LisaException(f"Unsupported OpenVMM IOMMU: {config.iommu}")

    def _add_pcie_args(self, args: List[str], config: OpenVmmLaunchConfig) -> None:
        use_virtio_disk = bool(config.disk_img_path) and (
            config.disk_device == OPENVMM_DISK_DEVICE_VIRTIO_BLK
        )
        use_virtio_network = config.network_device == OPENVMM_NETWORK_DEVICE_VIRTIO
        if use_virtio_disk or use_virtio_network:
            args.extend(["--pcie-root-complex", OPENVMM_VIRTIO_ROOT_COMPLEX])
            if config.iommu != OPENVMM_IOMMU_NONE:
                args.extend([f"--{config.iommu}", OPENVMM_VIRTIO_ROOT_COMPLEX])
        elif config.iommu != OPENVMM_IOMMU_NONE:
            raise LisaException(
                "OpenVMM IOMMU requires a virtio disk or network device on PCIe"
            )
        if use_virtio_disk:
            args.extend(
                [
                    "--pcie-root-port",
                    f"{OPENVMM_VIRTIO_ROOT_COMPLEX}:{OPENVMM_VIRTIO_DISK_PORT}",
                ]
            )
        if use_virtio_network:
            network_root_port = (
                f"{OPENVMM_VIRTIO_ROOT_COMPLEX}:{OPENVMM_VIRTIO_NETWORK_PORT}"
            )
            args.extend(
                [
                    "--pcie-root-port",
                    network_root_port,
                ]
            )

    def _add_disk_args(self, args: List[str], config: OpenVmmLaunchConfig) -> None:
        if config.dvd_disk_paths or (
            config.disk_img_path and config.disk_device == OPENVMM_DISK_DEVICE_SCSI
        ):
            args.extend(["--vmbus-scsi", f"id={OPENVMM_DEFAULT_SCSI_CONTROLLER}"])

        if config.disk_img_path:
            if config.disk_device == OPENVMM_DISK_DEVICE_SCSI:
                args.extend(
                    [
                        "--disk",
                        f"file:{config.disk_img_path},"
                        f"on={OPENVMM_DEFAULT_SCSI_CONTROLLER},lun=0",
                    ]
                )
            else:
                args.extend(
                    [
                        "--virtio-blk",
                        f"file:{config.disk_img_path},"
                        f"pcie_port={OPENVMM_VIRTIO_DISK_PORT}",
                    ]
                )

        for lun, dvd_disk_path in enumerate(config.dvd_disk_paths, start=1):
            args.extend(
                [
                    "--disk",
                    f"file:{dvd_disk_path},on={OPENVMM_DEFAULT_SCSI_CONTROLLER},"
                    f"lun={lun},dvd",
                ]
            )

    def _get_network_backend(self, config: OpenVmmLaunchConfig) -> str:
        if config.network_mode == "user":
            network_backend = OPENVMM_NETWORK_BACKEND_CONSOMME
            if config.network_cidr:
                network_backend = f"{network_backend}:{config.network_cidr}"
        elif config.network_mode == "tap":
            if not config.tap_name:
                raise LisaException("tap_name must be provided for tap networking")
            network_backend = f"tap:{config.tap_name}"
        else:
            raise LisaException(f"Unsupported network mode: {config.network_mode}")
        return network_backend

    def _add_network_args(
        self,
        args: List[str],
        config: OpenVmmLaunchConfig,
        network_backend: str,
    ) -> None:
        if config.network_queue_count is not None:
            network_backend = f"queues={config.network_queue_count}:{network_backend}"
        if config.network_device == OPENVMM_NETWORK_DEVICE_SYNTHETIC:
            args.extend(["--net", network_backend])
        else:
            args.extend(
                [
                    "--virtio-net",
                    f"pcie_port={OPENVMM_VIRTIO_NETWORK_PORT}:{network_backend}",
                ]
            )

    def launch_vm(
        self,
        config: OpenVmmLaunchConfig,
        cwd: Optional[PurePath] = None,
        sudo: bool = False,
    ) -> str:
        if not config.stdout_path or not config.stderr_path:
            raise LisaException("stdout_path and stderr_path must be provided")

        command = self.build_command(config)
        shell_command = self._build_launch_shell_command(command, config)
        result = self.node.execute(
            shell_command,
            shell=True,
            sudo=sudo,
            no_info_log=True,
            cwd=cwd,
        )
        pid_lines = [
            line.strip() for line in result.stdout.splitlines() if line.strip()
        ]
        pid = pid_lines[-1] if pid_lines else ""
        if not pid or not pid.isdigit():
            raise LisaException(
                "OpenVMM launch did not return a valid PID. "
                f"stdout: {result.stdout.strip() or '<empty>'}. "
                f"stderr: {result.stderr.strip() or '<empty>'}"
            )
        return pid

    def _build_launch_shell_command(
        self, command: str, config: OpenVmmLaunchConfig
    ) -> str:
        stdout_path = shlex.quote(config.stdout_path)
        if PurePath(config.stdout_path) == PurePath(config.stderr_path):
            return f"nohup {command} > {stdout_path} 2>&1 < /dev/null & echo $!"
        stderr_path = shlex.quote(config.stderr_path)
        pid_path = shlex.quote(f"{config.stdout_path}.pid")

        def _build_child_command(launch_command: str, use_pty: bool) -> str:
            inner_command = shlex.quote(f"echo $$ > {pid_path}; exec {launch_command}")
            wrapped_command = f"sh -c {inner_command}"
            if not use_pty:
                return wrapped_command
            return f"script -qefc {shlex.quote(wrapped_command)} /dev/null"

        if config.auto_restart_on_guest_reset:
            restart_config = replace(config, create_vmgs=False)
            restart_command = self.build_command(restart_config)
            fifo_path = shlex.quote(f"{config.stdout_path}.stdin")
            feeder_pid_path = shlex.quote(f"{config.stdout_path}.feeder.pid")

            def _build_supervisor_command(use_pty: bool) -> str:
                def _build_supervised_child(launch_command: str) -> str:
                    child_command = _build_child_command(
                        launch_command,
                        use_pty=use_pty,
                    )
                    if use_pty:
                        return (
                            f"rm -f {fifo_path}; "
                            f"mkfifo {fifo_path}; "
                            f"tail -f /dev/null > {fifo_path} & "
                            "feeder_pid=$!; "
                            f"echo $feeder_pid > {feeder_pid_path}; "
                            f"{child_command} < {fifo_path}; "
                            "exit_code=$?; "
                            'kill "$feeder_pid" >/dev/null 2>&1 || true; '
                            'wait "$feeder_pid" 2>/dev/null || true; '
                            "feeder_pid=''; "
                            f"rm -f {fifo_path} {pid_path} {feeder_pid_path}"
                        )
                    return f"{child_command}; exit_code=$?; rm -f {pid_path}"

                first_child = _build_supervised_child(command)
                restart_child = _build_supervised_child(restart_command)
                return shlex.quote(
                    "feeder_pid=''; "
                    "cleanup() { "
                    f"if [ -s {pid_path} ]; then "
                    f"child_pid=$(cat {pid_path}); "
                    'if [ -n "$child_pid" ]; then '
                    'kill "$child_pid" >/dev/null 2>&1 || true; '
                    "fi; "
                    "fi; "
                    'if [ -n "$feeder_pid" ]; then '
                    'kill "$feeder_pid" >/dev/null 2>&1 || true; '
                    "fi; "
                    f"rm -f {fifo_path} {pid_path} {feeder_pid_path}; "
                    "}; "
                    "trap 'cleanup; exit 143' INT TERM; "
                    "trap cleanup EXIT; "
                    "restart_count=0; "
                    f"{first_child}; "
                    f'while [ "$exit_code" -eq '
                    f"{config.guest_reset_exit_code} ] && "
                    f'[ "$restart_count" -lt '
                    f"{config.max_guest_reset_restarts} ]; do "
                    "restart_count=$((restart_count + 1)); "
                    'echo "Restarting OpenVMM after guest reset '
                    "($restart_count/"
                    f'{config.max_guest_reset_restarts})" >&2; '
                    f"{restart_child}; "
                    'done; exit "$exit_code"'
                )

            wait_for_child = (
                "supervisor_pid=$!; "
                "attempt=0; "
                "while [ $attempt -lt 100 ]; do "
                f"if [ -s {pid_path} ]; then "
                "echo $supervisor_pid; exit 0; fi; "
                "if ! kill -0 $supervisor_pid >/dev/null 2>&1; then break; fi; "
                "attempt=$((attempt + 1)); "
                "sleep 0.1; "
                "done; "
                "echo 'OpenVMM supervisor did not record a child PID.' >&2; "
                "exit 1"
            )
            pty_supervisor = _build_supervisor_command(use_pty=True)
            direct_supervisor = _build_supervisor_command(use_pty=False)
            return (
                f"rm -f {pid_path}; "
                "if command -v script >/dev/null 2>&1; then "
                f"nohup sh -c {pty_supervisor} > {stdout_path} "
                f"2> {stderr_path} < /dev/null & {wait_for_child}; "
                "else "
                f"nohup sh -c {direct_supervisor} > {stdout_path} "
                f"2> {stderr_path} < /dev/null & {wait_for_child}; "
                "fi"
            )

        inner_command = shlex.quote(f"echo $$ > {pid_path}; exec {command}")
        wrapped_command = shlex.quote(f"sh -c {inner_command}")
        pty_command = shlex.quote(
            f"tail -f /dev/null | script -qefc {wrapped_command} /dev/null"
        )

        # OpenVMM's management loop expects a tty for its stdio thread. Feed an
        # always-open empty stream into script so detached launches behave like
        # an interactive session instead of exiting on immediate stdin EOF. The
        # script wrapper records the exec'd OpenVMM PID so later liveness checks
        # and forced cleanup target the VM process rather than the wrapper shell.
        return (
            "if command -v script >/dev/null 2>&1; then "
            f"rm -f {pid_path}; "
            f"nohup sh -c {pty_command} > {stdout_path} "
            f"2> {stderr_path} < /dev/null & wrapper_pid=$!; "
            "attempt=0; "
            "while [ $attempt -lt 100 ]; do "
            f"if [ -s {pid_path} ]; then cat {pid_path}; exit 0; fi; "
            "if ! kill -0 $wrapper_pid >/dev/null 2>&1; then break; fi; "
            "attempt=$((attempt + 1)); "
            "sleep 0.1; "
            "done; "
            "echo 'OpenVMM launch did not record a child PID from the "
            "script wrapper.' >&2; "
            "exit 1; "
            "else "
            f"nohup {command} > {stdout_path} 2> {stderr_path} < /dev/null & echo $!; "
            "fi"
        )
