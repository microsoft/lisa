# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

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
from lisa.util import SkippedException


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="""
    Boot validation for the Windows Network Watcher Agent VM extension
    (Microsoft.Azure.NetworkWatcher.NetworkWatcherAgentWindows).
    """,
    tags=["VM_Extension", "microsoft.azure.networkwatcher.networkwatcheragentwindows"],
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        supported_os=[Windows],
    ),
)
class NetworkWatcherAgentWindowsTests(VmExtensionTestBase):  # type: ignore[misc]
    PUBLISHER = "Microsoft.Azure.NetworkWatcher"
    EXTENSION_TYPE = "NetworkWatcherAgentWindows"
    EXTENSION_KEY = "network_watcher_agent_windows"

    @TestCaseMetadata(
        description="""
        Installs the explicitly requested candidate with empty settings, as
        Network Watcher does not support user-supplied configuration. Verifies
        provisioning, the installed handler version when a full version is
        supplied, and VM reachability. Confirms NetworkWatcherAgent.exe is
        running from the installed handler's directory before cleanup.

        Requires 'extension_version' or 'network_watcher_agent_windows_version'.
        Skips VMs with an existing instance of the requested handler to avoid
        modifying a policy-managed installation. This is startup validation,
        not packet-capture or connection-monitor validation.
        """,
        priority=5,
        tags=["microsoft.azure.networkwatcher.networkwatcheragentwindows"],
        maturity="preview",
    )
    def microsoft_azure_networkwatcher_networkwatcheragentwindows_boot_validation_test(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._get_version(variables, use_default=False)
        publisher = self._resolve_publisher(variables)
        extension_type = self._resolve_type(variables)
        extension = node.features[AzureExtension]
        for existing in extension.list_all():
            if (
                existing.publisher.casefold() == publisher.casefold()
                and existing.type_properties_type.casefold()
                == extension_type.casefold()
            ):
                raise SkippedException(
                    f"Extension '{existing.name}' already provides "
                    f"{publisher}.{extension_type}. Use a fresh VM without this "
                    "handler; the test will not replace an existing installation."
                )

        self._boot_validation(
            node=node,
            log=log,
            variables=variables,
            settings={},
            post_provision=lambda node: self._verify_agent_running(node, variables),
        )

    def _verify_agent_running(self, node: Node, variables: Dict[str, Any]) -> None:
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
        self._assert_agent_running(node, installation_directory)

    @retry(exceptions=AssertionError, tries=6, delay=10)  # type: ignore
    def _assert_agent_running(
        self, node: Node, installation_directory: PureWindowsPath
    ) -> None:
        result = node.execute(
            "powershell.exe -NoProfile -NonInteractive -Command "
            '"Get-CimInstance Win32_Process -Filter '
            "'Name = ''NetworkWatcherAgent.exe''' -ErrorAction Stop "
            '| Select-Object -ExpandProperty ExecutablePath"',
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Failed to inspect the Windows Network Watcher Agent process."
            ),
            timeout=60,
        )
        paths = [
            PureWindowsPath(line.strip())
            for line in result.stdout.splitlines()
            if line.strip()
        ]
        assert_that(
            any(installation_directory in path.parents for path in paths)
        ).described_as(
            "Expected NetworkWatcherAgent.exe to be running from "
            f"'{installation_directory}', but found executable paths {paths}. "
            "A process from another handler version does not validate this candidate."
        ).is_true()
