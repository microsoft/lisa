"""This file sets up custom plugins.

https://docs.pytest.org/en/stable/writing_plugins.html

"""
from __future__ import annotations

import typing
from functools import partial
from pathlib import Path

import yaml

try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader  # type: ignore

if typing.TYPE_CHECKING:
    from typing import Any, Dict, List, Optional

    from _pytest.config import Config
    from _pytest.config.argparsing import Parser

    from pytest import Item, Session

pytest_plugins = "node_plugin"


def pytest_addoption(parser: Parser) -> None:
    """Pytest hook for adding arbitrary CLI options.

    https://docs.pytest.org/en/latest/example/simple.html

    """
    parser.addoption("--keep-vms", action="store_true", help="Keeps deployed VMs.")
    parser.addoption("--check", action="store_true", help="Run semantic analysis.")
    parser.addoption("--demo", action="store_true", help="Run in demo mode.")
    parser.addoption("--playbook", type=Path, help="Path to test playbook.")


def pytest_configure(config: Config) -> None:
    """Set default configurations passed on custom flags."""
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
    playbook_path: Optional[Path] = config.getoption("--playbook")
    new_items: List[Item] = []
    force_exclude: List[Item] = []

    def select_item(action: Optional[str], times: int, item: Item) -> None:
        """Includes or excludes the item as appropriate."""
        if action == "forceExclude":
            print(f"    Forcing exclusion of item {item}")
            force_exclude.append(item)
        else:
            print(f"    Keeping {item} selected {times} times")
            for _ in range(times - new_items.count(item)):
                new_items.append(item)

    # TODO: Review, refactor, and fix logging. If we do schema
    # validation and have reasonable defaults we can delete most of
    # the `is not None` checks. Suggest using:
    # https://pypi.org/project/schema/
    if playbook_path:
        playbook = dict()
        with open(playbook_path) as f:
            playbook = yaml.load(f, Loader=Loader)
        for play in playbook:
            criteria = play.get("criteria")
            if criteria is None:
                print(f"Criteria missing, cannot parse play {play}")
                continue
            else:
                print(f"Parsing criteria {criteria}")
            select_action = play.get("select_action", "forceInclude")
            times = play.get("times", 1)
            select = partial(select_item, select_action, times)

            name = criteria.get("name")
            priority = criteria.get("priority")
            area = criteria.get("area")
            for i in items:
                marker = i.get_closest_marker("lisa")
                if marker is None:
                    # TODO: This should be a warning.
                    continue
                lisa = marker.kwargs
                if name is not None:
                    if i.name.startswith(name):
                        print(f"  Selecting test {i} because name is {name}!")
                        select(i)
                if priority is not None:
                    if lisa.get("priority") == priority:
                        print(f"  Selecting test {i} because priority is {priority}!")
                        select(i)
                if area and lisa.get("area"):
                    if lisa["area"].lower() == area:
                        print(f"  Selecting test {i} because area is {area}!")
                        select(i)
        items[:] = [i for i in new_items if i not in force_exclude]


def pytest_html_report_title(report):  # type: ignore
    report.title = "LISAv3 (Using Pytest) Results"


LINUX_SCRIPTS = Path("../Testscripts/Linux")
