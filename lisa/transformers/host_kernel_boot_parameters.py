# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import shlex
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.node import Node
from lisa.tools import Cat, GrubConfig
from lisa.transformers.deployment_transformer import (
    DeploymentTransformer,
    DeploymentTransformerSchema,
)
from lisa.util import LisaException, field_metadata
from lisa.util.logger import Logger

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
        self.apply_to_node(
            self._node, runbook.parameters, self._log, runbook.reboot_timeout
        )
        return {}

    @classmethod
    def apply_to_node(
        cls,
        node: Node,
        parameters: str,
        log: Logger,
        reboot_timeout: int = 900,
    ) -> None:
        kernel_parameters = cls._parse_parameters(parameters)

        if not kernel_parameters:
            log.info("No kernel boot parameters were provided")
            return

        log.info(
            "Applying kernel boot parameters: "
            f"{cls._format_parameters(kernel_parameters)}"
        )

        grub_config = node.tools[GrubConfig]
        for parameter_name, parameter_value in kernel_parameters:
            log.info(
                f"Setting kernel boot parameter "
                f"'{parameter_name}={parameter_value}'"
            )
            grub_config.set_kernel_cmdline_arg(parameter_name, parameter_value)

        log.info(
            f"Rebooting after setting kernel boot parameters "
            f"(timeout: {reboot_timeout}s)"
        )
        node.reboot(time_out=reboot_timeout)
        cls._validate_parameters_applied(node, kernel_parameters, log)

    @staticmethod
    def _validate_parameters_applied(
        node: Node, kernel_parameters: List[Tuple[str, str]], log: Logger
    ) -> None:
        cmdline = (
            node.tools[Cat].read("/proc/cmdline", sudo=True, force_run=True).strip()
        )
        cmdline_tokens = set(cmdline.split())
        expected_parameters = [
            f"{parameter_name}={parameter_value}"
            for parameter_name, parameter_value in kernel_parameters
        ]
        missing_parameters = [
            parameter
            for parameter in expected_parameters
            if parameter not in cmdline_tokens
        ]
        if missing_parameters:
            raise LisaException(
                "Kernel boot parameters were not applied after reboot. "
                f"Missing parameters: {', '.join(missing_parameters)}. "
                f"Actual /proc/cmdline: {cmdline}"
            )

        log.info(
            "Validated kernel boot parameters in /proc/cmdline: "
            f"{', '.join(expected_parameters)}"
        )

    @staticmethod
    def _parse_parameters(raw_parameters: str) -> List[Tuple[str, str]]:
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

    @staticmethod
    def _format_parameters(kernel_parameters: List[Tuple[str, str]]) -> str:
        return " ".join(
            f"{parameter_name}={parameter_value}"
            for parameter_name, parameter_value in kernel_parameters
        )
