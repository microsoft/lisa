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

OPENVMM_NETWORK_BACKEND_CONSOMME = "consomme"


@dataclass
class OpenVmmLaunchConfig:
    uefi_firmware_path: str
    with_hv: bool = True
    hypervisor: str = "mshv"
    disk_img_path: str = ""
    dvd_disk_paths: List[str] = field(default_factory=list)
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
            stdout_output = result.stdout.strip()
            stderr_output = result.stderr.strip()
            output = stdout_output or stderr_output
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
        if config.with_hv:
            args.append("--hv")
        if config.hypervisor:
            args.extend(["--hypervisor", config.hypervisor])
        args.extend(["--processors", str(config.processors)])
        args.extend(["--memory", f"{config.memory_mb}MB"])

        if not config.uefi_firmware_path:
            raise LisaException("uefi_firmware_path must be provided for UEFI boot")
        args.append("--uefi")
        args.extend(["--uefi-firmware", config.uefi_firmware_path])

        if config.disk_img_path:
            args.extend(["--disk", f"file:{config.disk_img_path}"])

        for dvd_disk_path in config.dvd_disk_paths:
            args.extend(["--disk", f"file:{dvd_disk_path},dvd"])

        if config.network_mode == "user":
            network_backend = OPENVMM_NETWORK_BACKEND_CONSOMME
            if config.network_cidr:
                network_backend = f"{network_backend}:{config.network_cidr}"
            args.extend(["--net", network_backend])
        elif config.network_mode == "tap":
            if not config.tap_name:
                raise LisaException("tap_name must be provided for tap networking")
            args.extend(["--net", f"tap:{config.tap_name}"])
        else:
            raise LisaException(f"Unsupported network mode: {config.network_mode}")

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
        pid = result.stdout.strip()
        if not pid:
            raise LisaException("OpenVMM launch did not return a PID")
        return pid

    def _build_launch_shell_command(
        self, command: str, config: OpenVmmLaunchConfig
    ) -> str:
        stdout_path = shlex.quote(config.stdout_path)
        if PurePath(config.stdout_path) == PurePath(config.stderr_path):
            return f"nohup {command} > {stdout_path} 2>&1 < /dev/null & echo $!"
        stderr_path = shlex.quote(config.stderr_path)
        return f"nohup {command} > {stdout_path} 2> {stderr_path} < /dev/null & echo $!"
