"""Pytest plugin implementing a Node fixture for running remote commands."""
import json
from io import BytesIO
from typing import Dict, Iterator, Optional, Tuple
from uuid import uuid4

import _pytest
from fabric import Connection  # type: ignore
from invoke import Config, Context  # type: ignore
from invoke.runners import Result  # type: ignore

import pytest

# Setup a sane configuration for local and remote commands.
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
            # Don’t let remote commands take longer than five minutes
            # (unless later overridden). This is to prevent hangs.
            "timeout": 300,
        }
    }
)

# Provide a configured local Invoke context for running commands
# before establishing a connection. (Use like `local.run(...)`).
local = Context(config=config)


def check_az_cli() -> None:
    if not local.run("which az", warn=True):
        # TODO: Use Invoke for pipes.
        local.run(
            "curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash",
        )

    # TODO: Login with service principal (az login) and set
    # default subscription (az account set -s) using secrets.
    account: Result = local.run("az account show")
    assert account.ok, "Please `az login`!"
    subs = json.loads(account.stdout)
    assert subs["isDefault"], "Please `az account set -s <subscription>`!"


def create_boot_storage(location: str) -> str:
    """Create a separate resource group and storage account for boot diagnostics."""
    account = "pytestbootdiag"
    # This command always exits with 0 but returns a string.
    if local.run("az group exists -n pytest-lisa").stdout.strip() == "false":
        local.run(f"az group create -n pytest-lisa --location {location}")
    if not local.run(f"az storage account show -g pytest-lisa -n {account}", warn=True):
        local.run(f"az storage account create -g pytest-lisa -n {account}")
    return account


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

    check_az_cli()
    boot_storage = create_boot_storage(location)

    local.run(
        f"az group create -n {name}-rg --location {location}",
    )

    vm_command = [
        "az vm create",
        f"-g {name}-rg",
        f"-n {name}",
        f"--image {vm_image}",
        f"--size {vm_size}",
        f"--boot-diagnostics-storage {boot_storage}",
        "--generate-ssh-keys",
    ]
    if networking == "SRIOV":
        vm_command.append("--accelerated-networking true")

    result: Dict[str, str] = json.loads(
        local.run(
            " ".join(vm_command),
        ).stdout
    )
    request.config.cache.set(name, result)
    return name, result


def delete_vm(name: str) -> None:
    local.run(f"az group delete -n {name}-rg --yes")


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
    with Node(host, config=config, inline_ssh_env=True) as n:
        n.name = name
        yield n

    # Clean up!
    # TODO: This logic is wrong.
    if request.config.getoption("cacheclear") and name:
        delete_vm(name)
