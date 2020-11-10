from __future__ import annotations

import typing
from pathlib import Path

from schema import Optional, Or, Schema  # type: ignore

import pytest

if typing.TYPE_CHECKING:
    from _pytest.mark.structures import Mark

LISA = pytest.mark.lisa
LINUX_SCRIPTS = Path("../Testscripts/Linux")

# Setup a sane configuration for local and remote commands. Note that
# the defaults between Fabric and Invoke are different, so we use
# their Config classes explicitly.
config = {
    "run": {
        # Show each command as its run.
        "echo": True,
        # Disable stdin forwarding.
        "in_stream": False,
        # Don’t let remote commands take longer than five minutes
        # (unless later overridden). This is to prevent hangs.
        "command_timeout": 1200,
    }
}

lisa_schema = Schema(
    {
        "platform": str,
        "category": Or("Functional", "Performance", "Stress", "Community", "Longhaul"),
        "area": str,
        "priority": Or(0, 1, 2, 3),
        Optional("features", default=list): [str],
        Optional(object): object,
    },
    ignore_extra_keys=True,
)


def validate(mark: Optional[Mark]) -> None:
    """Validate each test's LISA parameters."""
    if not mark:
        return
    assert not mark.args, "LISA marker cannot have positional arguments!"
    mark.kwargs.update(lisa_schema.validate(mark.kwargs))
