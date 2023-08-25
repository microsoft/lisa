import time
from typing import Any

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import CBLMariner, Debian, Posix, RPMDistro
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.tools import Azsecd
from lisa.tools import Cat, Journalctl, Rpm, Service


@TestSuiteMetadata(
    area="AzSecPack",
    category="functional",
    description="""
    This test is a BVT for the following services in the AzSecPack: Azure-security, Azsec-monitor, Auoms

    If the subscription is within AutoConfig scope, the AutoCoonfig onboarding method
    is recommended. It needs adding resoure tag for AzSecPack, creating and assigning
    UserAssigned Managed Identity AzSecPack AutoConfig to the ARM resources.

    The test uses the extension onboarding method to onboard AzSecPack.

    install Azure Monitor Linux Agent extension and uninstall it
    install AzureSecurityLinuxAgent VM extension and uninstall it
    Following below link to onboard AzSecPack:
    Another way is to use 
    """,
)
class AzSecPack(TestSuite):
    @TestCaseMetadata(
        description="""
            Verify whether Azure-Security, Azsec-monitor, Auoms is installed, running, and uninstalled successfully
        """,
        priority=0,
        use_new_environment=True,
    )
    def verify_azsecpack(self, node: Node, log: Logger) -> None:
        # Use the Azure Monitor Linux Agent extension to install the monitoring agent
        # Refer to https://eng.ms/docs/products/geneva/getting_started/environments/linuxvm
        # When using az cli, one parameter is --settings, the json is '{"genevaConfiguration":{"enable":true}}', please translate it to python dict
        # When using AzureExtension, the parameter is settings, the json is '{"genevaConfiguration":{"enable":true}}', please translate it to python dict
        # The extension will be installed in the VM, and the extension will be uninstalled after the test
        # the setting is different with mariner test case
        settings = {"genevaConfiguration": {"enable": True}}
        extension = node.features[AzureExtension]
        result = extension.create_or_update(
            name="AzureMonitorLinuxAgent",
            publisher="Microsoft.Azure.Monitor",
            type_="AzureMonitorLinuxAgent",
            type_handler_version="1.0",
            auto_upgrade_minor_version=True,
            enable_automatic_upgrade=True,
            settings=settings
        )
        assert_that(result["provisioning_state"]).described_as(
            "Expected the extension to succeed"
        ).is_equal_to("Succeeded")

        # Install AzureSecurityLinuxAgent VM extension
        azsec_settings = {
            "enableGenevaUpload": True,
            "AMASocketBasePath": "/var/run/mdsd/asa"
        }
        result = extension.create_or_update(
            name="AzureSecurityLinuxAgent",
            publisher="Microsoft.Azure.Security.Monitoring",
            type_="AzureSecurityLinuxAgent",
            type_handler_version="2.0",
            auto_upgrade_minor_version=True,
            enable_automatic_upgrade=True,
            settings=azsec_settings
        )
        assert_that(result["provisioning_state"]).described_as(
            "Expected the extension to succeed"
        ).is_equal_to("Succeeded")


