"""Pytest plugin implementing a Node fixture for running remote commands."""
import json
from io import BytesIO
from typing import Dict, Iterator, Optional, Tuple
from uuid import uuid4

import _pytest
import invoke  # type: ignore
from fabric import Config, Connection  # type: ignore

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
    request: _pytest.fixtures.FixtureRequest,
    location: str = "westus2",
    vm_image: str = "UbuntuLTS",
    vm_size: str = "Standard_DS1_v2",
    setup: str = "",
    networking: str = "",
) -> Tuple[str, Dict[str, str]]:

    key = f"{location}/{vm_image}/{vm_size}"
    name: Optional[str] = request.config.cache.get(key, None)
    if name:
        result: Dict[str, str] = request.config.cache.get(name, {})
        assert result, "There was a cache problem, use --cache-clear and try again."
        return name, result

    name = f"pytest-{uuid4()}"
    request.config.cache.set(key, name)

    install_az_cli()

    invoke.run(
        f"az group create -n {name}-rg --location {location}",
        echo=True,
        in_stream=False,
    )

    vm_command = [
        "az vm create",
        f"-g {name}-rg",
        f"-n {name}",
        f"--image {vm_image}",
        f"--size {vm_size}",
        "--generate-ssh-keys",
        # TODO: Create unique boot diagnostics storage account.
        # `az storage account create -g {name}-rg -n pytestbootdiag`
        f"--boot-diagnostics-storage pytestbootdiag",
    ]
    if networking == "SRIOV":
        vm_command.append("--accelerated-networking true")

    result: Dict[str, str] = json.loads(
        invoke.run(
            " ".join(vm_command),
            echo=True,
            in_stream=False,
        ).stdout
    )
    request.config.cache.set(name, result)
    return name, result


def delete_vm(name: str) -> None:
    invoke.run(f"az group delete -n {name}-rg --yes", echo=True, in_stream=False)


class Node(Connection):
    """Extends 'fabric.Connection' with our own utilities."""

    name: str

    def get_boot_diagnostics(self):
        """Gets the serial console logs."""
        return self.local(
            f"az vm boot-diagnostics get-boot-log -n {self.name} -g {self.name}-rg"
        )

    def platform_restart(self):
        """TODO: Should this '--force' and redeploy?"""
        return self.local(f"az vm restart -n {self.name} -g {self.name}-rg")

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
        name, result = deploy_vm(request, **deploy_marker.kwargs)
        host = result["publicIpAddress"]

    # Get the host from the test’s marker.
    connect_marker = request.node.get_closest_marker("connect")
    if connect_marker:
        name = "local"
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
                "env": {
                    "PATH": "/sbin:/usr/sbin:/usr/local/sbin:/bin:/usr/bin:/usr/local/bin"
                },
                # Don’t let remote commands take longer than a minute
                # (unless later overridden).
                "timeout": 60,
            }
        }
    )

    with Node(host, config=config, inline_ssh_env=True) as n:
        n.name = name
        yield n

    # Clean up!
    # TODO: This logic is wrong.
    if request.config.getoption("cacheclear") and name:
        delete_vm(name)
