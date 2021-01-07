"""A plugin for creating, validating, and reading a playbook.

Use the ``pytest_playbook_schema`` hook to modify the schema
dictionary representing the data expected to be read and validated
from a ``playbook.yaml`` file, the path to which is provided by the
user with the command-line flag ``--playbook``.

This module's ``data`` attribute will hold the read and validated data
after all ``pytest_configure`` hooks have run. See
``pytest_playbook_schema`` for example usage.

Remember not to use ``from playbook import data`` because then the
attribute will not contain the shared data. Instead use ``import
playbook`` and reference ``playbook.data``.

"""

from __future__ import annotations

import json
import typing
import warnings
from pathlib import Path

import yaml  # TODO: Optionally load yaml.
from schema import Schema, SchemaError  # type: ignore

# See https://pyyaml.org/wiki/PyYAMLDocumentation
try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader  # type: ignore

import pytest

if typing.TYPE_CHECKING:
    from typing import Any, Dict, Optional

    from _pytest.config import Config, PytestPluginManager
    from _pytest.config.argparsing import Parser

data: Dict[Any, Any] = dict()
"""This global is the data read from the given playbook."""


class Hooks:
    """Provides the hook specifications."""

    @pytest.hookspec
    def pytest_playbook_schema(self, schema: Dict[Any, Any], config: Config) -> None:
        """Update the Playbook's schema dict.

        The 'schema' is a mutable dict, and 'config' is optional.
        Example usage:

        .. code-block:: python

           import playbook
           from schema import Schema

           def pytest_playbook_schema(schema):
               schema["targets"] = Schema({"name": str, "platform": str, "cpus": int})

           def pytest_sessionstart(session):
               for target in playbook.playbook["targets"]:
                   print(target["name"])

        """


# Now provide the hook implementations.
def pytest_addhooks(pluginmanager: PytestPluginManager) -> None:
    """Pytest hook to register our hooks."""
    pluginmanager.add_hookspecs(Hooks)


def pytest_addoption(parser: Parser, pluginmanager: PytestPluginManager) -> None:
    """Pytest hook to add our CLI options."""
    group = parser.getgroup("playbook")
    group.addoption("--playbook", type=Path, help="Path to playbook.")
    group.addoption(
        "--print-schema",
        type=Path,
        help="Print the JSON schema of the playbook to the given path.",
    )


# TODO: See if this works without ‘trylast’.
@pytest.hookimpl(trylast=True)
def pytest_configure(config: Config) -> None:
    """Pytest hook to configure our plugin.

    This is set to be tried last so that all other plugins have been
    loaded and defined their ``pytest_playbook_schema`` hooks.

    """
    schema_dict: Dict[Any, Any] = dict()
    config.hook.pytest_playbook_schema(schema=schema_dict, config=config)
    schema = Schema(schema_dict)

    json_schema: Optional[Path] = config.getoption("print_schema")
    if json_schema:
        with json_schema.open("w") as f:
            json.dump(schema.json_schema(json_schema.name), f, indent=2)
        pytest.exit(f"Printed schema to {json_schema}!", pytest.ExitCode.OK)

    global data

    path: Optional[Path] = config.getoption("playbook")
    if not path or not path.is_file():
        warnings.warn("No playbook was specified, using defaults...")
        data = schema.validate({})
    else:
        try:
            with path.open() as f:
                data = yaml.load(f, Loader=Loader)
            data = schema.validate(data)
        except (yaml.YAMLError, SchemaError, OSError) as e:
            pytest.exit(
                f"Error loading playbook '{path}': {e}", pytest.ExitCode.USAGE_ERROR
            )
