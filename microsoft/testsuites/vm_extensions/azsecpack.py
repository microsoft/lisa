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
from lisa.operating_system import CBLMariner, Debian, Posix, Ubuntu
from lisa.sut_orchestrator.azure.tools import Azsecd
from lisa.tools import Cat, Journalctl, Rpm, Service


@TestSuiteMetadata(
    area="azsecpack",
    category="functional",
    description="""
    This test is a BVT for the following services in the AzSecPack:
    Azure-security, Azsec-monitor, Auoms
    """,
)
class AzSecPack(TestSuite):
    @TestCaseMetadata(
        description="""
            Verify whether Azure-Security, Azsec-monitor, Auoms is installed, 
            running, and uninstalled successfully
        """,
        priority=1,
        use_new_environment=True,
    )
    def verify_azsecpack(self, node: Node, log: Logger) -> None:
        log.info("Waiting to setup azsecpack")

        rpm = node.tools[Rpm]

        # Check if azsec packages are already installed
        if (
            node.execute("rpm -ql azure-security").exit_code == 0
            and node.execute("rpm -ql azsec-monitor").exit_code == 0
            and node.execute("rpm -ql azsec-clamav").exit_code == 0
            and node.execute("rpm -ql auoms").exit_code == 0
        ):
            log.info("Azsecpack is already installed")
        else:
            i = 0
            while i < 10:
                time.sleep(60)
                if (
                    node.execute("rpm -ql azure-security").exit_code == 0
                    and node.execute("rpm -ql azsec-monitor").exit_code == 0
                    and node.execute("rpm -ql azsec-clamav").exit_code == 0
                    and node.execute("rpm -ql auoms").exit_code == 0
                ):
                    break
                i += 1

            if i == 10:
                log.error("Packages not installed properly")

        azure_security = "-ql azure-security"
        result = rpm.run(azure_security)
        log.info(result.stdout)
        log.info(result.stderr)
        log.info(result.exit_code)
        assert_that(result.stderr).is_equal_to("")
        assert_that(result.exit_code).is_equal_to(0)
        log.info("Azure-Security is installed successfully")

        azsec_clamav = "-ql azsec-clamav"
        result = rpm.run(azsec_clamav)
        log.info(result.stdout)
        log.info(result.stderr)
        log.info(result.exit_code)
        assert_that(result.stderr).is_equal_to("")
        assert_that(result.exit_code).is_equal_to(0)
        log.info("Azsec-clamav is installed successfully")

        azsec_monitor = "-ql azsec-monitor"
        result = rpm.run(azsec_monitor)
        log.info(result.stdout)
        log.info(result.stderr)
        log.info(result.exit_code)
        assert_that(result.stderr).is_equal_to("")
        assert_that(result.exit_code).is_equal_to(0)
        log.info("Azsec-monitor is installed successfully")

        auoms = "-ql auoms"
        result = rpm.run(auoms)
        log.info(result.stdout)
        log.info(result.stderr)
        log.info(result.exit_code)
        assert_that(result.stderr).is_equal_to("")
        assert_that(result.exit_code).is_equal_to(0)
        log.info("Auoms is installed successfully")

        systemctl = node.tools[Service]

        verify_azure_security = "status azsecd.service"
        verify_run = systemctl.run(verify_azure_security)
        log.info(verify_run.stdout)
        assert_that(verify_run.stderr).is_equal_to("")
        assert_that(verify_run.exit_code).is_equal_to(0)
        log.info("Azure-Security is running successfully")

        verify_azsec_monitor = "status azsecmond.service"
        verify_run = systemctl.run(verify_azsec_monitor)
        log.info(verify_run.stdout)
        assert_that(verify_run.stderr).is_equal_to("")
        assert_that(verify_run.exit_code).is_equal_to(0)
        log.info("Azsec-monitor is running successfully")

        verify_auoms = "status auoms.service"
        verify_run = systemctl.run(verify_auoms)
        log.info(verify_run.stdout)
        assert_that(verify_run.stderr).is_equal_to("")
        assert_that(verify_run.exit_code).is_equal_to(0)
        log.info("Auoms is running successfully")

        azsecd = node.tools[Azsecd]

        verify_run = azsecd.run("status", sudo=True)
        log.info(verify_run.stdout)
        autoconfig_log = verify_run.stdout
        assert_that(verify_run.stderr).is_equal_to("")
        assert_that(verify_run.exit_code).is_equal_to(0)
        assert_that(
            autoconfig_log.find("Enabled(true), MdsdTenantStatus(running)") >= 0
        )
        assert_that(
            autoconfig_log.find(
                "Path(/var/run/mdsd/asa/default_djson.socket)\nIsAvailableToConnect(true)"
            )
            >= 0
        )
        assert_that(
            autoconfig_log.find(
                "Path(/var/run/azsecmon/azsecmond.socket)\nIsAvailableToConnect(true)"
            )
            >= 0
        )

        journalctl = node.tools[Journalctl]

        journalctl_run = journalctl.run("-ru azsecd", sudo=True)
        assert_that(journalctl_run.stdout.find("Connected to mdsd") >= 0)
        log.info("Azsecd connection to mdsd is successful")
        assert_that(journalctl_run.stdout.find("Scan 'certsinuse' completed") >= 0)
        log.info("Scan 'certsinuse' completed")
        assert_that(journalctl_run.stdout.find("Scan 'heartbeat' completed") >= 0)
        log.info("Scan 'heartbeat' completed")

        journalctl_run = journalctl.run("-ru azsecmond", sudo=True)
        assert_that(journalctl_run.stdout.find("Connected to mdsd") >= 0)
        log.info("Azsecmond connection to mdsd is successful")

        journalctl_run = journalctl.run("-ru auoms", sudo=True)
        assert_that(journalctl_run.stdout.find("Output(mdsd): Connected") >= 0)
        log.info("Auoms connection to mdsd is successful")
        assert_that(journalctl_run.stdout.find("Output(azsecmond): Connected") >= 0)
        log.info("Auoms connection to azsecmond is successful")

        mdsd_logs = ""
        cat = node.tools[Cat]
        i = 0
        while mdsd_logs == "" and i < 15:
            mdsd_logs = cat.read("/var/log/mdsd/asa.qos", sudo=True)
            time.sleep(60)
            i += 1

        assert_that(
            mdsd_logs.find("MaRunTransmitBondNotification,LinuxAsmHeartbeat") >= 0
        )
        log.info("LinuxAsmHeartbeat is transmitted to Geneva")
        assert_that(mdsd_logs.find("MaRunTransmitBondNotification,LinuxAsmAudit") >= 0)
        log.info("LinuxAsmAudit is transmitted to Geneva")
        assert_that(mdsd_logs.find("MaRunTransmitBondNotification,LinuxAsmAlert") >= 0)
        log.info("LinuxAsmAlert is transmitted to Geneva")
        log.info(
            "Azsecpack Autoconfig is configured successfully, Connected to mdsd successfully"
        )

    def before_suite(self, node: Node, log: Logger, **kwargs: Any) -> None:
        package_name = "azure-mdsd"
        node.os.install_packages(package_name)
        log.info("Installed azure-mdsd")

        systemctl = node.tools[Service]

        enable_mdsdmgr = systemctl.run("enable mdsdmgr.service", sudo=True)
        log.info("Enabled mdsdmgr")
        start_mdsdmgr = systemctl.run("start mdsdmgr.service", sudo=True)
        log.info("Started mdsdmgr")
        log.info(systemctl.run("status mdsdmgr.service").stdout)

        enable_mdsd_amacoreagent = systemctl.run(
            "enable mdsd-amacoreagent.service", sudo=True
        )
        log.info("Enabled mdsd-amacoreagent")
        start_mdsd_amacoreagent = systemctl.run(
            "start mdsd-amacoreagent.service", sudo=True
        )
        log.info("Started mdsd-amacoreagent")
        log.info(systemctl.run("status mdsd-amacoreagent.service").stdout)

        log.info(systemctl.run("status mdsd.service").stdout)

    def _is_supported(self, node: Node) -> None:
        supported_versions: Dict[Any, List[str]] = {
            CBLMariner: ["1.0", "2.0"],
            Ubuntu: ["18.04", "20.04"],
            Debian: ["10"],
        }
        release = self._node.os.information.release
        if release not in supported_versions.get(type(self._node.os), []):
            raise SkippedException(
                UnsupportedDistroException(node.os, " doesn't support this version.")
            )
