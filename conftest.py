"""This file sets up custom plugins.

https://docs.pytest.org/en/stable/writing_plugins.html

"""
from __future__ import annotations

import typing

import playbook

# See https://pypi.org/project/schema/
from schema import Optional, Or, Schema, SchemaMissingKeyError  # type: ignore

import azure  # noqa
import lisa
import pytest
from target import Target

if typing.TYPE_CHECKING:
    from typing import Any, Dict, Iterator, List, Type

    from _pytest.config import Config
    from _pytest.config.argparsing import Parser
    from _pytest.fixtures import SubRequest
    from _pytest.python import Metafunc

    from pytest import Item, Session

pytest_plugins = ["playbook"]


@pytest.fixture(scope="session")
def pool(request: SubRequest) -> Iterator[List[Target]]:
    """This fixture tracks all deployed target resources."""
    targets: List[Target] = []
    yield targets
    for t in targets:
        print(f"Created target: {t.features} / {t.parameters}")
        if not request.config.getoption("keep_vms"):
            t.delete()


@pytest.fixture
def target(pool: List[Target], request: SubRequest) -> Iterator[Target]:
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
    platform: Type[Target] = platforms[request.param["platform"]]
    parameters: Dict[str, Any] = request.param["parameters"]
    marker = request.node.get_closest_marker("lisa")
    features = set(marker.kwargs["features"])

    # TODO: If `t` is not already in use, deallocate the previous
    # target, and ensure the tests have been sorted (and so grouped)
    # by their requirements.
    for t in pool:
        # TODO: Implement full feature comparison, etc. and not just
        # proof-of-concept string set comparison.
        if (
            isinstance(t, platform)
            and t.parameters == parameters
            and t.features >= features
        ):
            yield t
            break
    else:
        # TODO: Reimplement caching.
        t = platform(parameters, features)
        pool.append(t)
        yield t
    t.connection.close()


def pytest_addoption(parser: Parser) -> None:
    """Pytest hook for adding arbitrary CLI options.

    https://docs.pytest.org/en/latest/example/simple.html
    https://docs.pytest.org/en/latest/reference.html#pytest.hookspec.pytest_addoption

    """
    parser.addoption("--keep-vms", action="store_true", help="Keeps deployed VMs.")
    parser.addoption("--check", action="store_true", help="Run semantic analysis.")
    parser.addoption("--demo", action="store_true", help="Run in demo mode.")


platforms: Dict[str, Type[Target]] = dict()


def pytest_playbook_schema(schema: Dict[Any, Any], config: Config) -> None:
    """Describes the YAML schema for the playbook file.

    'platforms' is a mapping of platform names (strings) to the
    implementing subclass of 'Target' where each subclass defines its
    own 'parameters' schema, 'deploy' and 'delete' methods, and other
    platform-specific functionality. A 'Target' subclass need only be
    defined in a file loaded by Pytest, so a 'contest.py' file works
    just fine. No manual subclass of 'Target' where each subc ass
    defines its own 'parameters' schema, 'deploy' and 'delete'
    methods, and other platform-specific functionality. A 'Target'
    subclass need only be defined in a file loaded by Pytest, so a 'c

    TODO: Add field annotations, friendly error reporting, automatic
    case transformations, etc.

    """
    global platforms
    platforms = {cls.__name__: cls for cls in Target.__subclasses__()}  # type: ignore
    target_schema = Schema(
        {
            "name": str,
            "platform": Or(*[platform for platform in platforms.keys()]),
            # TODO: What should we do when lacking parameters? Ideally we
            # use the platform’s defaults from its own schema, but that
            # means this value must be set, even if to an empty dict.
            Optional("parameters", default=dict): Or(
                *[cls.schema for cls in platforms.values()]
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

    schema[Optional("targets", default=[default_target])] = [target_schema]
    schema[Optional("criteria", default=list)] = [criteria_schema]


targets: List[Dict[str, Any]] = []
target_ids: List[str] = []


def pytest_sessionstart(session: Session) -> None:
    """Determines the targets based on the playbook."""
    for t in playbook.playbook.get("targets", []):
        targets.append(t)
        target_ids.append(t["name"])


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


def pytest_generate_tests(metafunc: Metafunc) -> None:
    """Parametrize the tests based on our inputs.

    Note that this hook is run for each test, so we do the file I/O in
    'pytest_configure' and save the results.

    https://docs.pytest.org/en/latest/reference.html#pytest.hookspec.pytest_generate_tests

    """
    if "target" in metafunc.fixturenames:
        metafunc.parametrize("target", targets, True, target_ids)


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
