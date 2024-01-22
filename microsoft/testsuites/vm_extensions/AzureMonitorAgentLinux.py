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
    CpuArchitecture,
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
    description="Tests for the Azure Monitor Agent Linux VM Extension",
)
class AzureMonitorAgentLinuxExtension(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        if not self._is_supported_linux_distro(node):
            raise SkippedException(
                f"{str(node.os.information.full_version)} is not supported."
            )

    @TestCaseMetadata(
        description="""
        Installs and runs the Azure Monitor Agent Linux VM Extension.
        Deletes the VM Extension.
        """,
        priority=1,
        requirement=simple_requirement(
            supported_features=[AzureExtension],
        ),
    )
    def verify_azuremonitoragent_linux(self, log: Logger, node: Node) -> None:
        # Run VM Extension
        extension = node.features[AzureExtension]

        extension_result = extension.create_or_update(
            name="AzureMonitorLinuxAgent",
            publisher="Microsoft.Azure.Monitor",
            type_="AzureMonitorLinuxAgent",
            type_handler_version="1.0",
            auto_upgrade_minor_version=True,
        )

        assert_that(extension_result["provisioning_state"]).described_as(
            "Expected the extension to succeed"
        ).is_equal_to("Succeeded")

        # Delete VM Extension
        extension.delete("AzureMonitorLinuxAgent")

        assert_that(extension.check_exist("AzureMonitorLinuxAgent")).described_as(
            "Found the VM Extension still unexpectedly exists on the VM after deletion"
        ).is_false()

    def _is_supported_linux_distro(self, node: Node) -> bool:
        supported_major_versions_x86_64 = {
            Redhat: [7, 8, 9],
            CentOs: [7, 8],
            Oracle: [7, 8, 9],
            Debian: [9, 10, 11],
            Ubuntu: [16, 18, 20],
            Suse: [12, 15],
            SLES: [12, 15],
            CBLMariner: [2],
        }

        supported_major_versions_arm64 = {
            Redhat: [8],
            CentOs: [7],
            Debian: [11],
            Ubuntu: [18, 20],
            SLES: [15],
            CBLMariner: [2],
        }

        for distro in supported_major_versions_x86_64:
            if type(node.os) == distro:
                version_list = None
                arch = node.os.get_kernel_information().hardware_platform
                if arch == CpuArchitecture.ARM64:
                    version_list = supported_major_versions_arm64.get(distro)
                else:
                    version_list = supported_major_versions_x86_64.get(distro)

                if (
                    version_list is not None
                    and node.os.information.version.major in version_list
                ):
                    return True
                else:
                    return False
        return False
