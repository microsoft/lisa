"""Pytest plugin implementing a Node fixture for running remote commands."""
import json
from io import BytesIO
from typing import Dict, Iterator
from uuid import uuid4

import _pytest
import invoke  # type: ignore
from fabric import Config, Connection  # type: ignore
from invoke.runners import Result  # type: ignore

import pytest


def install_az_cli() -> None:
    if not invoke.run("which az", warn=True, echo=False, in_stream=False):
        # TODO: Use Invoke for pipes.
        invoke.run(
            "curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash",
            echo=True,
            in_stream=False,
        )
        # TODO: Login with service principal (az login) and set
        # default subscription (az account set -s) using secrets.


def deploy_vm(
    name: str,
    location: str = "westus2",
    vm_image: str = "UbuntuLTS",
    vm_size: str = "Standard_DS1_v2",
    setup: str = "",
    networking: str = "",
) -> str:
    install_az_cli()
    invoke.run(
        f"az group create --name {name}-rg --location {location}",
        echo=True,
        in_stream=False,
    )
    vm_command = [
        "az vm create",
        f"--resource-group {name}-rg",
        f"--name {name}",
        f"--image {vm_image}",
        f"--size {vm_size}",
        "--generate-ssh-keys",
    ]
    if networking == "SRIOV":
        vm_command.append("--accelerated-networking true")
    vm_result: Result = invoke.run(
        " ".join(vm_command),
        echo=True,
        in_stream=False,
    )
    vm_data: Dict[str, str] = json.loads(vm_result.stdout)
    return vm_data["publicIpAddress"]


def delete_vm(name: str) -> None:
    invoke.run(f"az group delete --name {name}-rg --yes", echo=True)


class Node(Connection):
    """Extends 'fabric.Connection' with our own utilities."""

    def cat(self, path: str) -> str:
        """Gets the value of a remote file without a temporary file."""
        with BytesIO() as buf:
            self.get(path, buf)
            return buf.getvalue().decode("utf-8").strip()


# TODO: Scope this to a module.
@pytest.fixture
def node(request: _pytest.fixtures.FixtureRequest) -> Iterator[Node]:
    """Yields a safe remote Node on which to run commands."""
    # TODO: The deploy and connect markers should be mutually
    # exclusive.
    host = "localhost"

    # Deploy a node.
    name = f"pytest-{uuid4()}"
    deploy_marker = request.node.get_closest_marker("deploy")
    if deploy_marker:
        host = deploy_vm(name, **deploy_marker.kwargs)

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
    print(f"Host is {host}")
    with Node(host, config=config, inline_ssh_env=True) as n:
        yield n
    # Clean up!
    if deploy_marker:
        delete_vm(name)
