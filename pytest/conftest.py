"""This file sets up custom plugins.

https://docs.pytest.org/en/stable/writing_plugins.html

"""
from __future__ import annotations

import sys
import typing
from functools import partial
from pathlib import Path

import yaml

import lisa

# TODO: Use importlib instead
from azure import Azure
from target import Target

try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader  # type: ignore

import pytest

if typing.TYPE_CHECKING:
    from typing import Any, Dict, Iterator, List, Optional

    from _pytest.config import Config
    from _pytest.config.argparsing import Parser
    from _pytest.fixtures import FixtureRequest
    from _pytest.python import Metafunc

    from pytest import Item, Session


LISA = pytest.mark.lisa
LINUX_SCRIPTS = Path("../Testscripts/Linux")


@pytest.fixture(scope="session")
def pool(request: FixtureRequest) -> Iterator[List[Target]]:
    """This fixture tracks all deployed target resources."""
    targets: List[Target] = []
    yield targets
    for t in targets:
        print(f"Created target: {t.features} / {t.params}")
        if not request.config.getoption("keep_vms"):
            t.delete()


@pytest.fixture
def target(pool, worker_id, request: FixtureRequest) -> Iterator[Target]:
    """This fixture provides a connected target for each test.

    It is parametrized indirectly in 'pytest_generate_tests'.

    In this fixture we can check if any existing target matches all
    the requirements. If so, we can re-use that target, and if not, we
    can deallocate the currently running target and allocate a new
    one. When all tests are finished, the pool fixture above will
    delete all created VMs. Coupled with performing discrete
    optimization in the test collection phase and ordering the tests
    such that the test(s) with the lowest common denominator
    requirements are executed first, we have the two-layer scheduling
    as asked.

    However, this feels like putting the cart before the horse to me.
    It would be much simpler in terms of design, implementation, and
    usage that features are specified upfront when the targets are
    specified. Then all this goes away, and tests are skipped when the
    feature is missing, which also leaves users in full control of
    their environments.

    """
    params = request.param
    marker = request.node.get_closest_marker("lisa")
    features = marker.kwargs["features"]
    for t in pool:
        # TODO: Implement full feature comparison, etc. and not just
        # proof-of-concept string set comparison.
        if params == t.params and features <= t.features:
            yield t
            break
    else:
        # TODO: Reimplement caching.
        # TODO: Dynamically load platform module and use it.
        t = Azure(params, features)
        pool.append(t)
        yield t
    t.connection.close()


def pytest_addoption(parser: Parser) -> None:
    """Pytest hook for adding arbitrary CLI options.

    https://docs.pytest.org/en/latest/example/simple.html

    """
    parser.addoption("--keep-vms", action="store_true", help="Keeps deployed VMs.")
    parser.addoption("--check", action="store_true", help="Run semantic analysis.")
    parser.addoption("--demo", action="store_true", help="Run in demo mode.")
    parser.addoption("--targets", type=Path, help="Path to targets playbook.")
    parser.addoption("--criteria", type=Path, help="Path to criteria playbook.")


TARGETS = []
TARGET_IDS = []


def pytest_configure(config: Config) -> None:
    """Parse provided user inputs to setup configuration.

    Determines the targets based on the playbook and sets default
    configurations based user mode.
    """
    playbook_path: Optional[Path] = config.getoption("--targets")
    if playbook_path:
        playbook = dict()
        with open(playbook_path) as f:
            playbook = yaml.load(f, Loader=Loader)
        for play in playbook:
            t = play.get("target")
            if t is None:
                continue
            else:
                print(f"Parsing target {t}")
            setup = {
                "platform": t.get("platform", "Azure"),
                "image": t.get("image", "UbuntuLTS"),
                "sku": t.get("sku", "Standard_DS1_v2"),
            }
            TARGETS.append(setup)
            TARGET_IDS.append("-".join(setup.values()))

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


def pytest_generate_tests(metafunc: Metafunc):
    """Parametrize the tests based on our inputs.

    Note that this hook is run for each test, so we do the file I/O in
    'pytest_configure' and save the results.

    """
    # TODO: Provide a default target?
    assert TARGETS, "No targets specified!"
    if "target" in metafunc.fixturenames:
        metafunc.parametrize("target", TARGETS, True, TARGET_IDS)


def pytest_collection_modifyitems(
    session: Session, config: Config, items: List[Item]
) -> None:
    """Pytest hook for modifying the selected items (tests).

    https://docs.pytest.org/en/latest/reference.html#pytest.hookspec.pytest_collection_modifyitems

    """
    # Validate LISA mark on every item.
    for item in items:
        mark = item.get_closest_marker("lisa")
        assert mark, f"{item} is missing required LISA marker!"
        lisa.validate(mark)

    # Optionally select tests based on a playbook.
    playbook_path: Optional[Path] = config.getoption("--criteria")
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
                marker = i.get_closest_marker("LISA")
                args = marker.kwargs
                if name is not None:
                    if i.name.startswith(name):
                        print(f"  Selecting test {i} because name is {name}!")
                        select(i)
                if priority is not None:
                    if args.get("priority") == priority:
                        print(f"  Selecting test {i} because priority is {priority}!")
                        select(i)
                if area and args.get("area"):
                    if args["area"].lower() == area:
                        print(f"  Selecting test {i} because area is {area}!")
                        select(i)
        items[:] = [i for i in new_items if i not in force_exclude]


def pytest_html_report_title(report):  # type: ignore
    report.title = "LISAv3 (Using Pytest) Results"
