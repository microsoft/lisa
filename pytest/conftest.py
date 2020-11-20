"""LISA tests' specific configurations go here.

This file is essentially the staging ground for contributions to
`pytest-lisa`, the plugin (and package). Anything that is reusable and
stable should be sent upstream.

"""
from __future__ import annotations

import typing
from pathlib import Path

if typing.TYPE_CHECKING:
    from typing import Any, Dict

    from _pytest.config import Config
    from _pytest.config.argparsing import Parser

pytest_plugins = ["playbook", "target", "lisa"]

LINUX_SCRIPTS = Path("../Testscripts/Linux")


def pytest_addoption(parser: Parser) -> None:
    """Pytest hook to add our CLI options."""
    parser.addoption("--check", action="store_true", help="Run semantic analysis.")
    parser.addoption("--demo", action="store_true", help="Run in demo mode.")


def pytest_configure(config: Config) -> None:
    """Parse provided user inputs to setup configuration.

    https://docs.pytest.org/en/latest/reference.html#pytest.hookspec.pytest_configure

    """
    # Search ‘_pytest’ for ‘addoption’ to find these.
    options: Dict[str, Any] = {}  # See ‘pytest.ini’ for defaults.
    if config.getoption("--check"):
        options.update(
            {
                "flake8": True,
                "mypy": True,
                "markexpr": "flake8 or mypy",
                "reportchars": "fE",
            }
        )
    if config.getoption("--demo"):
        options.update(
            {
                "html": "demo.html",
                "no_header": True,
                "showcapture": "log",
                "tb": "line",
            }
        )
    for attr, value in options.items():
        setattr(config.option, attr, value)


def pytest_html_report_title(report):  # type: ignore
    report.title = "LISAv3 (Using Pytest) Results"
