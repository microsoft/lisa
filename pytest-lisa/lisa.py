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

TODO
====
* Provide test metadata statistics via a command-line flag.
* Improve schemata with annotations, error messages, etc.
* Assert every test has a LISA marker.
* Register custom marker.

"""
from __future__ import annotations

import typing

import playbook
import pytest
from schema import Optional, Or, Schema, SchemaMissingKeyError  # type: ignore

if typing.TYPE_CHECKING:
    from typing import Any, Dict, List

    from _pytest.config import Config
    from _pytest.mark.structures import Mark
    from pytest import Item, Session

LISA = pytest.mark.lisa


def pytest_playbook_schema(schema: Dict[Any, Any]) -> None:
    """pytest-playbook hook to update the playbook schema."""
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


lisa_schema = Schema(
    {
        "platform": str,
        "category": Or("Functional", "Performance", "Stress", "Community", "Longhaul"),
        "area": str,
        "priority": Or(0, 1, 2, 3),
        Optional("features", default=list): [str],
        Optional("tags", default=list): [str],
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

    for c in playbook.playbook.get("criteria", []):
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
