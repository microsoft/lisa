from pathlib import PurePath
from typing import Any, Dict, List, cast

from assertpy import assert_that

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.operating_system import CBLMariner, Debian, Posix, Ubuntu
from lisa.tools import Curl, Echo, Service
from lisa.util import LisaException, SkippedException, UnsupportedDistroException


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
            Verify whether MetricsExtension is installed, running, updated,
            and uninstalled successfully
        """,
        priority=2,
        use_new_environment=True,
    )
    def verify_metricsextension(self, node: Node, log: Logger) -> None:
        package = "metricsext2"
        posix_os: Posix = cast(Posix, node.os)
        self._is_supported(node)

        # Add repo
        if isinstance(posix_os, CBLMariner):
            release = posix_os.information.release
            curl = node.tools[Curl]
            curl.fetch(
                arg="-o /etc/yum.repos.d/mariner-extras.repo",
                execute_arg="",
                url=f"https://raw.githubusercontent.com/microsoft/CBL-Mariner/{release}/SPECS/mariner-repos/mariner-extras.repo",  # noqa: E501
                sudo=True,
            )
        else:
            posix_os.add_azure_core_repo()

        # Install metricsext2
        is_installed = posix_os.package_exists(package)
        if not is_installed:
            if posix_os.is_package_in_repo(package):
                posix_os.install_packages(package)
                log.info("MetricsExtension is installed successfully")
            else:
                raise LisaException(
                    f"The supported distro doesn't have {package} in its repo"
                )
        else:
            log.info("MetricsExtension is already installed")

        # Set MDM options
        echo = node.tools[Echo]
        echo.write_to_file(
            value="MDM_OPTIONS=-Logger syslog -LogLevel Info -MonitoringAccount testMarinerIDC",  # noqa: E501
            file=PurePath("/etc/default/mdm"),
            sudo=True,
        )
        log.info("Setting MDM_OPTIONS")
        log.info(node.execute("cat /etc/default/mdm", sudo=True).stdout)
        log.info("MetricsExtension is installed successfully")

        # Start the service and check the status
        service = node.tools[Service]
        service.restart_service("mdm")
        log.info("MetricsExtension is started successfully")
        assert_that(service.check_service_status("mdm")).is_equal_to(True)
        log.info("MetricsExtension is running successfully")

        # Uninstall metricsext2 if it doesn't exist originally
        if not is_installed:
            posix_os.uninstall_packages(package)
            log.info("MetricsExtension is removed successfully")

    def _is_supported(self, node: Node) -> None:
        # MDM is only supported
        supported_versions: Dict[Any, List[str]] = {
            CBLMariner: ["1.0", "2.0"],
            Ubuntu: ["18.04", "20.04"],
            Debian: [f"10.{i}" for i in range(0, 14)],
        }
        release = node.os.information.release
        if release not in supported_versions.get(type(node.os), []):
            raise SkippedException(
                UnsupportedDistroException(node.os, "MDM doesn't support this version.")
            )
