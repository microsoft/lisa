"""These tests are meant to run in a CI environment."""
from __future__ import annotations

import typing

import pytest

if typing.TYPE_CHECKING:
    from target import SSH
    from typing import List

from lisa import LISA


@LISA(platform="SSH", category="Functional", area="self-test", priority=1)
def test_basic(target: SSH) -> None:
    """Basic test which creates a `Target` connection to 'localhost'."""
    target.local("echo Hello World")


@LISA(platform="SSH", category="Functional", area="self-test", priority=1, count=3)
@pytest.mark.skip("Need to fix cache bug with `targets`")
def test_basic_multiple(targets: List[SSH]) -> None:
    """Basic test which asks for 3 unique targets."""
    assert len({target.name for target in targets}) == 3
