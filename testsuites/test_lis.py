"""Runs 'LIS-Tests.xml' using Pytest."""
from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from target import Azure

import pytest
from lisa import LISA

from conftest import LINUX_SCRIPTS


@LISA(platform="Azure", category="Functional", priority=0, area="LIS_DEPLOY")
def test_lis_driver_version(target: Azure) -> None:
    """Checks that the installed drivers have the correct version."""
    # TODO: Include “utils.sh” automatically? Or something...
    for f in ["utils.sh", "LIS-VERSION-CHECK.sh"]:
        target.put(LINUX_SCRIPTS / f)
        target.run(f"chmod +x {f}")
    target.sudo("yum install -y bc")
    target.run("./LIS-VERSION-CHECK.sh")
    assert target.cat("state.txt") == "TestCompleted"
