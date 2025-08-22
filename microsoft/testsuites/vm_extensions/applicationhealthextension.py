from typing import Any

from assertpy import assert_that
from retry import retry

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
    description="Tests for the Application Health Extension (AHE) on Linux",
)
class ApplicationHealthExtension(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        if not self._is_supported_linux_distro(node):
            raise SkippedException(
                f"{str(node.os.information.full_version)} is not supported."
            )

    @TestCaseMetadata(
        description="""
        Installs and verifies the Application Health Extension (AHE).
        Checks logs for expected message.
        Deletes the VM Extension.
        """,
        priority=1,
        requirement=simple_requirement(
            supported_features=[AzureExtension],
        ),
    )
    def verify_application_health_extension(self, log: Logger, node: Node) -> None:
        extension = node.features[AzureExtension]

        extension_result = extension.create_or_update(
            name="HealthExtension",
            publisher="Microsoft.ManagedServices.Edp",
            type_="ApplicationHealthLinux",
            type_handler_version="2.0",
            auto_upgrade_minor_version=True,
        )

        assert_that(extension_result["provisioning_state"]).described_as(
            "Expected the extension to succeed"
        ).is_equal_to("Succeeded")

        self._check_extension_logs(
            node=node,
            log_file="/var/log/azure/applicationhealth-extension/handler.log",
            expected_app_health_message="Committed health state is healthy",
        )

        extension.delete("HealthExtension")

        assert_that(extension.check_exist("HealthExtension")).described_as(
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

    @retry(tries=5, delay=60)  # type:ignore
    def _check_extension_logs(
        self, node: Node, log_file: str, expected_app_health_message: str
    ) -> None:
        result = node.execute(
            f"grep '{expected_app_health_message}' {log_file}", sudo=True
        )
        assert_that(result.exit_code).described_as(
            f"Expected to find '{expected_app_health_message}' in {log_file}"
        ).is_equal_to(0)
