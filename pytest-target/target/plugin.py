# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Provides and parameterizes the :py:func:`.target` fixture(s).

.. TODO::

   * Deallocate targets when switching to a new target.
   * Use richer feature/requirements comparison for targets.

"""
from __future__ import annotations

import logging
import typing
import warnings
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import playbook
import pytest
from filelock import FileLock  # type: ignore

# See https://pypi.org/project/schema/
from schema import Optional, Or, Schema  # type: ignore
from target.target import SSH, Target, TargetData

if typing.TYPE_CHECKING:
    from typing import Any, Dict, Generator, Iterator, List

    from _pytest.config import Config
    from _pytest.config.argparsing import Parser
    from _pytest.fixtures import SubRequest
    from _pytest.mark.structures import Mark
    from _pytest.python import Metafunc
    from pytest import Session


def pytest_addoption(parser: Parser) -> None:
    """Pytest `addoption hook`_ to add our CLI options.

    .. _addoption hook: https://docs.pytest.org/en/stable/reference.html#pytest.hookspec.pytest_addoption

    """
    group = parser.getgroup("target")
    group.addoption(
        "--keep-targets", action="store_true", help="Keeps targets between runs."
    )
    group.addoption(
        "--delete-targets", action="store_true", help="Deletes all cached targets."
    )


def pytest_playbook_schema(schema: Dict[Any, Any]) -> None:
    """:py:mod:`playbook` hook to update the playbook schema.

    This adds ``platforms`` and ``targets`` keys to the playbook
    schema, with their nested schemata accumulated from each
    platform's implementations of
    :py:meth:`~target.target.Target.defaults` and
    :py:meth:`~target.target.Target.schema`. We do this by iterating
    over the subclasses of :py:class:`~target.target.Target`, a handy
    feature of Python that lets us automatically discover users'
    implementations, even if they're defined in a local
    ``conftest.py`` Pytest configuration file.

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


@contextmanager
def target_pool(config: Config) -> Generator[Dict[str, Any], None, None]:
    """Exclusive access to the cached targets pool.

    This handles access to the Pytest cache of serialized targets. The
    cache is a dict of ``{target.name: target.to_json()}``. We use a
    file lock to provide exclusive access even if Pytest is being run
    in parallel with `pytest-xdist`_. Entries have a ``locked``
    property and must only be modified during a session when locked by
    that session. Locking means setting ``locked`` to ``True`` and
    updating the entry before exiting this context manager.

    .. _pytest-xdist: https://github.com/pytest-dev/pytest-xdist

    """
    # TODO: Handle edge case where cache plugin is disabled.
    assert config.cache is not None
    lock = Path(config.cache.makedir("target")) / "pool.lock"
    with FileLock(str(lock)):
        pool = config.cache.get("target/pool", {})
        yield pool
        config.cache.set("target/pool", pool)


def delete_targets(config: Config) -> None:
    """Deletes all cached targets."""
    with target_pool(config) as pool:
        for name, json in pool.items():
            try:
                Target.from_json(json).delete()
            except Exception as e:
                warnings.warn(f"Failed to delete '{name}': {e}")
        pool.clear()


def pytest_configure(config: Config) -> None:
    """Pytest `configure hook`_ to perform initial configuration.

    .. _configure hook: https://docs.pytest.org/en/stable/reference.html#pytest.hookspec.pytest_configure

    We're registering our custom marker so that it passes
    ``--strict-markers``.

    """
    config.addinivalue_line(
        "markers",
        "target(platform, features, reuse, count): Specify target requirements.",
    )

    if config.getoption("delete_targets"):
        logging.info("Deleting all cached targets!")
        delete_targets(config)
        pytest.exit("Deleted all cached targets!", pytest.ExitCode.OK)


def pytest_unconfigure(config: Config) -> None:
    """Pytest `unconfigure hook`_ to perform teardown.

    .. _unconfigure hook: https://docs.pytest.org/en/stable/reference.html#pytest.hookspec.pytest_unconfigure

    """
    if not config.getoption("keep_targets"):
        # TODO: Ignore `--help` or other times tests weren’t run.
        logging.info("Deleting targets! Pass `--keep-targets` to prevent this.")
        delete_targets(config)


def get_target(request: SubRequest) -> Target:
    """Common case of getting one ``Target``."""
    marker = request.node.get_closest_marker("target")
    count = marker.kwargs.get("count", 1)
    assert count == 1, "Use `targets` fixture with `count` instead!"
    return get_targets(request).pop()


def get_targets(request: SubRequest) -> List[Target]:
    """This function gets or creates N ``Target`` instances.

    1. Unpack request into params, required features, and count
    2. Setup fitness criteria for target(s)
    3. Find or create necessary targets
    4. Return targets

    """
    params: Dict[Any, Any] = request.param
    mark: Optional[Mark] = request.node.get_closest_marker("target")
    assert mark is not None
    features = mark.kwargs.get("features", [])
    count = mark.kwargs.get("count", 1)

    targets: List[Target] = []
    with target_pool(request.config) as pool:

        def fits(t: TargetData) -> bool:
            """Checks if a given ``Target`` fits the current search criteria.

            Converting the cached JSON to a ``TargetData`` instance is
            cheap and lets us use typed fields here.

            """
            # TODO: Implement full feature comparison, etc. and not
            # just proof-of-concept string set comparison.
            logging.debug(f"Checking fit of {t}...")
            return (
                not t.locked
                and params == t.params
                and set(features) <= set(t.features)
                and count <= sum(t.group == x["group"] for x in pool.values())
            )

        # TODO: If `t` is not already in use, deallocate the previous
        # target, and ensure the tests have been sorted (and so grouped)
        # by their requirements.
        logging.debug(f"Looking for {count} target(s) which fit: {params}...")
        for i in range(count):
            for name, json in pool.items():
                if fits(TargetData(**json)):
                    logging.debug(f"Found fit target '{i}'!")
                    t = Target.from_json(json)
                    assert name == t.name  # Sanity check.
                    t.locked = True
                    pool[t.name] = t.to_json()
                    targets.append(t)
                    break  # Continue outer counting loop...
    if targets:
        assert len(targets) == count
    else:
        group = f"pytest-{uuid4()}"
        for i in range(count):
            logging.info(f"Instantiating target '{group}-{i}': {params}...")
            t = Target.from_json(
                {
                    "group": group,
                    "params": params,
                    "features": features,
                    "data": {},
                    "number": i,
                    "locked": True,
                }
            )
            with target_pool(request.config) as pool:
                pool[t.name] = t.to_json()
            targets.append(t)
    return targets


def cleanup_target(t: Target, request: SubRequest) -> None:
    """This is called by fixtures after they're done with a :py:class:`~target.target.Target`."""
    t.conn.close()
    mark: Optional[Mark] = request.node.get_closest_marker("target")
    assert mark is not None
    with target_pool(request.config) as pool:
        if mark.kwargs.get("reuse", True):
            t.locked = False
            pool[t.name] = t.to_json()
        else:
            logging.info(f"Deleting target '{t.group}/{t.number}'...")
            t.delete()
            del pool[t.name]


@pytest.fixture
def target(request: SubRequest) -> Iterator[Target]:
    """This fixture provides a connected :py:class:`~target.target.Target` for each test.

    It is parametrized indirectly in :py:func:`pytest_generate_tests`.

    """
    t = get_target(request)
    yield t
    cleanup_target(t, request)


@pytest.fixture
def targets(request: SubRequest) -> Iterator[List[Target]]:
    """This fixture is the same as :py:func:`.target` but gets a ``Target`` list.

    For example, use ``pytest.mark.target(count=2)`` to get a list of
    two targets with the same parameters, in the same group.

    """
    ts = get_targets(request)
    yield ts
    for t in ts:
        cleanup_target(t, request)


@pytest.fixture(scope="class")
def c_target(request: SubRequest) -> Iterator[Target]:
    """This fixture is the same as :py:func:`.target` but shared across a class."""
    t = get_target(request)
    yield t
    cleanup_target(t, request)


@pytest.fixture(scope="module")
def m_target(request: SubRequest) -> Iterator[Target]:
    """This fixture is the same as :py:func:`.target` but shared across a module."""
    t = get_target(request)
    yield t
    cleanup_target(t, request)


target_params: Dict[str, Dict[str, Any]] = {}


def pytest_sessionstart(session: Session) -> None:
    """Pytest `sessionstart hook`_ to setup the session.

    .. _sessionstart hook: https://docs.pytest.org/en/stable/reference.html#pytest.hookspec.pytest_sessionstart

    Gather the targets from the playbook.

    First collect any user supplied defaults from the ``platforms``
    key in the playbook, which will default to the given ``defaults``
    implemented for each platform. Copy the defaults and then
    overwrite with the target's specific parameters.

    """
    platform_defaults = playbook.data.get("platforms", {})
    for t in playbook.data.get("targets", []):
        params = platform_defaults.get(t["platform"], {}).copy()
        params.update(t)
        target_params["Target=" + t["name"]] = params


def pytest_generate_tests(metafunc: Metafunc) -> None:
    """Pytest `generate_tests hook`_ to indirectly parameterize :py:func:`.target`.

    .. _generate_tests hook: https://docs.pytest.org/en/stable/reference.html#pytest.hookspec.pytest_generate_tests

    This takes the given targets (probably from the playbook) and
    transforms them into parameters for all the tests using the
    :py:func:`.target` fixture. Since this hook is run for each test,
    so we gather the targets in :py:func:`pytest_sessionstart`.

    """
    assert target_params, "This should not be empty!"
    for f in "target", "targets", "m_target", "c_target":
        if f in metafunc.fixturenames:
            metafunc.parametrize(f, target_params.values(), True, target_params.keys())
