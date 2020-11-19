"""A plugin for creating, validating, and reading a playbook.

Use the `pytest_playbook_schema` hook to modify the schema dictionary
representing the data expected to be read and validated from a
`playbook.yaml` file, the path to which is provided by the user with
the command-line flag `--playbook`.

This module's `playbook` attribute will hold the read and validated
data after all `pytest_configure` hooks have run. See
`pytest_playbook_schema` for example usage.

Remember not to use `from playbook import playbook` because then the
attribute will not contain the shared data. Instead use `import
playbook` and reference `playbook.playbook`.

"""

from __future__ import annotations

import typing
from pathlib import Path

import yaml  # TODO: Optionally load yaml.
from schema import Schema  # type: ignore

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

# TODO: I’m not a fan of this name.
playbook: Dict[Any, Any] = dict()


class Hooks:
    """Provides the hook specifications."""

    @pytest.hookspec
    def pytest_playbook_schema(self, schema: Dict[Any, Any], config: Config) -> None:
        """Update the Playbook's schema dict.

        The 'schema' is a mutable dict, and 'config' is optional.
        Example usage::

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


@pytest.hookimpl(trylast=True)
def pytest_configure(config: Config) -> None:
    """Pytest hook to configure our plugin.

    This is set to be tried last so that all other plugins have been
    loaded and defined their `pytest_playbook_schema` hooks.

    """
    path: Optional[Path] = config.getoption("playbook")
    if not path or not path.is_file():
        # TODO: Log an appropriate warning.
        return

    schema: Dict[Any, Any] = dict()
    config.hook.pytest_playbook_schema(schema=schema, config=config)

    global playbook
    with open(path) as f:
        # TODO: Handle ‘SchemaMissingKeyError’.
        playbook = Schema(schema).validate(yaml.load(f, Loader=Loader))
