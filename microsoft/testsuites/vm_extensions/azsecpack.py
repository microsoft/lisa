import time
from typing import cast

from assertpy import assert_that
from azure.core.exceptions import HttpResponseError
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
    BSD,
    SLES,
    AlmaLinux,
    CBLMariner,
    CentOs,
    Debian,
    Oracle,
    Posix,
    Redhat,
    Ubuntu,
)
from lisa.sut_orchestrator.azure.common import (
    add_tag_for_vm,
    add_user_assign_identity,
    get_managed_service_identity_client,
    get_node_context,
)
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.sut_orchestrator.azure.tools import Azsecd
from lisa.testsuite import TestResult
from lisa.tools import Journalctl, Service
from lisa.util import (
    LisaException,
    SkippedException,
    UnsupportedDistroException,
    check_till_timeout,
)


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="""
    BVT for Azure Security Pack.
    Azure Security Pack includes core security features that provide security logging
    and monitoring coverage for the service.

    This test suite validate if Azure security pack can be installed, uninstalled
    successfully, and check if the autoconfig is configured successfully.

    This test requires your subscription is within AutoConfig scope. It manually enables
    the AzSecPack AutoConfig on the Linux VM. The steps are:
    1. Add resource tag for AzSecPack
    2. Create an assign user assigned managed identity AzSecPack to the VM
    3. Add Azure VM extensions for AMA and ASA to the VM

    If the subscription is within AutoConfig scope, the AutoCoonfig onboarding method
    is recommended. It needs adding resoure tag for AzSecPack, creating and assigning
    UserAssigned Managed Identity AzSecPack AutoConfig to the ARM resources.
    """,
)
class AzSecPack(TestSuite):
    @TestCaseMetadata(
        description="""
            Verify whether Azure security pack can be installed, uninstalled
            successfully, and check if the autoconfig is configured successfully.
        """,
        priority=1,
        requirement=simple_requirement(
            supported_features=[AzureExtension], unsupported_os=[BSD]
        ),
    )
    def verify_azsecpack(self, node: Node, log: Logger, result: TestResult) -> None:
        self._is_supported(node)

        environment = result.environment
        assert environment, "fail to get environment from testresult"
        platform = environment.platform
        assert isinstance(platform, AzurePlatform)
        rm_client = platform._rm_client
        assert rm_client
        msi_client = get_managed_service_identity_client(platform)

        node_context = get_node_context(node)
        resource_group_name = node_context.resource_group_name
        location = node_context.location
        vm_name = node_context.vm_name

        # Add resource tag for AzSecPack
        tag = {"azsecpack": "nonprod"}
        add_tag_for_vm(platform, resource_group_name, vm_name, tag, log)

        # Create an AzSecPackAutoConfigRG resource group with the specific location
        # For Public cloud, the specific location is "eastus".
        # Note: The resource group name can't be changed.
        autoconfig_rg_name = "AzSecPackAutoConfigRG"
        autoconfig_rg_exists = rm_client.resource_groups.check_existence(
            autoconfig_rg_name
        )
        if not autoconfig_rg_exists:
            params = {"location": "eastus"}
            rm_client.resource_groups.create_or_update(autoconfig_rg_name, params)
            log.info(f"{autoconfig_rg_name} is created successfully")
        else:
            log.info(f"{autoconfig_rg_name} is already existed")

        # Create a user assigned managed identity
        msi_name = f"AzSecPackAutoConfigUA-{location}"
        msi = msi_client.user_assigned_identities.create_or_update(
            resource_group_name=autoconfig_rg_name,
            resource_name=msi_name,
            parameters={"location": location},
        )
        log.info(f"{msi.id} is created successfully")

        # Assign the user assigned managed identity to the VM
        add_user_assign_identity(platform, resource_group_name, vm_name, msi.id, log)

        # mdsd should be installed fisrtly
        self._install_mdsd(node, log)
        # Install agent extension
        try:
            self._install_monitor_agent_extension(node)
            self._install_security_agent_extension(node, log)
        except HttpResponseError as e:
            if any(
                s in str(e)
                for s in ["OS is not supported", "Unsupported operating system"]
            ):
                raise SkippedException(UnsupportedDistroException(node.os))
            else:
                raise e

        # Check and verify
        self._check_mdsd_service_status(node, log)
        self._check_azsec_services_status(node, log)
        self._check_azsecd_status(node, log)
        self._check_azsecd_scanners(node, log)
        self._check_journalctl_logs(node, log)

    def _install_mdsd(self, node: Node, log: Logger) -> None:
        package = "azure-mdsd"
        posix_os: Posix = cast(Posix, node.os)
        is_installed = posix_os.package_exists(package)
        if not is_installed:
            posix_os.add_azure_core_repo()
            if posix_os.is_package_in_repo(package):
                posix_os.install_packages(package)
                log.info("azure-mdsd is installed successfully")
            else:
                raise UnsupportedDistroException(
                    node.os, f"The distro doesn't have {package} in its repo"
                )
        else:
            log.info("azure-mdsd is already installed")

    def _install_monitor_agent_extension(self, node: Node) -> None:
        # Use the Azure Monitor Linux Agent extension to install the monitoring agent
        # This test uses autoconfig, the settings should be {"GCS_AUTO_CONFIG":true}
        settings = {"GCS_AUTO_CONFIG": True}
        extension = node.features[AzureExtension]
        try:
            result = extension.create_or_update(
                name="AzureMonitorLinuxAgent",
                publisher="Microsoft.Azure.Monitor",
                type_="AzureMonitorLinuxAgent",
                type_handler_version="1.0",
                auto_upgrade_minor_version=True,
                enable_automatic_upgrade=True,
                settings=settings,
            )
            assert_that(result["provisioning_state"]).described_as(
                "Expected the extension to succeed"
            ).is_equal_to("Succeeded")
        except HttpResponseError as e:
            if "already added" in str(e):
                node.log.debug(
                    "AzureMonitorLinuxAgent has been installed in current VM."
                )
                result = extension.get("Microsoft.Azure.Monitor.AzureMonitorLinuxAgent")
                node.log.debug(f"extension status {result.provisioning_state}")
            else:
                raise e

        # After Azure Monitor Linux Agent extension is installed, the package
        # azuremonitoragent should be installed.
        posix_os: Posix = cast(Posix, node.os)
        check_till_timeout(
            lambda: posix_os.package_exists("azuremonitoragent") is True,
            timeout_message="Expected the azuremonitoragent package to be installed",
        )

    def _install_security_agent_extension(self, node: Node, log: Logger) -> None:
        # Install AzureSecurityLinuxAgent VM extension
        azsec_settings = {
            "enableGenevaUpload": True,
            "enableAutoConfig": True,
        }
        extension = node.features[AzureExtension]
        try:
            result = extension.create_or_update(
                name="AzureSecurityLinuxAgent",
                publisher="Microsoft.Azure.Security.Monitoring",
                type_="AzureSecurityLinuxAgent",
                type_handler_version="2.0",
                auto_upgrade_minor_version=True,
                enable_automatic_upgrade=True,
                settings=azsec_settings,
            )
            assert_that(result["provisioning_state"]).described_as(
                "Expected the extension to succeed"
            ).is_equal_to("Succeeded")
        except HttpResponseError as e:
            if "already added" in str(e):
                node.log.debug(
                    "AzureSecurityLinuxAgent has been installed in current VM."
                )
            else:
                raise e

        # Check azure-security, azsec-monitor, azsec-clamav, auoms are installed
        # After installing extension, some packages might not be installed completely.
        # So add a loop to check if all packages are installed.
        posix_os: Posix = cast(Posix, node.os)
        azsec_packages = ["azure-security", "azsec-monitor", "azsec-clamav", "auoms"]
        loop_count = 0
        while loop_count < 30:
            result = True
            for package in azsec_packages:
                result = posix_os.package_exists(package) and result
                if result is False:
                    log.info(f"{package} is not installed successfully")
                    break
            if result is True:
                break
            time.sleep(5)
            loop_count += 1

        assert_that(result).described_as(
            "The packages of Azure security extension might not be installed properly"
        ).is_equal_to(True)

    def _check_mdsd_service_status(self, node: Node, log: Logger) -> None:
        arch = node.os.get_kernel_information().hardware_platform  # type: ignore
        if arch == "aarch64":
            mdsd_services = ["mdsdmgr"]
        else:
            mdsd_services = ["mdsdmgr", "mdsd-amacoreagent"]
        service = node.tools[Service]
        for mdsd_service in mdsd_services:
            service.enable_service(mdsd_service)
            service.restart_service(mdsd_service)
            assert_that(service.check_service_status(mdsd_service)).described_as(
                f"{mdsd_service} is not running successfully"
            ).is_equal_to(True)
            log.info(f"{mdsd_service} is running successfully")

    @retry(tries=5, delay=10)  # type:ignore
    def _check_azsec_services_status(self, node: Node, log: Logger) -> None:
        service = node.tools[Service]
        azsec_services = ["azsecd", "azsecmond", "auoms"]
        for azsec_service in azsec_services:
            assert_that(service.check_service_status(azsec_service)).described_as(
                f"{azsec_service} is not running successfully"
            ).is_equal_to(True)
            log.info(f"{azsec_service} is running successfully")

    @retry(tries=20, delay=30)  # type:ignore
    def _check_azsecd_status(self, node: Node, log: Logger) -> None:
        azsecd = node.tools[Azsecd]
        output = azsecd.run(
            parameters="status",
            sudo=True,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to run azsecd status",
        ).stdout
        strings_to_check = [
            "Enabled(true), MdsdTenantStatus(running)",
            "Path(/var/run/mdsd/asa/default_djson.socket)\r\n\t\t"
            "IsAvailableToConnect(true)",
            "Path(/var/run/azsecmon/azsecmond.socket)\r\n\t\t"
            "IsAvailableToConnect(true)",
        ]
        # It is expected that the socket conection is not available until autoconfig
        # is enabled and asa mdsd tenant is in running state. Wait for 7+ minutes
        # after deploying the required changes for autoconfig. So retries 20 times
        # with delay 30s
        for s in strings_to_check:
            if s not in output:
                raise LisaException(
                    f"'{s}' string is not in azsecd status output. "
                    "Please check if azsecd is running successfully."
                )
        log.info("Azsecd status is checked successfully")

    @retry(tries=5, delay=10)  # type:ignore
    def _check_azsecd_scanners(self, node: Node, log: Logger) -> None:
        azsecd = node.tools[Azsecd]
        scanners = ["heartbeat", "time", "certsinuse"]
        for s in scanners:
            output = azsecd.run_scanners(s)
            if f"Scan '{s}' completed" not in output:
                raise LisaException(
                    f"'Scan {s} completed' string is not in the output."
                    " Please check if azsecd scanner is running successfully."
                )

    @retry(tries=5, delay=10)  # type:ignore
    def _check_journalctl_logs(self, node: Node, log: Logger) -> None:
        journalctl = node.tools[Journalctl]
        output = journalctl.logs_for_unit("azsecmond", sudo=True)
        if "Connected to mdsd" not in output:
            raise LisaException(
                "'Connected to mdsd' string is not in azsecmond logs "
                "Please check if Azsecmond connects to mdsd successfully."
            )
        log.info("Azsecmond connection to mdsd is successful")

        output = journalctl.logs_for_unit("auoms", sudo=True)

        # Previously, we also checked the string "Output(azsecmond): Connected".
        # However, in some scenarios, such as with the Mariner images in locations
        # other than westus2, this string is not present in the logs. We confirmed
        # with AzSecPack team that they didn't find any impact. Therefore, we have
        # temporarily removed this check until the AzSecPack team provides final
        # confirmation.
        strings_to_check = [
            "Output(mdsd): Connected",
        ]
        for s in strings_to_check:
            if s not in output:
                raise LisaException(
                    f"'{s}' string is not in auoms logs. Please check if the connection"
                    " auoms to mdsd is successful."
                )
        log.info("Auoms connection to mdsd is successful")

    def _is_supported(self, node: Node) -> None:
        supported_major_versions_x86_64 = {
            Redhat: [7, 8, 9],
            CentOs: [7],
            Oracle: [8, 9],
            Debian: [10, 11],
            Ubuntu: [20, 22, 18],
            SLES: [15],
            AlmaLinux: [8],
            CBLMariner: [2, 3],
        }
        supported_major_versions_arm64 = {
            Redhat: [8, 9],
            CentOs: [7],
            Debian: [11],
            Ubuntu: [20],
            CBLMariner: [2, 3],
        }

        arch = node.os.get_kernel_information().hardware_platform  # type: ignore
        if arch == "aarch64":
            supported_major_versions = supported_major_versions_arm64
        else:
            supported_major_versions = supported_major_versions_x86_64

        for distro in supported_major_versions:
            if type(node.os) is distro:
                version_list = supported_major_versions.get(distro)
                if (
                    version_list is None
                    or node.os.information.version.major not in version_list
                ):
                    raise SkippedException(
                        UnsupportedDistroException(
                            node.os, "AzSecPack doesn't support this Distro version."
                        )
                    )
