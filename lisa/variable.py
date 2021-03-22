# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union, cast

import yaml

from lisa import schema, secret
from lisa.util import LisaException, constants

DataType = Union[str, bool, int]

_VARIABLE_PATTERN = re.compile(r"(\$\(.+?\))", re.MULTILINE)
_ENV_START = "LISA_"
_SECRET_ENV_START = "S_LISA_"


@dataclass
class VariableEntry:
    data: Any
    is_used: bool = False


def replace_variables(data: Any, variables: Dict[str, VariableEntry]) -> Any:

    new_variables: Dict[str, VariableEntry] = dict()
    for key, value in variables.items():
        new_variables[f"$({key})"] = value

    return _replace_variables(data, new_variables)


def load_variables(
    runbook_data: Any,
    higher_level_variables: Union[List[str], Dict[str, VariableEntry], None] = None,
) -> Dict[str, VariableEntry]:
    """
    Args::
        higher_level_variables: it has higher level than current variables. It
         may be from command lines, or parent runbooks.
    """
    if higher_level_variables is None:
        higher_level_variables = {}

    env_variables = _load_from_env()
    current_variables: Dict[str, VariableEntry] = dict()
    if isinstance(higher_level_variables, list):
        cmd_variables = _load_from_pairs(higher_level_variables)
    else:
        current_variables.update(higher_level_variables)
        cmd_variables = {}
    # current_variables uses to support variable in variable file path
    current_variables.update(env_variables)
    current_variables.update(cmd_variables)

    final_variables: Dict[str, VariableEntry] = dict()
    final_variables.update(
        _load_from_runbook(runbook_data, current_variables=current_variables)
    )
    if isinstance(higher_level_variables, dict):
        final_variables.update(higher_level_variables)
    final_variables.update(env_variables)
    final_variables.update(cmd_variables)

    return final_variables


def _load_from_env() -> Dict[str, Any]:
    results: Dict[str, VariableEntry] = {}
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
            _add_variable(name, value, results, is_secret=is_secret)
    return results


def _load_from_runbook(
    runbook_data: Any, current_variables: Dict[str, VariableEntry]
) -> Dict[str, VariableEntry]:
    # make a copy to prevent modifying existing dict
    current_variables = current_variables.copy()
    results: Dict[str, VariableEntry] = {}

    if constants.VARIABLE in runbook_data:
        variable_entries = schema.Variable.schema().load(  # type:ignore
            runbook_data[constants.VARIABLE], many=True
        )
        variable_entries = cast(List[schema.Variable], variable_entries)
        for entry in variable_entries:
            if entry.file:
                path = replace_variables(entry.file, current_variables)
                loaded_variables = _load_from_file(path, is_secret=entry.is_secret)
                results.update()
            else:
                value = replace_variables(entry.value, current_variables)
                loaded_variables = load_from_variable_entry(
                    entry.name,
                    value,
                    is_secret=entry.is_secret,
                )
            results.update(loaded_variables)
            current_variables.update(loaded_variables)
    return results


def _load_from_file(
    file_name: str,
    is_secret: bool = False,
) -> Dict[str, VariableEntry]:
    results: Dict[str, VariableEntry] = {}
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
        results.update(load_from_variable_entry(key, raw_value, is_secret=is_secret))
    return results


def _load_from_pairs(
    raw_pairs: Optional[List[str]],
) -> Dict[str, VariableEntry]:
    results: Dict[str, VariableEntry] = {}
    if raw_pairs is None:
        return results
    for raw_pair in raw_pairs:
        is_secret = False
        if raw_pair.lower().startswith("s:"):
            is_secret = True
            raw_pair = raw_pair[2:]
        key, value = raw_pair.split(":", 1)
        _add_variable(key, value, results, is_secret=is_secret)
    return results


def load_from_variable_entry(
    name: str,
    raw_value: Any,
    is_secret: bool = False,
) -> Dict[str, VariableEntry]:

    assert isinstance(name, str), f"actual: {type(name)}"
    results: Dict[str, VariableEntry] = {}
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
        results,
        is_secret=is_secret,
        mask_pattern_name=mask_pattern_name,
    )
    return results


def _replace_variables(data: Any, variables: Dict[str, VariableEntry]) -> Any:
    if isinstance(data, dict):
        for key, value in data.items():
            data[key] = _replace_variables(value, variables)
    elif isinstance(data, list):
        for index, item in enumerate(data):
            data[index] = _replace_variables(item, variables)
    elif isinstance(data, str):
        lower_name = data.lower()
        if lower_name in variables:
            # If a variable value matches a variable name completely, it may not be a
            #   string.
            # So replace the whole value here to support other types.
            entry = variables[lower_name]
            entry.is_used = True
            data = entry.data
        else:
            matches = _VARIABLE_PATTERN.findall(data)
            if matches:
                for variable_name in matches:
                    lower_variable_name = variable_name.lower()
                    if lower_variable_name in variables:
                        variables[lower_variable_name].is_used = True
                    else:
                        raise LisaException(
                            f"cannot find variable '{variable_name[2:-1]}', "
                            f"make sure it's defined"
                        )
                data = _VARIABLE_PATTERN.sub(
                    lambda matched: str(
                        variables[
                            matched.string[matched.start() : matched.end()].lower()
                        ].data,
                    ),
                    data,
                )

    return data


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
