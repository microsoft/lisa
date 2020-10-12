"""Runs 'FunctionalTests-XDP.xml' using Pytest."""


import conftest
import pytest
from node_plugin import Node


@pytest.mark.lisa(
    platform="Azure",
    category="Functional",
    area="XDP",
    tags=["xdp", "network", "hv_netvsc", "sriov"],
    priority=0,
)
@pytest.mark.deploy(setup="OneVM2NIC", networking="SRIOV", vm_size="Standard_DS4_v2")
@pytest.mark.skip(reason="Not Implemented")
def test_verify_xdp_compliance(node: Node) -> None:
    for f in [
        "xdpdumpsetup.sh",
        "xdputils.sh",
        "utils.sh",
        "enable_passwordless_root.sh",
        "enable_root.sh",
    ]:
        node.put(conftest.LINUX_SCRIPTS / f)
        node.run(f"chmod +x {f}")
