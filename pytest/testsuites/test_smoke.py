"""Runs a 'smoke' test for an Azure Linux VM deployment."""
import logging
import socket
import time

from invoke.runners import CommandTimedOut, Result, UnexpectedExit  # type: ignore
from paramiko import SSHException  # type: ignore

import pytest
from node_plugin import Node

# TODO: This is an example of leveraging Pytest’s parameterization
# support. We can implement a small YAML parser to read a playbook at
# runtime to generate this instead of using the below list.
params = [
    pytest.param(i, marks=pytest.mark.deploy(vm_image=i, vm_size="Standard_DS2_v2"))
    for i in [
        "citrix:netscalervpx-130:netscalerbyol:latest",
        "audiocodes:mediantsessionbordercontroller:mediantvirtualsbcazure:latest",
        "credativ:Debian:9:9.0.201706190",
        "github:github-enterprise:github-enterprise:latest",
    ]
]


@pytest.mark.parametrize("urn", params)
@pytest.mark.flaky(reruns=1)
def test_smoke(urn: str, node: Node) -> None:
    """Check that a VM can be deployed and is responsive.

    1. Deploy the VM (via 'node' fixture) and log it.
    2. Ping the VM.
    3. Connect to the VM via SSH.
    4. Attempt to reboot via SSH, otherwise use the platform.
    5. Fetch the serial console logs.

    For commands where we expect a possible non-zero exit code, we
    pass 'warn=True' to prevent it from throwing 'UnexpectedExit' and
    we instead check its result at the end.

    SSH failures DO NOT fail this test.

    """
    logging.info("Pinging before reboot...")
    ping1 = Result()
    try:
        ping1 = node.ping()
    except UnexpectedExit:
        logging.warning(f"Pinging {node.host} before reboot failed")

    ssh_errors = (TimeoutError, CommandTimedOut, SSHException, socket.error)

    try:
        logging.info("SSHing before reboot...")
        node.open()
    except ssh_errors as e:
        logging.warning(f"SSH before reboot failed: '{e}'")

    reboot_exit = 0
    try:
        logging.info("Rebooting...")
        # If this succeeds, we should expect the exit code to be -1
        reboot_exit = node.sudo("reboot", timeout=5).exited
    except ssh_errors as e:
        logging.warning(f"SSH failed, using platform to reboot: '{e}'")
        node.platform_restart()
    except UnexpectedExit:
        # TODO: How do we differentiate reboot working and the SSH
        # connection disconnecting for other reasons?
        if reboot_exit != -1:
            logging.warning("While SSH worked, 'reboot' command failed")

    logging.info("Sleeping for 10 seconds after reboot...")
    time.sleep(10)

    logging.info("Pinging after reboot...")
    ping2 = Result()
    try:
        ping2 = node.ping()
    except UnexpectedExit:
        logging.warning(f"Pinging {node.host} after reboot failed")

    try:
        logging.info("SSHing after reboot...")
        node.open()
    except ssh_errors as e:
        logging.warning(f"SSH after reboot failed: '{e}'")

    logging.info("Retrieving boot diagnostics...")
    try:
        node.get_boot_diagnostics()
    except UnexpectedExit:
        logging.warning("Retrieving boot diagnostics failed.")
    else:
        logging.info("See full report for boot diagnostics.")

    # NOTE: The test criteria is to fail only if ping fails.
    assert ping1.ok
    assert ping2.ok
