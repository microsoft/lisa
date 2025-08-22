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
from lisa.operating_system import (
    SLES,
    CBLMariner,
    CentOs,
    Debian,
    Oracle,
    Redhat,
    Suse,
    Ubuntu,
)
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.util import SkippedException


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="Tests for the Azure Network Watcher VM Extension",
)
class NetworkWatcherExtension(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        if not self._is_supported_linux_distro(node):
            raise SkippedException(
                f"{str(node.os.information.full_version)} is not supported."
            )

    @TestCaseMetadata(
        description="""
        Installs and runs the Azure Network Watcher VM Extension.
        Deletes the VM Extension.
        """,
        priority=1,
        requirement=simple_requirement(
            supported_features=[AzureExtension],
        ),
    )
    def verify_azure_network_watcher(self, log: Logger, node: Node) -> None:
        # Run VM Extension
        extension = node.features[AzureExtension]

        extension_result = extension.create_or_update(
            name="AzureNetworkWatcherAgentLinux",
            publisher="Microsoft.Azure.NetworkWatcher",
            type_="NetworkWatcherAgentLinux",
            type_handler_version="1.4",
            auto_upgrade_minor_version=True,
        )

        assert_that(extension_result["provisioning_state"]).described_as(
            "Expected the extension to succeed"
        ).is_equal_to("Succeeded")

        # Delete VM Extension
        extension.delete("AzureNetworkWatcherAgentLinux")

        assert_that(
            extension.check_exist("AzureNetworkWatcherAgentLinux")
        ).described_as(
            "Found the VM Extension still unexpectedly exists on the VM after deletion"
        ).is_false()

    def _is_supported_linux_distro(self, node: Node) -> bool:
        supported_major_versions = {
            Redhat: [7, 8],
            CentOs: [6, 7],
            Oracle: [6, 7],
            Debian: [7, 8],
            Ubuntu: [16, 18, 20, 22],
            Suse: [12, 15],
            SLES: [12, 15],
            CBLMariner: [2, 3],
        }

        for distro in supported_major_versions:
            if type(node.os) is distro:
                version_list = supported_major_versions.get(distro)
                if (
                    version_list is not None
                    and node.os.information.version.major in version_list
                ):
                    return True
                else:
                    return False
        return False
