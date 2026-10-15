# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
from pathlib import PureWindowsPath
from typing import Any, Dict

from assertpy import assert_that
from microsoft.testsuites.vm_extensions.vm_extension_base import (
    VmExtensionTestBase,
    _get_boot_validation_extension_name,
)
from retry import retry

from lisa import Logger, Node, TestCaseMetadata, TestSuiteMetadata, simple_requirement
from lisa.operating_system import Windows
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.util import LisaException, SkippedException


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="""
    Boot validation for Microsoft.Azure.Geneva.GenevaMonitoring on Windows.
    Checks standby infrastructure readiness without tenant telemetry settings.
    """,
    tags=["VM_Extension", "microsoft.azure.geneva.genevamonitoring"],
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        supported_os=[Windows],
    ),
)
class GenevaMonitoringWindowsTests(VmExtensionTestBase):  # type: ignore[misc]
    PUBLISHER = "Microsoft.Azure.Geneva"
    EXTENSION_TYPE = "GenevaMonitoring"
    EXTENSION_KEY = "geneva_monitoring_windows"

    @TestCaseMetadata(
        description="""
        Installs the explicitly requested candidate with empty public and
        protected settings. Checks provisioning, the installed handler version
        when a full candidate is supplied, and SSH reachability.

        Verifies MonAgentManager.exe and MonAgentHost.exe are running from the
        installed candidate directory. Reads the machine-scoped
        MonAgentClientLocation and checks that its MonAgentClient.exe exists
        under the same candidate. Checks that the registered JSON drop
        directory exists.

        Requires 'extension_version' or 'geneva_monitoring_windows_version'.
        Uses an isolated environment and skips Windows kernels older than 6.3.
        Shared installation removes pre-existing matching handlers before
        installing the candidate. Marks the node dirty
        before installation because monitoring changes machine-wide state.
        Does not launch a tenant agent, submit configurations, validate
        telemetry ingestion, or test reboot survival.
        """,
        priority=5,
        tags=["microsoft.azure.geneva.genevamonitoring"],
        maturity="preview",
        use_new_environment=True,
    )
    def microsoft_azure_geneva_genevamonitoring_boot_validation_test(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._get_version(variables, use_default=False)
        version = node.os.information.version
        if (version.major, version.minor) < (6, 3):
            raise SkippedException(
                "GenevaMonitoring requires Windows Server 2012 R2 or later "
                "(Windows kernel version 6.3 or newer)."
            )
        self._boot_validation(
            node=node,
            log=log,
            variables=variables,
            settings={},
            post_provision=lambda node: self._verify_standby_ready(
                node, log, variables
            ),
            mark_dirty_before_install=True,
        )

    def _verify_standby_ready(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        publisher = self._resolve_publisher(variables)
        extension_type = self._resolve_type(variables)
        extension_name = _get_boot_validation_extension_name(publisher, extension_type)
        installed_version = node.features[
            AzureExtension
        ].get_installed_type_handler_version(extension_name)
        installation_directory = (
            PureWindowsPath(r"C:\Packages\Plugins")
            / f"{publisher}.{extension_type}"
            / installed_version
        )
        self._assert_standby_ready(node, log, installation_directory)

    @retry(exceptions=AssertionError, tries=6, delay=10)  # type: ignore
    def _assert_standby_ready(
        self, node: Node, log: Logger, installation_directory: PureWindowsPath
    ) -> None:
        result = node.execute(
            "powershell.exe -NoProfile -NonInteractive -Command "
            "\"$ErrorActionPreference = 'Stop'; "
            "$processes = @(Get-CimInstance Win32_Process -Filter "
            "'Name = ''MonAgentManager.exe'' OR Name = ''MonAgentHost.exe''' "
            "| Select-Object Name,ExecutablePath); "
            "$client = [Environment]::GetEnvironmentVariable("
            "'MonAgentClientLocation', 'Machine'); "
            "$clientPath = if ([string]::IsNullOrWhiteSpace($client)) { '' } "
            "else { Join-Path $client 'MonAgentClient.exe' }; "
            "$drop = (Get-ItemProperty -LiteralPath "
            "'HKLM:\\SOFTWARE\\Microsoft\\Geneva\\MonitoringAgent\\MultiTenant'"
            ").JsonDropDirectory; "
            "@{ Processes = $processes; ClientPath = $clientPath; "
            "ClientExists = ([bool]$clientPath -and "
            "(Test-Path -LiteralPath $clientPath -PathType Leaf)); "
            "DropDirectory = $drop; DropDirectoryExists = ([bool]$drop -and "
            "(Test-Path -LiteralPath $drop -PathType Container)) } "
            '| ConvertTo-Json -Compress -Depth 4"',
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Failed to inspect Geneva monitoring standby infrastructure."
            ),
            timeout=60,
        )
        try:
            status = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise LisaException(
                f"Geneva standby query returned invalid JSON: {result.stdout!r}"
            ) from error
        if not isinstance(status, dict):
            raise LisaException(
                f"Expected a Geneva standby status object, received: {status!r}"
            )
        processes = status.get("Processes")
        if not isinstance(processes, list) or any(
            not isinstance(process, dict) for process in processes
        ):
            raise LisaException(
                f"Expected a Geneva process array, received: {processes!r}"
            )
        for name in ("MonAgentManager.exe", "MonAgentHost.exe"):
            paths = [
                PureWindowsPath(process["ExecutablePath"])
                for process in processes
                if isinstance(process.get("Name"), str)
                and process["Name"].casefold() == name.casefold()
                and isinstance(process.get("ExecutablePath"), str)
                and process["ExecutablePath"]
            ]
            assert_that(
                any(
                    installation_directory in path.parents
                    and path.name.casefold() == name.casefold()
                    for path in paths
                )
            ).described_as(
                f"Expected {name} running under '{installation_directory}', "
                f"but found {paths}. Another handler version does not validate "
                "this candidate."
            ).is_true()

        client_path = status.get("ClientPath")
        assert_that(
            isinstance(client_path, str)
            and installation_directory in PureWindowsPath(client_path).parents
            and PureWindowsPath(client_path).name.casefold() == "monagentclient.exe"
            and status.get("ClientExists") is True
        ).described_as(
            f"Expected a discoverable MonAgentClient.exe under "
            f"'{installation_directory}', but received status {status!r}."
        ).is_true()
        drop_directory = status.get("DropDirectory")
        assert_that(
            isinstance(drop_directory, str)
            and PureWindowsPath(drop_directory).is_absolute()
            and status.get("DropDirectoryExists") is True
        ).described_as(
            f"Expected an existing registered Geneva JSON drop directory, "
            f"but received status {status!r}."
        ).is_true()
        log.info(f"Geneva standby infrastructure validated: {status}")
