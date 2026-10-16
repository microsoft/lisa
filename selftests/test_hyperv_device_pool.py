# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple, cast
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.sut_orchestrator.hyperv.context import (
    DevicePassthroughContext,
    HyperVNvmeRecoveryState,
    NodeContext,
    NvmeDiskState,
)
from lisa.sut_orchestrator.hyperv.get_assignable_devices import HypervAssignableDevices
from lisa.sut_orchestrator.hyperv.hyperv_device_pool import HyperVDevicePool
from lisa.sut_orchestrator.hyperv.schema import (
    DeviceAddressSchema,
    HypervPlatformSchema,
)
from lisa.sut_orchestrator.util.schema import (
    DeviceLocationPathIdentifier,
    HostDevicePoolSchema,
    HostDevicePoolType,
    VendorDeviceIdIdentifier,
)
from lisa.tools import PowerShell
from lisa.util import LisaException


class HyperVDevicePoolTestCase(TestCase):
    def test_nvme_discovery_filters_pci_compatible_ids(self) -> None:
        powershell = MagicMock()
        powershell.run_cmdlet.return_value = ""
        node = SimpleNamespace(tools={PowerShell: powershell})
        assignable_devices = HypervAssignableDevices(
            host_node=cast(Any, node),
            log=MagicMock(),
        )
        nvme_record = SimpleNamespace(
            instance_id="PCI\\NVME",
            friendly_name="NVMe controller",
            location_paths=["PCIROOT(1)#PCI(0000)"],
            compatible_ids=["PCI\\CC_010802"],
        )
        other_record = SimpleNamespace(
            instance_id="PCI\\OTHER",
            friendly_name="Other controller",
            location_paths=["PCIROOT(2)#PCI(0000)"],
            compatible_ids=["PCI\\CC_0108020"],
        )
        discovered_device = DeviceAddressSchema(instance_id=nvme_record.instance_id)

        with patch.object(
            assignable_devices,
            "_HypervAssignableDevices__get_present_pci_devices_with_location_paths",
            return_value=[other_record, nvme_record],
        ):
            with patch.object(
                assignable_devices,
                "_HypervAssignableDevices__get_dda_properties",
                return_value=discovered_device,
            ) as get_dda_properties:
                devices = assignable_devices.get_assignable_nvme_devices()

        self.assertEqual([discovered_device], devices)
        self.assertEqual(nvme_record.location_paths[0], devices[0].location_path)
        self.assertEqual(nvme_record.friendly_name, devices[0].friendly_name)
        get_dda_properties.assert_called_once_with(device_id=nvme_record.instance_id)

    @patch("lisa.sut_orchestrator.hyperv.hyperv_device_pool.HypervAssignableDevices")
    def test_auto_discovers_one_safe_nvme_recovery_candidate(
        self, assignable_devices_type: MagicMock
    ) -> None:
        unsafe_device = DeviceAddressSchema(
            instance_id="PCI\\UNSAFE",
            location_path="PCIROOT(1)#PCI(0000)",
        )
        safe_device = DeviceAddressSchema(
            instance_id="PCI\\SAFE",
            location_path="PCIROOT(2)#PCI(0000)",
        )
        get_nvme_devices = (
            assignable_devices_type.return_value.get_assignable_nvme_devices
        )
        get_nvme_devices.return_value = [
            unsafe_device,
            safe_device,
        ]
        powershell = MagicMock()
        powershell.run_cmdlet.side_effect = [
            "other-vm",
            "",
            3,
            {
                "Number": 3,
                "UniqueId": "disk-unique-id",
                "SerialNumber": "disk-serial",
                "BusType": "NVMe",
                "IsBoot": False,
                "IsSystem": False,
                "IsOffline": False,
                "IsMounted": False,
                "PhysicalDiskCount": 1,
                "IsStoragePoolMember": False,
                "StoragePoolNames": "",
            },
        ]
        node = SimpleNamespace(tools={PowerShell: powershell})
        pool = HyperVDevicePool(
            node=cast(Any, node),
            runbook=HypervPlatformSchema(),
            log=MagicMock(),
        )

        state = pool.capture_nvme_recovery_state()

        self.assertEqual(safe_device.location_path, state.location_path)
        self.assertEqual(safe_device.instance_id, state.instance_id)

    @patch("lisa.sut_orchestrator.hyperv.hyperv_device_pool.HypervAssignableDevices")
    def test_rejects_ambiguous_safe_nvme_recovery_candidates(
        self, assignable_devices_type: MagicMock
    ) -> None:
        devices = [
            DeviceAddressSchema(
                instance_id=f"PCI\\SAFE_{index}",
                location_path=f"PCIROOT({index + 1})#PCI(0000)",
            )
            for index in range(2)
        ]
        get_nvme_devices = (
            assignable_devices_type.return_value.get_assignable_nvme_devices
        )
        get_nvme_devices.return_value = devices
        disk_record = {
            "Number": 3,
            "UniqueId": "disk-unique-id",
            "SerialNumber": "disk-serial",
            "BusType": "NVMe",
            "IsBoot": False,
            "IsSystem": False,
            "IsOffline": False,
            "IsMounted": False,
            "PhysicalDiskCount": 1,
            "IsStoragePoolMember": False,
            "StoragePoolNames": "",
        }
        powershell = MagicMock()
        powershell.run_cmdlet.side_effect = [
            "",
            3,
            disk_record,
            "",
            4,
            {**disk_record, "Number": 4, "UniqueId": "other-disk"},
        ]
        node = SimpleNamespace(tools={PowerShell: powershell})
        pool = HyperVDevicePool(
            node=cast(Any, node),
            runbook=HypervPlatformSchema(),
            log=MagicMock(),
        )

        with self.assertRaisesRegex(LisaException, "exactly one safe"):
            pool.capture_nvme_recovery_state()

    @patch("lisa.sut_orchestrator.hyperv.hyperv_device_pool.HypervAssignableDevices")
    def test_auto_discovers_safe_pci_nvme_pool(
        self, assignable_devices_type: MagicMock
    ) -> None:
        state = self._create_recovery_state()
        device = DeviceAddressSchema(
            instance_id=state.instance_id,
            location_path=state.location_path,
        )
        assignable_devices_type.return_value.get_assignable_devices_by_location_paths.return_value = [  # noqa: E501
            device
        ]
        pool = self._create_pool(MagicMock())

        with patch.object(pool, "capture_nvme_recovery_state", return_value=state):
            pool.auto_discover_pool(HostDevicePoolType.PCI_NVME)

        self.assertEqual(
            [device], pool.available_host_devices[HostDevicePoolType.PCI_NVME]
        )

    def test_persists_nvme_recovery_state_before_offline(self) -> None:
        state_path = "C:/ProgramData/LISA/state/nvme.json"
        device = DeviceAddressSchema(
            instance_id="PCI\\VEN_144D&DEV_A80A",
            location_path="PCIROOT(1)#PCI(0000)",
        )
        disk_state = NvmeDiskState(
            number=3,
            unique_id="disk-unique-id",
            serial_number="disk-serial",
            was_offline=False,
        )
        powershell = MagicMock()
        pool = HyperVDevicePool(
            node=cast(Any, SimpleNamespace(tools={PowerShell: powershell})),
            runbook=HypervPlatformSchema(nvme_recovery_state_path=state_path),
            log=MagicMock(),
        )
        calls = MagicMock()
        persist = MagicMock()
        offline = MagicMock()
        calls.attach_mock(persist, "persist")
        calls.attach_mock(offline, "offline")

        with patch.object(
            pool,
            "_validate_nvme_devices",
            return_value={device.instance_id: disk_state},
        ):
            with patch.object(pool, "_persist_nvme_recovery_state", persist):
                with patch.object(pool, "_set_nvme_disk_offline", offline):
                    pool._assign_devices_to_vm(
                        vm_name="vm1",
                        pool_type=HostDevicePoolType.PCI_NVME,
                        devices=[device],
                    )

        self.assertEqual(["persist", "offline"], [item[0] for item in calls.mock_calls])
        persisted_state = persist.call_args.args[1]
        self.assertEqual(state_path, persist.call_args.args[0])
        self.assertEqual(device.location_path, persisted_state.location_path)
        self.assertEqual(disk_state, persisted_state.disk)

    def test_state_persistence_failure_prevents_nvme_assignment(self) -> None:
        device = DeviceAddressSchema(
            instance_id="PCI\\VEN_144D&DEV_A80A",
            location_path="PCIROOT(1)#PCI(0000)",
        )
        disk_state = NvmeDiskState(
            number=3,
            unique_id="disk-unique-id",
            serial_number="disk-serial",
            was_offline=False,
        )
        powershell = MagicMock()
        pool = HyperVDevicePool(
            node=cast(Any, SimpleNamespace(tools={PowerShell: powershell})),
            runbook=HypervPlatformSchema(
                nvme_recovery_state_path="C:/ProgramData/LISA/state/nvme.json"
            ),
            log=MagicMock(),
        )

        with patch.object(
            pool,
            "_validate_nvme_devices",
            return_value={device.instance_id: disk_state},
        ):
            with patch.object(
                pool,
                "_persist_nvme_recovery_state",
                side_effect=LisaException("state write failed"),
            ):
                with self.assertRaisesRegex(LisaException, "state write failed"):
                    pool._assign_devices_to_vm(
                        vm_name="vm1",
                        pool_type=HostDevicePoolType.PCI_NVME,
                        devices=[device],
                    )

        powershell.run_cmdlet.assert_not_called()

    def test_rejects_changed_existing_nvme_recovery_state(self) -> None:
        expected = self._create_recovery_state()
        actual = HyperVNvmeRecoveryState(
            schema_version=expected.schema_version,
            location_path="PCIROOT(2)#PCI(0000)",
            instance_id=expected.instance_id,
            disk=expected.disk,
        )
        pool = self._create_pool(MagicMock())

        with patch.object(pool, "read_nvme_recovery_state", return_value=expected):
            with self.assertRaisesRegex(LisaException, "identity mismatch"):
                pool._persist_nvme_recovery_state("state.json", actual)

    def test_nvme_recovery_state_json_round_trip_and_validation(self) -> None:
        state = HyperVNvmeRecoveryState(
            schema_version=1,
            location_path="PCIROOT(1)#PCI(0000)",
            instance_id="PCI\\VEN_144D&DEV_A80A",
            disk=NvmeDiskState(
                number=3,
                unique_id="disk-unique-id",
                serial_number="disk-serial",
                was_offline=False,
            ),
        )

        self.assertEqual(state, HyperVNvmeRecoveryState.from_json(state.to_json()))
        with self.assertRaisesRegex(LisaException, "schema version"):
            HyperVNvmeRecoveryState.from_json(
                state.to_json().replace('"schema_version": 1', '"schema_version": 2')
            )
        with self.assertRaisesRegex(LisaException, "was_offline"):
            HyperVNvmeRecoveryState.from_json(
                state.to_json().replace('"was_offline": false', '"was_offline": 0')
            )

    @patch("lisa.sut_orchestrator.hyperv.hyperv_device_pool.HypervAssignableDevices")
    def test_recovers_nvme_device_with_identity_checks(
        self, assignable_devices_type: MagicMock
    ) -> None:
        state = HyperVNvmeRecoveryState(
            schema_version=1,
            location_path="PCIROOT(1)#PCI(0000)",
            instance_id="PCI\\VEN_144D&DEV_A80A",
            disk=NvmeDiskState(
                number=3,
                unique_id="disk-unique-id",
                serial_number="disk-serial",
                was_offline=False,
            ),
        )
        powershell = MagicMock()
        powershell.run_cmdlet.side_effect = ["vm1", "", "", "", "", ""]
        powershell.run_cmdlet_async.return_value = MagicMock()
        powershell.wait_result.return_value = SimpleNamespace(exit_code=0, stdout="")
        get_pnp_device = (
            assignable_devices_type.return_value.get_pnp_device_by_location_path
        )
        get_pnp_device.return_value = SimpleNamespace(
            instance_id=state.instance_id, config_manager_error_code="22"
        )
        node = SimpleNamespace(tools={PowerShell: powershell})
        pool = HyperVDevicePool(
            node=cast(Any, node),
            runbook=HypervPlatformSchema(),
            log=MagicMock(),
        )

        with patch.object(pool, "_wait_for_pnp_device_enabled") as wait_enabled:
            with patch.object(pool, "_restore_nvme_disk_state") as restore_disk:
                pool.recover_nvme_device(state, "vm1")

        commands = [
            call.kwargs.get("cmdlet", call.args[0] if call.args else "")
            for call in powershell.run_cmdlet.call_args_list
        ]
        self.assertIn("Stop-VM", commands[1])
        self.assertIn("Remove-VMAssignableDevice", commands[2])
        self.assertIn("Enable-PnpDevice", commands[5])
        wait_enabled.assert_called_once_with(
            state.instance_id,
            state.location_path,
            require_healthy=True,
        )
        restore_disk.assert_called_once_with(state.disk)

    @patch("lisa.sut_orchestrator.hyperv.hyperv_device_pool.HypervAssignableDevices")
    def test_recovery_rejects_changed_nvme_controller_identity(
        self, assignable_devices_type: MagicMock
    ) -> None:
        state = HyperVNvmeRecoveryState(
            schema_version=1,
            location_path="PCIROOT(1)#PCI(0000)",
            instance_id="PCI\\EXPECTED",
            disk=NvmeDiskState(
                number=3,
                unique_id="disk-unique-id",
                serial_number="",
                was_offline=False,
            ),
        )
        powershell = MagicMock()
        powershell.run_cmdlet.return_value = ""
        powershell.run_cmdlet_async.return_value = MagicMock()
        powershell.wait_result.return_value = SimpleNamespace(exit_code=0, stdout="")
        get_pnp_device = (
            assignable_devices_type.return_value.get_pnp_device_by_location_path
        )
        get_pnp_device.return_value = SimpleNamespace(
            instance_id="PCI\\DIFFERENT", config_manager_error_code="22"
        )
        node = SimpleNamespace(tools={PowerShell: powershell})
        pool = HyperVDevicePool(
            node=cast(Any, node),
            runbook=HypervPlatformSchema(),
            log=MagicMock(),
        )

        with self.assertRaisesRegex(LisaException, "controller identity changed"):
            pool.recover_nvme_device(state, "vm1")

        self.assertFalse(
            any(
                "Enable-PnpDevice" in call.kwargs.get("cmdlet", "")
                for call in powershell.run_cmdlet.call_args_list
            )
        )

    def test_recovery_rejects_unexpected_assigned_vm_before_detach(self) -> None:
        state = self._create_recovery_state()
        powershell = MagicMock()
        powershell.run_cmdlet.return_value = "unexpected-vm"
        pool = self._create_pool(powershell)

        with self.assertRaisesRegex(LisaException, "unexpected VM"):
            pool.recover_nvme_device(state, "expected-vm")

        self.assertFalse(
            any(
                "Remove-VMAssignableDevice" in call.kwargs.get("cmdlet", "")
                for call in powershell.run_cmdlet.call_args_list
            )
        )

    def test_recovery_rejects_multiple_assigned_vms_without_hint(self) -> None:
        state = self._create_recovery_state()
        powershell = MagicMock()
        powershell.run_cmdlet.return_value = "vm1\r\nvm2"
        pool = self._create_pool(powershell)

        with self.assertRaisesRegex(LisaException, "multiple VMs"):
            pool.recover_nvme_device(state, "")

        self.assertFalse(
            any(
                "Remove-VMAssignableDevice" in call.kwargs.get("cmdlet", "")
                for call in powershell.run_cmdlet.call_args_list
            )
        )

    def test_recovery_fails_closed_when_assignment_inventory_fails(self) -> None:
        state = self._create_recovery_state()
        powershell = MagicMock()
        powershell.run_cmdlet.side_effect = LisaException("inventory failed")
        pool = self._create_pool(powershell)

        with self.assertRaisesRegex(LisaException, "inventory failed"):
            pool.recover_nvme_device(state, "vm1")

        self.assertEqual(1, powershell.run_cmdlet.call_count)

    @patch("lisa.sut_orchestrator.hyperv.hyperv_device_pool.HypervAssignableDevices")
    def test_recovery_discovers_single_assigned_vm(
        self, assignable_devices_type: MagicMock
    ) -> None:
        state = self._create_recovery_state()
        powershell = MagicMock()
        powershell.run_cmdlet.side_effect = ["vm1", "", "", "", "", ""]
        powershell.run_cmdlet_async.return_value = MagicMock()
        powershell.wait_result.return_value = SimpleNamespace(exit_code=0, stdout="")
        assignable_devices_type.return_value.get_pnp_device_by_location_path.return_value = SimpleNamespace(  # noqa: E501
            instance_id=state.instance_id,
            config_manager_error_code="22",
        )
        pool = self._create_pool(powershell)

        with patch.object(pool, "_wait_for_pnp_device_enabled"):
            with patch.object(pool, "_restore_nvme_disk_state"):
                recovered_vm_name = pool.recover_nvme_device(state, " ")

        self.assertEqual("vm1", recovered_vm_name)
        commands = [
            call.kwargs.get("cmdlet", call.args[0] if call.args else "")
            for call in powershell.run_cmdlet.call_args_list
        ]
        self.assertIn("Stop-VM", commands[1])
        self.assertIn("$vmName = 'vm1'", commands[1])
        self.assertIn("Remove-VMAssignableDevice", commands[2])
        self.assertIn("-VMName 'vm1'", commands[2])

    def test_recovery_does_not_detach_until_vm_is_off(self) -> None:
        state = self._create_recovery_state()
        powershell = MagicMock()
        powershell.run_cmdlet.side_effect = [
            "vm1",
            LisaException("VM did not stop"),
        ]
        pool = self._create_pool(powershell)

        with self.assertRaisesRegex(LisaException, "did not stop"):
            pool.recover_nvme_device(state, "vm1")

        commands = [
            call.kwargs["cmdlet"] for call in powershell.run_cmdlet.call_args_list
        ]
        self.assertTrue(any("Stop-VM" in command for command in commands))
        self.assertFalse(
            any("Remove-VMAssignableDevice" in command for command in commands)
        )

    def test_recovery_does_not_mount_device_still_assigned_after_removal(
        self,
    ) -> None:
        state = self._create_recovery_state()
        powershell = MagicMock()
        powershell.run_cmdlet.side_effect = ["vm1", "", "", "vm1"]
        pool = self._create_pool(powershell)

        with self.assertRaisesRegex(LisaException, "still assigned"):
            pool.recover_nvme_device(state, "vm1")

        powershell.run_cmdlet_async.assert_not_called()

    def _create_recovery_state(self) -> HyperVNvmeRecoveryState:
        return HyperVNvmeRecoveryState(
            schema_version=1,
            location_path="PCIROOT(1)#PCI(0000)",
            instance_id="PCI\\VEN_144D&DEV_A80A",
            disk=NvmeDiskState(
                number=3,
                unique_id="disk-unique-id",
                serial_number="disk-serial",
                was_offline=False,
            ),
        )

    def _create_pool(self, powershell: MagicMock) -> HyperVDevicePool:
        node = SimpleNamespace(tools={PowerShell: powershell})
        return HyperVDevicePool(
            node=cast(Any, node),
            runbook=HypervPlatformSchema(),
            log=MagicMock(),
        )

    @patch("lisa.sut_orchestrator.hyperv.hyperv_device_pool.HypervAssignableDevices")
    def test_capture_nvme_recovery_state_reuses_safety_validation(
        self, assignable_devices_type: MagicMock
    ) -> None:
        location_path = "PCIROOT(1)#PCI(0000)"
        device = DeviceAddressSchema(
            instance_id="PCI\\VEN_144D&DEV_A80A",
            location_path=location_path,
        )
        assignable_devices = assignable_devices_type.return_value
        get_by_location_path = (
            assignable_devices.get_assignable_devices_by_location_paths
        )
        get_by_location_path.return_value = [device]
        powershell = MagicMock()
        powershell.run_cmdlet.side_effect = [
            "",
            3,
            {
                "Number": 3,
                "UniqueId": "disk-unique-id",
                "SerialNumber": "disk-serial",
                "FriendlyName": "NVMe data disk",
                "BusType": "NVMe",
                "IsBoot": False,
                "IsSystem": False,
                "IsOffline": False,
                "IsMounted": False,
                "PhysicalDiskCount": 1,
                "IsStoragePoolMember": False,
                "StoragePoolNames": "",
            },
        ]
        node = SimpleNamespace(tools={PowerShell: powershell})
        pool = HyperVDevicePool(
            node=cast(Any, node),
            runbook=HypervPlatformSchema(),
            log=MagicMock(),
        )

        state = pool.capture_nvme_recovery_state(location_path)

        self.assertEqual(
            HyperVNvmeRecoveryState(
                schema_version=1,
                location_path=location_path,
                instance_id=device.instance_id,
                disk=NvmeDiskState(
                    number=3,
                    unique_id="disk-unique-id",
                    serial_number="disk-serial",
                    was_offline=False,
                ),
            ),
            state,
        )
        get_by_location_path.assert_called_once_with([location_path])

    @patch("lisa.sut_orchestrator.hyperv.hyperv_device_pool.HypervAssignableDevices")
    def test_configure_pci_nvme_pool_from_vendor_device_id(
        self, assignable_devices_type: MagicMock
    ) -> None:
        nvme_device = DeviceAddressSchema(
            instance_id="PCI\\VEN_144D&DEV_A80A",
            location_path="PCIROOT(1)#PCI(0000)",
        )
        get_assignable_devices = (
            assignable_devices_type.return_value.get_assignable_devices
        )
        get_assignable_devices.return_value = [nvme_device]
        powershell = MagicMock()
        powershell.run_cmdlet.side_effect = [
            1,
            {
                "Number": 1,
                "UniqueId": "disk-unique-id",
                "SerialNumber": "disk-serial",
                "FriendlyName": "NVMe data disk",
                "BusType": "NVMe",
                "IsBoot": False,
                "IsSystem": False,
                "IsOffline": False,
                "IsMounted": False,
                "PhysicalDiskCount": 1,
                "IsStoragePoolMember": False,
                "StoragePoolNames": "",
            },
        ]
        node = SimpleNamespace(tools={PowerShell: powershell})
        pool = HyperVDevicePool(
            node=cast(Any, node),
            runbook=HypervPlatformSchema(),
            log=MagicMock(),
        )

        pool.configure_device_passthrough_pool(
            [
                HostDevicePoolSchema(
                    type=HostDevicePoolType.PCI_NVME,
                    devices=[
                        VendorDeviceIdIdentifier(vendor_id="144D", device_id="A80A")
                    ],
                )
            ]
        )

        get_assignable_devices.assert_called_once_with(
            vendor_id="144D",
            device_id="A80A",
        )
        self.assertEqual(
            [nvme_device],
            pool.available_host_devices[HostDevicePoolType.PCI_NVME],
        )
        cmdlets = [
            call.kwargs["cmdlet"] for call in powershell.run_cmdlet.call_args_list
        ]
        self.assertIn("DEVPKEY_Device_Children", cmdlets[0])
        self.assertIn("$childrenProperty.PSObject.Properties['Data']", cmdlets[0])
        self.assertNotIn("$childrenProperty.Data", cmdlets[0])
        self.assertIn("Get-StoragePool", cmdlets[1])
        self.assertIn("-PhysicalDisk", cmdlets[1])
        self.assertIn("-not $_.IsPrimordial", cmdlets[1])
        self.assertIn("IsNullOrWhiteSpace", cmdlets[1])
        for cmdlet in cmdlets:
            encoded_command = base64.b64encode(
                f"{cmdlet.rstrip()} | ConvertTo-Json".encode("utf-16-le")
            ).decode("utf-8")
            self.assertLess(len(encoded_command), 7000)

    @patch("lisa.sut_orchestrator.hyperv.hyperv_device_pool.HypervAssignableDevices")
    def test_configure_pci_nvme_pool_from_location_path(
        self, assignable_devices_type: MagicMock
    ) -> None:
        location_path = "PCIROOT(1)#PCI(0000)"
        nvme_device = DeviceAddressSchema(
            instance_id="PCI\\VEN_144D&DEV_A80A",
            location_path=location_path,
        )
        assignable_devices = assignable_devices_type.return_value
        get_by_location_path = (
            assignable_devices.get_assignable_devices_by_location_paths
        )
        get_by_location_path.return_value = [nvme_device]
        powershell = MagicMock()
        powershell.run_cmdlet.side_effect = [
            1,
            {
                "Number": 1,
                "UniqueId": "disk-unique-id",
                "SerialNumber": "disk-serial",
                "FriendlyName": "NVMe data disk",
                "BusType": "NVMe",
                "IsBoot": False,
                "IsSystem": False,
                "IsOffline": False,
                "IsMounted": False,
                "PhysicalDiskCount": 1,
                "IsStoragePoolMember": False,
                "StoragePoolNames": "",
            },
        ]
        node = SimpleNamespace(tools={PowerShell: powershell})
        pool = HyperVDevicePool(
            node=cast(Any, node),
            runbook=HypervPlatformSchema(),
            log=MagicMock(),
        )

        with patch.object(pool, "_prepare_devices_on_host") as prepare_devices:
            pool.configure_device_passthrough_pool(
                [
                    HostDevicePoolSchema(
                        type=HostDevicePoolType.PCI_NVME,
                        devices=DeviceLocationPathIdentifier(
                            location_path=[location_path]
                        ),
                    )
                ]
            )

        prepare_devices.assert_called_once_with([location_path])
        get_by_location_path.assert_called_once_with([location_path])
        self.assertEqual(
            [nvme_device],
            pool.available_host_devices[HostDevicePoolType.PCI_NVME],
        )

    @patch("lisa.sut_orchestrator.hyperv.hyperv_device_pool.HypervAssignableDevices")
    def test_rejects_missing_or_ambiguous_pci_nvme_vendor_device_selection(
        self, assignable_devices_type: MagicMock
    ) -> None:
        node = SimpleNamespace(tools={PowerShell: MagicMock()})
        pool = HyperVDevicePool(
            node=cast(Any, node),
            runbook=HypervPlatformSchema(),
            log=MagicMock(),
        )
        get_assignable_devices = (
            assignable_devices_type.return_value.get_assignable_devices
        )

        for device_count in (0, 2):
            with self.subTest(device_count=device_count):
                devices = [
                    DeviceAddressSchema(instance_id=f"PCI\\DEVICE_{device_index}")
                    for device_index in range(device_count)
                ]
                get_assignable_devices.return_value = devices

                with self.assertRaisesRegex(LisaException, "exactly one"):
                    pool.create_device_pool_from_vendor_device_id(
                        pool_type=HostDevicePoolType.PCI_NVME,
                        vendor_id="144D",
                        device_id="A80A",
                    )

    def test_rejects_unsafe_pci_nvme_disk(self) -> None:
        device = DeviceAddressSchema(
            instance_id="PCI\\VEN_144D&DEV_A80A",
            location_path="PCIROOT(1)#PCI(0000)",
        )
        safety_cases: Dict[str, Tuple[Any, Any, str]] = {
            "missing disk": ([], None, "exactly one Windows disk"),
            "incomplete record": (
                1,
                {},
                "incomplete Windows disk safety record",
            ),
            "multiple disks": (
                [1, 2],
                None,
                "exactly one Windows disk",
            ),
            "RAID disk": (
                1,
                {
                    "Number": 1,
                    "UniqueId": "disk-unique-id",
                    "SerialNumber": "disk-serial",
                    "BusType": "RAID",
                    "IsBoot": False,
                    "IsSystem": False,
                    "IsOffline": False,
                    "IsMounted": False,
                    "PhysicalDiskCount": 1,
                    "IsStoragePoolMember": False,
                    "StoragePoolNames": "",
                },
                "not NVMe",
            ),
            "boot disk": (
                0,
                {
                    "Number": 0,
                    "UniqueId": "disk-unique-id",
                    "SerialNumber": "disk-serial",
                    "BusType": "NVMe",
                    "IsBoot": True,
                    "IsSystem": False,
                    "IsOffline": False,
                    "IsMounted": False,
                    "PhysicalDiskCount": 1,
                    "IsStoragePoolMember": False,
                    "StoragePoolNames": "",
                },
                "boot",
            ),
            "system disk": (
                0,
                {
                    "Number": 0,
                    "UniqueId": "disk-unique-id",
                    "SerialNumber": "disk-serial",
                    "BusType": "NVMe",
                    "IsBoot": False,
                    "IsSystem": True,
                    "IsOffline": False,
                    "IsMounted": False,
                    "PhysicalDiskCount": 1,
                    "IsStoragePoolMember": False,
                    "StoragePoolNames": "",
                },
                "system",
            ),
            "mounted disk": (
                1,
                {
                    "Number": 1,
                    "UniqueId": "disk-unique-id",
                    "SerialNumber": "disk-serial",
                    "BusType": "NVMe",
                    "IsBoot": False,
                    "IsSystem": False,
                    "IsOffline": False,
                    "IsMounted": True,
                    "PhysicalDiskCount": 1,
                    "IsStoragePoolMember": False,
                    "StoragePoolNames": "",
                },
                "mounted",
            ),
            "missing physical disk": (
                1,
                {
                    "Number": 1,
                    "UniqueId": "disk-unique-id",
                    "SerialNumber": "disk-serial",
                    "BusType": "NVMe",
                    "IsBoot": False,
                    "IsSystem": False,
                    "IsOffline": False,
                    "IsMounted": False,
                    "PhysicalDiskCount": 0,
                    "IsStoragePoolMember": False,
                    "StoragePoolNames": "",
                },
                "exactly one Windows physical disk",
            ),
            "ambiguous physical disk": (
                1,
                {
                    "Number": 1,
                    "UniqueId": "disk-unique-id",
                    "SerialNumber": "disk-serial",
                    "BusType": "NVMe",
                    "IsBoot": False,
                    "IsSystem": False,
                    "IsOffline": False,
                    "IsMounted": False,
                    "PhysicalDiskCount": 2,
                    "IsStoragePoolMember": False,
                    "StoragePoolNames": "",
                },
                "exactly one Windows physical disk",
            ),
            "storage pool member": (
                1,
                {
                    "Number": 1,
                    "UniqueId": "disk-unique-id",
                    "SerialNumber": "disk-serial",
                    "BusType": "NVMe",
                    "IsBoot": False,
                    "IsSystem": False,
                    "IsOffline": False,
                    "IsMounted": False,
                    "PhysicalDiskCount": 1,
                    "IsStoragePoolMember": True,
                    "StoragePoolNames": "S2D on LSG2104-07",
                },
                "Storage Spaces pool",
            ),
        }

        for case_name, (
            disk_numbers,
            disk_record,
            expected_error,
        ) in safety_cases.items():
            with self.subTest(case_name):
                powershell = MagicMock()
                powershell.run_cmdlet.side_effect = [disk_numbers, disk_record]
                node = SimpleNamespace(tools={PowerShell: powershell})
                pool = HyperVDevicePool(
                    node=cast(Any, node),
                    runbook=HypervPlatformSchema(),
                    log=MagicMock(),
                )

                with self.assertRaisesRegex(LisaException, expected_error):
                    pool._validate_nvme_devices([device])

    def test_pci_gpu_still_excludes_primary_nic(self) -> None:
        primary_nic = DeviceAddressSchema(
            instance_id="PCI\\PRIMARY_NIC",
            location_path="PCIROOT(1)#PCI(0000)",
        )
        node = SimpleNamespace(tools={PowerShell: MagicMock()})
        pool = HyperVDevicePool(
            node=cast(Any, node),
            runbook=HypervPlatformSchema(),
            log=MagicMock(),
        )

        with patch.object(
            pool, "get_primary_nic_id", return_value=[primary_nic.instance_id]
        ) as get_primary_nic_id:
            pool._append_devices_to_pool(HostDevicePoolType.PCI_GPU, [primary_nic])

        get_primary_nic_id.assert_called_once_with()
        self.assertEqual([], pool.available_host_devices[HostDevicePoolType.PCI_GPU])

    def test_release_pci_nvme_restores_host_device(self) -> None:
        device = DeviceAddressSchema(
            instance_id="PCI\\VEN_144D&DEV_A80A",
            location_path="PCIROOT(1)#PCI(0000)",
        )
        powershell = MagicMock()
        node = SimpleNamespace(tools={PowerShell: powershell})
        pool = HyperVDevicePool(
            node=cast(Any, node),
            runbook=HypervPlatformSchema(),
            log=MagicMock(),
        )
        node_context = NodeContext(
            vm_name="vm1",
            passthrough_devices=[
                DevicePassthroughContext(
                    pool_type=HostDevicePoolType.PCI_NVME,
                    device_list=[device],
                    requested_count=1,
                    nvme_disk_states={
                        device.instance_id: NvmeDiskState(
                            number=3,
                            unique_id="disk-unique-id",
                            serial_number="disk-serial",
                            was_offline=False,
                        )
                    },
                )
            ],
        )

        with patch.object(pool, "_wait_for_pnp_device_enabled") as wait_enabled:
            pool.release_devices(node_context)

        commands = [
            call.kwargs.get("cmdlet", call.args[0] if call.args else "")
            for call in powershell.run_cmdlet.call_args_list
        ]
        self.assertIn("Remove-VMAssignableDevice", commands[0])
        self.assertIn("Mount-VMHostAssignableDevice", commands[1])
        self.assertIn("Enable-PnpDevice", commands[2])
        self.assertIn("Set-Disk", commands[3])
        self.assertIn("-IsOffline $false", commands[3])
        self.assertIn("disk-unique-id", commands[3])
        self.assertIn("disk-serial", commands[3])
        self.assertIn("AddSeconds", commands[3])
        self.assertIn("Start-Sleep", commands[3])
        wait_enabled.assert_called_once_with(device.instance_id, device.location_path)
        self.assertEqual(
            [device], pool.available_host_devices[HostDevicePoolType.PCI_NVME]
        )
        self.assertEqual([], node_context.passthrough_devices)

    def test_pci_nvme_assignment_offlines_disk_before_disable(self) -> None:
        device = DeviceAddressSchema(
            instance_id="PCI\\VEN_144D&DEV_A80A",
            location_path="PCIROOT(1)#PCI(0000)",
        )
        powershell = MagicMock()
        powershell.run_cmdlet.side_effect = [
            3,
            {
                "Number": 3,
                "UniqueId": "disk-unique-id",
                "SerialNumber": "disk-serial",
                "BusType": "NVMe",
                "IsBoot": False,
                "IsSystem": False,
                "IsMounted": False,
                "IsOffline": False,
                "PhysicalDiskCount": 1,
                "IsStoragePoolMember": False,
                "StoragePoolNames": "",
            },
            "",
            "",
            "",
            "",
        ]
        node = SimpleNamespace(tools={PowerShell: powershell})
        pool = HyperVDevicePool(
            node=cast(Any, node),
            runbook=HypervPlatformSchema(),
            log=MagicMock(),
        )

        disk_states = pool._assign_devices_to_vm(
            vm_name="vm1",
            pool_type=HostDevicePoolType.PCI_NVME,
            devices=[device],
        )

        commands = [
            call.kwargs.get("cmdlet", call.args[0] if call.args else "")
            for call in powershell.run_cmdlet.call_args_list
        ]
        offline_index = next(
            index
            for index, command in enumerate(commands)
            if "Set-Disk" in command and "-IsOffline $true" in command
        )
        disable_index = next(
            index
            for index, command in enumerate(commands)
            if "Disable-PnpDevice" in command
        )
        self.assertLess(offline_index, disable_index)
        self.assertEqual(
            NvmeDiskState(
                number=3,
                unique_id="disk-unique-id",
                serial_number="disk-serial",
                was_offline=False,
            ),
            disk_states[device.instance_id],
        )

    def test_revalidates_pci_nvme_before_assignment(self) -> None:
        device = DeviceAddressSchema(
            instance_id="PCI\\VEN_144D&DEV_A80A",
            location_path="PCIROOT(1)#PCI(0000)",
        )
        powershell = MagicMock()
        powershell.run_cmdlet.side_effect = [
            0,
            {
                "Number": 0,
                "UniqueId": "disk-unique-id",
                "SerialNumber": "disk-serial",
                "BusType": "NVMe",
                "IsBoot": True,
                "IsSystem": True,
                "IsOffline": False,
                "IsMounted": True,
                "PhysicalDiskCount": 1,
                "IsStoragePoolMember": False,
                "StoragePoolNames": "",
            },
        ]
        node = SimpleNamespace(tools={PowerShell: powershell})
        pool = HyperVDevicePool(
            node=cast(Any, node),
            runbook=HypervPlatformSchema(),
            log=MagicMock(),
        )

        with self.assertRaisesRegex(LisaException, "unsafe Windows disk"):
            pool._assign_devices_to_vm(
                vm_name="vm1",
                pool_type=HostDevicePoolType.PCI_NVME,
                devices=[device],
            )

        commands = [
            call.kwargs.get("cmdlet", call.args[0] if call.args else "")
            for call in powershell.run_cmdlet.call_args_list
        ]
        self.assertFalse(any("Disable-PnpDevice" in command for command in commands))
        self.assertEqual(
            [device], pool.available_host_devices[HostDevicePoolType.PCI_NVME]
        )

    def test_pci_nvme_assignment_preserves_offline_disk(self) -> None:
        device = DeviceAddressSchema(
            instance_id="PCI\\VEN_144D&DEV_A80A",
            location_path="PCIROOT(1)#PCI(0000)",
        )
        powershell = MagicMock()
        powershell.run_cmdlet.side_effect = [
            3,
            {
                "Number": 3,
                "UniqueId": "disk-unique-id",
                "SerialNumber": "disk-serial",
                "BusType": "NVMe",
                "IsBoot": False,
                "IsSystem": False,
                "IsOffline": True,
                "IsMounted": False,
                "PhysicalDiskCount": 1,
                "IsStoragePoolMember": False,
                "StoragePoolNames": "",
            },
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ]
        node = SimpleNamespace(tools={PowerShell: powershell})
        pool = HyperVDevicePool(
            node=cast(Any, node),
            runbook=HypervPlatformSchema(),
            log=MagicMock(),
        )

        disk_states = pool._assign_devices_to_vm(
            vm_name="vm1",
            pool_type=HostDevicePoolType.PCI_NVME,
            devices=[device],
        )
        node_context = NodeContext(
            vm_name="vm1",
            passthrough_devices=[
                DevicePassthroughContext(
                    pool_type=HostDevicePoolType.PCI_NVME,
                    device_list=[device],
                    requested_count=1,
                    nvme_disk_states=disk_states,
                )
            ],
        )

        with patch.object(pool, "_wait_for_pnp_device_enabled"):
            pool.release_devices(node_context)

        commands = [
            call.kwargs.get("cmdlet", call.args[0] if call.args else "")
            for call in powershell.run_cmdlet.call_args_list
        ]
        restore_command = next(
            command for command in commands if "Returned Windows NVMe disk" in command
        )
        self.assertIn("-IsOffline $true", restore_command)
        self.assertIn("Start-Sleep", restore_command)

    def test_pci_nvme_assignment_rollback_restores_offline_disk(self) -> None:
        device = DeviceAddressSchema(
            instance_id="PCI\\VEN_144D&DEV_A80A",
            location_path="PCIROOT(1)#PCI(0000)",
        )
        commands: List[str] = []

        def run_cmdlet(cmdlet: str, **_: Any) -> Any:
            commands.append(cmdlet)
            if "DEVPKEY_Device_Children" in cmdlet:
                return 3
            if "[PSCustomObject]" in cmdlet:
                return {
                    "Number": 3,
                    "UniqueId": "disk-unique-id",
                    "SerialNumber": "disk-serial",
                    "BusType": "NVMe",
                    "IsBoot": False,
                    "IsSystem": False,
                    "IsOffline": True,
                    "IsMounted": False,
                    "PhysicalDiskCount": 1,
                    "IsStoragePoolMember": False,
                    "StoragePoolNames": "",
                }
            if "Dismount-VMHostAssignableDevice" in cmdlet:
                raise LisaException("pcip failed")
            return ""

        powershell = SimpleNamespace(run_cmdlet=MagicMock(side_effect=run_cmdlet))
        node = SimpleNamespace(tools={PowerShell: powershell})
        pool = HyperVDevicePool(
            node=cast(Any, node),
            runbook=HypervPlatformSchema(),
            log=MagicMock(),
        )

        with patch.object(pool, "_wait_for_pnp_device_enabled"):
            with self.assertRaisesRegex(LisaException, "pcip failed"):
                pool._assign_devices_to_vm(
                    vm_name="vm1",
                    pool_type=HostDevicePoolType.PCI_NVME,
                    devices=[device],
                )

        enable_index = next(
            index
            for index, command in enumerate(commands)
            if "Enable-PnpDevice" in command
        )
        restore_index = next(
            index
            for index, command in enumerate(commands)
            if "Returned Windows NVMe disk" in command and "-IsOffline $true" in command
        )
        self.assertLess(enable_index, restore_index)

    def test_pci_nvme_assignment_rollback_restores_online_disk(self) -> None:
        device = DeviceAddressSchema(
            instance_id="PCI\\VEN_144D&DEV_A80A",
            location_path="PCIROOT(1)#PCI(0000)",
        )
        commands: List[str] = []

        def run_cmdlet(cmdlet: str, **_: Any) -> Any:
            commands.append(cmdlet)
            if "DEVPKEY_Device_Children" in cmdlet:
                return 3
            if "[PSCustomObject]" in cmdlet:
                return {
                    "Number": 3,
                    "UniqueId": "disk-unique-id",
                    "SerialNumber": "disk-serial",
                    "BusType": "NVMe",
                    "IsBoot": False,
                    "IsSystem": False,
                    "IsOffline": False,
                    "IsMounted": False,
                    "PhysicalDiskCount": 1,
                    "IsStoragePoolMember": False,
                    "StoragePoolNames": "",
                }
            if "Dismount-VMHostAssignableDevice" in cmdlet:
                raise LisaException("pcip failed")
            return ""

        powershell = SimpleNamespace(run_cmdlet=MagicMock(side_effect=run_cmdlet))
        node = SimpleNamespace(tools={PowerShell: powershell})
        pool = HyperVDevicePool(
            node=cast(Any, node),
            runbook=HypervPlatformSchema(),
            log=MagicMock(),
        )

        with patch.object(pool, "_wait_for_pnp_device_enabled"):
            with self.assertRaisesRegex(LisaException, "pcip failed"):
                pool._assign_devices_to_vm(
                    vm_name="vm1",
                    pool_type=HostDevicePoolType.PCI_NVME,
                    devices=[device],
                )

        enable_index = next(
            index
            for index, command in enumerate(commands)
            if "Enable-PnpDevice" in command
        )
        restore_index = next(
            index
            for index, command in enumerate(commands)
            if "Set-Disk" in command and "-IsOffline $false" in command
        )
        self.assertLess(enable_index, restore_index)

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
                    pool_type=HostDevicePoolType.PCI_NIC,
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
        self.assertEqual(
            [first_device, second_device],
            pool.available_host_devices[HostDevicePoolType.PCI_NIC],
        )
        self.assertFalse(any("Set-Disk" in command for command in commands))

    def test_assignment_rollback_failure_keeps_device_out_of_pool(self) -> None:
        device = DeviceAddressSchema(
            instance_id="PCI\\DEVICE",
            location_path="PCIROOT(1)#PCI(0000)",
        )

        def run_cmdlet(cmdlet: str, **_: Any) -> str:
            if "Dismount-VMHostAssignableDevice" in cmdlet:
                raise LisaException("dismount failed")
            if "Enable-PnpDevice" in cmdlet:
                raise LisaException("enable failed")
            return ""

        powershell = SimpleNamespace(run_cmdlet=MagicMock(side_effect=run_cmdlet))
        node = SimpleNamespace(tools={PowerShell: powershell})
        pool = HyperVDevicePool(
            node=cast(Any, node),
            runbook=HypervPlatformSchema(),
            log=MagicMock(),
        )

        with self.assertRaisesRegex(LisaException, "Rollback also failed"):
            pool._assign_devices_to_vm(
                vm_name="vm1",
                pool_type=HostDevicePoolType.PCI_NIC,
                devices=[device],
            )

        self.assertNotIn(HostDevicePoolType.PCI_NIC, pool.available_host_devices)
