"""Provides and parameterizes the `pool` and `target` fixtures.

# TODO:
* Deallocate targets when switching to a new target.
* Use richer feature/requirements comparison for targets.
* Make cache compatible with pytest-xdist.
* Cleanup `targets/pool` cache with a context manager.

"""
from __future__ import annotations

import logging
import typing
from uuid import uuid4

import playbook
import pytest

# See https://pypi.org/project/schema/
from schema import Optional, Or, Schema  # type: ignore
from target.target import SSH, Target

if typing.TYPE_CHECKING:
    from typing import Any, Dict, Iterator, List

    from _pytest.config import Config
    from _pytest.config.argparsing import Parser
    from _pytest.fixtures import SubRequest
    from _pytest.python import Metafunc


def pytest_addoption(parser: Parser) -> None:
    """Pytest hook to add our CLI options."""
    group = parser.getgroup("target")
    group.addoption(
        "--keep-targets", action="store_true", help="Keeps targets between runs."
    )
    group.addoption(
        "--delete-targets", action="store_true", help="Deletes all cached targets."
    )


def pytest_configure(config: Config) -> None:
    """Pytest hook to perform initial configuration.

    We're registering our custom marker so that it passes
    `--strict-markers`.

    """
    config.addinivalue_line(
        "markers",
        "target(platform, features, reuse, count): Specify target requirements.",
    )



def pytest_playbook_schema(schema: Dict[Any, Any]) -> None:
    """pytest-playbook hook to update the playbook schema.

    This adds `platforms` and `targets` keys to the playbook schema,
    with their nested schemata accumulated from each platform's
    implementations of `defaults()` and `schema()`. We do this by
    iterating over the subclasses of `Target`, a handy feature of
    Python that lets us automatically discover users' implementations,
    even if they're defined in a local `conftest.py` Pytest
    configuration file.

    """
    classes = Target.__subclasses__()

    # The platforms schema is a set of optional mappings of each
    # platform’s name to defaults for its provided schema.
    platforms_schema = dict(cls.get_defaults() for cls in classes)
    default_platforms = Schema(platforms_schema).validate({})
    schema.update(
        {
            Optional(
                "platforms",
                default=default_platforms,
                description="A set of objects with default values for each platform.",
            ): platforms_schema
        }
    )

    # The targets schema is a list of ‘any of’ the platforms’
    # reference schemata.
    targets_schema = [Or(*(cls.get_schema() for cls in classes))]
    default_target = {
        "name": "Default",
        "platform": "SSH",
        **Schema(SSH.schema()).validate({}),  # Fill in the defaults
    }
    schema.update(
        {
            Optional(
                "targets",
                default=[default_target],
                description="A list of targets with which to parameterize the tests.",
            ): targets_schema
        }
    )


@pytest.fixture(scope="session")
def pool(request: SubRequest) -> Iterator[List[Target]]:
    """This fixture tracks all deployed target resources."""
    targets: List[Target] = []
    yield targets
    # TODO: Catch interrupts and always delete targets:
    # `UnexpectedExit`, `KeyboardInterrupt`, `SystemExit`.
    if not request.config.getoption("keep_targets"):
        logging.info("Deleting targets! Pass `--keep-targets` to prevent this.")
        for t in targets:
            t.delete()
        targets.clear()
        assert request.config.cache is not None
        request.config.cache.set("target/pool", [])


def get_target(pool: List[Target], request: SubRequest) -> Target:
    """Common case of getting one target."""
    marker = request.node.get_closest_marker("target")
    count = marker.kwargs.get("count", 1)
    assert count == 1, "Use `targets` fixture with `count` instead!"
    return get_targets(pool, request).pop()


def get_targets(pool: List[Target], request: SubRequest) -> List[Target]:
    """This function gets or creates an appropriate number of `Target`s.

    1. Update `pool` (list of targets) from the cache
    2. Unpack request into params, required features, and count
    3. Setup fitness criteria for target(s)
    4. Find or create necessary targets
    5. Update cache with modified `pool`
    6. Return targets

    """
    assert request.config.cache is not None
    # TODO: Use a file lock to handle multi-processing, and handle
    # edge case where cache plugin isn’t available.
    key = "target/pool"
    # NOTE: We’re explicitly modifying this argument.
    pool[:] = [Target.from_json(**x) for x in request.config.cache.get(key, [])]

    # Get the required params for this test.
    params: Dict[Any, Any] = request.param

    # Get the required features for this test.
    marker = request.node.get_closest_marker("target")
    features = marker.kwargs.get("features", [])
    count = marker.kwargs.get("count", 1)

    def fits(t: Target) -> bool:
        # TODO: Implement full feature comparison, etc. and not just
        # proof-of-concept string set comparison.
        logging.debug(f"Checking fit of {t.to_json()}...")
        return (
            t.free
            and params == t.params
            and set(features) <= t.features
            and count <= sum(t.group == x.group for x in pool)
        )

    # TODO: If `t` is not already in use, deallocate the previous
    # target, and ensure the tests have been sorted (and so grouped)
    # by their requirements.
    ts: List[Target] = []
    logging.debug(f"Looking for {count} target(s) which fit: {params}...")
    for i in range(count):
        for t in pool:
            if fits(t):
                logging.debug(f"Found fit target '{i}'!")
                t.free = False
                ts.append(t)
                break
        if count == len(ts):
            break
    else:
        group = f"pytest-{uuid4()}"
        for i in range(count):
            logging.info(f"Instantiating target '{group}/{i}': {params}...")
            t = Target.from_json(group, params, features, {}, i, False)
            ts.append(t)
            pool.append(t)
    request.config.cache.set(key, [x.to_json() for x in pool])
    return ts


def cleanup_target(t: Target, pool: List[Target], request: SubRequest) -> None:
    """This is called by fixtures after they're done with a target."""
    t.conn.close()
    marker = request.node.get_closest_marker("target")
    if marker.kwargs.get("reuse", True):
        # Leave in pool and mark free for use.
        t.free = True
    else:
        logging.info(f"Deleting target '{t.group}/{t.number}'...")
        t.delete()
        pool.remove(t)
    assert request.config.cache is not None
    request.config.cache.set("target/pool", [x.to_json() for x in pool])


@pytest.fixture
def target(pool: List[Target], request: SubRequest) -> Iterator[Target]:
    """This fixture provides a connected target for each test.

    It is parametrized indirectly in `pytest_generate_tests`.

    """
    t = get_target(pool, request)
    yield t
    cleanup_target(t, pool, request)


@pytest.fixture
def targets(pool: List[Target], request: SubRequest) -> Iterator[List[Target]]:
    """This fixture is the same as `target` but gets a list of targets.

    For example, use `pytest.mark.target(count=2)` to get a list of
    two targets with the same parameters, in the same group.

    """
    ts = get_targets(pool, request)
    yield ts
    for t in ts:
        cleanup_target(t, pool, request)


@pytest.fixture(scope="class")
def c_target(pool: List[Target], request: SubRequest) -> Iterator[Target]:
    """This fixture is the same as `target` but shared across a class."""
    t = get_target(pool, request)
    yield t
    cleanup_target(t, pool, request)


@pytest.fixture(scope="module")
def m_target(pool: List[Target], request: SubRequest) -> Iterator[Target]:
    """This fixture is the same as `target` but shared across a module."""
    t = get_target(pool, request)
    yield t
    cleanup_target(t, pool, request)


target_params: Dict[str, Dict[str, Any]] = {}


def pytest_sessionstart() -> None:
    """Gather the `targets` from the playbook.

    First collect any user supplied defaults from the `platforms` key
    in the playbook, which will default to the given `defaults`
    implemented for each platform. Copy the defaults and then
    overwrite with the target's specific parameters.

    """
    platform_defaults = playbook.data.get("platforms", {})
    for t in playbook.data.get("targets", []):
        params = platform_defaults.get(t["platform"], {}).copy()
        params.update(t)
        target_params["Target=" + t["name"]] = params


def pytest_generate_tests(metafunc: Metafunc) -> None:
    """Indirectly parametrize the `target` fixture based on the playbook.

    This hook is run for each test, so we gather the `targets` in
    `pytest_sessionstart`.

    """
    assert target_params, "This should not be empty!"
    for f in "target", "targets", "m_target", "c_target":
        if f in metafunc.fixturenames:
            metafunc.parametrize(f, target_params.values(), True, target_params.keys())
