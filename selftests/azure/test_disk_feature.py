# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import sys
from types import SimpleNamespace
from typing import Any
from unittest.case import TestCase
from unittest.mock import MagicMock, call, patch

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

from lisa import LisaException, constants, schema, search_space
from lisa.sut_orchestrator.azure import features
from lisa.util.logger import get_logger


class AzureDiskFeatureTestCase(TestCase):
    def test_disk_type_no_disk_req(self) -> None:
        # no disk in req, the cap get from lowest cost StandardHDDLRS. iops and
        # disk size
        req = features.AzureDiskOptionSettings()
        cap = self._get_default_cap()
        self._assert_disk(
            req,
            cap,
            data_disk_count=0,
        )

    def test_disk_type_overlap(self) -> None:
        # req and cap both have DiskPremiumSSDLRS, so it's selected
        req = features.AzureDiskOptionSettings(
            data_disk_type=search_space.SetSpace[schema.DiskType](
                items=[schema.DiskType.PremiumSSDLRS, schema.DiskType.StandardSSDLRS]
            )
        )
        cap = self._get_default_cap()
        self._assert_disk(
            req,
            cap,
            data_disk_count=0,
            disk_type=schema.DiskType.PremiumSSDLRS,
            data_disk_iops=120,
            data_disk_size=4,
        )

    def test_disk_type_no_common(self) -> None:
        # req and cap has no common disk type
        req = features.AzureDiskOptionSettings(
            data_disk_type=search_space.SetSpace[schema.DiskType](
                items=[schema.DiskType.StandardSSDLRS]
            )
        )
        cap = self._get_default_cap()
        reason = req.check(cap)
        self.assertFalse(reason.result)
        with self.assertRaises(LisaException) as cm:
            req.choose_value(cap)
        self.assertIsInstance(cm.exception, LisaException)
        self.assertIn("capability doesn't support requirement", str(cm.exception))

    def test_disk_one_default_data_disk(self) -> None:
        # 1 data disk in req, no value, the cap get from lowest cost
        # StandardHDDLRS, iops and disk size
        req = features.AzureDiskOptionSettings(
            data_disk_count=1,
        )
        cap = self._get_default_cap()
        self._assert_disk(
            req,
            cap,
        )

    def test_disk_specify_caching_type(self) -> None:
        # the caching type is defined by req, not cap
        req = features.AzureDiskOptionSettings(
            data_disk_caching_type=constants.DATADISK_CACHING_TYPE_READYWRITE,
            data_disk_count=1,
        )
        cap = self._get_default_cap()
        self._assert_disk(
            req,
            cap,
            data_disk_caching_type=constants.DATADISK_CACHING_TYPE_READYWRITE,
        )

    def test_disk_specify_iops_min_to_biggest(self) -> None:
        # given a min iops value, which can may only the biggest value.
        req = features.AzureDiskOptionSettings(
            data_disk_count=1,
            data_disk_iops=search_space.IntRange(min=1800),
        )
        cap = self._get_default_cap()
        self._assert_disk(req, cap, data_disk_iops=2000, data_disk_size=16384)

    def test_disk_specify_iops_a_range(self) -> None:
        # given a range of iops, match min one in range
        req = features.AzureDiskOptionSettings(
            data_disk_count=1,
            data_disk_type=schema.DiskType.PremiumSSDLRS,
            os_disk_type=schema.DiskType.PremiumSSDLRS,
            data_disk_iops=search_space.IntRange(min=1800, max=8000),
        )
        cap = self._get_default_cap()
        self._assert_disk(
            req,
            cap,
            disk_type=schema.DiskType.PremiumSSDLRS,
            data_disk_iops=2300,
            data_disk_size=512,
        )

    def test_disk_specify_iops_range_both_req_cap(self) -> None:
        # given a range of iops on req and cap, match min one in range
        req = features.AzureDiskOptionSettings(
            data_disk_count=1,
            data_disk_type=schema.DiskType.PremiumSSDLRS,
            os_disk_type=schema.DiskType.PremiumSSDLRS,
            data_disk_iops=search_space.IntRange(min=1800, max=8000),
        )
        cap = self._get_default_cap()
        cap.data_disk_iops = search_space.IntRange(min=4000, max=800000)
        self._assert_disk(
            req,
            cap,
            disk_type=schema.DiskType.PremiumSSDLRS,
            data_disk_iops=5000,
            data_disk_size=1024,
        )

    def test_disk_specify_iops_use_premium(self) -> None:
        # given premium disk type
        req = features.AzureDiskOptionSettings(
            data_disk_type=search_space.SetSpace[schema.DiskType](
                items=[schema.DiskType.PremiumSSDLRS]
            ),
            data_disk_count=1,
            data_disk_iops=search_space.IntRange(min=1800),
        )
        cap = self._get_default_cap()
        self._assert_disk(
            req,
            cap,
            disk_type=schema.DiskType.PremiumSSDLRS,
            data_disk_iops=2300,
            data_disk_size=512,
        )

    def test_disk_specify_disk_size_min_to_biggest(self) -> None:
        # given min value to disk size, match the max one
        req = features.AzureDiskOptionSettings(
            data_disk_count=1,
            data_disk_size=search_space.IntRange(min=9000),
        )
        cap = self._get_default_cap()
        self._assert_disk(
            req,
            cap,
            data_disk_iops=2000,
            data_disk_size=16384,
        )

    def test_disk_specify_disk_size_a_range(self) -> None:
        # given a range to disk size, match the min one in range
        req = features.AzureDiskOptionSettings(
            data_disk_type=search_space.SetSpace[schema.DiskType](
                items=[schema.DiskType.PremiumSSDLRS]
            ),
            data_disk_count=1,
            data_disk_size=search_space.IntRange(min=1500, max=30000),
        )
        cap = self._get_default_cap()
        self._assert_disk(
            req,
            cap,
            disk_type=schema.DiskType.PremiumSSDLRS,
            data_disk_iops=7500,
            data_disk_size=2048,
        )

    def _assert_disk(
        self,
        req: features.AzureDiskOptionSettings,
        cap: features.AzureDiskOptionSettings,
        disk_type: schema.DiskType = schema.DiskType.StandardHDDLRS,
        data_disk_count: int = 1,
        data_disk_caching_type: str = constants.DATADISK_CACHING_TYPE_NONE,
        data_disk_iops: int = 500,
        data_disk_size: int = 32,
    ) -> None:
        reason = req.check(cap)
        self.assertTrue(reason.result, f"check reasons: {reason.reasons}")
        min_value: features.AzureDiskOptionSettings = req.choose_value(cap)
        self.assertEqual(disk_type, min_value.data_disk_type)
        self.assertEqual(data_disk_count, min_value.data_disk_count)
        self.assertEqual(data_disk_caching_type, min_value.data_disk_caching_type)
        self.assertEqual(data_disk_iops, min_value.data_disk_iops)
        self.assertEqual(data_disk_size, min_value.data_disk_size)

    def _get_default_cap(self) -> features.AzureDiskOptionSettings:
        return features.AzureDiskOptionSettings(
            data_disk_type=search_space.SetSpace[schema.DiskType](
                items=[schema.DiskType.PremiumSSDLRS, schema.DiskType.StandardHDDLRS]
            ),
            data_disk_iops=search_space.IntRange(max=sys.maxsize),
            data_disk_size=search_space.IntRange(max=sys.maxsize),
        )


class AzureDiskHotAddTestCase(TestCase):
    def setUp(self) -> None:
        self.node = MagicMock()
        self.node.name = "vm"
        self.node.log = get_logger("test", "disk")
        self.node.capability = schema.NodeSpace(
            disk=features.AzureDiskOptionSettings(
                data_disk_count=0, max_data_disk_count=4
            )
        )
        self.node.get_context.return_value = SimpleNamespace(
            vm_name="vm", resource_group_name="rg"
        )
        self.vm = SimpleNamespace(
            name="vm",
            id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/"
            "virtualMachines/vm",
            storage_profile=SimpleNamespace(data_disks=[]),
        )
        self.compute = MagicMock()
        self.compute.disks.list_by_resource_group.return_value = []
        self.compute.disks.begin_create_or_update.side_effect = self._create_disk
        for name, value in (
            ("get_compute_client", self.compute),
            ("get_vm", self.vm),
        ):
            patcher = patch.object(features, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.disk = features.Disk(
            features.AzureDiskOptionSettings(), self.node, MagicMock()
        )
        self.disk.initialize()

    def test_initialize_avoids_reusing_a_leftover_disk(self) -> None:
        self.vm.storage_profile.data_disks = [
            SimpleNamespace(name="lisa_data_disk_0_vm", lun=0)
        ]
        disk = features.Disk(features.AzureDiskOptionSettings(), self.node, MagicMock())
        disk.initialize()

        self.assertEqual(1, self.node.capability.disk.data_disk_count)
        names = disk.add_data_disk(3, schema.DiskType.StandardSSDLRS)

        self.assertEqual(
            ["lisa_data_disk_1_vm", "lisa_data_disk_2_vm", "lisa_data_disk_3_vm"],
            names,
        )
        self.assertEqual(4, self.node.capability.disk.data_disk_count)

    def test_add_uses_free_luns_with_stale_count(self) -> None:
        self.vm.storage_profile.data_disks = [
            SimpleNamespace(name="existing-1", lun=1),
            SimpleNamespace(name="existing-3", lun=3),
        ]

        names = self.disk.add_data_disk(2)

        self.assertEqual(
            [0, 2],
            [disk["lun"] for disk in self.vm.storage_profile.data_disks[2:]],
        )
        self.assertEqual(4, self.node.capability.disk.data_disk_count)
        self.assertEqual(names, self.disk.disks)

    def test_add_avoids_attached_and_detached_disk_names(self) -> None:
        self.vm.storage_profile.data_disks = [
            SimpleNamespace(name="lisa_data_disk_1_vm", lun=0)
        ]
        self.compute.disks.list_by_resource_group.return_value = [
            SimpleNamespace(name="lisa_data_disk_2_vm")
        ]

        names = self.disk.add_data_disk(1, schema.DiskType.StandardSSDLRS)

        self.assertEqual(["lisa_data_disk_3_vm"], names)
        self.assertEqual(
            "StandardSSD_LRS",
            self.compute.disks.begin_create_or_update.call_args.args[2]["sku"]["name"],
        )

    def test_add_rejects_occupied_lun_and_exceeded_capacity(self) -> None:
        self.vm.storage_profile.data_disks = [SimpleNamespace(name="existing", lun=2)]

        with self.assertRaisesRegex(LisaException, "LUN 2 is already occupied"):
            self.disk.add_data_disk(1, lun=2)
        with self.assertRaisesRegex(LisaException, "1 of 4 disks are already attached"):
            self.disk.add_data_disk(4)

        self.compute.disks.begin_create_or_update.assert_not_called()

    def test_cleanup_tracks_partial_disk_creation(self) -> None:
        self.compute.disks.begin_create_or_update.side_effect = [
            self._create_disk("rg", "lisa_data_disk_0_vm", {}),
            MagicMock(result=MagicMock(side_effect=HttpResponseError("create failed"))),
        ]

        with self.assertRaisesRegex(HttpResponseError, "create failed"):
            self.disk.add_data_disk(2)
        self.assertEqual(
            ["lisa_data_disk_0_vm", "lisa_data_disk_1_vm"], self.disk.disks
        )

        self.disk.remove_data_disk()

        self.assertEqual(
            [call("rg", "lisa_data_disk_0_vm"), call("rg", "lisa_data_disk_1_vm")],
            self.compute.disks.begin_delete.call_args_list,
        )
        self.assertEqual([], self.disk.disks)
        self.assertEqual(0, self.node.capability.disk.data_disk_count)
        self.compute.virtual_machines.begin_create_or_update.assert_not_called()

    def test_cleanup_tracks_failed_attachment(self) -> None:
        vm_update = self.compute.virtual_machines.begin_create_or_update.return_value
        vm_update.wait.side_effect = HttpResponseError("attach failed")

        with self.assertRaisesRegex(HttpResponseError, "attach failed"):
            self.disk.add_data_disk(1)
        self.assertEqual(["lisa_data_disk_0_vm"], self.disk.disks)

        # The update can reach Azure even when waiting for its result fails.
        self.vm.storage_profile.data_disks = [
            SimpleNamespace(name="lisa_data_disk_0_vm", lun=0)
        ]
        vm_update.wait.side_effect = None
        self.disk.remove_data_disk()

        self.assertEqual([], self.vm.storage_profile.data_disks)
        self.assertEqual([], self.disk.disks)
        self.assertEqual(0, self.node.capability.disk.data_disk_count)

    def test_cleanup_recovers_only_this_vms_hot_add_disks(self) -> None:
        self.vm.storage_profile.data_disks = [
            SimpleNamespace(name="lisa_data_disk_0_vm", lun=0),
            SimpleNamespace(name="runbook-disk", lun=2),
        ]
        self.compute.disks.list_by_resource_group.return_value = [
            SimpleNamespace(name="lisa_data_disk_0_vm", managed_by=self.vm.id),
            SimpleNamespace(name="lisa_data_disk_1_vm", managed_by=None),
            SimpleNamespace(name="runbook-disk", managed_by=self.vm.id),
            SimpleNamespace(name="lisa_data_disk_0_other-vm", managed_by=None),
            SimpleNamespace(name="lisa_data_disk_2_vm", managed_by="/another/vm"),
        ]

        self.disk.remove_data_disk()

        self.assertEqual(
            ["runbook-disk"],
            [disk.name for disk in self.vm.storage_profile.data_disks],
        )
        self.assertEqual(
            [call("rg", "lisa_data_disk_0_vm"), call("rg", "lisa_data_disk_1_vm")],
            self.compute.disks.begin_delete.call_args_list,
        )
        self.assertEqual(1, self.node.capability.disk.data_disk_count)

    def test_cleanup_retains_failed_deletion_for_retry(self) -> None:
        name = "lisa_data_disk_0_vm"
        self.disk.disks = [name]
        self.vm.storage_profile.data_disks = [SimpleNamespace(name=name, lun=0)]
        self.compute.disks.begin_delete.return_value.wait.side_effect = (
            HttpResponseError("delete failed")
        )

        with self.assertRaisesRegex(HttpResponseError, "delete failed"):
            self.disk.remove_data_disk([name, name])
        self.assertEqual([name], self.disk.disks)
        self.assertEqual(0, self.node.capability.disk.data_disk_count)

        self.compute.disks.begin_delete.side_effect = ResourceNotFoundError("not found")
        self.disk.remove_data_disk([name])

        self.assertEqual([], self.disk.disks)
        self.assertEqual(0, self.node.capability.disk.data_disk_count)
        self.assertEqual(2, self.compute.disks.begin_delete.call_count)
        self.compute.virtual_machines.begin_create_or_update.assert_called_once()

    def _create_disk(self, group: str, name: str, parameters: Any) -> MagicMock:
        return MagicMock(
            result=MagicMock(
                return_value=SimpleNamespace(name=name, id=f"/disks/{name}")
            )
        )
