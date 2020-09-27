from argparse import Namespace
from functools import partial
from pathlib import Path, PurePath
from typing import Any, Dict, Optional, cast

import yaml
from marshmallow import Schema

from lisa import schema
from lisa.util import constants
from lisa.util.logger import get_logger
from lisa.util.module import import_module
from lisa.variable import (
    load_from_env,
    load_from_pairs,
    load_from_runbook,
    replace_variables,
)

_schema: Optional[Schema] = None

_get_init_logger = partial(get_logger, "init", "runbook")


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


def _load_extends(base_path: Path, extends_runbook: schema.Extension) -> None:
    for index, p in enumerate(extends_runbook.paths):
        path = PurePath(p)
        if not path.is_absolute():
            path = base_path.joinpath(path)
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


def load(args: Namespace) -> schema.Runbook:
    # make sure extension in lisa is loaded
    base_module_path = Path(__file__).parent.parent
    import_module(base_module_path, logDetails=False)

    # merge all parameters
    path = Path(args.runbook).absolute()
    data = _load_data(path)
    constants.RUNBOOK_PATH = path.parent

    # load extended modules
    if constants.EXTENSION in data:
        extends_runbook = schema.Extension.schema().load(  # type:ignore
            data[constants.EXTENSION]
        )
        _load_extends(path.parent, extends_runbook)

    # load arg variables
    variables: Dict[str, Any] = dict()
    load_from_runbook(data, variables)
    load_from_env(variables)
    if hasattr(args, "variables"):
        load_from_pairs(args.variables, variables)

    # replace variables:
    data = replace_variables(data, variables)

    # validate runbook, after extensions loaded
    runbook = validate_data(data)

    log = _get_init_logger()
    constants.RUN_NAME = f"lisa_{runbook.name}_{constants.RUN_ID}"
    log.info(f"run name is {constants.RUN_NAME}")
    return runbook
