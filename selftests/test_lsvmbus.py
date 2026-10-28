# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import inspect
from unittest import TestCase
from unittest.mock import MagicMock

from lisa.microsoft.testsuites.core.lsvmbus import LsVmBus
from lisa.tools.lsvmbus import ChannelVPMap, VmBusDevice


class LsVmBusTestCase(TestCase):
    def test_scsi_allows_per_cpu_channels_without_mana(self) -> None:
        for thread_count in (3, 16, 64, 128):
            with self.subTest(thread_count=thread_count):
                self._verify_scsi_channels(
                    thread_count, min(thread_count, 64), has_mana=False
                )

    def test_scsi_preserves_legacy_channels_without_mana(self) -> None:
        for thread_count, channels in ((3, 1), (16, 4), (256, 64)):
            with self.subTest(thread_count=thread_count):
                self._verify_scsi_channels(thread_count, channels, has_mana=False)

    def test_scsi_rejects_unexpected_counts(self) -> None:
        for has_mana in (False, True):
            for channels in (0, 8, 17):
                with self.subTest(has_mana=has_mana, channels=channels):
                    with self.assertRaises(AssertionError):
                        self._verify_scsi_channels(16, channels, has_mana=has_mana)
        with self.assertRaises(AssertionError):
            self._verify_scsi_channels(128, 65, has_mana=False)

    def test_scsi_preserves_mana_expectation(self) -> None:
        self._verify_scsi_channels(16, 16, has_mana=True)
        with self.assertRaises(AssertionError):
            self._verify_scsi_channels(16, 4, has_mana=True)

    def _verify_scsi_channels(
        self, thread_count: int, channels: int, has_mana: bool
    ) -> None:
        node = MagicMock()
        node.tools.__getitem__.return_value.get_thread_count.return_value = thread_count
        node.nics.is_mana_device_present.return_value = has_mana
        node.features.is_supported.return_value = False
        suite = MagicMock()
        suite._verify_and_get_lsvmbus_devices.return_value = [
            VmBusDevice(
                name="Synthetic SCSI Controller",
                channel_vp_map=[
                    ChannelVPMap("1", str(index), str(index))
                    for index in range(channels)
                ],
            )
        ]
        suite_class = inspect.unwrap(LsVmBus)
        suite_class.verify_vmbus_devices_channels(suite, node, MagicMock())
