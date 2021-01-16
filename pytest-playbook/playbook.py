# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""A plugin for creating, validating, and reading a playbook.

Use the :py:meth:`~Hooks.pytest_playbook_schema` hook to modify the
`schema`_ dictionary representing the data expected to be read and
validated from a ``playbook.yaml`` `YAML`_ file, the path to which is
provided by the user with the command-line flag
``--playbook=<data.yaml>``.

.. _schema: https://github.com/keleshev/schema
.. _YAML: https://pyyaml.org/wiki/PyYAMLDocumentation

This module's :py:data:`data` attribute will hold the read and
validated data after all :py:func:`pytest_configure` hooks have run.
Use it in your ``conftest.py`` (or Pytest plugin) like so:

.. code-block:: python

   import playbook
   from schema import Schema

   def pytest_playbook_schema(schema):
       schema["targets"] = Schema({"name": str, "platform": str, "cpus": int})

   def pytest_sessionstart(session):
       for target in playbook.data["targets"]:
           print(target["name"])

Remember not to use ``from playbook import data`` because then the
attribute will not contain the shared data. Instead use ``import
playbook`` and reference :py:data:`playbook.data`.

All registered schema can be printed to a `JSON Schema`_ file with
``--print-schema=<file.json>``.

.. _JSON Schema: https://json-schema.org/

"""

from __future__ import annotations

import json
import typing
import warnings
from pathlib import Path

import yaml  # TODO: Optionally load yaml.
from schema import Schema, SchemaError  # type: ignore

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

        :param schema: mutable dict passed to ``schema.validate()`` in :py:func:`pytest_configure`.
        :param config: optional, allows access to Pytest ``Config`` object if given.

        """


# Now provide the hook implementations.
def pytest_addhooks(pluginmanager: PytestPluginManager) -> None:
    """Pytest `addhooks hook`_ to register our hooks.

    .. _addhooks hook: https://docs.pytest.org/en/stable/reference.html#pytest.hookspec.pytest_addhooks

    """
    pluginmanager.add_hookspecs(Hooks)


def pytest_addoption(parser: Parser, pluginmanager: PytestPluginManager) -> None:
    """Pytest `addoption hook`_ to add our CLI options.

    .. _addoption hook: https://docs.pytest.org/en/stable/reference.html#pytest.hookspec.pytest_addoption

    """
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
    """Pytest `configure hook`_ to configure our plugin.

    .. _configure hook: https://docs.pytest.org/en/stable/reference.html#pytest.hookspec.pytest_configure

    This is set to be tried last so that all other plugins and
    ``conftest.py`` files have been loaded and defined their
    :py:meth:`~Hooks.pytest_playbook_schema` hooks.

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
