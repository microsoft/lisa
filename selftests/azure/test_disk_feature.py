# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import sys
from types import SimpleNamespace
from typing import Any, Dict
from unittest.case import TestCase
from unittest.mock import Mock, patch

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

from lisa import LisaException, constants, schema, search_space
from lisa.node import Node
from lisa.sut_orchestrator.azure import features
from lisa.sut_orchestrator.azure.common import NodeContext
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
        self.node = Mock(spec=Node)
        self.node.log = get_logger("test", "disk")
        self.node.capability = schema.NodeSpace(
            disk=features.AzureDiskOptionSettings(
                data_disk_count=0, max_data_disk_count=4
            )
        )
        self.node.get_context.return_value = NodeContext(
            resource_group_name="group", vm_name="vm"
        )
        self.vm = Mock()
        self.vm.name = "vm"
        self.vm.storage_profile.data_disks = []
        self.client = Mock()
        self.client.disks.begin_create_or_update.side_effect = self._create_disk
        for name, value in (("get_vm", self.vm), ("get_compute_client", self.client)):
            patcher = patch(
                f"lisa.sut_orchestrator.azure.features.{name}", return_value=value
            )
            self.addCleanup(patcher.stop)
            patcher.start()
        self.disk = features.Disk(features.AzureDiskOptionSettings(), self.node, Mock())
        self.disk.initialize()
        update_patcher = patch.object(
            self.disk, "_update_vm_disks", side_effect=self._update_vm
        )
        self.addCleanup(update_patcher.stop)
        self.update_vm = update_patcher.start()

    def test_initialize_refreshes_attached_disk_count(self) -> None:
        self.vm.storage_profile.data_disks = [SimpleNamespace(name="existing", lun=2)]
        self.disk._initialize()

        self.assertEqual(1, self.node.capability.disk.data_disk_count)
        self.assertEqual([], self.disk.disks)

    def test_add_uses_actual_attachments_and_free_luns(self) -> None:
        self.vm.storage_profile.data_disks = [
            SimpleNamespace(name="lisa_data_disk_0_vm", lun=0),
            SimpleNamespace(name="existing", lun=2),
        ]

        names = self.disk.add_data_disk(2, schema.DiskType.StandardSSDLRS)

        self.assertEqual(
            [0, 2, 1, 3], [disk.lun for disk in self.vm.storage_profile.data_disks]
        )
        self.assertNotIn("lisa_data_disk_0_vm", names)
        self.assertEqual(names, self.disk.disks)
        self.assertEqual(4, self.node.capability.disk.data_disk_count)

    def test_add_rejects_occupied_lun_and_excess_count_before_creation(self) -> None:
        self.vm.storage_profile.data_disks = [SimpleNamespace(name="existing", lun=0)]

        with self.assertRaisesRegex(LisaException, "occupied LUN 0"):
            self.disk.add_data_disk(1, lun=0)
        with self.assertRaisesRegex(LisaException, "Cannot add 4"):
            self.disk.add_data_disk(4)

        self.client.disks.begin_create_or_update.assert_not_called()
        self.assertEqual(1, self.node.capability.disk.data_disk_count)

    def test_failed_creation_remains_tracked_until_cleanup(self) -> None:
        self.client.disks.begin_create_or_update.return_value = Mock()
        self.client.disks.begin_create_or_update.side_effect = None
        poller = self.client.disks.begin_create_or_update.return_value
        poller.result.side_effect = HttpResponseError("creation failed")

        with self.assertRaisesRegex(HttpResponseError, "creation failed"):
            self.disk.add_data_disk(1)
        self.assertEqual(1, len(self.disk.disks))
        name = self.disk.disks[0]
        self.client.disks.begin_delete.side_effect = ResourceNotFoundError(
            "disk not created"
        )

        self.disk.remove_data_disk()

        self.client.disks.begin_delete.assert_called_once_with("group", name)
        self.assertEqual([], self.disk.disks)
        self.assertEqual(0, self.node.capability.disk.data_disk_count)
        self.update_vm.assert_not_called()

    def test_cleanup_after_failed_attachment_preserves_existing_disk(self) -> None:
        existing = SimpleNamespace(name="existing", lun=2)
        self.vm.storage_profile.data_disks = [existing]
        self.update_vm.side_effect = HttpResponseError("attachment failed")

        with self.assertRaisesRegex(HttpResponseError, "attachment failed"):
            self.disk.add_data_disk(2)
        names = list(self.disk.disks)
        self.assertEqual(2, len(names))
        # Model an attachment that partially reached Azure before the failure.
        self.vm.storage_profile.data_disks = [
            existing,
            SimpleNamespace(name=names[0], lun=0),
        ]
        self.update_vm.side_effect = self._update_vm

        self.disk.remove_data_disk()

        self.assertEqual([existing], self.vm.storage_profile.data_disks)
        self.assertEqual(
            names,
            [call.args[1] for call in self.client.disks.begin_delete.call_args_list],
        )
        self.assertEqual([], self.disk.disks)
        self.assertEqual(1, self.node.capability.disk.data_disk_count)

    def _create_disk(self, _group: str, name: str, _parameters: Dict[str, Any]) -> Mock:
        poller = Mock()
        poller.result.return_value = SimpleNamespace(name=name, id=name)
        return poller

    def _update_vm(self, _client: Any, _group: str, _name: str, vm: Any) -> None:
        vm.storage_profile.data_disks[:] = [
            SimpleNamespace(**disk) if isinstance(disk, dict) else disk
            for disk in vm.storage_profile.data_disks
        ]
