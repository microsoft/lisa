import string
from datetime import datetime, timezone
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
    AlmaLinux,
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
    def verify_azure_network_watcher(
        self, log: Logger, node: Node
    ) -> None:

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
            Debian: [8, 9, 10, 11],
            Ubuntu: [14, 16, 18, 20],
            Suse: [12, 15],
            SLES: [12, 15],
            AlmaLinux: [8],
            CBLMariner: [2],
        }

        for distro in supported_major_versions:
            if type(node.os) == distro:
                version_list = supported_major_versions.get(distro)
                if (
                    version_list is not None
                    and node.os.information.version.major in version_list
                    and not self._is_unsupported_version(node)
                ):
                    return True
                else:
                    return False
        return False

    def _is_unsupported_version(self, node: Node) -> bool:
        """
        These are specific Linux distro versions that are
        not supported by Azure Network Watcher Extension,
        even though the major version is generally supported
        """
        version = node.os.information.version
        if type(node.os) and (version == "8.0.0" or version == "8.0.1"):
            return True
        else:
            return False
