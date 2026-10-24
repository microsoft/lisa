# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from unittest import TestCase
from unittest.mock import MagicMock, call, patch

from lisa.node import Node
from lisa.operating_system import Ubuntu
from lisa.sut_orchestrator import OPENVMM
from lisa.tools import Ethtool
from lisa.tools.ethtool import DeviceFeatures, DeviceGroLroSettings
from lisa.util import LisaException, SkippedException
from lisa.util.package import import_package


class PortableNetworkSettingsTestCase(TestCase):
    _module: ModuleType

    @classmethod
    def setUpClass(cls) -> None:
        module_path = (
            Path(__file__).parent.parent
            / "lisa"
            / "microsoft"
            / "testsuites"
            / "network"
            / "networksettings.py"
        )
        import_package(module_path, "microsoft.testsuites.network", enable_log=False)
        cls._module = import_module("microsoft.testsuites.network.networksettings")

    def setUp(self) -> None:
        suite_class = cast(Any, self._module.NetworkSettings).__wrapped__
        self.suite = object.__new__(suite_class)
        self.node = MagicMock(spec=Node)
        self.node.type_name.return_value = OPENVMM
        self.node.os = MagicMock(spec=Ubuntu)
        self.node.nics = MagicMock()
        self.node.nics.default_nic = "eth0"
        self.node.tools = MagicMock()
        self.log = MagicMock()
        self.ethtool = MagicMock(spec=Ethtool)
        self.node.tools.__getitem__.side_effect = {Ethtool: self.ethtool}.__getitem__
        guard_patch = patch.object(
            self._module,
            "skip_if_no_synthetic_nics",
            side_effect=SkippedException("No synthetic NICs available for testing"),
        )
        self.netvsc_guard = guard_patch.start()
        self.addCleanup(guard_patch.stop)
        self.original = self._settings(True, False)
        self.ethtool.get_device_gro_lro_settings.return_value = self.original
        self.ethtool.change_device_gro_lro_settings.side_effect = (
            lambda interface, gro, lro: self._settings(gro, lro)
        )

    def _settings(
        self, gro: bool, lro: bool, gro_fixed: bool = False
    ) -> DeviceGroLroSettings:
        gro_value = "on" if gro else "off"
        lro_value = "on" if lro else "off"
        return DeviceGroLroSettings(
            "eth0",
            f"generic-receive-offload: {gro_value}"
            f"{' [fixed]' if gro_fixed else ''}\n"
            f"large-receive-offload: {lro_value} [fixed]\n",
        )

    def test_openvmm_required_offloads_remain_required(self) -> None:
        features = [
            "rx-checksumming",
            "tx-checksumming",
            "scatter-gather",
            "tcp-segmentation-offload",
        ]
        self.ethtool.get_device_enabled_features.return_value = DeviceFeatures(
            "eth0", features
        )

        self.suite.verify_device_enabled_features(node=self.node)

        features.remove("tx-checksumming")
        with self.assertRaisesRegex(LisaException, "Not all the required features"):
            self.suite.verify_device_enabled_features(node=self.node)
        self.netvsc_guard.assert_not_called()

    def test_openvmm_mutable_gro_is_toggled_and_restored(self) -> None:
        self.suite.verify_device_gro_lro_settings_change(node=self.node, log=self.log)

        self.assertEqual(
            self.ethtool.change_device_gro_lro_settings.call_args_list,
            [call("eth0", False, False), call("eth0", True, False)],
        )
        self.netvsc_guard.assert_not_called()

    def test_failed_gro_change_still_restores_original_settings(self) -> None:
        self.ethtool.change_device_gro_lro_settings.side_effect = [
            self.original,
            self.original,
        ]

        with self.assertRaisesRegex(AssertionError, "Changing GRO"):
            self.suite.verify_device_gro_lro_settings_change(
                node=self.node, log=self.log
            )

        self.assertEqual(
            self.ethtool.change_device_gro_lro_settings.call_args_list,
            [call("eth0", False, False), call("eth0", True, False)],
        )

    def test_fixed_offloads_are_na_without_modification(self) -> None:
        self.ethtool.get_device_gro_lro_settings.return_value = self._settings(
            True, False, gro_fixed=True
        )

        with self.assertRaisesRegex(SkippedException, "fixed"):
            self.suite.verify_device_gro_lro_settings_change(
                node=self.node, log=self.log
            )

        self.ethtool.change_device_gro_lro_settings.assert_not_called()

    def test_restoration_failure_marks_guest_dirty_and_remains_a_failure(self) -> None:
        self.ethtool.change_device_gro_lro_settings.side_effect = [
            self._settings(False, False),
            LisaException("restore failed"),
        ]

        with self.assertRaisesRegex(LisaException, "restore failed"):
            self.suite.verify_device_gro_lro_settings_change(
                node=self.node, log=self.log
            )

        self.node.mark_dirty.assert_called_once()

    def test_other_platforms_keep_the_netvsc_requirement(self) -> None:
        self.node.type_name.return_value = "remote"

        with self.assertRaisesRegex(SkippedException, "No synthetic NICs"):
            self.suite.verify_device_enabled_features(node=self.node)

        self.netvsc_guard.assert_called_once_with(self.node)
