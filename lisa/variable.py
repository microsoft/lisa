import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union, cast

import yaml

from lisa import schema, secret
from lisa.util import LisaException, constants

DataType = Union[str, bool, int]

_VARIABLE_PATTERN = re.compile(r"^\$\((.+)\)$")
_ENV_START = "LISA_"
_SECRET_ENV_START = "S_LISA_"


@dataclass
class VariableEntry:
    data: Any
    is_used: bool = False


def replace_variables(data: Any, variables: Dict[str, VariableEntry]) -> Any:
    if isinstance(data, dict):
        for key, value in data.items():
            data[key] = replace_variables(value, variables)
    elif isinstance(data, list):
        for index, item in enumerate(data):
            data[index] = replace_variables(item, variables)
    elif isinstance(data, str):
        matches = _VARIABLE_PATTERN.match(data)
        if matches:
            variable_name = matches[1]
            lower_variable_name = variable_name.lower()
            if lower_variable_name in variables:
                entry = variables[lower_variable_name]
                entry.is_used = True
                data = entry.data
            else:
                raise LisaException(
                    f"cannot find variable '{variable_name}', make sure it's defined"
                )

    return data


def load_from_env(current_variables: Dict[str, Any]) -> None:
    for env_name in os.environ:
        is_lisa_variable = True
        is_secret = False
        name = ""
        if env_name.startswith(_ENV_START):
            name = env_name[len(_ENV_START) :]
            value = os.environ[env_name]
        elif env_name.startswith(_SECRET_ENV_START):
            name = env_name[len(_SECRET_ENV_START) :]
            is_secret = True
        else:
            is_lisa_variable = False

        if is_lisa_variable:
            value = os.environ[env_name]
            _add_variable(
                name, value, current_variables=current_variables, is_secret=is_secret
            )


def load_from_runbook(
    runbook_data: Any, current_variables: Dict[str, VariableEntry]
) -> None:
    if constants.VARIABLE in runbook_data:
        variable_entries = schema.Variable.schema().load(  # type:ignore
            runbook_data[constants.VARIABLE], many=True
        )
        variable_entries = cast(List[schema.Variable], variable_entries)
        for entry in variable_entries:
            if entry.file:
                load_from_file(entry.file, current_variables, is_secret=entry.is_secret)
            else:
                load_from_variable_entry(
                    entry.name,
                    entry.value,
                    current_variables,
                    is_secret=entry.is_secret,
                )


def load_from_file(
    file_name: str,
    current_variables: Dict[str, VariableEntry],
    is_secret: bool = False,
) -> None:
    if is_secret:
        secret.add_secret(file_name, secret.PATTERN_FILENAME)

    path = constants.RUNBOOK_PATH.joinpath(file_name)

    if path.suffix.lower() not in [".yaml", ".yml"]:
        raise LisaException("variable support only yaml and yml")

    try:
        with open(path, "r") as fp:
            raw_variables = yaml.safe_load(fp)
    except FileNotFoundError:
        raise FileNotFoundError(f"cannot find variable file: {path}")
    if not isinstance(raw_variables, Dict):
        raise LisaException("variable file must be dict")

    for key, raw_value in raw_variables.items():
        load_from_variable_entry(
            key, raw_value, current_variables=current_variables, is_secret=is_secret
        )


def load_from_pairs(
    pairs: Optional[List[str]], current_variables: Dict[str, VariableEntry]
) -> None:
    if pairs is None:
        return
    for pair in pairs:
        is_secret = False
        if pair.lower().startswith("s:"):
            is_secret = True
            pair = pair[2:]
        key, value = pair.split(":", 1)
        _add_variable(key, value, current_variables, is_secret=is_secret)


def load_from_variable_entry(
    name: str,
    raw_value: Any,
    current_variables: Dict[str, VariableEntry],
    is_secret: bool = False,
) -> None:

    assert isinstance(name, str), f"actual: {type(name)}"
    mask_pattern_name = ""
    if type(raw_value) in [str, int, bool, float]:
        value = raw_value
    else:
        if isinstance(raw_value, dict):
            raw_value = cast(
                schema.VariableEntry,
                schema.VariableEntry.schema().load(raw_value),  # type: ignore
            )
        is_secret = is_secret or raw_value.is_secret
        mask_pattern_name = raw_value.mask
        value = raw_value.value
    _add_variable(
        name,
        value,
        current_variables,
        is_secret=is_secret,
        mask_pattern_name=mask_pattern_name,
    )


def _add_variable(
    key: str,
    value: Any,
    current_variables: Dict[str, VariableEntry],
    is_secret: bool = False,
    mask_pattern_name: str = "",
) -> None:
    key = key.lower()
    current_variables[key] = VariableEntry(value)
    pattern = None
    if is_secret:
        if mask_pattern_name:
            pattern = secret.patterns.get(mask_pattern_name, None)
            if pattern is None:
                raise LisaException(f"cannot find mask pattern: {mask_pattern_name}")
        secret.add_secret(value, mask=pattern)
