"""Provides and parameterizes the `pool` and `target` fixtures.

# TODO
* Deallocate targets when switching to a new target.
* Use richer feature/requirements comparison for targets.
* Reimplement caching of targets between runs.

"""
from __future__ import annotations

import logging
import typing

import playbook
import pytest

# See https://pypi.org/project/schema/
from schema import Literal, Optional, Or, Schema  # type: ignore
from target.target import SSH, Target

if typing.TYPE_CHECKING:
    from typing import Any, Dict, Iterator, List, Type

    from _pytest.config import Config
    from _pytest.config.argparsing import Parser
    from _pytest.fixtures import SubRequest
    from _pytest.python import Metafunc


def pytest_addoption(parser: Parser) -> None:
    """Pytest hook to add our CLI options."""
    group = parser.getgroup("target")
    group.addoption("--keep-vms", action="store_true", help="Keeps deployed VMs.")


def pytest_configure(config: Config) -> None:
    """Pytest hook to perform initial configuration.

    We're registering our custom marker so that it passes
    `--strict-markers`.

    """
    config.addinivalue_line(
        "markers",
        ("target(platform, features, reuse, count): " "Specify target requirements."),
    )


platforms: Dict[str, Type[Target]] = dict()


def pytest_playbook_schema(schema: Dict[Any, Any]) -> None:
    """pytest-playbook hook to update the playbook schema.

    The `platforms` global is a mapping of platform names (strings) to
    the implementing subclasses of `Target` where each subclass
    defines its own parameters `schema`, optional `defaults`,
    `deploy`, `delete` methods, and other platform-specific
    functionality. A `Target` subclass need only be defined in a file
    loaded by Pytest, so a `conftest.py` file works just fine.

    """
    # Map the subclasses of `Target` into name and class pairs, used
    # by `get_target` to lookup the type based on the name.
    global platforms
    platforms = {cls.__name__: cls for cls in Target.__subclasses__()}  # type: ignore

    # The platform schema is an optional mapping of the platform name
    # to defaults for its provided schema. Setting the defaults here
    # is a bit particular, as we need to have the schema library parse
    # the given dict as a schema, and fill in the nested defaults.
    platform_description = "The class name of the platform implementation."
    platform_schemas = {
        Optional(
            platform,
            default=Schema(cls.defaults()).validate({}),
            description=platform_description,
        ): Schema(cls.defaults(), name=f"{platform}_defaults", as_reference=True)
        for platform, cls in platforms.items()
    }
    # TODO: Assert that the set of key names in each `defaults()` is a
    # subset of the key names in the corresponding `schema()`.
    schema[
        Optional(
            "platforms",
            default=Schema(platform_schemas).validate({}),
            description="Default values for each platform.",
        )
    ] = platform_schemas

    # The targets schema is a list of dicts where each dict is ‘any
    # of’ (`Or`) the platforms’ schemata, with the addition of a
    # required ‘platform’ key matching the class name, and a friendly
    # name for the target itself (which should be unique).
    target_schemas = [
        Schema(
            {
                # We’re adding ‘name’ and ‘platform’ keys to each
                # platform’s schema.
                Literal("name", description="A friendly name for the target."): str,
                Literal("platform", description=platform_description): platform,
                # Unpack the rest of the schema’s items.
                **cls.schema(),
            },
            name=f"{platform}_schema",
            as_reference=True,
        )
        for platform, cls in platforms.items()
    ]
    # TODO: Perhaps elevate ‘name’ to the key, with the nested schema
    # as the value.
    target_schema = Or(*target_schemas)
    default_target = {
        "name": "Default",
        "platform": "SSH",
        **Schema(SSH.schema()).validate({}),  # Fill in the defaults
    }
    schema[Optional("targets", default=[default_target])] = [target_schema]


@pytest.fixture(scope="session")
def pool(request: SubRequest) -> Iterator[List[Target]]:
    """This fixture tracks all deployed target resources."""
    targets: List[Target] = []
    yield targets
    for t in targets:
        if not request.config.getoption("keep_vms"):
            logging.debug(f"Deleting target '{t.name}'")
            t.delete()


def get_target(
    pool: List[Target],
    request: SubRequest,
) -> Target:
    """This function gets or creates an appropriate `Target`.

    First check if any existing target in the `pool` matches all the
    `features` and other requirements. If so, we can re-use that
    target, and if not, we can deallocate the currently running target
    and allocate a new one. When all tests are finished, the pool
    fixture above will delete all created VMs. We can achieve
    two-layer scheduling by implementing a custom scheduler in
    pytest-xdist via `pytest_xdist_make_scheduler` and sorting the
    tests such that they're grouped by features.

    """
    # Alias because we use it a lot in this function.
    params: Dict[Any, Any] = request.param
    # Get the intended class for this parameterization of `target`.
    platform: Type[Target] = platforms[params["platform"]]

    # Get the required features for this test.
    marker = request.node.get_closest_marker("target")
    features = set(marker.kwargs.get("features", []))

    # TODO: If `t` is not already in use, deallocate the previous
    # target, and ensure the tests have been sorted (and so grouped)
    # by their requirements.
    for t in pool:
        # TODO: Implement full feature comparison, etc. and not just
        # proof-of-concept string set comparison.
        if (
            isinstance(t, platform)
            # NOTE: This is not the same as `t.name`!
            and t.params["name"] == params["name"]
            and t.features >= features
        ):
            pool.remove(t)
            return t
    else:
        # TODO: Reimplement caching.
        logging.debug(f"Creating target '{params}' with features '{features}'")
        t = platform(None, params, features)
        return t


def cleanup_target(pool: List[Target], request: SubRequest, t: Target) -> None:
    """This is called by fixtures after they're done with a target."""
    t.conn.close()
    marker = request.node.get_closest_marker("target")
    if marker.kwargs.get("reuse", True):
        pool.append(t)
    else:
        t.delete()


@pytest.fixture
def target(pool: List[Target], request: SubRequest) -> Iterator[Target]:
    """This fixture provides a connected target for each test.

    It is parametrized indirectly in `pytest_generate_tests`.

    """
    t = get_target(pool, request)
    yield t
    cleanup_target(pool, request, t)


@pytest.fixture
def targets(pool: List[Target], request: SubRequest) -> Iterator[List[Target]]:
    """This fixture obtains N targets for a test."""
    marker = request.node.get_closest_marker("target")
    count = marker.kwargs.get("count", 1)
    # TODO: Support sharing a `name` across the targets such that
    # they’re in the same logical group for any platform.
    ts = [get_target(pool, request) for _ in range(count)]
    yield ts
    for t in ts:
        cleanup_target(pool, request, t)


@pytest.fixture(scope="class")
def c_target(pool: List[Target], request: SubRequest) -> Iterator[Target]:
    """This fixture is the same as `target` but shared across a class."""
    t = get_target(pool, request)
    yield t
    cleanup_target(pool, request, t)


@pytest.fixture(scope="module")
def m_target(pool: List[Target], request: SubRequest) -> Iterator[Target]:
    """This fixture is the same as `target` but shared across a module."""
    t = get_target(pool, request)
    yield t
    cleanup_target(pool, request, t)


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
