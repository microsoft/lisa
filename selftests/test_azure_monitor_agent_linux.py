from unittest import TestCase
from unittest.mock import MagicMock

from lisa.microsoft.testsuites.vm_extensions.AzureMonitorAgentLinux import (
    AzureMonitorAgentLinuxExtension,
)
from lisa.operating_system import CpuArchitecture, OsInformation
from lisa.util import SkippedException, parse_version


class AzureMonitorAgentLinuxExtensionTestCase(TestCase):
    def setUp(self) -> None:
        self.suite = AzureMonitorAgentLinuxExtension.__new__(
            AzureMonitorAgentLinuxExtension
        )

    def test_simulates_supported_identity(self) -> None:
        node = self._create_node("CentOS 7.9", "7.9")
        node.execute.return_value.stdout = "/tmp/lisa-ama-os-release.test\n"
        log = MagicMock()

        with self.suite._simulate_supported_linux_identity(node, log, "rhel", "7"):
            pass

        self.assertEqual(3, node.execute.call_count)
        simulation_command = node.execute.call_args_list[1].args[0]
        self.assertIn('ID=\\"rhel\\"', simulation_command)
        self.assertIn('VERSION_ID=\\"7\\"', simulation_command)
        restore_command = node.execute.call_args_list[2].args[0]
        self.assertIn("cmp -s", restore_command)
        self.assertIn("rm -f", restore_command)
        log.info.assert_called_once()

    def test_restores_identity_after_provisioning_failure(self) -> None:
        node = self._create_node("Unsupported Linux 1", "1")
        node.execute.return_value.stdout = "/tmp/lisa-ama-os-release.test\n"

        with self.assertRaisesRegex(RuntimeError, "provisioning failed"):
            with self.suite._simulate_supported_linux_identity(
                node, MagicMock(), "ubuntu", "22.04"
            ):
                raise RuntimeError("provisioning failed")

        self.assertEqual(3, node.execute.call_count)
        self.assertIn("tee /etc/os-release", node.execute.call_args.args[0])

    def test_preserves_supported_rpm_major_version(self) -> None:
        node = self._create_node("CentOS 7.9", "7.9")
        node.execute.return_value.stdout = "rpm"

        identity = self.suite._get_supported_linux_identity(node)

        self.assertEqual(("rhel", "7"), identity)

    def test_uses_rpm_baseline_for_unsupported_version(self) -> None:
        node = self._create_node("Amazon Linux 2023", "2023")
        node.execute.return_value.stdout = "rpm"

        identity = self.suite._get_supported_linux_identity(node)

        self.assertEqual(("rhel", "9"), identity)

    def test_preserves_supported_dpkg_version(self) -> None:
        node = self._create_node("Unsupported DEB Linux 24.04", "24.04")
        node.execute.return_value.stdout = "dpkg"

        identity = self.suite._get_supported_linux_identity(node)

        self.assertEqual(("ubuntu", "24.04"), identity)

    def test_uses_dpkg_baseline_for_unsupported_version(self) -> None:
        node = self._create_node("Unsupported DEB Linux 12", "12")
        node.execute.return_value.stdout = "dpkg"

        identity = self.suite._get_supported_linux_identity(node)

        self.assertEqual(("ubuntu", "22.04"), identity)

    def test_skips_unknown_package_family(self) -> None:
        node = self._create_node("Unsupported Linux 1", "1")
        node.execute.return_value.stdout = ""

        with self.assertRaisesRegex(SkippedException, "neither rpm nor dpkg"):
            self.suite._get_supported_linux_identity(node)

    def _create_node(
        self,
        full_version: str,
        version: str,
        architecture: CpuArchitecture = CpuArchitecture.X64,
    ) -> MagicMock:
        node = MagicMock()
        node.os.information = OsInformation(
            version=parse_version(version),
            vendor=full_version.split()[0],
            full_version=full_version,
        )
        node.os.get_kernel_information.return_value.hardware_platform = architecture
        return node
