from typing import Any, Dict, List, cast

from assertpy import assert_that

from lisa import (Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata,
                  simple_requirement)
from lisa.operating_system import CBLMariner, Debian, Posix, Ubuntu
from lisa.sut_orchestrator.azure.tools import Waagent
from lisa.tools import Cat, Echo, Rpm, Service
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
            Verify whether MetricsExtension is installed, running, and uninstalled successfully
        """,
        priority=1,
        use_new_environment=True,
    )
    def verify_metricsextension(self, node: Node, log: Logger) -> None:
        # https://eng.ms/docs/products/geneva/getting_started/environments/metrics/linux_vm
        #self._is_supported(node)
        posix_os: Posix = cast(Posix, node.os)
        posix_os.add_azure_core_repo()
        self._install_dep_packages(node)

        # Install metricsext2
        posix_os.install_packages("metricsext2")

        echo = node.tools[Echo]
        echo.write_to_file(
            value="MDM_OPTIONS=-Logger syslog -LogLevel Info -MonitoringAccount testMarinerIDC",
            file="/etc/default/mdm",
            sudo=True,
        )
        log.info("Setting MDM_OPTIONS")
        log.info(node.execute("cat /etc/default/mdm", sudo=True).stdout)
        log.info("MetricsExtension is installed successfully")

        service = node.tools[Service]
        service.restart_service("mdm")
        log.info("MetricsExtension is started successfully")

        assert_that(service.check_service_status("mdm")).is_equal_to(True)
        log.info("MetricsExtension is running successfully")

    def _is_supported(self, node: Node) -> None:
        supported_versions: Dict[Any, List[str]] = {
            CBLMariner: ["1.0", "2.0"],
            Ubuntu: ["18.04", "20.04"],
            Debian: ["10"],
        }
        release = node.os.information.release
        if release not in supported_versions.get(type(node.os), []):
            raise SkippedException(
                UnsupportedDistroException(node.os, "MDM doesn't support this version.")
            )

    def _install_dep_packages(self, node: Node) -> None:
        package_list: List[str] = []
        posix_os: Posix = cast(Posix, node.os)
        if isinstance(node.os, CBLMariner):
            package_list.extend(
                [
                    "diffutils",
                    "autoconf",
                    "libtool",
                    "automake",
                    "gettext",
                    "binutils",
                    "glibc-devel",
                    "kernel-headers",
                ]
            )

        for package in list(package_list):
            if posix_os.is_package_in_repo(package):
                posix_os.install_packages(package)
