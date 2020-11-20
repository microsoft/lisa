"""Runs a 'smoke' test for an Azure Linux VM deployment."""
from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from target import Azure

import logging
import socket
import time

from invoke.runners import CommandTimedOut, Result, UnexpectedExit  # type: ignore
from paramiko import SSHException  # type: ignore

from lisa import LISA


@LISA(
    platform="Azure",
    category="Functional",
    area="deploy",
    priority=0,
    sku="Standard_DS2_v2",
)
def test_smoke(target: Azure) -> None:
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
        ping1 = target.ping()
    except UnexpectedExit:
        logging.warning(f"Pinging {target.host} before reboot failed")

    ssh_errors = (TimeoutError, CommandTimedOut, SSHException, socket.error)

    try:
        logging.info("SSHing before reboot...")
        target.connection.open()
    except ssh_errors as e:
        logging.warning(f"SSH before reboot failed: '{e}'")

    reboot_exit = 0
    try:
        logging.info("Rebooting...")
        # If this succeeds, we should expect the exit code to be -1
        reboot_exit = target.sudo("reboot", timeout=5).exited
    except ssh_errors as e:
        logging.warning(f"SSH failed, using platform to reboot: '{e}'")
        target.platform_restart()
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
        ping2 = target.ping()
    except UnexpectedExit:
        logging.warning(f"Pinging {target.host} after reboot failed")

    try:
        logging.info("SSHing after reboot...")
        target.connection.open()
    except ssh_errors as e:
        logging.warning(f"SSH after reboot failed: '{e}'")

    logging.info("Retrieving boot diagnostics...")
    try:
        target.get_boot_diagnostics()
    except UnexpectedExit:
        logging.warning("Retrieving boot diagnostics failed.")
    else:
        logging.info("See full report for boot diagnostics.")

    # NOTE: The test criteria is to fail only if ping fails.
    assert ping1.ok
    assert ping2.ok
