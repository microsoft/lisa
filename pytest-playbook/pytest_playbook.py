"""A plugin for creating, validating, and loading a playbook.

After the last call to 'pytest_configure', 'playbook' will be
populated with the validated data.

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


class Hooks:
    """Class which contains our hooks."""

    def pytest_playbook_schema(self, schema: Dict[Any, Any], config: Config) -> None:
        """Update the Playbook's schema dict."""


def pytest_addhooks(pluginmanager: PytestPluginManager) -> None:
    """Pytest hook to register hooks."""
    pluginmanager.add_hookspecs(Hooks)


def pytest_addoption(parser: Parser, pluginmanager: PytestPluginManager) -> None:
    """Pytest hook to add CLI options."""
    group = parser.getgroup("playbook")
    group.addoption("--playbook", type=Path, help="Path to playbook.")


playbook: Dict[Any, Any] = dict()


@pytest.hookimpl(trylast=True)
def pytest_configure(config: Config) -> None:
    """Pytest hook to configure each plugin."""
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
