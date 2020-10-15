"""Runs a 'smoke' test for an Azure Linux VM deployment."""
import platform
import socket

from invoke.runners import Result  # type: ignore
from paramiko import SSHException

import pytest
from node_plugin import Node


@pytest.mark.deploy(setup="OneVM", vm_size="Standard_DS2_v2")
def test_smoke(node: Node) -> None:
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
    TODO: Log warnings instead of printing.
    """
    # TODO: Move to ‘Node.ping()’
    ping_flag = "-c 1" if platform.system() == "Linux" else "-n 1"
    # TODO: Can’t ping by default, need to enable.
    ping1_result: Result = node.local(f"ping {ping_flag} {node.host}", warn=True)

    try:
        node.run("uptime")  # If SSH fails, we catch it.
        reboot_result: Result = node.sudo("reboot", warn=True)  # Expect -1
    except (TimeoutError, SSHException, socket.error) as e:
        print(f"SSH failed '{e}', using platform to reboot...")
        node.platform_restart()

    # Try pinging and SSH again.
    ping2_result: Result = node.local(f"ping {ping_flag} {node.host}", warn=True)

    try:
        node.run("uptime")
    except (TimeoutError, SSHException, socket.error) as e:
        print(f"SSH failed '{e}' after the reboot.")

    # Always download the serial console logs.
    node.get_boot_diagnostics()

    assert ping1_result.ok
    assert reboot_result.exited == -1, "Reboot failed, used platform instead"
    assert ping2_result.ok
