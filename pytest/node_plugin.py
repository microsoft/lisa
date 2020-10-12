"""Pytest plugin implementing a Node fixture for running remote commands."""
from io import BytesIO
from typing import Iterator

from fabric import Config, Connection  # type: ignore

import pytest


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
