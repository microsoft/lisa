# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Provides an ``Azure(Target)`` implementation using the Azure CLI."""
from __future__ import annotations

import json
import logging
import typing

import invoke  # type: ignore
from invoke.runners import Result  # type: ignore
from schema import Optional  # type: ignore
from target.target import Target
from tenacity import retry, stop_after_attempt, wait_exponential  # type: ignore

if typing.TYPE_CHECKING:
    from typing import Any, Dict


class AzureCLI(Target):
    """Implements Azure-specific target methods.

    This implementation uses the Azure CLI `az` to automate creating
    VMs based on the given parameters.

    """

    # Custom instance attribute(s).
    internal_address: str
    """Internal IP address of this target."""

    @classmethod
    def schema(cls) -> Dict[Any, Any]:
        return {
            # TODO: Maybe validate as URN or path etc.
            "image": str,
            Optional("sku"): str,
            Optional("location"): str,
            Optional("networking"): str,
        }

    @classmethod
    def defaults(cls) -> Dict[Any, Any]:
        return {
            Optional("image", default="UbuntuLTS"): str,
            Optional("sku", default="Standard_DS1_v2"): str,
            Optional("location", default="eastus2"): str,
            Optional("networking", default=""): str,
        }

    @classmethod
    def _local(cls, *args: Any, **kwargs: Any) -> Result:
        """A quiet version of `local()`."""
        # TODO: Consider adding this to the superclass.
        config = Target._config.copy()
        config["run"]["hide"] = True
        context = invoke.Context(config=invoke.Config(overrides=config))
        return context.run(*args, **kwargs)

    # A class attribute because it’s defined.
    _az_ok = False

    @classmethod
    def check_az_cli(cls) -> None:
        """Assert that the `az` CLI is installed and logged in."""
        if cls._az_ok:  # Shortcut if we already checked.
            return
        # E.g. on Ubuntu: `curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash`
        assert cls._local("az --version", warn=True), "Please install the `az` CLI!"
        # TODO: Login with service principal (az login) and set
        # default subscription (az account set -s) using secrets.
        account: Result = cls._local("az account show")
        assert account.ok, "Please `az login`!"
        sub = json.loads(account.stdout)
        assert sub["isDefault"], "Please `az account set -s <subscription>`!"
        logging.info(
            f"Using account '{sub['user']['name']}' with subscription '{sub['name']}'"
        )
        cls._az_ok = True

    def create_boot_storage(self, location: str) -> str:
        """Create a separate resource group and storage account for boot diagnostics."""
        # TODO: Use a different account per user.
        account = "pytestbootdiag"
        # This command always exits with 0 but returns a string.
        if self._local("az group exists -n pytest-lisa").stdout.strip() == "false":
            self._local(f"az group create -n pytest-lisa --location {location}")
        if not self._local(
            f"az storage account show -g pytest-lisa -n {account}", warn=True
        ):
            self._local(f"az storage account create -g pytest-lisa -n {account}")
        return account

    def allow_ping(self) -> None:
        """Create NSG rules to enable ICMP ping.

        ICMP ping is disallowed by the Azure load balancer by default, but
        there’s strong debate about if this is necessary, and our tests
        like to check if the host is up using ping, so we create inbound
        and outbound rules in the VM's network security group to allow it.

        """
        try:
            for d in ["Inbound", "Outbound"]:
                self.local(
                    f"az network nsg rule create "
                    f"--name allow{d}ICMP --resource-group {self.group}-rg "
                    f"--nsg-name {self.name}NSG --priority 150  "
                    f"--access Allow --direction '{d}' --protocol Icmp "
                    "--source-port-ranges '*' --destination-port-ranges '*'",
                    hide=True,
                )
        except Exception as e:
            logging.warning(
                f"Failed creating ICMP allow rules in '{self.name}NSG': {e}"
            )

    def parse_data(self) -> str:
        self.internal_address = self.data["privateIpAddress"]
        return typing.cast(str, self.data["publicIpAddress"])

    def deploy(self) -> str:
        """Given deployment info, deploy a new VM."""
        if self.data:  # Shortcut if refreshing from cache.
            return self.parse_data()

        AzureCLI.check_az_cli()

        image = self.params["image"]
        sku = self.params["sku"]
        location = self.params["location"]
        networking = self.params["networking"]

        logging.info(
            "Deploying VM...\n"
            f"	Group:		'{self.group}-rg'\n"
            f"	Region:		'{location}'\n"
            f"	Image:		'{image}'\n"
            f"	SKU:		'{sku}'"
        )

        boot_storage = self.create_boot_storage(location)

        self._local(f"az group create -n {self.group}-rg --location {location}")

        # TODO: Accept EULA terms when necessary. Like:
        #
        # local.run(f"az vm image terms accept --urn {vm_image}")
        #
        # However, this command fails unless the terms exist and have yet
        # to be accepted.

        vm_command = [
            "az vm create",
            f"-g {self.group}-rg",
            f"-n {self.name}",
            f"--image {image}",
            f"--size {sku}",
            f"--boot-diagnostics-storage {boot_storage}",
            "--generate-ssh-keys",
        ]
        # TODO: Support setting up to NICs.
        if networking == "SRIOV":
            vm_command.append("--accelerated-networking true")

        self.data = json.loads(self.local(" ".join(vm_command)).stdout)
        self.allow_ping()
        # TODO: Enable auto-shutdown 4 hours from deployment.
        return self.parse_data()

    def delete(self) -> None:
        """Delete the entire allocated resource group."""
        # TODO: Delete VM '{self.name}'. Only if it was
        # the last VM then delete the entire resource group.
        logging.debug(f"Deleting resource group '{self.group}-rg'")
        try:
            self.local(f"az group delete -n {self.group}-rg --yes --no-wait")
        except Exception as e:
            logging.warning(f"Failed deleting resource group '{self.group}-rg': {e}")

    @retry(reraise=True, wait=wait_exponential(), stop=stop_after_attempt(3))
    def get_boot_diagnostics(self, **kwargs: Any) -> Result:
        """Gets the serial console logs."""
        # NOTE: Some images can cause the `az` CLI to crash because
        # their logs aren’t UTF-8 encoded. I’ve filed a bug:
        # https://github.com/Azure/azure-cli/issues/15590
        return self.local(
            f"az vm boot-diagnostics get-boot-log -n {self.name} -g {self.group}-rg",
            **kwargs,
        )

    def platform_restart(self) -> Result:
        """Should this use `--force` and redeploy?"""
        return self.local(f"az vm restart -n {self.name} -g {self.group}-rg")
