"""A plugin for organizing, analyzing, and selecting tests.

This plugin provides the mark `pytest.mark.lisa`, aliased as `LISA`,
for marking up tests metadata beyond that which Pytest provides by
default. See the `lisa_schema` for the expected metadata input.

Tests can be selected through a `playbook.yaml` file using the
criteria schema. For example::

    criteria:
      # Select all Priority 0 tests.
      - priority: 0
      # Run tests with 'smoke' in the name twice.
      - name: smoke
        times: 2
      # Exclude all tests in Area "xdp"
      - area: xdp
        exclude: true

# TODO:
* Provide test metadata statistics via a command-line flag.
* Assert every test has a LISA marker.
* Remove 'features' from marker.

"""
from __future__ import annotations

import re
import sys
import typing

import playbook
import py
import pytest
from schema import Literal, Optional, Or, Schema, SchemaMissingKeyError  # type: ignore
from xdist.scheduler.loadscope import LoadScopeScheduling  # type: ignore

if typing.TYPE_CHECKING:
    from typing import Any, Dict, List

    from _pytest.config import Config
    from _pytest.mark.structures import Mark
    from pytest import Item, Session

LISA = pytest.mark.lisa


def main() -> None:
    """Wrapper function so we can have a `lisa` binary."""
    sys.exit(pytest.main())


def pytest_configure(config: Config) -> None:
    """Pytest hook to perform initial configuration.

    We're registering our custom marker so that it passes
    `--strict-markers`.

    """
    config.addinivalue_line(
        "markers",
        (
            "lisa(platform, category, area, priority, features, tags): "
            "Annotate a test with metadata."
        ),
    )


def pytest_playbook_schema(schema: Dict[Any, Any]) -> None:
    """pytest-playbook hook to update the playbook schema."""
    # TODO: We also want to support a criteria selection on each
    # `target` in the playbook, which this top-level criteria being
    # the default.
    criteria_schema = Schema(
        {
            # TODO: Should any/all of the strings be regex comparisons?
            Optional(
                "name", description="Substring match of test name.", default=None
            ): str,
            Optional(
                "module",
                description="Substring match of test file (Python module).",
                default=None,
            ): str,
            Optional(
                "area",
                description="Case-folded equality comparison of test's area.",
                default=None,
            ): str,
            Optional(
                "category",
                description="Case-folded equality comparison of test's category.",
                default=None,
            ): str,
            Optional(
                "priority",
                # TODO: Should this instead be a range comparison?
                description="Equality comparison of test's priority.",
                default=None,
            ): int,
            Optional(
                "tags", description="Subset comparison of test's tags.", default=list
            ): [str],
            Optional(
                "times",
                description="Number of times to run the matched tests.",
                default=1,
            ): int,
            Optional(
                "exclude",
                description="Exclude the matched tests instead.",
                default=False,
            ): bool,
        }
    )
    schema[Optional("criteria", default=list)] = [criteria_schema]


lisa_schema = Schema(
    {
        # TODO: Move platform to `pytest.mark.target`.
        Literal("platform", description="The test's intended platform."): str,
        Literal("category", description="The kind of test this is."): Or(
            "Functional", "Performance", "Stress", "Community", "Longhaul"
        ),
        Literal("area", description="The test's area (or 'feature')."): str,
        Literal(
            "priority", description="The test's priority with 0 being the highest."
        ): Or(0, 1, 2, 3),
        # TODO: Move `features` to `pytest.mark.target` and don’t
        # allow extra keys.
        Optional("features", default=list): [str],
        Optional(
            "tags",
            description="An arbitrary set of tags used for selection.",
            default=list,
        ): [str],
        Optional(object): object,
    },
    ignore_extra_keys=True,
)


def validate_mark(mark: typing.Optional[Mark]) -> None:
    """Validate each test's LISA parameters."""
    if not mark:
        # TODO: `assert mark, "LISA marker is missing!"` but not all
        # tests will have it, such as static analysis tests.
        return
    assert not mark.args, "LISA marker cannot have positional arguments!"
    mark.kwargs.update(lisa_schema.validate(mark.kwargs))  # type: ignore


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
            validate_mark(item.get_closest_marker("lisa"))
        except (SchemaMissingKeyError, AssertionError) as e:
            pytest.exit(f"Error validating test '{item.name}' metadata: {e}")

    # Optionally select tests based on a playbook.
    included: List[Item] = []
    excluded: List[Item] = []

    def select(item: Item, times: int, exclude: bool) -> None:
        """Includes or excludes the item as appropriate."""
        if exclude:
            excluded.append(item)
        else:
            for _ in range(times - included.count(item)):
                included.append(item)

    for c in playbook.data.get("criteria", []):
        for item in items:
            mark = item.get_closest_marker("lisa")
            if not mark:
                # Not all tests will have the LISA marker, such as
                # static analysis tests.
                continue
            i = mark.kwargs
            if any(
                [
                    c["name"] and c["name"] in item.name,
                    # NOTE: `Item` does have a `module` field, though it’s untyped.
                    c["module"] and c["module"] in item.module.__name__,  # type: ignore
                    c["area"] and c["area"].casefold() == i["area"].casefold(),
                    c["category"]
                    and c["category"].casefold() == i["category"].casefold(),
                    c["priority"] and c["priority"] == i["priority"],
                    c["tags"] and set(c["tags"]) <= set(i["tags"]),
                ]
            ):
                select(item, c["times"], c["exclude"])
    # Handle edge case of no items selected for inclusion.
    if not included:
        included = items
    items[:] = [i for i in included if i not in excluded]


class LISAScheduling(LoadScopeScheduling):
    """Implement load scheduling across nodes, but grouping by parameter.

    This algorithm ensures that all tests which share the same set of
    parameters (namely the target) will run on the same executor as a
    single work-unit.

    TODO: This essentially confines the targets and one target won't
    be spun up multiple times when run in parallel, so we should make
    this scheduler optional, as an alternative scenario is to spin up
    multiple near-identical instances of a target in order to run
    tests in parallel.

    This is modeled after the built-in `LoadFileScheduling`, which
    also simply subclasses `LoadScopeScheduling`. See `_split_scope`
    for the important part. Note that we can extend this to implement
    any kind of scheduling algorithm we want.

    """

    def __init__(self, config: Config, log=None):  # type: ignore
        super().__init__(config, log)
        if log is None:
            self.log = py.log.Producer("lisasched")
        else:
            self.log = log.lisasched

    # NOTE: Needs to handle whitespace, so can’t be `\w+`.
    regex = re.compile(r"\[Target=([^\[\]]+)\]")

    def _split_scope(self, nodeid: str) -> str:
        """Determine the scope (grouping) of a `nodeid`.

        Example of a parameterized test's `nodeid`:

        * ``example/test_module.py::test_function[Target=A]``
        * ``example/test_module.py::test_function[A][Target=B]``
        * ``example/test_module.py::test_function_extra[A][B][Target=C]``

        `LoadScopeScheduling` uses ``nodeid.rsplit("::", 1)[0]``, or
        the first ``::`` from the right, to split by scope, such that
        classes will be grouped, then modules. ``LoadFileScheduling``
        uses ``nodeid.split("::", 1)[0]``, or the first ``::`` from
        the left, to instead split only by modules (Python files).

        We opportunistically find the "Target" parameter and use it as
        the scope. If the target parameter is missing then we simply
        fallback to the algorithm of `LoadScopeScheduling`. So the
        above would map into the scopes: 'A', 'B', and 'C'.

        >>> class Config:
        ...     def getoption(self, option):
        ...         return False
        ...     def getvalue(self, value):
        ...         return ["popen"]
        >>> s = LISAScheduling(Config())
        >>> s._split_scope("example/test_module.py::test_function[Target=A][B][C]")
        'A'
        >>> s._split_scope("example/test_module.py::test_function[A][Target=B][C]")
        'B'
        >>> s._split_scope("example/test_module.py::test_function[A][B][Target=C]")
        'C'
        >>> s._split_scope("example/test_module.py::test_function")
        'example/test_module.py'
        >>> s._split_scope("example/test_module.py::test_class::test_function")
        'example/test_module.py::test_class'

        """
        search = self.regex.search(nodeid)
        if search:
            scope = search.group(1)
            if self.config.getoption("verbose"):
                self.log(f"Split nodeid '{nodeid}' into scope '{scope}'")
            return scope
        return super()._split_scope(nodeid)  # type: ignore


def pytest_xdist_make_scheduler(config: Config) -> LISAScheduling:
    """pytest-xdist hook for implementing a custom scheduler.

    https://github.com/pytest-dev/pytest-xdist/blob/master/OVERVIEW.md

    """
    return LISAScheduling(config)
