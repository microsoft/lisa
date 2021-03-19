# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, cast

import yaml
from marshmallow import Schema

from lisa import schema
from lisa.util import LisaException, constants
from lisa.util.logger import get_logger
from lisa.util.module import import_module
from lisa.variable import VariableEntry, load_variables, replace_variables

_schema: Optional[Schema] = None

_get_init_logger = partial(get_logger, "init", "runbook")


def _load_extend_paths(
    current_path: Path, data: Any, variables: Optional[Dict[str, VariableEntry]] = None
) -> List[str]:
    result: List[str] = []
    if constants.EXTENSION in data:
        raw_extension = data[constants.EXTENSION]
        if isinstance(raw_extension, Dict):
            # for compatibility, convert extension to list of strings
            raw_extension = schema.Extension.schema().load(  # type:ignore
                data[constants.EXTENSION]
            )
            raw_extension = raw_extension.paths
        # support variables in extension paths
        if variables:
            raw_extension = replace_variables(raw_extension, variables=variables)
        result = [
            str(current_path.joinpath(path).absolute().resolve())
            for path in raw_extension
        ]
    return result


def _merge_variables(
    merged_path: Path,
    data_from_parent: Dict[str, Any],
    data_from_current: Dict[str, Any],
) -> List[Any]:
    variables_from_parent: List[schema.Variable] = []
    if constants.VARIABLE in data_from_parent and data_from_parent[constants.VARIABLE]:
        variables_from_parent = [
            schema.Variable.schema().load(variable)  # type: ignore
            for variable in data_from_parent[constants.VARIABLE]
        ]
        # resolve to absolute path
        for parent_variable in variables_from_parent:
            if parent_variable.file:
                parent_variable.file = str(
                    (merged_path / parent_variable.file).resolve()
                )
    if (
        constants.VARIABLE in data_from_current
        and data_from_current[constants.VARIABLE]
    ):
        variables_from_current: List[schema.Variable] = [
            schema.Variable.schema().load(variable)  # type: ignore
            for variable in data_from_current[constants.VARIABLE]
        ]

        # remove duplicate items
        for current_variable in variables_from_current:
            for parent_variable in variables_from_parent:
                if (
                    parent_variable.name
                    and parent_variable.name == current_variable.name
                ) or (
                    parent_variable.file
                    and parent_variable.file == current_variable.file
                ):
                    variables_from_parent.remove(parent_variable)
                    break
        variables_from_parent.extend(variables_from_current)

    # serialize back for loading together
    return [variable.to_dict() for variable in variables_from_parent]  # type: ignore


def _merge_extensions(
    merged_path: Path,
    data_from_parent: Dict[str, Any],
    data_from_current: Dict[str, Any],
) -> List[Any]:
    old_extensions = _load_extend_paths(merged_path, data_from_parent)
    extensions = _load_extend_paths(constants.RUNBOOK_PATH, data_from_current)
    # remove duplicate paths
    for old_extension in old_extensions:
        for extension in extensions:
            if extension == old_extension:
                extensions.remove(extension)
                break
    if extensions or old_extensions:
        # don't change the order, old ones should be imported earlier.
        old_extensions.extend(extensions)
        extensions = old_extensions
    return extensions


def _merge_data(
    merged_path: Path,
    data_from_parent: Dict[str, Any],
    data_from_current: Dict[str, Any],
) -> Dict[str, Any]:
    """
    merge parent data to data_from_current. The current data has higher priority.
    """
    result = data_from_parent.copy()

    # merge others
    result.update(data_from_current)

    # merge variables, latest should be effective last
    variables = _merge_variables(merged_path, data_from_parent, data_from_current)
    if variables:
        result[constants.VARIABLE] = variables

    # merge extensions
    extensions = _merge_extensions(merged_path, data_from_parent, data_from_current)
    if extensions:
        result[constants.EXTENSION] = extensions

    return result


def _load_data(path: Path, used_path: Set[str], cmd_variables_args: List[str]) -> Any:
    """
    Load runbook, but not to validate. It will be validated after extension imported.
    To support partial runbooks, it loads recursively.
    """

    with open(path, "r") as file:
        data_from_current = yaml.safe_load(file)

    variables = load_variables(data_from_current, cmd_variables_args=cmd_variables_args)

    if constants.PARENT in data_from_current and data_from_current[constants.PARENT]:
        parents_config = data_from_current[constants.PARENT]

        log = _get_init_logger()
        indent = len(used_path) * 4 * " "

        data_from_parent: Dict[str, Any] = {}
        for parent_config in parents_config:
            try:
                parent: schema.Parent = schema.Parent.schema().load(  # type: ignore
                    parent_config
                )
            except Exception as identifer:
                raise LisaException(
                    f"error on loading parent node [{parent_config}]: {identifer}"
                )
            if parent.strategy:
                raise NotImplementedError("Parent doesn't implement Strategy")

            raw_path = parent.path
            if variables:
                raw_path = replace_variables(raw_path, variables)
            if raw_path in used_path:
                raise LisaException(
                    f"cycle reference parent runbook detected: {raw_path}"
                )

            # use relative path to parent runbook
            parent_path = (path.parent / raw_path).resolve().absolute()
            log.debug(f"{indent}loading parent: {raw_path}")

            # clone a set to support same path is used in different tree.
            new_used_path = used_path.copy()
            new_used_path.add(raw_path)
            parent_data = _load_data(
                parent_path,
                used_path=new_used_path,
                cmd_variables_args=cmd_variables_args,
            )
            data_from_parent = _merge_data(
                parent_path.parent, parent_data, data_from_parent
            )
        data_from_current = _merge_data(
            path.parent, data_from_parent, data_from_current
        )

    return data_from_current


def _import_extends(extends_runbook: List[str]) -> None:
    for index, path in enumerate(extends_runbook):
        import_module(Path(path), index=index)


def validate_data(data: Any) -> schema.Runbook:
    global _schema
    if not _schema:
        _schema = schema.Runbook.schema()  # type: ignore

    assert _schema
    runbook = cast(schema.Runbook, _schema.load(data))

    log = _get_init_logger()
    log.debug(f"merged runbook: {runbook.to_dict()}")  # type: ignore

    return runbook


def load_runbook(
    path: Path, cmd_variables_args: Optional[List[str]] = None
) -> schema.Runbook:
    """
    Loads a runbook given a user-supplied path and set of variables.
    """
    constants.RUNBOOK_PATH = path.parent
    constants.RUNBOOK_FILE = path

    if cmd_variables_args is None:
        cmd_variables_args = []

    # load lisa itself modules
    base_module_path = Path(__file__).parent.parent
    import_module(base_module_path, logDetails=False)

    # merge all parameters
    log = _get_init_logger()
    log.info(f"loading runbook: {path}")
    data = _load_data(path.absolute(), set(), cmd_variables_args=cmd_variables_args)

    # load final variables
    variables = load_variables(runbook_data=data, cmd_variables_args=cmd_variables_args)

    # load extended modules
    if constants.EXTENSION in data:
        _import_extends(_load_extend_paths(constants.RUNBOOK_PATH, data, variables))

    # replace variables:
    try:
        data = replace_variables(data, variables)
        constants.RUNBOOK = json.dumps(data, indent=2)
    except Exception as identifier:
        # log current runbook for troubleshooting.
        log.info(f"current runbook: {data}")
        raise identifier

    # log message for unused variables, it's helpful to see which variable is not used.
    log = _get_init_logger()
    unused_keys = [key for key, value in variables.items() if not value.is_used]
    if unused_keys:
        log.debug(f"variables {unused_keys} are not used.")

    # validate runbook, after extensions loaded
    runbook = validate_data(data)

    log = _get_init_logger()
    constants.RUN_NAME = f"lisa_{runbook.name}_{constants.RUN_ID}"
    log.info(f"run name is '{constants.RUN_NAME}'")
    return runbook
