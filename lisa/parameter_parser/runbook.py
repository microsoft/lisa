from argparse import Namespace
from dataclasses import field, make_dataclass
from functools import partial
from pathlib import Path, PurePath
from typing import Any, Dict, List, Optional, Tuple, Type, cast

import yaml
from marshmallow import Schema
from marshmallow import validate as marshmallow_validate

from lisa import schema
from lisa.environment import environments, load_environments
from lisa.platform_ import initialize_platforms, load_platforms, platforms
from lisa.sut_orchestrator.ready import ReadyPlatform
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
    if not path.exists():
        raise FileNotFoundError(path)

    with open(path, "r") as file:
        data = yaml.safe_load(file)

    return data


def _load_extends(base_path: Path, extends_runbook: schema.Extension) -> None:
    for p in extends_runbook.paths:
        path = PurePath(p)
        if not path.is_absolute():
            path = base_path.joinpath(path)
        import_module(Path(path))


def _inner_validate(runbook: schema.Runbook) -> None:
    if runbook.environment:
        log = _get_init_logger()
        for environment in environments.values():
            if environment.runbook is not None and isinstance(
                platforms.default, ReadyPlatform
            ):
                log.warn_or_raise(
                    runbook.environment.warn_as_error,
                    "the ready platform cannot process environment requirement",
                )


def _set_schema_class(
    schema_type: Type[Any], updated_fields: Optional[List[Tuple[str, Any, Any]]] = None
) -> None:
    if updated_fields is None:
        updated_fields = []
    setattr(
        schema,
        schema_type.__name__,
        make_dataclass(
            schema_type.__name__, fields=updated_fields, bases=(schema_type,),
        ),
    )


def _update_platform_schema() -> None:
    # load platform extensions
    platform_fields: List[Tuple[str, Any, Any]] = []
    node_fields: List[Tuple[str, Any, Any]] = []
    platform_field_names: List[str] = []

    # 1. discover extension schemas and construct new field
    for platform in platforms.values():
        platform_type_name = platform.platform_type()

        platform_schema = platform.platform_schema
        if platform_schema:
            platform_field = (
                platform_type_name,
                Optional[platform_schema],
                field(default=None),
            )
            platform_fields.append(platform_field)
            platform_field_names.append(platform_type_name)
        node_schema = platform.node_schema
        if node_schema:
            node_field = (
                platform_type_name,
                Optional[node_schema],
                field(default=None),
            )
            node_fields.append(node_field)

    # 2. refresh data class in schema platform and environment
    if platform_fields or node_fields:
        if platform_fields:
            # add in platform type
            platform_with_type_fields = platform_fields.copy()
            platform_field_names.append(constants.PLATFORM_READY)
            type_field = (
                constants.TYPE,
                str,
                field(
                    default=constants.PLATFORM_READY,
                    metadata=schema.metadata(
                        required=True,
                        validate=marshmallow_validate.OneOf(platform_field_names),
                    ),
                ),
            )
            platform_with_type_fields.append(type_field)
            # refresh platform
            _set_schema_class(schema.Platform, platform_with_type_fields)
            schema.Platform.supported_types = platform_field_names

        if node_fields:
            # refresh node requirement, and chain dataclasses
            _set_schema_class(schema.NodeSpace, node_fields)

            requirements_in_env = (
                constants.ENVIRONMENTS_NODES_REQUIREMENT,
                Optional[List[schema.NodeSpace]],
                field(default=None),
            )
            _set_schema_class(schema.Environment, [requirements_in_env])
            env_in_envroot = (
                constants.ENVIRONMENTS,
                Optional[List[schema.Environment]],
                field(default=None),
            )
            _set_schema_class(schema.EnvironmentRoot, [env_in_envroot])

        platform_in_runbook = (
            constants.PLATFORM,
            List[schema.Platform],
            field(default_factory=list),
        )
        environment_in_runbook = (
            constants.ENVIRONMENT,
            Optional[schema.EnvironmentRoot],
            field(default=None),
        )
        _set_schema_class(schema.Runbook, [platform_in_runbook, environment_in_runbook])


def validate_data(data: Any) -> schema.Runbook:
    _update_platform_schema()

    global _schema
    if not _schema:
        _schema = schema.Runbook.schema()  # type: ignore

    assert _schema
    runbook = cast(schema.Runbook, _schema.load(data))

    _inner_validate(runbook=runbook)

    log = _get_init_logger()
    log.debug(f"final runbook: {runbook.to_dict()}")  # type: ignore

    return runbook


def load(args: Namespace) -> schema.Runbook:
    # make sure extension in lisa is loaded
    base_module_path = Path(__file__).parent
    import_module(base_module_path, logDetails=False)

    initialize_platforms()

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
    # initialize environment
    load_environments(runbook.environment)

    # initialize platform
    load_platforms(runbook.platform)

    return runbook
