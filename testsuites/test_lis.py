"""Runs 'LIS-Tests.xml' using Pytest."""
from pathlib import Path

import pytest
from node_plugin import Node

LINUX_SCRIPTS = Path("../Testscripts/Linux")


@pytest.mark.host("centos")
def test_lis_driver_version(node: Node) -> None:
    # TODO: Include “utils.sh” automatically? Or something...
    for f in ["utils.sh", "LIS-VERSION-CHECK.sh"]:
        node.put(LINUX_SCRIPTS / f)
        node.run(f"chmod +x {f}")
    node.sudo("yum install -y bc")
    node.run("./LIS-VERSION-CHECK.sh")
    assert node.cat("state.txt") == "TestCompleted"
