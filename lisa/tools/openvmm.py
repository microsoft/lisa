# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import shlex
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import List, Optional

from lisa.executable import Tool
from lisa.util import LisaException


VERSION_PATTERN = re.compile(r"openvmm(?:\.exe)?\s+(?P<version>.+)")


@dataclass
class OpenVmmLaunchConfig:
    uefi_firmware_path: str
    disk_img_path: str = ""
    processors: int = 1
    memory_mb: int = 1024
    network_mode: str = "user"
    tap_name: str = ""
    network_cidr: str = ""
    serial_mode: str = "file"
    serial_path: str = ""
    extra_args: List[str] = field(default_factory=list)
    stdout_path: str = ""
    stderr_path: str = ""


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
            output = (result.stdout or result.stderr).strip()
            if not output:
                continue
            normalized_output = output.lower()
            match = VERSION_PATTERN.search(output)
            if match:
                return match.group("version").strip()
            if result.exit_code == 0 or (
                "usage:" in normalized_output
                and "command not found" not in normalized_output
            ):
                return output.splitlines()[0].strip()
        return "Unknown"

    def build_command(self, config: OpenVmmLaunchConfig) -> str:
        args: List[str] = [self.command]
        args.extend(["--processors", str(config.processors)])
        args.extend(["--memory", f"{config.memory_mb}MB"])

        if not config.uefi_firmware_path:
            raise LisaException("uefi_firmware_path must be provided for UEFI boot")
        args.append("--uefi")
        args.extend(["--uefi-firmware", config.uefi_firmware_path])

        pcie_port_index = 0
        has_network = config.network_mode != "none"
        if config.disk_img_path or has_network:
            args.extend(["--pcie-root-complex", "rc0"])

        if config.disk_img_path:
            args.extend(["--disk", f"file:{config.disk_img_path}"])

        if config.network_mode == "user":
            nic_port = f"rp{pcie_port_index}"
            args.extend(["--pcie-root-port", f"rc0:{nic_port}"])
            network_backend = "consomme"
            if config.network_cidr:
                network_backend = f"{network_backend}:{config.network_cidr}"
            args.extend(["--virtio-net", f"pcie_port={nic_port}:{network_backend}"])
        elif config.network_mode == "tap":
            if not config.tap_name:
                raise LisaException("tap_name must be provided for tap networking")
            nic_port = f"rp{pcie_port_index}"
            args.extend(["--pcie-root-port", f"rc0:{nic_port}"])
            args.extend(
                [
                    "--virtio-net",
                    f"pcie_port={nic_port}:tap:{config.tap_name}",
                ]
            )

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

    def launch_vm(
        self, config: OpenVmmLaunchConfig, cwd: Optional[PurePath] = None
    ) -> str:
        if not config.stdout_path or not config.stderr_path:
            raise LisaException("stdout_path and stderr_path must be provided")

        command = self.build_command(config)
        shell_command = (
            f"nohup {command} > {shlex.quote(config.stdout_path)} "
            f"2> {shlex.quote(config.stderr_path)} < /dev/null & echo $!"
        )
        result = self.node.execute(
            shell_command,
            shell=True,
            no_info_log=True,
            cwd=cwd,
        )
        pid = result.stdout.strip()
        if not pid:
            raise LisaException("OpenVMM launch did not return a PID")
        return pid
