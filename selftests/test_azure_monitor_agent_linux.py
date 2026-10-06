from contextlib import nullcontext
from typing import Any, cast
from unittest import TestCase
from unittest.mock import MagicMock, patch

from azure.core.exceptions import HttpResponseError

from lisa.microsoft.testsuites.vm_extensions.AzureMonitorAgentLinux import (
    AzureMonitorAgentLinuxExtension,
)
from lisa.operating_system import CpuArchitecture, OsInformation
from lisa.util import LisaException, SkippedException, parse_version


class AzureMonitorAgentLinuxExtensionTestCase(TestCase):
    def setUp(self) -> None:
        suite_class = cast(Any, AzureMonitorAgentLinuxExtension).__wrapped__
        self.suite = object.__new__(suite_class)

    def test_simulates_supported_identity(self) -> None:
        node = self._create_node("CentOS 7.9", "7.9")
        node.execute.return_value.stdout = "/tmp/lisa-ama-os-release.test\n"
        log = MagicMock()

        with self.suite._simulate_supported_linux_identity(node, log, "rhel", "7"):
            pass

        self.assertEqual(3, node.execute.call_count)
        simulation_command = node.execute.call_args_list[1].args[0]
        self.assertIn("simulated_os_release=$(awk", simulation_command)
        self.assertIn('print "ID=rhel"', simulation_command)
        self.assertIn('print "VERSION_ID=7"', simulation_command)
        self.assertIn(") && printf", simulation_command)
        self.assertIn('"$simulated_os_release"', simulation_command)
        restore_command = node.execute.call_args_list[2].args[0]
        self.assertIn("cp --dereference", restore_command)
        self.assertIn("cmp -s", restore_command)
        self.assertIn("rm -f", restore_command)
        self.assertNotIn("tee /etc/os-release", restore_command)
        log.info.assert_called_once()

    def test_does_not_restore_identity_when_backup_fails(self) -> None:
        node = self._create_node("Unsupported Linux 1", "1")
        node.execute.side_effect = RuntimeError("backup failed")

        with self.assertRaisesRegex(RuntimeError, "backup failed"):
            with self.suite._simulate_supported_linux_identity(
                node, MagicMock(), "ubuntu", "22.04"
            ):
                pass

        node.execute.assert_called_once()
        self.assertNotIn("tee /etc/os-release", node.execute.call_args.args[0])

    def test_restores_identity_after_provisioning_failure(self) -> None:
        node = self._create_node("Unsupported Linux 1", "1")
        node.execute.return_value.stdout = "/tmp/lisa-ama-os-release.test\n"

        with self.assertRaisesRegex(RuntimeError, "provisioning failed"):
            with self.suite._simulate_supported_linux_identity(
                node, MagicMock(), "ubuntu", "22.04"
            ):
                raise RuntimeError("provisioning failed")

        self.assertEqual(3, node.execute.call_count)
        self.assertIn("cp --dereference", node.execute.call_args.args[0])

    def test_marks_node_dirty_when_identity_restore_fails(self) -> None:
        node = self._create_node("Unsupported Linux 1", "1")
        backup_result = MagicMock(stdout="/tmp/lisa-ama-os-release.test\n")
        simulation_result = MagicMock(exit_code=0)
        node.execute.side_effect = [
            backup_result,
            simulation_result,
            LisaException("restore failed"),
        ]

        with self.assertRaisesRegex(LisaException, "/tmp/lisa-ama-os-release.test"):
            with self.suite._simulate_supported_linux_identity(
                node, MagicMock(), "ubuntu", "22.04"
            ):
                pass

        node.mark_dirty.assert_called_once()

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

    def test_cleans_up_extension_when_fallback_fails(self) -> None:
        node = self._create_node("CentOS 7.9", "7.9")
        extension = MagicMock()
        extension.delete.return_value = False
        extension.create_or_update.side_effect = [
            HttpResponseError(message="Unsupported operating system"),
            RuntimeError("fallback failed"),
        ]
        extension.check_exist.return_value = False
        node.features.__getitem__.return_value = extension

        with patch.object(
            self.suite,
            "_get_supported_linux_identity",
            return_value=("rhel", "7"),
        ), patch.object(
            self.suite,
            "_simulate_supported_linux_identity",
            return_value=nullcontext(),
        ):
            with self.assertRaisesRegex(RuntimeError, "fallback failed"):
                self.suite.verify_azuremonitoragent_linux(MagicMock(), node)

        extension.delete.assert_any_call(
            name="Microsoft.Azure.Monitor.AzureMonitorLinuxAgent",
            ignore_not_found=True,
        )
        self.assertEqual(3, extension.delete.call_count)
        extension.check_exist.assert_called_once_with(
            "Microsoft.Azure.Monitor.AzureMonitorLinuxAgent"
        )

    def test_does_not_delete_extension_before_fallback_validation(self) -> None:
        node = self._create_node("Unsupported Linux 1", "1")
        extension = MagicMock()
        node.features.__getitem__.return_value = extension

        with patch.object(
            self.suite,
            "_get_supported_linux_identity",
            side_effect=SkippedException("unsupported package family"),
        ):
            with self.assertRaisesRegex(SkippedException, "unsupported package family"):
                self.suite.verify_azuremonitoragent_linux(MagicMock(), node)

        extension.delete.assert_not_called()

    def _create_node(
        self,
        full_version: str,
        version: str,
        architecture: CpuArchitecture = CpuArchitecture.X64,
    ) -> MagicMock:
        node = MagicMock()
        node.execute.return_value.exit_code = 0
        node.os.information = OsInformation(
            version=parse_version(version),
            vendor=full_version.split()[0],
            full_version=full_version,
        )
        node.os.get_kernel_information.return_value.hardware_platform = architecture
        return node
