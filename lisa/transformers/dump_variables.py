# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Type

import yaml
from dataclasses_json import dataclass_json

from lisa import schema
from lisa.transformer import Transformer
from lisa.util import constants

DUMP_VARIABLES = "dump_variables"


@dataclass_json
@dataclass
class DumpVariablesTransformerSchema(schema.Transformer):
    # variables to be dumped as yaml
    variables: List[str] = field(default_factory=list)
    json_output: bool = field(default=False)
    file_path: str = field(
        default="./lisa_dumped_variables",
    )


class DumpVariablesTransformer(Transformer):
    """
    This transformer dumps given items and values to a yaml file.
    """

    @classmethod
    def type_name(cls) -> str:
        return DUMP_VARIABLES

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return DumpVariablesTransformerSchema

    @property
    def _output_names(self) -> List[str]:
        return []

    def _internal_run(self) -> Dict[str, Any]:
        runbook: DumpVariablesTransformerSchema = self.runbook
        required_data: Dict[str, Dict[str, Any]] = {}
        variables_data = self._runbook_builder.variables
        for var in runbook.variables:
            try:
                var_data = variables_data[var]
                required_data[var] = {
                    "value": var_data.data,
                    "is_case_visible": var_data.is_case_visible,
                }
            except KeyError:
                self._log.info(f"Variable '{var}' is not found")
        # it will be used as log files
        file_path = Path(self.__get_file_with_ext(runbook.file_path))
        if not file_path.is_absolute():
            file_path = constants.RUN_LOCAL_LOG_PATH / file_path
        with open(file_path, "w") as dump_file:
            if runbook.json_output:
                json.dump(required_data, dump_file)
            else:
                yaml.safe_dump(required_data, dump_file)
        return {}

    def __get_file_with_ext(self, file_path: str) -> str:
        if file_path.lower().endswith((".yml", ".json")):
            return file_path

        runbook: DumpVariablesTransformerSchema = self.runbook
        if runbook.json_output:
            return file_path + ".json"
        else:
            return file_path + ".yml"
