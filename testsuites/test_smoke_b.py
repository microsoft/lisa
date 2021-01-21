from __future__ import annotations  # For type checking.

import typing

if typing.TYPE_CHECKING:
    from target import AzureCLI
    from _pytest.logging import LogCaptureFixture
    from pathlib import Path

import logging
import socket
import time

from invoke.runners import CommandTimedOut, UnexpectedExit  # type: ignore
from paramiko import SSHException  # type: ignore

from lisa import LISA


@LISA(platform="Azure", category="Functional", area="deploy", priority=0)
def test_smoke(target: AzureCLI, caplog: LogCaptureFixture, tmp_path: Path) -> None:
    """Check that an Azure Linux VM can be deployed and is responsive.

    This example uses exactly one function for the entire test, which
    means we have to catch failures that don't fail the test, and
    instead emit warnings. It works, and it's closer to how LISAv2
    would have implemented it, but it's less Pythonic. For a more
    "modern" example, see `test_smoke_a.py`.

    1. Deploy the VM (via `target` fixture).
    2. Ping the VM.
    3. Connect to the VM via SSH.
    4. Attempt to reboot via SSH, otherwise use the platform.
    5. Fetch the serial console logs AKA boot diagnostics.

    SSH failures DO NOT fail this test.

    """
    # Capture INFO and above logs for this test.
    caplog.set_level(logging.INFO)

    logging.info("Pinging before reboot...")
    ping1 = target.ping()

    ssh_errors = (TimeoutError, CommandTimedOut, SSHException, socket.error)

    try:
        logging.info("SSHing before reboot...")
        target.conn.open()
    except ssh_errors as e:
        logging.warning(f"SSH before reboot failed: '{e}'")

    reboot_exit = 0
    try:
        logging.info("Rebooting...")
        # If this succeeds, we should expect the exit code to be -1
        reboot_exit = target.conn.sudo("reboot", timeout=5).exited
    except ssh_errors as e:
        logging.warning(f"SSH failed, using platform to reboot: '{e}'")
        target.platform_restart()
    except UnexpectedExit:
        # TODO: How do we differentiate reboot working and the SSH
        # connection disconnecting for other reasons?
        if reboot_exit != -1:
            logging.warning("While SSH worked, 'reboot' command failed")

    # TODO: We should check something more concrete here instead of
    # sleeping an arbitrary amount of time.
    logging.info("Sleeping for 10 seconds after reboot...")
    time.sleep(10)

    logging.info("Pinging after reboot...")
    ping2 = target.ping()

    try:
        logging.info("SSHing after reboot...")
        target.conn.open()
    except ssh_errors as e:
        logging.warning(f"SSH after reboot failed: '{e}'")

    logging.info("Retrieving boot diagnostics...")
    path = tmp_path / "diagnostics.txt"
    try:
        # NOTE: It’s actually more interesting to emit the downloaded
        # boot diagnostics to `stdout` as they’re then captured in the
        # HTML report, but this is to demo using `tmp_path`.
        diagnostics = target.get_boot_diagnostics(hide=True)
        path.write_text(diagnostics.stdout)
    except UnexpectedExit:
        logging.warning("Retrieving boot diagnostics failed.")
    else:
        logging.info(f"See '{path}' for boot diagnostics.")

    # NOTE: The test criteria is to fail only if ping fails.
    assert ping1.ok, f"Pinging {target.host} before reboot failed"
    assert ping2.ok, f"Pinging {target.host} after reboot failed"
