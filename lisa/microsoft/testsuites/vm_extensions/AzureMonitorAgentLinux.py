import shlex
from contextlib import contextmanager
from typing import Any, Iterator, Tuple

from assertpy import assert_that
from azure.core.exceptions import HttpResponseError

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import CpuArchitecture
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.util import SkippedException


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="Tests for the Azure Monitor Agent Linux VM Extension",
    tags=["VM_Extension"],
)
class AzureMonitorAgentLinuxExtension(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        if not node.os.is_posix:
            raise SkippedException("Azure Monitor Agent requires a Linux distro.")

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
        extension_name = "Microsoft.Azure.Monitor.AzureMonitorLinuxAgent"
        is_extension_present = False
        is_extension_present = extension.delete(
            name=extension_name, ignore_not_found=True
        )

        try:
            extension_result = extension.create_or_update(
                name=extension_name,
                publisher="Microsoft.Azure.Monitor",
                type_="AzureMonitorLinuxAgent",
                type_handler_version="1.0",
                auto_upgrade_minor_version=True,
            )

            assert_that(extension_result["provisioning_state"]).described_as(
                "Expected the extension to succeed"
            ).is_equal_to("Succeeded")
        except HttpResponseError as e:
            if "already added" in str(e):
                node.log.debug(
                    "AzureMonitorLinuxAgent has been installed in current VM."
                )
                is_extension_present = True
                result = extension.get(extension_name)
                node.log.debug(f"extension status {result.provisioning_state}")
            elif self._is_unsupported_os_error(e):
                extension.delete(name=extension_name, ignore_not_found=True)
                simulated_id, simulated_version = self._get_supported_linux_identity(
                    node
                )
                with self._simulate_supported_linux_identity(
                    node,
                    log,
                    simulated_id,
                    simulated_version,
                ):
                    extension_result = extension.create_or_update(
                        name=extension_name,
                        publisher="Microsoft.Azure.Monitor",
                        type_="AzureMonitorLinuxAgent",
                        type_handler_version="1.0",
                        auto_upgrade_minor_version=True,
                    )
                    assert_that(extension_result["provisioning_state"]).described_as(
                        "Expected the extension to succeed"
                    ).is_equal_to("Succeeded")
            else:
                raise

        if not is_extension_present:
            extension.delete(extension_name)

            assert_that(extension.check_exist(extension_name)).described_as(
                "Found the VM Extension still unexpectedly exists on the VM"
                " after deletion"
            ).is_false()

    def _is_unsupported_os_error(self, error: HttpResponseError) -> bool:
        error_message = str(error)
        return any(
            message in error_message
            for message in ["OS is not supported", "Unsupported operating system"]
        )

    def _get_supported_linux_identity(self, node: Node) -> Tuple[str, str]:
        package_manager_result = node.execute(
            "if [ -f /etc/debian_version ] && "
            "command -v dpkg >/dev/null 2>&1; then "
            "printf dpkg; "
            "elif [ -f /etc/redhat-release ] && "
            "command -v rpm >/dev/null 2>&1; then "
            "printf rpm; "
            "elif command -v dpkg >/dev/null 2>&1 && "
            "! command -v rpm >/dev/null 2>&1; then "
            "printf dpkg; "
            "elif command -v rpm >/dev/null 2>&1; then "
            "printf rpm; "
            "fi",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Failed to determine the Linux package family"
            ),
        )
        package_manager = package_manager_result.stdout.strip()
        os_version = node.os.information.version
        architecture = node.os.get_kernel_information().hardware_platform

        if package_manager == "rpm":
            supported_versions = ["7", "8", "9", "10"]
            if architecture == CpuArchitecture.ARM64:
                supported_versions = ["8", "9", "10"]
            current_version = str(os_version.major)
            simulated_version = (
                current_version if current_version in supported_versions else "9"
            )
            return "rhel", simulated_version

        if package_manager == "dpkg":
            supported_versions = [
                "16.04",
                "18.04",
                "20.04",
                "22.04",
                "24.04",
                "26.04",
            ]
            if architecture == CpuArchitecture.ARM64:
                supported_versions.remove("16.04")
            current_version = f"{os_version.major}.{os_version.minor:02d}"
            simulated_version = (
                current_version if current_version in supported_versions else "22.04"
            )
            return "ubuntu", simulated_version

        raise SkippedException(
            "Cannot simulate a supported Azure Monitor Agent distro because "
            "neither rpm nor dpkg is available."
        )

    @contextmanager
    def _simulate_supported_linux_identity(
        self,
        node: Node,
        log: Logger,
        simulated_id: str,
        simulated_version: str,
    ) -> Iterator[None]:
        backup_result = node.execute(
            "mktemp /tmp/lisa-ama-os-release.XXXXXX",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Failed to create a backup file for /etc/os-release"
            ),
        )
        backup_path = backup_result.stdout.strip()
        quoted_backup_path = shlex.quote(backup_path)
        log.info(
            f"Temporarily identifying {node.os.information.full_version} as "
            f"{simulated_id} {simulated_version} while provisioning the "
            "Azure Monitor Agent extension."
        )

        try:
            node.execute(
                "cp --dereference /etc/os-release "
                f"{quoted_backup_path} && "
                "awk 'BEGIN { id = 0; version = 0 } "
                f"/^ID=/ {{ print \"ID=\\\"{simulated_id}\\\"\"; id = 1; next }} "
                "/^VERSION_ID=/ { "
                f"print \"VERSION_ID=\\\"{simulated_version}\\\"\"; "
                "version = 1; next } "
                "{ print } "
                "END { "
                f"if (!id) print \"ID=\\\"{simulated_id}\\\"\"; "
                "if (!version) "
                f"print \"VERSION_ID=\\\"{simulated_version}\\\"\" "
                f"}}' {quoted_backup_path} | tee /etc/os-release >/dev/null && "
                f"grep -q '^ID=\"{simulated_id}\"$' /etc/os-release && "
                f"grep -q '^VERSION_ID=\"{simulated_version}\"$' /etc/os-release",
                sudo=True,
                shell=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Failed to simulate a supported Linux identity"
                ),
            )
            yield
        finally:
            node.execute(
                f"cat {quoted_backup_path} | tee /etc/os-release >/dev/null && "
                f"cmp -s {quoted_backup_path} /etc/os-release && "
                f"rm -f {quoted_backup_path}",
                sudo=True,
                shell=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "Failed to restore the original /etc/os-release"
                ),
            )
