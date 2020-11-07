"""This file sets up custom plugins.

https://docs.pytest.org/en/stable/writing_plugins.html

"""
from __future__ import annotations

import typing
from pathlib import Path

import schema

import lisa
import playbook
import pytest

# TODO: Use importlib instead
from azure import Azure
from target import Target

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
    features = set(marker.kwargs["features"])
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
    parser.addoption("--playbook", type=Path, help="Path to playbook.")


TARGETS = []
TARGET_IDS = []


def get_playbook(path: Optional[Path]) -> dict():
    book = dict()
    if not path:
        return book
    with open(path) as f:
        book = playbook.schema.validate(f)
    return book


def pytest_configure(config: Config) -> None:
    """Parse provided user inputs to setup configuration.

    Determines the targets based on the playbook and sets default
    configurations based user mode.

    configurations based user mode."""
    book = get_playbook(config.getoption("--playbook"))
    for t in book.get("targets"):
        TARGETS.append(t)
        TARGET_IDS.append(t["name"])

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
        m = item.get_closest_marker("lisa")
        assert m, f"{item} is missing required LISA marker!"
        try:
            lisa.validate(m)
        except schema.SchemaMissingKeyError as e:
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

    book = get_playbook(config.getoption("--playbook"))
    for c in book.get("criteria"):
        print(f"Parsing criteria {c}")
        for item in items:
            m = item.get_closest_marker("lisa").kwargs
            if any(
                [
                    c["name"] and c["name"] in item.name,
                    c["area"] and c["area"].casefold() == m["area"].casefold(),
                    c["category"]
                    and c["category"].casefold() == m["category"].casefold(),
                    c["priority"] and c["priority"] == m["priority"],
                    c["tags"] and set(c["tags"]) <= set(m["tags"]),
                ]
            ):
                select(item, c["times"], c["exclude"])
    if not included:
        included = items
    items[:] = [i for i in included if i not in excluded]


def pytest_html_report_title(report):  # type: ignore
    report.title = "LISAv3 (Using Pytest) Results"
