from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, cast

import yaml
from marshmallow import Schema

from lisa import schema
from lisa.util import LisaException, constants
from lisa.util.logger import get_logger
from lisa.util.module import import_module
from lisa.variable import (
    VariableEntry,
    load_from_env,
    load_from_pairs,
    load_from_runbook,
    replace_variables,
)

_schema: Optional[Schema] = None

_get_init_logger = partial(get_logger, "init", "runbook")


def _load_extend_paths(current_path: Path, data: Any) -> List[str]:
    result: List[str] = []
    if constants.EXTENSION in data:
        raw_extension = data[constants.EXTENSION]
        if isinstance(raw_extension, Dict):
            # for compatibility, convert extension to list of strings
            raw_extension = schema.Extension.schema().load(  # type:ignore
                data[constants.EXTENSION]
            )
            raw_extension = raw_extension.paths
        result = [
            str(current_path.joinpath(path).absolute().resolve())
            for path in raw_extension
        ]
    return result


def _merge_variables(
    merged_path: Path, merged_data: Dict[str, Any], existing_data: Dict[str, Any]
) -> List[Any]:
    variables: List[schema.Variable] = []
    if constants.VARIABLE in merged_data and merged_data[constants.VARIABLE]:
        variables = [
            schema.Variable.schema().load(variable)  # type: ignore
            for variable in merged_data[constants.VARIABLE]
        ]
        # resolve to absolute path
        for variable in variables:
            if variable.file:
                variable.file = str((merged_path / variable.file).resolve())
    if constants.VARIABLE in existing_data and existing_data[constants.VARIABLE]:
        existing_variables: List[schema.Variable] = [
            schema.Variable.schema().load(variable)  # type: ignore
            for variable in existing_data[constants.VARIABLE]
        ]

        # remove duplicate items
        for existing_variable in existing_variables:
            for variable in variables:
                if (variable.name and variable.name == existing_variable.name) or (
                    variable.file and variable.file == existing_variable.file
                ):
                    variables.remove(variable)
                    break
        variables.extend(existing_variables)

    # serialize back for loading together
    return [variable.to_dict() for variable in variables]  # type: ignore


def _merge_extensions(
    merged_path: Path, merged_data: Dict[str, Any], existing_data: Dict[str, Any]
) -> List[Any]:
    old_extensions = _load_extend_paths(merged_path, merged_data)
    extensions = _load_extend_paths(constants.RUNBOOK_PATH, existing_data)
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
    merged_path: Path, merged_data: Dict[str, Any], existing_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    merge parent data to existing data. The existing data has higher priority.
    """
    result = merged_data.copy()

    # merge others
    result.update(existing_data)

    # merge variables, latest should be effective last
    variables = _merge_variables(merged_path, merged_data, existing_data)
    if variables:
        result[constants.VARIABLE] = variables

    # merge extensions
    extensions = _merge_extensions(merged_path, merged_data, existing_data)
    if extensions:
        result[constants.EXTENSION] = extensions

    return result


def _load_data(path: Path, used_path: Set[str]) -> Any:
    """
    Load runbook, but not to validate. It will be validated after extension imported.
    To support partial runbooks, it loads recursively.
    """

    with open(path, "r") as file:
        data = yaml.safe_load(file)

    if constants.PARENT in data and data[constants.PARENT]:
        parents_config = data[constants.PARENT]

        log = _get_init_logger()
        indent = len(used_path) * 4 * " "
        # log.debug(f"{indent}found {len(parents_config)} parent runbooks")
        merged_data: Dict[str, Any] = {}
        for parent_config in parents_config:
            parent: schema.Parent = schema.Parent.schema().load(  # type: ignore
                parent_config
            )
            if parent.strategy:
                raise NotImplementedError("Parent doesn't implement Strategy")

            raw_path = parent.path
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
            parent_data = _load_data(parent_path, used_path=new_used_path)
            merged_data = _merge_data(parent_path.parent, parent_data, merged_data)
        data = _merge_data(path.parent, merged_data, data)

    return data


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


def load_runbook(path: Path, user_variables: Optional[List[str]]) -> schema.Runbook:
    """
    Loads a runbook given a user-supplied path and set of variables.
    """
    constants.RUNBOOK_PATH = path.parent

    # load lisa itself modules
    base_module_path = Path(__file__).parent.parent
    import_module(base_module_path, logDetails=False)

    # merge all parameters
    log = _get_init_logger()
    log.info(f"loading runbook: {path}")
    data = _load_data(path.absolute(), set())

    # load extended modules
    if constants.EXTENSION in data:
        _import_extends(_load_extend_paths(constants.RUNBOOK_PATH, data))

    # load arg variables
    variables: Dict[str, VariableEntry] = dict()
    variables.update(load_from_runbook(data))
    variables.update(load_from_env())
    variables.update(load_from_pairs(user_variables))

    # replace variables:
    try:
        data = replace_variables(data, variables)
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
