# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import shlex
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.tools import GrubConfig
from lisa.transformers.deployment_transformer import (
    DeploymentTransformer,
    DeploymentTransformerSchema,
)
from lisa.util import LisaException, field_metadata

_KERNEL_ARG_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_KERNEL_ARG_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9_.,:/+%@=-]*$")


@dataclass_json
@dataclass
class HostKernelBootParametersTransformerSchema(DeploymentTransformerSchema):
    parameters: str = field(default="", metadata=field_metadata(required=False))
    reboot_timeout: int = field(default=900, metadata=field_metadata(required=False))


class HostKernelBootParameters(DeploymentTransformer):
    @classmethod
    def type_name(cls) -> str:
        return "host_kernel_boot_parameters"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return HostKernelBootParametersTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def _internal_run(self) -> Dict[str, Any]:
        runbook: HostKernelBootParametersTransformerSchema = self.runbook
        kernel_parameters = self._parse_parameters(runbook.parameters)

        if not kernel_parameters:
            self._log.info("No host kernel boot parameters were provided")
            return {}

        self._log.info(
            "Applying host kernel boot parameters: "
            f"{self._format_parameters(kernel_parameters)}"
        )
        self._dump_boot_debug_state("before setting host kernel boot parameters")

        grub_config = self._node.tools[GrubConfig]
        for parameter_name, parameter_value in kernel_parameters:
            self._log.info(
                "Setting host kernel boot parameter "
                f"'{parameter_name}={parameter_value}'"
            )
            grub_config.set_kernel_cmdline_arg(parameter_name, parameter_value)
            self._dump_boot_debug_state(
                f"after setting host kernel boot parameter {parameter_name}"
            )

        self._dump_boot_debug_state("before host kernel boot parameter reboot")
        self._log.info(
            "Rebooting after setting host kernel boot parameters with timeout "
            f"{runbook.reboot_timeout} seconds"
        )
        try:
            self._node.reboot(time_out=runbook.reboot_timeout)
        except Exception:
            self._dump_boot_debug_state(
                "after failed host kernel boot parameter reboot"
            )
            raise

        self._dump_boot_debug_state("after host kernel boot parameter reboot")
        return {}

    def _parse_parameters(self, raw_parameters: str) -> List[Tuple[str, str]]:
        raw_parameters = raw_parameters.strip()
        if not raw_parameters:
            return []

        try:
            parameter_tokens = shlex.split(raw_parameters)
        except ValueError as identifier:
            raise LisaException(
                f"Failed to parse host kernel boot parameters: {identifier}"
            ) from identifier

        kernel_parameters: List[Tuple[str, str]] = []
        for parameter_token in parameter_tokens:
            if "=" not in parameter_token:
                raise LisaException(
                    "Host kernel boot parameters must be whitespace-separated "
                    f"name=value pairs. Invalid parameter: '{parameter_token}'"
                )

            parameter_name, parameter_value = parameter_token.split("=", 1)
            if not _KERNEL_ARG_NAME_PATTERN.fullmatch(parameter_name):
                raise LisaException(
                    "Host kernel boot parameter names may contain only letters, "
                    "numbers, underscores, dots, and hyphens. Invalid name: "
                    f"'{parameter_name}'"
                )
            if not _KERNEL_ARG_VALUE_PATTERN.fullmatch(parameter_value):
                raise LisaException(
                    "Host kernel boot parameter values may contain only letters, "
                    "numbers, underscores, dots, commas, colons, slashes, plus "
                    "signs, percent signs, at signs, equals signs, and hyphens. "
                    f"Invalid value for '{parameter_name}': '{parameter_value}'"
                )

            kernel_parameters.append((parameter_name, parameter_value))

        return kernel_parameters

    def _format_parameters(self, kernel_parameters: List[Tuple[str, str]]) -> str:
        return " ".join(
            f"{parameter_name}={parameter_value}"
            for parameter_name, parameter_value in kernel_parameters
        )

    def _dump_boot_debug_state(self, label: str) -> None:
        self._log.info(f"[host-kernel-params-debug] collecting boot state: {label}")
        commands = [
            "uname -a",
            "cat /proc/cmdline",
            "who -b",
            "uptime -s",
            "cat /etc/default/grub",
            "ls -la /boot /boot/grub2 /boot/efi /boot/efi/EFI",
            (
                "grep -R -n -E 'menuentry|linux|initrd|GRUB_DEFAULT|"
                "GRUB_CMDLINE|set default|saved_entry' "
                "/etc/default/grub /boot/grub2/grub.cfg "
                "/boot/efi/EFI/*/grub.cfg /etc/grub.d/40_custom* "
                "/boot/loader/entries/* 2>/dev/null"
            ),
            "grubby --default-kernel --default-index --info=ALL",
            "bootctl status",
            "efibootmgr -v",
        ]
        for command in commands:
            try:
                result = self._node.execute(
                    command,
                    shell=True,
                    sudo=True,
                    no_info_log=False,
                    timeout=20,
                )
                self._log.info(
                    f"[host-kernel-params-debug][{label}] command: {command}\n"
                    f"exit_code: {result.exit_code}\n"
                    f"stdout:\n{result.stdout}\n"
                    f"stderr:\n{result.stderr}"
                )
            except Exception as identifier:
                self._log.info(
                    f"[host-kernel-params-debug][{label}] command failed or "
                    f"timed out: {command}\nerror: {identifier}"
                )
