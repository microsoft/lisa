"""Describes the YAML schema for the playbook file.

This module should be imported at runtime such that 'PLATFORMS' is
defined after all 'Target' subclasses have been defined.

PLATFORMS is a mapping of platform names (strings) to the implementing
subclass of 'Target' where each subclass defines its own 'parameters'
schema, 'deploy' and 'delete' methods, and other platform-specific
functionality. A 'Target' subclass need only be defined in a file
loaded by Pytest, so a 'contest.py' file works just fine. No manual
registration is required, it will be discovered automatically.

TODO: Add field annotations, friendly error reporting, automatic case
transformations, etc.

"""
from __future__ import annotations

import typing

# See https://pypi.org/project/schema/
from schema import Optional, Or, Schema  # type: ignore

from target import Target

if typing.TYPE_CHECKING:
    from typing import Mapping, Type

# See https://github.com/python/mypy/issues/4717 for why we ignore the type.
PLATFORMS: Mapping[str, Type[Target]] = {
    cls.__name__: cls for cls in Target.__subclasses__()  # type: ignore
}

target_schema = Schema(
    {
        "name": str,
        "platform": Or(*[platform for platform in PLATFORMS.keys()]),
        # TODO: What should we do when lacking parameters? Ideally we
        # use the platform’s defaults from its own schema, but that
        # means this value must be set, even if to an empty dict.
        Optional("parameters", default=dict): Or(
            *[cls.schema for cls in PLATFORMS.values()]
        ),
    }
)

default_target = {"name": "Default", "platform": "Local"}

criteria_schema = Schema(
    {
        # TODO: Validate that these strings are valid regular
        # expressions if we change our matching logic.
        Optional("name", default=None): str,
        Optional("area", default=None): str,
        Optional("category", default=None): str,
        Optional("priority", default=None): int,
        Optional("tags", default=list): [str],
        Optional("times", default=1): int,
        Optional("exclude", default=False): bool,
    }
)

schema = Schema(
    {
        Optional("targets", default=[default_target]): [target_schema],
        Optional("criteria", default=list): [criteria_schema],
    }
)
