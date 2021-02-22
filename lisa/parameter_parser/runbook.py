from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

import yaml
from marshmallow import Schema

from lisa import schema
from lisa.util import constants
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


def _load_data(path: Path) -> Any:
    """
    load runbook, not to validate it, since some extended runbooks are not ready
    before extended modules imported.
    """

    log = _get_init_logger()
    log.info(f"load runbook from: {path}")
    with open(path, "r") as file:
        data = yaml.safe_load(file)

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
    """Loads a runbook given a user-supplied path and set of variables."""
    # make sure extension in lisa is loaded
    base_module_path = Path(__file__).parent.parent
    import_module(base_module_path, logDetails=False)

    # merge all parameters
    data = _load_data(path)
    constants.RUNBOOK_PATH = path.parent

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
