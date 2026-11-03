# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from time import sleep
from typing import Any, Callable, Dict, Generator, Optional

import requests
from azure.core.exceptions import HttpResponseError
from azure.mgmt.resource.resources import ResourceManagementClient
from azure.mgmt.resource.resources.models import (
    Deployment,
    DeploymentMode,
    DeploymentProperties,
)
from microsoft.testsuites.vm_extensions.vm_extension_base import (
    VmExtensionTestBase,
    _get_boot_validation_extension_name,
)

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuiteMetadata,
    node_requirement,
    schema,
)
from lisa.environment import Environment, EnvironmentStatus
from lisa.operating_system import Windows
from lisa.secret import add_secret
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    get_blob_service_client,
    get_compute_client,
    get_network_client,
    get_node_context,
    get_resource_management_client,
    wait_operation,
)
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.util import LisaException, SkippedException


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="""
    Validates JsonADDomainExtension against a temporary AD DS forest using only
    Azure control-plane operations. No SSH or other guest connection is used.
    """,
    tags=["VM_Extension", "JsonADDomainExtension"],
    requirement=node_requirement(
        schema.NodeSpace(extended_schemas={AZURE: {"enable_ssh": False}}),
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        supported_os=[Windows],
        environment_status=EnvironmentStatus.Deployed,
    ),
)
class JsonADDomainTests(VmExtensionTestBase):  # type: ignore[misc]
    PUBLISHER = "Microsoft.Compute"
    EXTENSION_TYPE = "JsonADDomainExtension"
    EXTENSION_KEY = "json_ad_domain"
    PACKAGE_URL = (
        "https://raw.githubusercontent.com/Azure/azure-quickstart-templates/"
        "refs/heads/master/application-workloads/active-directory/"
        "active-directory-new-domain/DSC/CreateADPDC.zip"
    )

    @TestCaseMetadata(
        description="""
        Ports the VMADDomainExtension synthetic without SSH: creates a Windows
        Server 2022 domain controller and forest using a package staged from
        private blob storage by CSE with managed identity. Pre-stages the client's
        computer account in the testaccounts OU, and configures client DNS using
        managed Run Command. Joins using Options=1 (reuse the existing account),
        verifies the candidate extension, restarts through the Azure API, and
        verifies domain membership and the secure channel through Run Command.

        Requires extension_version or json_ad_domain_version. ARM templates are
        in templates/json_ad_domain_*.json. Removes the extension and controller
        group even on failure. Marks the client dirty for environment teardown.
        """,
        priority=5,
        timeout=7200,
        use_new_environment=True,
        tags=["microsoft.compute.jsonaddomainextension"],
        maturity="preview",
    )
    def microsoft_compute_jsonaddomainextension_boot_validation_test(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        variables: Dict[str, Any],
    ) -> None:
        version = self._get_version(variables, use_default=False)
        extension = node.features[AzureExtension]
        try:
            (
                install_version,
                is_patch_version,
            ) = extension.normalize_type_handler_version(version)
        except LisaException:
            raise SkippedException(
                f"Version '{version}' is not a valid 'Major.Minor', "
                "'Major.Minor.Patch', or 'Major.Minor.Patch.Revision' value."
            )
        platform = environment.platform
        assert isinstance(platform, AzurePlatform), "Requires the Azure platform."
        context = get_node_context(node)
        compute = get_compute_client(platform)
        vm = compute.virtual_machines.get(context.resource_group_name, context.vm_name)
        if str(vm.storage_profile.os_disk.os_type).lower() != "windows":
            raise LisaException("Requires a Windows client VM.")
        computer_name = vm.os_profile.computer_name
        if not computer_name or len(computer_name) > 15:
            raise LisaException(f"Invalid Windows computer name: {computer_name!r}")

        primary_nic = next(
            (nic for nic in vm.network_profile.network_interfaces if nic.primary),
            vm.network_profile.network_interfaces[0],
        )
        nic_id = primary_nic.id.split("/")
        nic = get_network_client(platform).network_interfaces.get(nic_id[4], nic_id[-1])
        ip_config = next(
            (config for config in nic.ip_configurations if config.primary),
            nic.ip_configurations[0],
        )
        client_ip = ip_config.private_ip_address
        if not client_ip:
            raise LisaException(
                "The client's primary Azure NIC has no private IP address."
            )
        suffix = uuid.uuid4().hex[:8]
        domain_prefix = f"lisa{suffix}"
        domain_name = f"{domain_prefix}.com"
        resource_group = f"lisa-ad-{suffix}"
        username = "lisaadadmin"
        password = f"Aa1!{uuid.uuid4().hex}"
        add_secret(password)
        resource_client = get_resource_management_client(
            platform.credential, platform.subscription_id, platform.cloud
        )
        node.mark_dirty()
        self._run_command(
            resource_client,
            context.resource_group_name,
            context.vm_name,
            context.location,
            "CheckWorkgroup",
            "$ErrorActionPreference = 'Stop'; "
            "if ((Get-CimInstance Win32_ComputerSystem).PartOfDomain) "
            "{ throw 'The client must not already belong to a domain' }",
        )
        extension_name = _get_boot_validation_extension_name(
            self._resolve_publisher(variables), self._resolve_type(variables)
        )
        with self._cleanup_on_exit(
            lambda: wait_operation(
                resource_client.resource_groups.begin_delete(resource_group),
                time_out=1800,
                failure_identity="Deleting temporary domain controller resource group",
            ),
            log,
            f"Failed to delete temporary domain controller group {resource_group}",
        ):
            resource_client.resource_groups.create_or_update(
                resource_group, {"location": context.location}
            )
            storage_account = f"lisaad{uuid.uuid4().hex[:18]}"
            package_url = self._stage_package(
                resource_client, platform, resource_group, storage_account, log
            )
            log.info(f"Creating domain controller in {resource_group}")
            deployment = self._deploy_template(
                resource_client,
                resource_group,
                "domain-controller",
                "json_ad_domain_controller.json",
                {
                    "adminUsername": username,
                    "adminPassword": password,
                    "subnetId": ip_config.subnet.id,
                    "storageAccountName": storage_account,
                    "packageBaseUrl": package_url,
                    "storageAccessScript": self._read_script(
                        "json_ad_domain_wait_storage.ps1"
                    ),
                },
                timeout=3600,
            )
            controller_ip = deployment["properties"]["outputs"]["privateIp"]["value"]
            controller_name = deployment["properties"]["outputs"]["vmName"]["value"]
            self._configure_forest(
                resource_client,
                platform,
                resource_group,
                controller_name,
                context.location,
                domain_name,
                username,
                password,
            )
            self._run_command(
                resource_client,
                resource_group,
                controller_name,
                context.location,
                "PrestageComputer",
                "$ErrorActionPreference = 'Stop'; Import-Module ActiveDirectory; "
                "New-ADOrganizationalUnit -Name 'testaccounts' "
                f"-Path 'DC={domain_prefix},DC=com'; "
                f"New-ADComputer -Name '{computer_name}' "
                f"-Path 'OU=testaccounts,DC={domain_prefix},DC=com'",
            )
            self._run_command(
                resource_client,
                context.resource_group_name,
                context.vm_name,
                context.location,
                "ConfigureDns",
                "$ErrorActionPreference = 'Stop'; "
                f"$ip = Get-NetIPAddress -IPAddress '{client_ip}'; "
                "Set-DnsClientServerAddress -InterfaceIndex $ip.InterfaceIndex "
                f"-ServerAddresses '{controller_ip}'; Clear-DnsClientCache",
            )
            # The shared boot helper checks SSH reachability; this case must not.
            with self._cleanup_on_exit(
                lambda: self._uninstall(node, name=extension_name),
                log,
                f"Failed to uninstall extension {extension_name}",
            ):
                result = self._install(
                    node,
                    variables,
                    name=extension_name,
                    version=install_version,
                    settings={
                        "Name": domain_name,
                        "User": f"{domain_name}\\{username}",
                        "Options": 1,
                        "OUPath": f"OU=testaccounts,DC={domain_prefix},DC=com",
                        "Restart": "false",
                    },
                    protected_settings={"Password": password},
                )
                self._assert_provisioned(result, variables)
                installed_version = extension.get_installed_type_handler_version(
                    extension_name
                )
                if is_patch_version and not extension.are_type_handler_versions_equal(
                    version, installed_version
                ):
                    raise LisaException(
                        f"Installed extension version mismatch: expected '{version}', "
                        f"actual '{installed_version}'."
                    )
                log.info(f"Installed '{extension_name}' version: {installed_version}")
                wait_operation(
                    compute.virtual_machines.begin_restart(
                        context.resource_group_name, context.vm_name
                    ),
                    time_out=900,
                    failure_identity="Restarting domain-joined Windows client",
                )
                self._run_command(
                    resource_client,
                    context.resource_group_name,
                    context.vm_name,
                    context.location,
                    "VerifyDomain",
                    "$ErrorActionPreference = 'Stop'; "
                    "$computer = Get-CimInstance Win32_ComputerSystem; "
                    "if (!$computer.PartOfDomain -or "
                    f"$computer.Domain -ine '{domain_name}') "
                    "{ throw 'The VM did not join the expected domain' }; "
                    "if (!(Test-ComputerSecureChannel -ErrorAction Stop)) "
                    "{ throw 'The domain secure channel is not healthy' }",
                )

    @contextmanager
    def _cleanup_on_exit(
        self, cleanup: Callable[[], Any], log: Logger, message: str
    ) -> Generator[None, None, None]:
        try:
            yield
        finally:
            failed = sys.exc_info()[0] is not None
            try:
                cleanup()
            except Exception:
                log.exception(message)
                if not failed:
                    raise

    def _read_script(self, filename: str) -> str:
        return (Path(__file__).parent / "templates" / filename).read_text(
            encoding="utf-8"
        )

    def _stage_package(
        self,
        client: ResourceManagementClient,
        platform: AzurePlatform,
        resource_group: str,
        storage_account: str,
        log: Logger,
    ) -> str:
        deployment = self._deploy_template(
            client,
            resource_group,
            "ad-package-storage",
            "json_ad_domain_storage.json",
            {
                "storageAccountName": storage_account,
            },
            timeout=900,
        )
        with requests.get(self.PACKAGE_URL, timeout=60) as response:
            response.raise_for_status()
            package = response.content
        with get_blob_service_client(
            cloud=platform.cloud,
            credential=platform.credential,
            account_name=storage_account,
            platform=platform,
        ) as blob_service:
            container = blob_service.get_container_client("packages")
            files = {
                "CreateADPDC.zip": package,
                "json_ad_domain_stage.ps1": self._read_script(
                    "json_ad_domain_stage.ps1"
                ).encode("utf-8"),
                "json_ad_domain_configure.ps1": self._read_script(
                    "json_ad_domain_configure.ps1"
                ).encode("utf-8"),
            }
            for name, data in files.items():
                for attempt in range(20):
                    try:
                        container.upload_blob(name=name, data=data, overwrite=True)
                        break
                    except HttpResponseError as error:
                        if error.status_code != 403 or attempt == 19:
                            raise
                        log.debug("Waiting for uploader storage role propagation")
                        sleep(15)
        endpoint = deployment["properties"]["outputs"]["blobEndpoint"]["value"]
        if not isinstance(endpoint, str) or not endpoint.startswith("https://"):
            raise LisaException("Storage deployment did not return an HTTPS endpoint")
        return endpoint.rstrip("/") + "/packages/"

    def _configure_forest(
        self,
        client: ResourceManagementClient,
        platform: AzurePlatform,
        resource_group: str,
        vm_name: str,
        location: str,
        domain_name: str,
        username: str,
        password: str,
    ) -> None:
        compute = get_compute_client(platform)
        command_name = "ConfigureForest"
        self._run_command(
            client,
            resource_group,
            vm_name,
            location,
            command_name,
            "param([string]$AdminPassword); $ErrorActionPreference = 'Stop'; "
            "& 'C:\\lisa\\ad\\json_ad_domain_configure.ps1' "
            f"-DomainName '{domain_name}' -AdminUsername '{username}' "
            "-AdminPassword $AdminPassword",
            protected_parameters={"AdminPassword": password},
            timeout_in_seconds=1800,
        )
        for reboot_count in range(4):
            command = compute.virtual_machine_run_commands.get_by_virtual_machine(
                resource_group, vm_name, command_name, expand="instanceView"
            )
            view = command.instance_view
            if not view or view.exit_code != 0 or not view.output:
                raise LisaException(
                    "DSC Run Command did not return a successful result"
                )
            state = view.output.strip().splitlines()[-1].strip()
            if state == "LISA_DSC_READY":
                return
            if state != "LISA_DSC_REBOOT_REQUIRED":
                raise LisaException(f"Unexpected DSC Run Command result: {state!r}")
            if reboot_count == 3:
                raise LisaException("DSC did not finish after three controller reboots")
            wait_operation(
                compute.virtual_machines.begin_restart(resource_group, vm_name),
                time_out=900,
                failure_identity="Restarting domain controller for DSC",
            )
            command_name = f"ResumeForest{reboot_count}"
            self._run_command(
                client,
                resource_group,
                vm_name,
                location,
                command_name,
                "$ErrorActionPreference = 'Stop'; "
                "& 'C:\\lisa\\ad\\json_ad_domain_configure.ps1' -Resume",
                timeout_in_seconds=1800,
            )

    def _run_command(
        self,
        client: ResourceManagementClient,
        resource_group: str,
        vm_name: str,
        location: str,
        name: str,
        script: str,
        protected_parameters: Optional[Dict[str, str]] = None,
        timeout_in_seconds: int = 600,
    ) -> None:
        self._deploy_template(
            client,
            resource_group,
            name,
            "json_ad_domain_run_command.json",
            {
                "vmName": vm_name,
                "location": location,
                "commandName": name,
                "script": script,
                "protectedScriptParameters": {
                    "items": [
                        {"name": key, "value": value}
                        for key, value in (protected_parameters or {}).items()
                    ]
                },
                "timeoutInSeconds": timeout_in_seconds,
            },
            timeout=timeout_in_seconds + 300,
        )

    def _deploy_template(
        self,
        client: ResourceManagementClient,
        resource_group: str,
        name: str,
        filename: str,
        parameters: Dict[str, Any],
        timeout: int,
    ) -> Dict[str, Any]:
        template_path = Path(__file__).parent / "templates" / filename
        with template_path.open(encoding="utf-8") as template_file:
            template = json.load(template_file)
        result: Dict[str, Any] = wait_operation(
            client.deployments.begin_create_or_update(
                resource_group,
                name,
                Deployment(
                    properties=DeploymentProperties(
                        mode=DeploymentMode.incremental,
                        template=template,
                        parameters={
                            key: {"value": value} for key, value in parameters.items()
                        },
                    )
                ),
            ),
            time_out=timeout,
            failure_identity=f"Deploying {name}",
        )
        if result["properties"]["provisioning_state"] != "Succeeded":
            raise LisaException(f"Deployment '{name}' did not succeed.")
        return result
