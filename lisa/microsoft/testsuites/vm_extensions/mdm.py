from typing import Any, Dict, List, cast

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import CBLMariner, Debian, Posix, Ubuntu
from lisa.sut_orchestrator import AZURE, READY
from lisa.tools import Sed, Service
from lisa.util import SkippedException, UnsupportedDistroException


@TestSuiteMetadata(
    area="MetricsExtension",
    category="functional",
    description="""
    This test is a BVT for MDM MetricsExtension
    """,
)
class MetricsExtension(TestSuite):
    @TestCaseMetadata(
        description="""
            Verify whether MetricsExtension is installed, running,
            and uninstalled successfully
        """,
        priority=1,
        use_new_environment=True,
        requirement=simple_requirement(supported_platform_type=[AZURE, READY]),
    )
    def verify_metricsextension(self, node: Node, log: Logger) -> None:
        package = "metricsext2"
        posix_os: Posix = cast(Posix, node.os)
        self._is_supported(node)

        # Add repo
        posix_os.add_azure_core_repo()

        # Install metricsext2
        is_installed = posix_os.package_exists(package)
        if not is_installed:
            if posix_os.is_package_in_repo(package):
                posix_os.install_packages(package)
                log.info("MetricsExtension is installed successfully")
            else:
                raise UnsupportedDistroException(
                    node.os, f"The distro doesn't have {package} in its repo"
                )
        else:
            log.info("MetricsExtension is already installed")

        # Set MDM options
        file_name = "/etc/default/mdm"
        sed = node.tools[Sed]
        sed.substitute(
            match_lines="^MDM_OPTIONS",
            regexp="MDM_OPTIONS",
            replacement="#MDM_OPTIONS",
            file=file_name,
            sudo=True,
        )
        sed.append(
            "MDM_OPTIONS=-Logger syslog -LogLevel Info -MonitoringAccount test",
            file_name,
            sudo=True,
        )
        node.execute("cat /etc/default/mdm", sudo=True)

        # Start the service and check the status
        service = node.tools[Service]
        service.restart_service("mdm")
        assert_that(service.check_service_status("mdm")).is_equal_to(True)
        log.info("MetricsExtension is running successfully")

        # Uninstall metricsext2 if it doesn't exist originally
        if not is_installed:
            posix_os.uninstall_packages(package)
            log.info("MetricsExtension is removed successfully")

    def _is_supported(self, node: Node) -> None:
        # MetricsExtension only supports these distributions
        supported_versions: Dict[Any, List[str]] = {
            CBLMariner: ["1.0", "2.0"],
            Ubuntu: ["18.04", "20.04"],
            Debian: [f"10.{i}" for i in range(0, 14)],
        }
        release = node.os.information.release
        if release not in supported_versions.get(type(node.os), []):
            raise SkippedException(
                UnsupportedDistroException(
                    node.os, "MetricsExtension  doesn't support this version."
                )
            )
