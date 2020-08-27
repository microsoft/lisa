from dataclasses import field, make_dataclass
from pathlib import Path
from typing import Any, List, Optional, Tuple, Type, cast

import yaml
from marshmallow import Schema
from marshmallow import validate as marshmallow_validate

from lisa import schema
from lisa.platform_ import platforms
from lisa.util import constants
from lisa.util.logger import get_logger

_schema: Optional[Schema] = None


def load(path: Path) -> Any:
    """
    load runbook, not to validate it, since some extended runbooks are not ready
    before extended modules imported.
    """
    log = get_logger("parser")

    log.info(f"load runbook from: {path}")
    if not path.exists():
        raise FileNotFoundError(path)

    with open(path, "r") as file:
        data = yaml.safe_load(file)

    log.debug(f"final runbook: {data}")
    return data


def validate(data: Any) -> schema.Runbook:
    _load_platform_schema()

    global _schema
    if not _schema:
        _schema = schema.Runbook.schema()  # type: ignore

    assert _schema
    runbook = cast(schema.Runbook, _schema.load(data))
    return runbook


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


def _load_platform_schema() -> None:
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
            # refresh node spec, template, and chain dataclasses
            _set_schema_class(schema.NodeSpec, node_fields)
            _set_schema_class(schema.Template, node_fields)

            template_in_env = (
                constants.ENVIRONMENTS_TEMPLATE,
                Optional[schema.Template],
                field(default=None),
            )
            _set_schema_class(schema.Environment, [template_in_env])
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
