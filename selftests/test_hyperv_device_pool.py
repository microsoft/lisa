# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from types import SimpleNamespace
from typing import Any, List, cast
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.sut_orchestrator.hyperv.hyperv_device_pool import HyperVDevicePool
from lisa.sut_orchestrator.hyperv.schema import (
    DeviceAddressSchema,
    HypervPlatformSchema,
)
from lisa.tools import PowerShell
from lisa.util import LisaException


class HyperVDevicePoolTestCase(TestCase):
    def test_assign_devices_rolls_back_on_dismount_failure(self) -> None:
        first_device = DeviceAddressSchema(
            instance_id="PCI\\FIRST",
            location_path="PCIROOT(1)#PCI(0000)",
        )
        second_device = DeviceAddressSchema(
            instance_id="PCI\\SECOND",
            location_path="PCIROOT(1)#PCI(0001)",
        )
        commands: List[str] = []

        def run_cmdlet(cmdlet: str, **_: Any) -> str:
            commands.append(cmdlet)
            if (
                "Dismount-VMHostAssignableDevice" in cmdlet
                and second_device.location_path in cmdlet
            ):
                raise LisaException("pcip failed")
            return ""

        powershell = SimpleNamespace(run_cmdlet=MagicMock(side_effect=run_cmdlet))
        node = SimpleNamespace(tools={PowerShell: powershell})
        pool = HyperVDevicePool(
            node=cast(Any, node),
            runbook=HypervPlatformSchema(),
            log=MagicMock(),
        )

        with patch.object(pool, "_wait_for_pnp_device_enabled") as wait_enabled:
            with self.assertRaises(LisaException):
                pool._assign_devices_to_vm(
                    vm_name="vm1",
                    devices=[first_device, second_device],
                )

        remove_index = next(
            index
            for index, command in enumerate(commands)
            if "Remove-VMAssignableDevice" in command
            and first_device.location_path in command
        )
        mount_index = next(
            index
            for index, command in enumerate(commands)
            if "Mount-VMHostAssignableDevice" in command
            and first_device.location_path in command
        )
        enable_second_index = next(
            index
            for index, command in enumerate(commands)
            if "Enable-PnpDevice" in command and second_device.instance_id in command
        )
        enable_first_index = next(
            index
            for index, command in enumerate(commands)
            if "Enable-PnpDevice" in command and first_device.instance_id in command
        )

        self.assertLess(remove_index, mount_index)
        self.assertLess(mount_index, enable_second_index)
        self.assertLess(enable_second_index, enable_first_index)
        wait_enabled.assert_any_call(
            second_device.instance_id, second_device.location_path
        )
        wait_enabled.assert_any_call(
            first_device.instance_id, first_device.location_path
        )
