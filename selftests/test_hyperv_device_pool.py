# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple, cast
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.sut_orchestrator.hyperv.context import (
    DevicePassthroughContext,
    NodeContext,
    NvmeDiskState,
)
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
