# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any

from assertpy import assert_that
from semver import VersionInfo

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.base_tools import Systemctl
from lisa.operating_system import CBLMariner
from lisa.sut_orchestrator.azure.common import get_node_context
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.testsuite import TestResult
from lisa.util import SkippedException


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="BVT for Azure DNS Serve Stale VM Extension",
    requirement=simple_requirement(supported_os=[CBLMariner]),
)
class DNSServeStaleExtensionBvt(TestSuite):
    EXTENSION_NAME = "DNSServeStale"
    PUBLISHER = "Microsoft.Azure.Networking.DNS.Dev"
    VERSION = "2.9"

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]

        # Check systemd version requirement
        systemctl = node.tools[Systemctl]
        systemd_version = systemctl.get_version()
        required_version = VersionInfo(255, 4)
        log.info(f"Detected systemd version: {systemd_version}")
        if systemd_version < required_version:
            raise SkippedException(
                f"systemd {systemd_version} is not supported. "
                "DNSServeStale requires systemd >= 255.4"
            )

    @TestCaseMetadata(
        description="""
        Validate basic lifecycle of DNSServeStale VM extension:
        - Install extension with settings
        - Verify provisioning succeeded
        - Update extension settings
        - Verify update succeeded
        - Delete extension
        """,
        priority=1,
        requirement=simple_requirement(
            supported_features=[AzureExtension],
            supported_os=[CBLMariner],
        ),
    )
    def verify_dns_serve_stale_extension(
        self, log: Logger, node: Node, result: TestResult
    ) -> None:
        environment = result.environment
        assert environment
        assert isinstance(environment.platform, AzurePlatform)

        node_context = get_node_context(node)
        extension = node.features[AzureExtension]

        initial_settings = {
            "StaleRetentionSec": "2d",
        }

        log.info(
            f"Installing {self.EXTENSION_NAME} on VM '{node_context.vm_name}' "
            f"with settings {initial_settings}"
        )

        # Install
        install_result = extension.create_or_update(
            name=self.EXTENSION_NAME,
            publisher=self.PUBLISHER,
            type_=self.EXTENSION_NAME,
            type_handler_version=self.VERSION,
            settings=initial_settings,
            auto_upgrade_minor_version=False,
            enable_automatic_upgrade=False,
        )

        assert_that(install_result["provisioning_state"]).described_as(
            "Extension installation should succeed"
        ).is_equal_to("Succeeded")

        # Validate extension exists via SDK
        ext = extension.get(self.EXTENSION_NAME)
        assert_that(ext).is_not_none()
        assert_that(ext.name).is_equal_to(self.EXTENSION_NAME)

        log.info("Extension installed and visible via Azure control plane")

        # Update settings
        updated_settings = {
            "StaleRetentionSec": "1d",
        }

        log.info(f"Updating extension settings to {updated_settings}")

        update_result = extension.create_or_update(
            name=self.EXTENSION_NAME,
            publisher=self.PUBLISHER,
            type_=self.EXTENSION_NAME,
            type_handler_version=self.VERSION,
            settings=updated_settings,
            auto_upgrade_minor_version=False,
            enable_automatic_upgrade=False,
        )

        assert_that(update_result["provisioning_state"]).described_as(
            "Extension update should succeed"
        ).is_equal_to("Succeeded")

        log.info("Extension update succeeded")

        # Verify update correctness - check that settings were actually updated
        expected_value = "1d"
        ext = extension.get(self.EXTENSION_NAME)
        assert_that(ext.settings["StaleRetentionSec"]).described_as(
            f"Extension settings should be updated to {expected_value}"
        ).is_equal_to(expected_value)

        log.info(f"Verified extension settings updated correctly to {expected_value}")

        # Verify extension still exists after update
        ext_after_update = extension.get(self.EXTENSION_NAME)
        assert_that(ext_after_update).is_not_none()
        assert_that(ext_after_update.name).is_equal_to(self.EXTENSION_NAME)

        # Delete
        log.info("Deleting DNSServeStale extension")
        extension.delete(self.EXTENSION_NAME)

        assert_that(extension.check_exist(self.EXTENSION_NAME)).described_as(
            "Extension should be removed after delete"
        ).is_false()

        log.info("DNSServeStale extension lifecycle validated successfully")

    @TestCaseMetadata(
        description="""
        Validate DNSServeStale runtime behavior:
        - Install DNSServeStale extension
        - DNS resolves normally
        - DNS server becomes unreachable
        - DNS resolution succeeds using stale cache
        """,
        priority=2,
        requirement=simple_requirement(
            supported_features=[AzureExtension],
            supported_os=[CBLMariner],
        ),
    )
    def verify_dns_serve_stale_functionality(
        self, log: Logger, node: Node, result: TestResult
    ) -> None:
        import time

        environment = result.environment
        assert environment, "fail to get environment from testresult"
        platform = environment.platform
        assert isinstance(platform, AzurePlatform)

        extension = node.features[AzureExtension]

        # Test domain for DNS resolution
        test_domain = "dnsclientcachepackage-test.azurewebsites.net"

        # Install extension with stale retention
        settings = {"StaleRetentionSec": "1d"}

        log.info(
            f"Installing {self.EXTENSION_NAME} for runtime behavior test "
            f"with settings {settings}"
        )

        # Step 1: Install extension
        install_result = extension.create_or_update(
            name=self.EXTENSION_NAME,
            publisher=self.PUBLISHER,
            type_=self.EXTENSION_NAME,
            type_handler_version=self.VERSION,
            settings=settings,
            auto_upgrade_minor_version=False,
            enable_automatic_upgrade=False,
        )

        assert_that(install_result["provisioning_state"]).described_as(
            "Extension installation should succeed for runtime behavior test"
        ).is_equal_to("Succeeded")

        # Allow systemd-resolved to stabilize
        log.info("Waiting for systemd-resolved to stabilize...")
        time.sleep(30)

        # Step 2: Initial DNS resolution (should succeed)
        log.info(f"Running initial dig query for {test_domain}")
        dig1 = node.execute(f"dig {test_domain} +time=2 +tries=1", timeout=30)

        assert_that(dig1.exit_code).described_as(
            "Initial DNS query should succeed"
        ).is_equal_to(0)
        log.info("Initial DNS resolution works correctly")

        # Step 3: Get DNS server IP from resolvectl
        log.info("Fetching DNS server IP via resolvectl")
        resolvectl = node.execute("resolvectl status", sudo=True)

        assert_that(resolvectl.exit_code).described_as(
            "resolvectl status should succeed"
        ).is_equal_to(0)

        dns_ip = None
        for line in resolvectl.stdout.splitlines():
            if "DNS Servers:" in line:
                dns_ip = line.split("DNS Servers:")[1].strip().split()[0]
                break

        # Fallback to Azure default DNS if not found
        if not dns_ip:
            dns_ip = "168.63.129.16"
            log.info(f"Using default Azure DNS server: {dns_ip}")
        else:
            log.info(f"Detected DNS server IP: {dns_ip}")

        # Step 4: Block DNS traffic using iptables
        log.info(f"Blocking DNS traffic to {dns_ip}")
        node.execute(
            f"iptables -A OUTPUT -p udp -d {dns_ip} --dport 53 -j DROP", sudo=True
        )
        node.execute(
            f"iptables -A OUTPUT -p tcp -d {dns_ip} --dport 53 -j DROP", sudo=True
        )
        node.execute("iptables-save", sudo=True)
        log.info("DNS traffic blocked successfully")
        # Wait for DNS blocking to take effect
        log.info("Waiting 30 seconds for DNS blocking to take effect...")
        time.sleep(30)

        # Step 5: DNS query under failure (should initially fail)
        log.info(f"Running dig after blocking DNS (expected timeout) for {test_domain}")
        dig2 = node.execute(f"dig {test_domain} +time=2 +tries=1", timeout=30)

        assert_that(dig2.exit_code).described_as(
            "DNS query should initially fail when upstream is unreachable"
        ).is_not_equal_to(0)
        log.info("DNS query timed out as expected")

        log.info("Waiting 30 seconds again.")
        time.sleep(30)

        # Step 6: Retry DNS query (expected to succeed via stale cache)
        log.info(f"Retrying dig to validate stale cache behavior for {test_domain}")
        dig3 = node.execute(f"dig {test_domain} +time=2 +tries=2", timeout=30)

        log.info(f"Final DNS query output {dig3.stdout}")

        assert_that(dig3.exit_code).described_as(
            "DNS query should succeed using stale cache"
        ).is_equal_to(0)

        log.info("✓ DNS stale caching working - resolved using stale data")

        # Cleanup: Remove iptables rules
        log.info("Cleaning up iptables rules")
        node.execute(
            f"iptables -D OUTPUT -p udp -d {dns_ip} --dport 53 -j DROP", sudo=True
        )
        node.execute(
            f"iptables -D OUTPUT -p tcp -d {dns_ip} --dport 53 -j DROP", sudo=True
        )
        node.execute("iptables-save", sudo=True)

        # Test DNS resolution works again after cleanup
        final_dig_result = node.execute(
            f"dig {test_domain} +time=2 +tries=1", timeout=30
        )
        assert_that(final_dig_result.exit_code).described_as(
            f"Final dig for {test_domain} should succeed after cleanup"
        ).is_equal_to(0)

        log.info("DNS resolution restored after iptables cleanup")

        # Cleanup extension
        extension.delete(self.EXTENSION_NAME)
        assert_that(extension.check_exist(self.EXTENSION_NAME)).described_as(
            "Extension should be removed after runtime behavior test"
        ).is_false()

        log.info("✓ DNSServeStale runtime behavior validated successfully")
