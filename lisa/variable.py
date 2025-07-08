# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

import yaml

from lisa import schema, secret
from lisa.util import LisaException, constants

DataType = Union[str, bool, int]

_VARIABLE_PATTERN = re.compile(r"(\$\(.+?\))", re.MULTILINE)
_ENV_START = "LISA_"
_SECRET_ENV_START = "S_LISA_"


@dataclass
class VariableEntry:
    name: str
    data: Any
    is_used: bool = False
    is_case_visible: bool = False

    def copy(self) -> "VariableEntry":
        return VariableEntry(
            name=self.name,
            data=self.data,
            is_used=self.is_used,
            is_case_visible=self.is_case_visible,
        )

    def update(self, new_variable: "VariableEntry") -> None:
        if new_variable:
            self.data = _try_convert_type(self.data, new_variable.data)
            self.is_used = self.is_used or new_variable.is_used
            self.is_case_visible = self.is_case_visible or new_variable.is_case_visible


def _try_convert_type(original_value: Any, new_value: Any) -> Any:
    """
    Take the non-string type. The string is default type, and it can be
    overridden in the variable section.
    """
    if original_value is None or new_value is None:
        return new_value

    original_type = type(original_value)
    new_type = type(new_value)
    if original_type == new_type:
        return new_value

    target_type = new_type if new_type is not str else original_type
    try:
        if target_type is bool:
            if new_value.lower() in ("y", "yes", "t", "true", "on", "1"):
                new_value = True
            elif new_value.lower() in ("n", "no", "f", "false", "off", "0"):
                new_value = False
        else:
            new_value = target_type(new_value)
    except Exception:
        # ignore error on converting, use its new type.
        ...
    return new_value


def replace_variables(data: Any, variables: Dict[str, VariableEntry]) -> Any:
    new_variables: Dict[str, VariableEntry] = {}
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
        may be from command lines, or included runbooks.
    """
    if higher_level_variables is None:
        higher_level_variables = {}

    current_variables: Dict[str, VariableEntry] = {}
    if isinstance(higher_level_variables, list):
        env_variables = _load_from_env()
        cmd_variables = add_secrets_from_pairs(higher_level_variables)
    else:
        merge_variables(current_variables, higher_level_variables)
        env_variables = {}
        cmd_variables = {}
    # current_variables uses to support variable in variable file path
    merge_variables(current_variables, env_variables)
    merge_variables(current_variables, cmd_variables)

    final_variables: Dict[str, VariableEntry] = {}
    merge_variables(
        final_variables,
        _load_from_runbook(runbook_data, higher_level_variables=current_variables),
    )
    if isinstance(higher_level_variables, dict):
        merge_variables(final_variables, higher_level_variables)
    else:
        merge_variables(final_variables, env_variables)
        merge_variables(final_variables, cmd_variables)

    return final_variables


def merge_variables(
    variables: Dict[str, VariableEntry], new_variables: Dict[str, VariableEntry]
) -> None:
    """
    in place update variables. If variables don't exist, will create them
    """
    for name, new_variable in new_variables.items():
        variable = variables.get(name, None)
        if variable:
            variable.update(new_variable)
        else:
            variables[name] = new_variable.copy()


def _get_undefined_variables(
    value: str, variables: Dict[str, VariableEntry]
) -> List[str]:
    undefined_variables: List[str] = []
    # check if there is variable or not in a value
    matches = _VARIABLE_PATTERN.findall(value)
    for variable_name in matches:
        lower_variable_name = variable_name[2:-1].lower()
        if lower_variable_name not in variables:
            undefined_variables.append(variable_name)
    return undefined_variables


def _load_from_env() -> Dict[str, VariableEntry]:
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
    runbook_data: Any, higher_level_variables: Dict[str, VariableEntry]
) -> Dict[str, VariableEntry]:
    # make a copy to prevent modifying existing dict
    current_variables = higher_level_variables.copy()

    if constants.VARIABLE in runbook_data:
        variable_entries: List[schema.Variable] = schema.load_by_type_many(
            schema.Variable, runbook_data[constants.VARIABLE]
        )

        left_variables = variable_entries.copy()
        undefined_variables: List[str] = []
        is_current_updated = True
        # when is_current_updated, it means one of variable is processed, and
        #  it's ok to loop again. If it's false, there are some variables cannot
        #  be resolved.
        while left_variables and is_current_updated:
            is_current_updated = False
            undefined_variables = []
            # solved variable will be removed later, so use a copy here to prevent
            #  operate enumerating collection.
            for entry in left_variables.copy():
                # this value is used to detect whether value used undefined variables.
                # in final merge, the referred variable may be defined later than used.
                # So it should to load referred variables firstly.
                checked_value = f"{entry.file}{entry.value}"

                current_undefined_variables = _get_undefined_variables(
                    checked_value, current_variables
                )
                if current_undefined_variables:
                    undefined_variables.extend(current_undefined_variables)
                    continue

                if entry.file:
                    path = replace_variables(entry.file, current_variables)
                    loaded_variables = _load_from_file(path, is_secret=entry.is_secret)
                else:
                    value = replace_variables(entry.value, current_variables)
                    loaded_variables = load_from_variable_entry(
                        entry.name,
                        value,
                        is_case_visible=entry.is_case_visible,
                        is_secret=entry.is_secret,
                        mask=entry.mask,
                    )
                merge_variables(current_variables, loaded_variables)
                merge_variables(current_variables, higher_level_variables)
                is_current_updated = True

                left_variables.remove(entry)
        if undefined_variables:
            raise LisaException(f"variables are undefined: {undefined_variables}")
    return current_variables


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
        try:
            entry = convert_to_variable_entry(raw_value, is_secret=is_secret)
            raw_value = entry.value
            is_secret = is_secret or entry.is_secret
            is_case_visible = entry.is_case_visible
            mask = entry.mask
        except AssertionError:
            # if parsing is failed, regard the raw_value as a value.
            is_case_visible = False
            mask = ""
        results.update(
            load_from_variable_entry(
                key,
                raw_value=raw_value,
                is_secret=is_secret,
                is_case_visible=is_case_visible,
                mask=mask,
            )
        )
    return results


def get_case_variables(variables: Dict[str, VariableEntry]) -> Dict[str, Any]:
    return {
        name: value.data for name, value in variables.items() if value.is_case_visible
    }


def add_secrets_from_pairs(
    raw_pairs: Optional[List[str]],
) -> Dict[str, VariableEntry]:
    """
    Given a list of command line style pairs of [s]:key:value tuples,
    take the ones prefixed with "s:" and make them recorded
    secrets. At the end, also return a dictionary of those tuples
    (still with raw values).

    """
    results: Dict[str, VariableEntry] = {}
    if raw_pairs is None:
        return results
    for raw_pair in raw_pairs:
        is_secret = False
        if raw_pair.lower().startswith("s:"):
            is_secret = True
            raw_pair = raw_pair[2:]
        try:
            key, value = raw_pair.split(":", 1)
        except Exception as e:
            raise LisaException(
                f"failed on parsing variable '{raw_pair}'. The right format is "
                f"like name:value. If there is whitespace in the value, quote "
                f'the whole string like "name:value has whitespace". If It\'s a '
                'secret variable, follow the formant "s:name:value"'
                f"The raw error: {e}"
            )
        _add_variable(key, value, results, is_secret=is_secret)
    return results


def convert_to_variable_entry(
    raw_value: Any, is_secret: bool = False
) -> schema.Variable:
    assert isinstance(raw_value, dict), f"actual {type(raw_value)}"
    entry = schema.load_by_type(schema.Variable, raw_value)
    entry.is_secret = is_secret or entry.is_secret

    return entry


def load_from_variable_entry(
    name: str,
    raw_value: Any,
    is_secret: bool = False,
    is_case_visible: bool = False,
    mask: str = "",
) -> Dict[str, VariableEntry]:
    assert isinstance(name, str), f"actual: {type(name)}"
    results: Dict[str, VariableEntry] = {}
    if type(raw_value) in [str, int, bool, float, list, dict, type(None)]:
        value = raw_value
    elif isinstance(raw_value, schema.Variable):
        value = raw_value.value
        is_secret = raw_value.is_secret
        is_case_visible = raw_value.is_case_visible
        mask = raw_value.mask
    else:
        raise LisaException(
            f"unsupported variable type on '{name}': "
            f"{type(raw_value)}, value: {raw_value}"
        )
    _add_variable(
        name,
        value,
        results,
        is_secret=is_secret,
        is_case_visible=is_case_visible,
        mask_pattern_name=mask,
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
                            "make sure its value filled in runbook, "
                            "command line or environment variables."
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
    is_case_visible: bool = False,
    mask_pattern_name: str = "",
) -> None:
    key = key.lower()
    variable = current_variables.get(key, None)
    if variable:
        variable.data = value
        variable.is_case_visible = variable.is_case_visible or is_case_visible
    else:
        variable = VariableEntry(name=key, data=value, is_case_visible=is_case_visible)
        current_variables[key] = variable

    pattern = None
    if is_secret:
        if mask_pattern_name:
            pattern = secret.patterns.get(mask_pattern_name, None)
            if pattern is None:
                raise LisaException(f"cannot find mask pattern: {mask_pattern_name}")
        secret.add_secret(value, mask=pattern)
