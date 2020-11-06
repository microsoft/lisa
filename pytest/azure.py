from __future__ import annotations

import json
import logging
import typing

from invoke.runners import Result  # type: ignore
from tenacity import retry, stop_after_attempt, wait_exponential  # type: ignore

from target import Target

if typing.TYPE_CHECKING:
    from typing import Any


class Azure(Target):
    """Implements Azure-specific target methods."""

    az_ok = False

    def check_az_cli(self) -> None:
        """Assert that the `az` CLI is installed and logged in."""
        if Azure.az_ok:
            return
        # E.g. on Ubuntu: `curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash`
        assert self.local("az --version", warn=True), "Please install the `az` CLI!"
        # TODO: Login with service principal (az login) and set
        # default subscription (az account set -s) using secrets.
        account: Result = self.local("az account show")
        assert account.ok, "Please `az login`!"
        sub = json.loads(account.stdout)
        assert sub["isDefault"], "Please `az account set -s <subscription>`!"
        logging.info(
            f"Using account '{sub['user']['name']}' with subscription '{sub['name']}'"
        )
        Azure.az_ok = True

    def create_boot_storage(self, location: str) -> str:
        """Create a separate resource group and storage account for boot diagnostics."""
        account = "pytestbootdiag"
        # This command always exits with 0 but returns a string.
        if self.local("az group exists -n pytest-lisa").stdout.strip() == "false":
            self.local(f"az group create -n pytest-lisa --location {location}")
        if not self.local(
            f"az storage account show -g pytest-lisa -n {account}", warn=True
        ):
            self.local(f"az storage account create -g pytest-lisa -n {account}")
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
                    f"az network nsg rule create --name allow{d}ICMP "
                    f"--nsg-name {self.name}NSG --priority 100 --resource-group {self.name}-rg "
                    f"--access Allow --direction '{d}' --protocol Icmp "
                    "--source-port-ranges '*' --destination-port-ranges '*'"
                )
        except Exception as e:
            logging.warning(f"Failed to create ICMP allow rules in NSG due to '{e}'")

    def deploy(self):
        """Given deployment info, deploy a new VM."""
        image = self.params["image"]
        sku = self.params["sku"]
        location = self.params.get("location", "eastus2")
        networking = self.params.get("networking", "")

        self.check_az_cli()

        logging.info(
            f"""Deploying VM...
        Resource Group:	'{self.name}-rg'
        Region:		'{location}'
        Image:		'{image}'
        SKU:		'{sku}'"""
        )

        boot_storage = self.create_boot_storage(location)

        self.local(f"az group create -n {self.name}-rg --location {location}")
        # TODO: Accept EULA terms when necessary. Like:
        #
        # local.run(f"az vm image terms accept --urn {vm_image}")
        #
        # However, this command fails unless the terms exist and have yet
        # to be accepted.

        vm_command = [
            "az vm create",
            f"-g {self.name}-rg",
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
        self.allow_ping(self.name)
        # TODO: Enable auto-shutdown 4 hours from deployment.
        return self.data["publicIpAddress"]

    def delete(self) -> None:
        """Delete the entire allocated resource group.

        TODO: Delete VM itself. Only if it was the last VM then delete
        the entire resource group.

        """
        logging.info(f"Deleting resource group '{self.name}-rg'")
        self.local(f"az group delete -n {self.name}-rg --yes --no-wait")

    @retry(reraise=True, wait=wait_exponential(), stop=stop_after_attempt(3))
    def get_boot_diagnostics(self, **kwargs: Any) -> Result:
        """Gets the serial console logs."""
        # NOTE: Some images can cause the `az` CLI to crash because
        # their logs aren’t UTF-8 encoded. I’ve filed a bug:
        # https://github.com/Azure/azure-cli/issues/15590
        return self.local(
            f"az vm boot-diagnostics get-boot-log -n {self.name} -g {self.name}-rg",
            **kwargs,
        )

    def platform_restart(self) -> Result:
        """TODO: Should this '--force' and redeploy?"""
        return self.local(f"az vm restart -n {self.name} -g {self.name}-rg")
