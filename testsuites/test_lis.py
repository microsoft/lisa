from io import BytesIO
from pathlib import Path
from typing import Iterator

from fabric import Config, Connection  # type: ignore

import pytest

LINUX_SCRIPTS = Path("../Testscripts/Linux")


class Node(Connection):
    """Extends 'fabric.Connection' with our own utilities."""

    def cat(self, path: str) -> str:
        """Gets the value of a remote file without a temporary file."""
        with BytesIO() as buf:
            self.get(path, buf)
            return buf.getvalue().decode("utf-8").strip()


# TODO: Make the hostname a parameter.
@pytest.fixture
def node() -> Iterator[Node]:
    """Yields a safe remote Node on which to run commands."""
    config = Config(
        overrides={
            "run": {
                # Show each command as its run.
                "echo": True,
                # Disable stdin forwarding.
                "in_stream": False,
                # Set PATH since it’s not a login shell.
                "env": {"PATH": "$PATH:/usr/local/sbin:/usr/sbin"},
            }
        }
    )
    with Node("centos", config=config, inline_ssh_env=True) as n:
        yield n


def test_lis_driver_version(node: Node) -> None:
    # TODO: Include “utils.sh” automatically? Or something...
    for f in ["utils.sh", "LIS-VERSION-CHECK.sh"]:
        node.put(LINUX_SCRIPTS / f)
        node.run(f"chmod +x {f}")
    node.sudo("yum install -y bc")
    node.run("./LIS-VERSION-CHECK.sh")
    assert node.cat("state.txt") == "TestCompleted"
