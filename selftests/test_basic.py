"""These tests are meant to run in a CI environment."""
from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from target import SSH

from lisa import LISA


@LISA(platform="Local", category="Functional", area="self-test", priority=1)
def test_basic(target: SSH) -> None:
    """Basic test which creates a `Target` connection to 'localhost'."""
    target.local("echo Hello World")
