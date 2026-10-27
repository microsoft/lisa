# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from typing import Any, List, cast
from unittest import TestCase
from unittest.mock import MagicMock, call, patch

from lisa.features import Gpu
from lisa.microsoft.testsuites.gpu.gpusuite import GpuTestSuite
from lisa.tools import Lspci, Modprobe, NvidiaSmi, Service
from lisa.util import LisaException
from lisa.util.process import ExecutableResult


def _result(stdout: str = "", stderr: str = "", exit_code: int = 0) -> ExecutableResult:
    return ExecutableResult(stdout, stderr, exit_code, "nvidia-smi", "test", 0)


class NvidiaPersistenceTestCase(TestCase):
    def setUp(self) -> None:
        self.smi = NvidiaSmi(MagicMock())
        self.run_mock = MagicMock()
        patcher = patch.object(self.smi, "run", self.run_mock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_reads_mixed_modes_and_unsupported_gpus(self) -> None:
        self.run_mock.return_value = _result(
            "GPU-a, Enabled\nGPU-b, Disabled\nGPU-c, [N/A]\n"
        )

        self.assertEqual(
            {"GPU-a": True, "GPU-b": False}, self.smi.get_persistence_modes()
        )
        self.assertTrue(self.run_mock.call_args.kwargs["force_run"])

    def test_rejects_empty_or_unrecognized_persistence_output(self) -> None:
        for output in ("", "GPU-a, Unknown", "GPU-a", "not-a-gpu, Enabled"):
            with self.subTest(output=output):
                self.run_mock.return_value = _result(output)
                with self.assertRaises(LisaException):
                    self.smi.get_persistence_modes()

    def test_query_and_set_failures_include_stderr(self) -> None:
        self.run_mock.return_value = _result(
            stderr="NVIDIA driver unavailable", exit_code=1
        )
        with self.assertRaisesRegex(AssertionError, "NVIDIA driver unavailable"):
            self.smi.get_persistence_modes()
        with self.assertRaisesRegex(AssertionError, "NVIDIA driver unavailable"):
            self.smi.set_persistence_mode("GPU-a", False)


class GpuRescindTestCase(TestCase):
    _suite_type = cast(Any, GpuTestSuite).__wrapped__

    def setUp(self) -> None:
        self.suite = self._suite_type.__new__(self._suite_type)
        self.node = MagicMock()
        self.log = MagicMock()
        self.modprobe = MagicMock()
        self.smi = MagicMock()
        self.service = MagicMock()
        self.lspci = MagicMock()
        self.gpu = MagicMock()
        self.node.features = {Gpu: self.gpu}
        self.node.tools = {
            Lspci: self.lspci,
            Modprobe: self.modprobe,
            NvidiaSmi: self.smi,
            Service: self.service,
        }
        self.devices = [MagicMock(), MagicMock()]
        self.lspci.get_gpu_devices.return_value = self.devices
        self.gpu.remove_virtual_gpus.return_value = self.devices
        self.modprobe.is_module_loaded.return_value = True
        self.modes = {"GPU-a": True, "GPU-b": False}
        self.running_services = {"nvidia-persistenced"}
        self.service.check_service_exists.side_effect = lambda name: name in (
            "nvidia-persistenced",
            "nvidia-fabricmanager",
        )
        self.service.is_service_running.side_effect = (
            lambda name: name in self.running_services
        )
        self.service.stop_service.side_effect = self.running_services.remove
        self.service.restart_service.side_effect = self._restart_service
        self.smi.get_persistence_modes.return_value = self.modes.copy()
        self.smi.set_persistence_mode.side_effect = self._set_mode
        self.modprobe.remove.side_effect = self._remove_modules
        self.node.execute.return_value = _result(
            "GPU holder stdout", "nvidia-persistenced holds /dev/nvidiactl"
        )

    def _restart_service(self, name: str) -> None:
        self.running_services.add(name)
        self.modes.update({gpu_uuid: True for gpu_uuid in self.modes})

    def _set_mode(self, gpu_uuid: str, enabled: bool) -> None:
        self.modes[gpu_uuid] = enabled

    def _remove_modules(self, modules: List[str]) -> None:
        if self.running_services or any(self.modes.values()):
            raise AssertionError("Module nvidia is in use")

    def _run_rescind(self) -> None:
        self.suite.verify_gpu_rescind_validation(self.node, Path("."), self.log)

    def _assert_original_state(self) -> None:
        self.assertEqual({"nvidia-persistenced"}, self.running_services)
        self.assertEqual({"GPU-a": True, "GPU-b": False}, self.modes)

    def test_releases_holders_and_restores_mixed_persistence_modes(self) -> None:
        self._run_rescind()

        self._assert_original_state()
        self.service.stop_service.assert_called_once_with("nvidia-persistenced")
        self.service.restart_service.assert_called_once_with("nvidia-persistenced")
        self.lspci.disable_device.assert_has_calls(
            [call(self.devices[0]), call(self.devices[1])]
        )
        self.lspci.enable_devices.assert_called_once()
        self.modprobe.load.assert_called_once_with("nvidia")
        self.node.mark_dirty.assert_not_called()

    def test_non_nvidia_path_does_not_require_nvidia_smi_or_services(self) -> None:
        self.modprobe.is_module_loaded.return_value = False
        self.modprobe.remove.side_effect = None

        self._run_rescind()

        self.smi.get_persistence_modes.assert_not_called()
        self.smi.set_persistence_mode.assert_not_called()
        self.service.stop_service.assert_not_called()
        self.modprobe.load.assert_not_called()
        self.lspci.enable_devices.assert_called_once()

    def test_partial_service_stop_failure_restores_previously_stopped_service(
        self,
    ) -> None:
        self.running_services.add("nvidia-fabricmanager")

        def stop_service(name: str) -> None:
            self.running_services.remove(name)
            if name == "nvidia-fabricmanager":
                raise AssertionError("service stop failed")

        self.service.stop_service.side_effect = stop_service

        with self.assertRaisesRegex(AssertionError, "service stop failed"):
            self._run_rescind()

        self.assertEqual(
            {"nvidia-persistenced", "nvidia-fabricmanager"}, self.running_services
        )
        self.service.restart_service.assert_has_calls(
            [call("nvidia-persistenced"), call("nvidia-fabricmanager")]
        )
        self.lspci.disable_device.assert_not_called()

    def test_unload_failure_reports_holders_and_restores_state(self) -> None:
        self.modprobe.remove.side_effect = AssertionError("Module nvidia is in use")

        with self.assertRaisesRegex(LisaException, "setup failed before PCI removal"):
            self._run_rescind()

        self._assert_original_state()
        self.lspci.disable_device.assert_not_called()
        self.lspci.enable_devices.assert_not_called()
        self.node.execute.assert_called_once_with(
            "fuser -v /dev/nvidia*", sudo=True, shell=True
        )
        diagnostic = self.log.error.call_args_list[0].args[0]
        self.assertIn("GPU holder stdout", diagnostic)
        self.assertIn("nvidia-persistenced holds /dev/nvidiactl", diagnostic)

    def test_partial_persistence_failure_restores_state_before_pci_removal(
        self,
    ) -> None:
        self.modes["GPU-b"] = True
        self.smi.get_persistence_modes.return_value = self.modes.copy()

        def set_mode(gpu_uuid: str, enabled: bool) -> None:
            if gpu_uuid == "GPU-b" and not enabled:
                raise AssertionError("persistence disable failed")
            self._set_mode(gpu_uuid, enabled)

        self.smi.set_persistence_mode.side_effect = set_mode

        with self.assertRaisesRegex(AssertionError, "persistence disable failed"):
            self._run_rescind()

        self.assertEqual({"GPU-a": True, "GPU-b": True}, self.modes)
        self.assertEqual({"nvidia-persistenced"}, self.running_services)
        self.modprobe.remove.assert_not_called()
        self.lspci.disable_device.assert_not_called()
        self.node.mark_dirty.assert_not_called()

    def test_partial_pci_failure_rescans_and_preserves_original_error(self) -> None:
        self.lspci.disable_device.side_effect = [
            None,
            LisaException("PCI removal failed"),
        ]
        self.lspci.enable_devices.side_effect = AssertionError("PCI rescan failed")

        with self.assertRaisesRegex(LisaException, "^PCI removal failed$"):
            self._run_rescind()

        self._assert_original_state()
        self.lspci.enable_devices.assert_called_once()
        self.node.mark_dirty.assert_called_once()
        self.assertIn("PCI rescan failed", self.log.error.call_args_list[0].args[0])

    def test_restore_failure_attempts_remaining_services_and_gpus(self) -> None:
        self.running_services.add("nvidia-fabricmanager")

        def restart_service(name: str) -> None:
            if name == "nvidia-persistenced":
                raise AssertionError("service restart failed")
            self._restart_service(name)

        def set_mode(gpu_uuid: str, enabled: bool) -> None:
            if gpu_uuid == "GPU-a" and enabled:
                raise AssertionError("persistence restore failed")
            self._set_mode(gpu_uuid, enabled)

        self.service.restart_service.side_effect = restart_service
        self.smi.set_persistence_mode.side_effect = set_mode

        with self.assertRaisesRegex(
            LisaException, "GPU rescind cleanup failed"
        ) as error:
            self._run_rescind()

        self.assertIn("service restart failed", str(error.exception))
        self.assertIn("persistence restore failed", str(error.exception))
        self.service.restart_service.assert_any_call("nvidia-fabricmanager")
        self.assertFalse(self.modes["GPU-b"])
        self.node.mark_dirty.assert_called_once()
