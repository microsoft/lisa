"""Runs 'LIS-Tests.xml' using Pytest."""
from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from target import AzureCLI

import pytest

from lisa import LISA


@LISA(platform="Azure", category="Functional", priority=0, area="LIS_DEPLOY")
@pytest.mark.skip(reason="Scripts missing")
def test_lis_driver_version(target: AzureCLI) -> None:
    """Checks that the installed drivers have the correct version."""
    # TODO: Include “utils.sh” automatically? Or something...
    for f in ["utils.sh", "LIS-VERSION-CHECK.sh"]:
        target.conn.put(f)
        target.conn.run(f"chmod +x {f}")
    target.conn.sudo("yum install -y bc")
    target.conn.run("./LIS-VERSION-CHECK.sh")
    assert target.cat("state.txt") == "TestCompleted"
