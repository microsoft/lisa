"""Pytest plugin implementing a Node fixture for running remote commands."""
from io import BytesIO
from typing import Iterator

import _pytest
from fabric import Config, Connection  # type: ignore

import pytest


class Node(Connection):
    """Extends 'fabric.Connection' with our own utilities."""

    def cat(self, path: str) -> str:
        """Gets the value of a remote file without a temporary file."""
        with BytesIO() as buf:
            self.get(path, buf)
            return buf.getvalue().decode("utf-8").strip()


@pytest.fixture
def node(request: _pytest.fixtures.FixtureRequest) -> Iterator[Node]:
    """Yields a safe remote Node on which to run commands."""
    # TODO: The deploy and connect markers should be mutually
    # exclusive.
    host = "localhost"

    # Deploy a node.
    deploy_marker = request.node.get_closest_marker("deploy")
    if deploy_marker:
        pass

    # Get the host from the test’s marker.
    connect_marker = request.node.get_closest_marker("connect")
    if connect_marker:
        host = connect_marker.args[0]

    # Yield the configured Node connection.
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
    with Node(host, config=config, inline_ssh_env=True) as n:
        yield n
