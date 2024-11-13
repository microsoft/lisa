# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.transformers.deployment_transformer import (
    DeploymentTransformer,
    DeploymentTransformerSchema,
)
from lisa.util import LisaException, field_metadata


class ScriptInterpreter(str, Enum):
    BASH = "bash"


@dataclass_json()
@dataclass
class ScriptEntry:
    script: str = ""
    interpreter: ScriptInterpreter = ScriptInterpreter.BASH
    args: Optional[str] = None
    expected_exit_code: Optional[int] = field(
        default=0, metadata=field_metadata(allow_none=True)
    )


@dataclass_json()
@dataclass
class ScriptFileTransformerSchema(DeploymentTransformerSchema):
    dependent_packages: List[str] = field(default_factory=list)
    scripts: List[ScriptEntry] = field(default_factory=list)
    reboot: bool = field(default=False)


class ScriptFileTransformer(DeploymentTransformer):
    """
    This Transformer is to execute scripts.

    Sample runbook section:
    - type: script_file
        phase: expanded
        connection:
        address: $(build_vm_address)
        private_key_file: $(admin_private_key_file)
        reboot: true
        exit_on_error: true
        dependent_packages:
        - git
        scripts:
        - script: "/tmp/waagent.sh"
          interpreter: bash
          args: "--flag"
    """

    __results_name = "results"

    @classmethod
    def type_name(cls) -> str:
        return "script_file"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return ScriptFileTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return [self.__results_name]

    def _internal_run(self) -> Dict[str, Any]:
        runbook: ScriptFileTransformerSchema = self.runbook
        if runbook.dependent_packages:
            self._node.os.install_packages(runbook.dependent_packages)  # type: ignore

        results: Dict[str, Any] = {}
        failed_scripts = []

        for item in runbook.scripts:
            command = f"{item.interpreter} {item.script} {item.args}"
            execution_result = self._node.execute(command, sudo=True, shell=True)
            results[item.script] = execution_result
            if item.expected_exit_code is not None:
                if item.expected_exit_code != execution_result.exit_code:
                    failed_scripts.append(
                        (
                            item.script,
                            execution_result.exit_code,
                            item.expected_exit_code,
                        )
                    )

        if failed_scripts:
            raise LisaException(
                "Execution failed for scripts "
                f"(name, exit_code, expected_exit_code): {failed_scripts}"
            )

        if runbook.reboot:
            self._node.reboot()
        return {self.__results_name: results}
