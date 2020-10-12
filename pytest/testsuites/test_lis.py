"""Runs 'LIS-Tests.xml' using Pytest."""
import conftest
import pytest
from node_plugin import Node


@pytest.mark.lisa(
    platform="Azure", category="Functional", area="LIS_DEPLOY", tags=["lis"], priority=0
)
# @pytest.mark.deploy(setup="OneVM")
@pytest.mark.connect("centos")
def test_lis_driver_version(node: Node) -> None:
    # TODO: Include “utils.sh” automatically? Or something...
    for f in ["utils.sh", "LIS-VERSION-CHECK.sh"]:
        node.put(conftest.LINUX_SCRIPTS / f)
        node.run(f"chmod +x {f}")
    node.sudo("yum install -y bc")
    node.run("./LIS-VERSION-CHECK.sh")
    assert node.cat("state.txt") == "TestCompleted"
