"""Check that an Azure Linux VM can be deployed and is responsive.

This example uses multiple tests with a module-scoped target fixture.
It's a more Pythonic approach, and since Pytest automatically groups
tests by fixture scopes, these run for each parameter of the target in
order as we would expect. This results in the "smoke test" actually
being a module of multiple unit tests. Another similar alternative is
to use a class and the class-scoped target fixture. See
`test_smoke_b.py` for the single-test approach.

"""
from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from target import AzureCLI

import socket
import time

import pytest
from invoke.runners import CommandTimedOut, UnexpectedExit  # type: ignore
from paramiko import SSHException  # type: ignore

from lisa import LISA

pytestmark = [
    LISA(
        platform="Azure",
        category="Functional",
        area="deploy",
        priority=0,
    ),
    pytest.mark.target,
]


def test_first_ping(m_target: AzureCLI) -> None:
    """"Pinging before reboot..."""
    assert m_target.ping(), f"Pinging {m_target.host} before reboot failed"


def test_first_ssh(m_target: AzureCLI) -> None:
    """SSHing before reboot..."""
    assert m_target.conn.open(), f"SSH {m_target.host} before reboot failed"


def test_reboot(m_target: AzureCLI) -> None:
    """Rebooting..."""
    reboot_exit = 0
    try:
        # If this succeeds, we should expect the exit code to be -1
        reboot_exit = m_target.conn.sudo("reboot", timeout=5).exited
    except (TimeoutError, CommandTimedOut, SSHException, socket.error) as e:
        print(f"SSH failed, using platform to reboot: '{e}'")
        m_target.platform_restart()
    except UnexpectedExit:
        # TODO: How do we differentiate reboot working and the SSH
        # connection disconnecting for other reasons?
        assert reboot_exit == -1, "While SSH worked, 'reboot' command failed"
    finally:
        print("Sleeping for 10 seconds after reboot...")
        time.sleep(10)


def test_second_ping(m_target: AzureCLI) -> None:
    """Pinging after reboot..."""
    assert m_target.ping(), f"Pinging {m_target.host} after reboot failed"


def test_second_ssh(m_target: AzureCLI) -> None:
    """SSHing after reboot..."""
    assert m_target.conn.open(), f"SSH {m_target.host} after reboot failed"


def test_boot_diagnostics(m_target: AzureCLI) -> None:
    """Retrieving boot diagnostics..."""
    m_target.get_boot_diagnostics()
