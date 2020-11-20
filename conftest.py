"""This file sets up custom plugins.

https://docs.pytest.org/en/stable/writing_plugins.html

"""
from __future__ import annotations

import typing

import playbook

# See https://pypi.org/project/schema/
from schema import Optional, Schema, SchemaMissingKeyError  # type: ignore

import lisa

if typing.TYPE_CHECKING:
    from typing import Any, Dict, List

    from _pytest.config import Config
    from _pytest.config.argparsing import Parser

    from pytest import Item, Session

pytest_plugins = ["playbook", "target"]


def pytest_addoption(parser: Parser) -> None:
    """Pytest hook for adding arbitrary CLI options.

    https://docs.pytest.org/en/latest/example/simple.html
    https://docs.pytest.org/en/latest/reference.html#pytest.hookspec.pytest_addoption

    """
    parser.addoption("--check", action="store_true", help="Run semantic analysis.")
    parser.addoption("--demo", action="store_true", help="Run in demo mode.")


def pytest_playbook_schema(schema: Dict[Any, Any], config: Config) -> None:
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
    schema[Optional("criteria", default=list)] = [criteria_schema]


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


def pytest_collection_modifyitems(
    session: Session, config: Config, items: List[Item]
) -> None:
    """Pytest hook for modifying the selected items (tests).

    https://docs.pytest.org/en/latest/reference.html#pytest.hookspec.pytest_collection_modifyitems

    """
    # TODO: The ‘Item’ object has a ‘user_properties’ attribute which
    # is a list of tuples and could be used to hold the validated
    # marker data, simplifying later usage.

    # Validate all LISA marks.
    for item in items:
        try:
            lisa.validate(item.get_closest_marker("lisa"))
        except SchemaMissingKeyError as e:
            print(f"Test {item.name} failed LISA validation {e}!")
            items[:] = []
            return

    # Optionally select tests based on a playbook.
    included: List[Item] = []
    excluded: List[Item] = []

    # TODO: Remove logging.
    def select(item: Item, times: int, exclude: bool) -> None:
        """Includes or excludes the item as appropriate."""
        if exclude:
            print(f"    Excluding {item}")
            excluded.append(item)
        else:
            print(f"    Including {item} {times} times")
            for _ in range(times - included.count(item)):
                included.append(item)

    for c in playbook.playbook.get("criteria", []):
        print(f"Parsing criteria {c}")
        for item in items:
            marker = item.get_closest_marker("lisa")
            if not marker:
                # Not all tests will have the LISA marker, such as
                # static analysis tests.
                continue
            i = marker.kwargs
            if any(
                [
                    c["name"] and c["name"] in item.name,
                    c["area"] and c["area"].casefold() == i["area"].casefold(),
                    c["category"]
                    and c["category"].casefold() == i["category"].casefold(),
                    c["priority"] and c["priority"] == i["priority"],
                    c["tags"] and set(c["tags"]) <= set(i["tags"]),
                ]
            ):
                select(item, c["times"], c["exclude"])
    if not included:
        included = items
    items[:] = [i for i in included if i not in excluded]


def pytest_html_report_title(report):  # type: ignore
    report.title = "LISAv3 (Using Pytest) Results"
