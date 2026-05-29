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

        grub_config = self._node.tools[GrubConfig]
        for parameter_name, parameter_value in kernel_parameters:
            self._log.info(
                f"Setting host kernel boot parameter "
                f"'{parameter_name}={parameter_value}'"
            )
            grub_config.set_kernel_cmdline_arg(parameter_name, parameter_value)

        self._log.info(
            f"Rebooting after setting host kernel boot parameters "
            f"(timeout: {runbook.reboot_timeout}s)"
        )
        self._node.reboot(time_out=runbook.reboot_timeout)
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
