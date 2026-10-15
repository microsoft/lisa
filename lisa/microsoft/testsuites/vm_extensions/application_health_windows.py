# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
from datetime import datetime
from typing import Any, Dict

from assertpy import assert_that
from azure.mgmt.compute import ComputeManagementClient
from dateutil.parser import isoparse
from microsoft.testsuites.vm_extensions.vm_extension_base import VmExtensionTestBase
from retry import retry

from lisa import (
    Environment,
    Logger,
    RemoteNode,
    TestCaseMetadata,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import Windows
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    NodeContext,
    get_compute_client,
    get_node_context,
)
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.util import LisaException


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="""
    Boot validation for Microsoft.ManagedServices.ApplicationHealthWindows.
    Probes the guest SSH listener over TCP and verifies fresh application health.
    """,
    tags=["VM_Extension", "microsoft.managedservices.applicationhealthwindows"],
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        supported_os=[Windows],
    ),
)
class ApplicationHealthWindowsTests(VmExtensionTestBase):  # type: ignore[misc]
    PUBLISHER = "Microsoft.ManagedServices"
    EXTENSION_TYPE = "ApplicationHealthWindows"
    EXTENSION_KEY = "application_health_windows"

    @TestCaseMetadata(
        description="""
        Installs the explicitly requested candidate with a TCP probe against
        the verified guest-local SSH port. Requires provisioning success, the
        installed handler version to match a full candidate, and SSH
        reachability. Polls Azure instance view for HealthState/healthy with a
        report timestamp no older than a post-install guest-clock watermark.
        A stale Healthy report does not validate the new candidate.

        Requires 'extension_version' or 'application_health_windows_version'.
        Uses an isolated environment and does not install another application,
        change SSH or firewall configuration, or download probe scripts.
        Validates initial TCP probing and health reporting, not reboot survival,
        HTTP/HTTPS response semantics, or automatic VM repair.
        """,
        priority=5,
        tags=["microsoft.managedservices.applicationhealthwindows"],
        maturity="preview",
        use_new_environment=True,
    )
    def microsoft_managedservices_applicationhealthwindows_boot_validation_test(
        self,
        log: Logger,
        node: RemoteNode,
        environment: Environment,
        variables: Dict[str, Any],
    ) -> None:
        self._get_version(variables, use_default=False)
        self._verify_tcp_endpoint(node, log)
        self._boot_validation(
            node=node,
            log=log,
            variables=variables,
            settings={
                "protocol": "tcp",
                "port": node.internal_port,
                "intervalInSeconds": 5,
                "numberOfProbes": 2,
            },
            post_provision=lambda _: self._verify_healthy(node, log, environment),
            mark_dirty_before_install=True,
        )

    def _verify_tcp_endpoint(self, node: RemoteNode, log: Logger) -> datetime:
        port = node.internal_port
        if type(port) is not int or not 1 <= port <= 65535:
            raise LisaException(f"Invalid guest SSH port for the TCP probe: {port!r}")
        result = node.execute(
            "powershell.exe -NoProfile -NonInteractive -Command "
            "\"$ErrorActionPreference = 'Stop'; "
            "$client = New-Object System.Net.Sockets.TcpClient; "
            "try { "
            f"if (-not $client.ConnectAsync('localhost', {port}).Wait(5000) "
            "-or -not $client.Connected) { "
            "throw 'Guest-local SSH TCP endpoint is not accepting connections' }; "
            f"@{{ Connected = $client.Connected; Port = {port}; "
            "UtcNow = [DateTime]::UtcNow.ToString('o') } "
            "| ConvertTo-Json -Compress "
            '} finally { $client.Dispose() }"',
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Application Health requires a reachable guest-local SSH TCP endpoint."
            ),
            timeout=30,
        )
        try:
            status = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise LisaException(
                f"TCP endpoint query returned invalid JSON: {result.stdout!r}"
            ) from error
        if (
            not isinstance(status, dict)
            or status.get("Connected") is not True
            or type(status.get("Port")) is not int
            or status["Port"] != port
            or not isinstance(status.get("UtcNow"), str)
        ):
            raise LisaException(f"Invalid TCP endpoint status: {status!r}")
        try:
            observed_at: datetime = isoparse(status["UtcNow"])
        except ValueError as error:
            raise LisaException(
                f"Invalid guest UTC timestamp: {status['UtcNow']!r}"
            ) from error
        if observed_at.utcoffset() is None:
            raise LisaException(
                f"Guest timestamp must include a UTC offset: {status!r}"
            )
        log.info(f"Guest-local TCP endpoint verified: {status}")
        return observed_at

    def _verify_healthy(
        self, node: RemoteNode, log: Logger, environment: Environment
    ) -> None:
        platform = environment.platform
        if not isinstance(platform, AzurePlatform):
            raise LisaException("Application Health validation requires AzurePlatform.")
        # Use the guest clock after candidate installation, not the controller's clock.
        observed_after = self._verify_tcp_endpoint(node, log)
        self._assert_fresh_healthy(
            get_compute_client(platform),
            get_node_context(node),
            log,
            observed_after,
        )
        log.info("Fresh application health validated for the guest-local TCP probe.")

    @retry(exceptions=AssertionError, tries=31, delay=10)  # type: ignore
    def _assert_fresh_healthy(
        self,
        compute_client: ComputeManagementClient,
        context: NodeContext,
        log: Logger,
        observed_after: datetime,
    ) -> None:
        instance_view = compute_client.virtual_machines.instance_view(
            context.resource_group_name,
            context.vm_name,
            connection_timeout=30,
            read_timeout=30,
        )
        health = instance_view.vm_health
        status = health.status if health is not None else None
        code = status.code if status is not None else None
        reported_at = status.time if status is not None else None
        log.info(
            f"Application health report: code={code!r}, time={reported_at!r}; "
            f"requiring Healthy reported at or after {observed_after.isoformat()}."
        )
        assert_that(code).described_as(
            "Expected Azure instance view vmHealth.status.code to be "
            "'HealthState/healthy' for the installed candidate."
        ).is_equal_to("HealthState/healthy")
        assert_that(
            isinstance(reported_at, datetime)
            and reported_at.utcoffset() is not None
            and reported_at >= observed_after
        ).described_as(
            f"Expected a fresh application-health report at or after "
            f"{observed_after.isoformat()}, received {reported_at!r}. "
            "A missing timestamp or historical Healthy status cannot validate "
            "the installed candidate."
        ).is_true()
