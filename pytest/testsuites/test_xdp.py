"""Runs 'FunctionalTests-XDP.xml' using Pytest."""


import pytest
from conftest import LINUX_SCRIPTS, LISA
from target import Target


@LISA(
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
def test_verify_xdp_compliance(target: Target) -> None:
    for f in [
        "utils.sh",
        "XDPDumpSetup.sh",
        "XDPUtils.sh",
        "enable_passwordless_root.sh",
        "enable_root.sh",
    ]:
        target.put(LINUX_SCRIPTS / f)
        target.run(f"chmod +x {f}")
    target.run("./enable_root.sh")
    target.run("./enable_passwordless_root.sh")
    synth_interface = target.run("source XDPUtils.sh ; get_extra_synth_nic").stdout
    target.run(f"./XDPDumpSetup.sh {target.internal_address} {synth_interface}")
    assert target.cat("state.txt") == "TestCompleted"
