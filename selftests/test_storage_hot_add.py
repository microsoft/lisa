# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import inspect
from typing import Type, cast
from unittest import TestCase
from unittest.mock import MagicMock, call, patch

from lisa.microsoft.testsuites.core.storage import Storage, _wait_for_added_disks
from lisa.schema import DiskType
from lisa.tools import Lsblk
from lisa.tools.lsblk import DiskInfo
from lisa.util import LisaException
from lisa.util.logger import Logger


class StorageHotAddTestCase(TestCase):
    def setUp(self) -> None:
        self.lsblk = MagicMock(spec=Lsblk)
        self.log = MagicMock(spec=Logger)
        self.os_disk = DiskInfo(name="nvme0n1", mountpoint="/")
        self.data_disk = DiskInfo(name="nvme0n2", mountpoint="", size=20 * 1024**3)
        sleep_patcher = patch("lisa.microsoft.testsuites.core.storage.time.sleep")
        self.addCleanup(sleep_patcher.stop)
        self.sleep = sleep_patcher.start()
        timer_patcher = patch("lisa.microsoft.testsuites.core.storage.create_timer")
        self.addCleanup(timer_patcher.stop)
        self.timer = timer_patcher.start().return_value
        self.timer.elapsed.return_value = 0

    def test_immediately_visible_disk_does_not_sleep(self) -> None:
        self.lsblk.get_disks.return_value = [self.os_disk, self.data_disk]

        disks = _wait_for_added_disks(self.lsblk, [self.os_disk], 1, self.log)

        self.assertEqual([self.data_disk], disks)
        self.lsblk.get_disks.assert_called_once_with(force_run=True)
        self.sleep.assert_not_called()

    def test_retries_until_disk_is_visible(self) -> None:
        self.lsblk.get_disks.side_effect = [
            [self.os_disk],
            [self.os_disk],
            [self.os_disk, self.data_disk],
        ]

        disks = _wait_for_added_disks(self.lsblk, [self.os_disk], 1, self.log)

        self.assertEqual([self.data_disk], disks)
        self.assertEqual([call(1), call(1)], self.sleep.call_args_list)
        self.assertEqual(
            [call(force_run=True)] * 3, self.lsblk.get_disks.call_args_list
        )

    def test_missing_disk_fails_at_sixty_seconds(self) -> None:
        self.lsblk.get_disks.return_value = [self.os_disk]
        self.timer.elapsed.side_effect = [0, 59, 60]

        with self.assertRaisesRegex(AssertionError, "within 60s"):
            _wait_for_added_disks(self.lsblk, [self.os_disk], 1, self.log)

        self.assertEqual(3, self.lsblk.get_disks.call_count)
        self.assertEqual([call(1), call(1)], self.sleep.call_args_list)
        self.log.debug.assert_called_with("Waiting for 1 added disks; detected []")

    def test_waits_for_all_expected_disks(self) -> None:
        second_disk = DiskInfo(name="nvme0n3", mountpoint="", size=20 * 1024**3)
        self.lsblk.get_disks.side_effect = [
            [self.os_disk, self.data_disk],
            [self.os_disk, self.data_disk, second_disk],
        ]

        disks = _wait_for_added_disks(self.lsblk, [self.os_disk], 2, self.log)

        self.assertEqual([self.data_disk, second_disk], disks)
        self.sleep.assert_called_once_with(1)

    def test_baseline_metadata_changes_are_not_new_disks(self) -> None:
        changed_os_disk = DiskInfo(name="nvme0n1", mountpoint="/", fstype="ext4")
        self.lsblk.get_disks.return_value = [changed_os_disk, self.data_disk]

        disks = _wait_for_added_disks(self.lsblk, [self.os_disk], 1, self.log)

        self.assertEqual([self.data_disk], disks)

    def test_extra_disks_do_not_satisfy_expected_count(self) -> None:
        extra_disk = DiskInfo(name="nvme0n3", mountpoint="", size=20 * 1024**3)
        self.lsblk.get_disks.return_value = [
            self.os_disk,
            self.data_disk,
            extra_disk,
        ]
        self.timer.elapsed.return_value = 60

        with self.assertRaisesRegex(AssertionError, "but was <2>"):
            _wait_for_added_disks(self.lsblk, [self.os_disk], 1, self.log)

    def test_disk_enumeration_error_is_not_swallowed(self) -> None:
        self.lsblk.get_disks.side_effect = LisaException("lsblk failed")

        with self.assertRaisesRegex(LisaException, "lsblk failed"):
            _wait_for_added_disks(self.lsblk, [self.os_disk], 1, self.log)

        self.sleep.assert_not_called()

    def test_waits_at_thirty_two_disk_boundary(self) -> None:
        data_disks = [
            DiskInfo(name=f"nvme0n{index + 2}", mountpoint="", size=20 * 1024**3)
            for index in range(32)
        ]
        self.lsblk.get_disks.side_effect = [
            [self.os_disk, *data_disks[:-1]],
            [self.os_disk, *data_disks],
        ]

        disks = _wait_for_added_disks(self.lsblk, [self.os_disk], 32, self.log)

        self.assertEqual(data_disks, disks)
        self.sleep.assert_called_once_with(1)

    def test_serial_path_waits_before_size_and_lun_checks(self) -> None:
        suite = cast(Type[Storage], inspect.unwrap(Storage))(MagicMock())
        node = MagicMock()
        node.capability.disk.max_data_disk_count = 1
        node.capability.disk.data_disk_count = 0
        node.tools.__getitem__.return_value = self.lsblk
        disk = node.features.__getitem__.return_value
        disk.add_data_disk.return_value = ["disk0"]
        disk.get_luns.side_effect = [
            {},
            {self.data_disk.device_name: 0},
            {self.data_disk.device_name: 0},
        ]
        self.lsblk.get_disks.side_effect = [
            [self.os_disk],
            [self.os_disk],
            [self.os_disk, self.data_disk],
            [self.os_disk],
        ]

        suite._hot_add_disk_serial(self.log, node, DiskType.PremiumSSDLRS, 20)

        self.sleep.assert_called_once_with(1)
        disk.add_data_disk.assert_called_once_with(1, DiskType.PremiumSSDLRS, 20, 0)
        disk.remove_data_disk.assert_called_once_with(["disk0"])

    def test_parallel_path_waits_for_all_disks(self) -> None:
        suite = cast(Type[Storage], inspect.unwrap(Storage))(MagicMock())
        node = MagicMock()
        node.capability.disk.max_data_disk_count = 2
        node.capability.disk.data_disk_count = 0
        node.tools.__getitem__.return_value = self.lsblk
        disk = node.features.__getitem__.return_value
        disk.add_data_disk.return_value = ["disk0", "disk1"]
        second_disk = DiskInfo(name="nvme0n3", mountpoint="", size=20 * 1024**3)
        self.lsblk.get_disks.side_effect = [
            [self.os_disk],
            [self.os_disk, self.data_disk],
            [self.os_disk, self.data_disk, second_disk],
            [self.os_disk],
        ]

        suite._hot_add_disk_parallel(self.log, node, DiskType.PremiumSSDLRS, 20)

        self.sleep.assert_called_once_with(1)
        disk.remove_data_disk.assert_called_once_with(["disk0", "disk1"])
