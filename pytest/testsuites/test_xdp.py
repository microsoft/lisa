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
@pytest.mark.deploy(
    setup="OneVM2NIC",
    networking="SRIOV",
    vm_image="Canonical:0001-com-ubuntu-server-focal:20_04-lts:latest",
    vm_size="Standard_DS4_v2",
)
@pytest.mark.skip(reason="Not Finished")
def test_verify_xdp_compliance(node: Node) -> None:
    for f in [
        "utils.sh",
        "XDPDumpSetup.sh",
        "XDPUtils.sh",
        "enable_passwordless_root.sh",
        "enable_root.sh",
    ]:
        node.put(conftest.LINUX_SCRIPTS / f)
        node.run(f"chmod +x {f}")
    node.run("./enable_root.sh")
    node.run("./enable_passwordless_root.sh")
    synth_interface = node.run("source XDPUtils.sh ; get_extra_synth_nic").stdout
    node.run(f"./XDPDumpSetup.sh {node.internal_address} {synth_interface}")
    assert node.cat("state.txt") == "TestCompleted"
