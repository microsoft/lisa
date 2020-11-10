"""Runs 'LIS-Tests.xml' using Pytest."""
from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from azure import Azure

from lisa import LINUX_SCRIPTS, LISA


@LISA(platform="Azure", category="Functional", priority=0, area="LIS_DEPLOY")
def test_lis_driver_version(target: Azure) -> None:
    # TODO: Include “utils.sh” automatically? Or something...
    for f in ["utils.sh", "LIS-VERSION-CHECK.sh"]:
        target.put(LINUX_SCRIPTS / f)
        target.run(f"chmod +x {f}")
    target.sudo("yum install -y bc")
    target.run("./LIS-VERSION-CHECK.sh")
    assert target.cat("state.txt") == "TestCompleted"
