# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from inspect import signature, unwrap
from typing import List
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa import schema, search_space
from lisa.messages import DiskType
from lisa.microsoft.testsuites.performance import common, storageperf
from lisa.microsoft.testsuites.performance.common import perf_premium_datadisks
from lisa.sut_orchestrator.azure.features import AzureDiskOptionSettings
from lisa.testsuite import get_cases_metadata
from lisa.tools.fio import IoEngine
from lisa.util import LisaException, LisaTimeoutException, SkippedException


class StoragePerformanceTestCase(TestCase):
    _case_names = [
        "perf_standardssd_datadisks_4k",
        "perf_standardssd_datadisks_1024k",
        "perf_premium_datadisks_4k",
        "perf_premium_datadisks_1024k",
        "perf_premium_datadisks_4k_io_uring",
        "perf_premium_datadisks_1024k_io_uring",
    ]

    def setUp(self) -> None:
        suite_type = unwrap(storageperf.StoragePerformance)
        self.suite = suite_type.__new__(suite_type)
        self.capability = schema.DiskOptionSettings(
            data_disk_type=schema.DiskType.PremiumSSDLRS,
            data_disk_count=1,
            max_data_disk_count=4,
            data_disk_size=8192,
            data_disk_iops=16000,
        )
        self.node = MagicMock()
        self.node.capability.disk = self.capability
        self.disk = self.node.features.__getitem__.return_value
        self.disk.add_data_disk.return_value = ["added1", "added2", "added3"]
        self.disk.get_raw_data_disks.return_value = [
            "/dev/data0",
            "/dev/data1",
            "/dev/data2",
            "/dev/data3",
        ]
        self.result = MagicMock()

    def test_six_variants_have_valid_iops_and_platform_requirements(self) -> None:
        metadata = get_cases_metadata()
        new_names = [
            name
            for name in metadata
            if name.startswith("StoragePerformance.") and name.endswith("_max_disks")
        ]
        self.assertEqual(6, len(new_names))
        for name in self._case_names:
            with self.subTest(case=name):
                case = metadata[f"StoragePerformance.{name}_max_disks"]
                requirement = case.requirement
                assert requirement.environment
                disk = requirement.environment.nodes[0].disk
                assert disk
                standard = "standardssd" in name
                disk_type = (
                    schema.DiskType.StandardSSDLRS
                    if standard
                    else schema.DiskType.PremiumSSDLRS
                )
                iops = 6000 if standard else 10000
                self.assertEqual(disk_type, disk.data_disk_type)
                self.assertEqual(disk_type, disk.os_disk_type)
                self.assertEqual(search_space.IntRange(min=iops), disk.data_disk_iops)
                self.assertEqual(search_space.IntRange(min=1), disk.data_disk_count)
                self.assertEqual(
                    search_space.SetSpace(is_allow_set=True, items=["azure"]),
                    requirement.platform_type,
                )

                resolved = AzureDiskOptionSettings(
                    data_disk_type=disk_type,
                    data_disk_iops=disk.data_disk_iops,
                    data_disk_count=disk.data_disk_count,
                ).choose_value(
                    AzureDiskOptionSettings(
                        data_disk_type=disk_type,
                        data_disk_iops=search_space.IntRange(max=20000),
                        data_disk_size=search_space.IntRange(max=32767),
                        data_disk_count=search_space.IntRange(max=64),
                        max_data_disk_count=64,
                    )
                )
                assert isinstance(resolved.data_disk_iops, int)
                self.assertGreaterEqual(resolved.data_disk_iops, iops)
                self.assertEqual(1, resolved.data_disk_count)
                self.assertEqual(64, resolved.max_data_disk_count)
                self.assertEqual(32767 if standard else 8192, resolved.data_disk_size)

    def test_original_requirements_are_unchanged(self) -> None:
        metadata = get_cases_metadata()
        for name in self._case_names:
            with self.subTest(case=name):
                requirement = metadata[f"StoragePerformance.{name}"].requirement
                assert requirement.environment
                disk = requirement.environment.nodes[0].disk
                assert disk
                self.assertEqual(search_space.IntRange(min=16), disk.data_disk_count)
                self.assertEqual(
                    search_space.IntRange(min=6000 if "standardssd" in name else 5000),
                    disk.data_disk_iops,
                )

    def test_variants_preserve_fio_parameters_and_remove_only_added_disks(self) -> None:
        for name in self._case_names:
            with self.subTest(case=name), patch.object(
                storageperf, "perf_premium_datadisks"
            ) as perf:
                self.disk.reset_mock()
                standard = "standardssd" in name
                self.capability.data_disk_type = (
                    schema.DiskType.StandardSSDLRS
                    if standard
                    else schema.DiskType.PremiumSSDLRS
                )
                self.capability.data_disk_size = 32767 if standard else 8192

                getattr(self.suite, f"{name}_max_disks")(self.node, self.result)

                self.disk.add_data_disk.assert_called_once_with(
                    3, self.capability.data_disk_type, self.capability.data_disk_size
                )
                self.disk.remove_data_disk.assert_called_once_with(
                    ["added1", "added2", "added3"]
                )
                perf.assert_called_once()
                bound = signature(perf_premium_datadisks).bind(
                    *perf.call_args.args, **perf.call_args.kwargs
                )
                bound.apply_defaults()
                self.assertIs(self.node, bound.arguments["node"])
                self.assertIs(self.result, bound.arguments["test_result"])
                self.assertEqual(
                    1024 if "1024k" in name else 4, bound.arguments["block_size"]
                )
                self.assertEqual(
                    DiskType.standardssd if standard else DiskType.premiumssd,
                    bound.arguments["disk_type"],
                )
                self.assertEqual(
                    IoEngine.IO_URING if "io_uring" in name else IoEngine.LIBAIO,
                    bound.arguments["ioengine"],
                )
                self.assertEqual(
                    1024 if "io_uring" in name else 256,
                    bound.arguments["max_iodepth"],
                )

    def test_fio_uses_all_disks_and_keeps_testcase_name(self) -> None:
        self.capability.max_data_disk_count = 64
        devices = [f"/dev/data{i}" for i in range(64)]
        added = [f"added{i}" for i in range(63)]
        self.disk.get_raw_data_disks.return_value = devices
        self.disk.add_data_disk.return_value = added
        self.node.tools.__getitem__.return_value.get_thread_count.return_value = 4
        with patch.object(
            common, "reset_partitions", return_value=devices
        ) as partition, patch.object(common, "perf_disk") as perf:
            self.suite.perf_premium_datadisks_4k_max_disks(self.node, self.result)

        self.disk.add_data_disk.assert_called_once_with(
            63, schema.DiskType.PremiumSSDLRS, 8192
        )
        partition.assert_called_once_with(self.node, devices)
        self.assertEqual(":".join(devices), perf.call_args.args[3])
        self.assertEqual(64, perf.call_args.kwargs["disk_count"])
        self.assertEqual(
            "perf_premium_datadisks_4k_max_disks", perf.call_args.kwargs["test_name"]
        )
        self.disk.remove_data_disk.assert_called_once_with(added)

    def test_already_at_maximum_does_not_add_or_remove_disks(self) -> None:
        self.capability.data_disk_count = 4
        with patch.object(storageperf, "perf_premium_datadisks") as perf:
            self.suite.perf_premium_datadisks_4k_max_disks(self.node, self.result)

        perf.assert_called_once()
        self.disk.add_data_disk.assert_not_called()
        self.disk.remove_data_disk.assert_not_called()

    def test_io_uring_skip_happens_before_disk_allocation(self) -> None:
        self.node.tools.__getitem__.return_value.is_enabled.return_value = False
        for name in self._case_names:
            if "io_uring" not in name:
                continue
            with self.subTest(case=name), patch.object(
                storageperf, "perf_premium_datadisks"
            ) as perf:
                with self.assertRaisesRegex(SkippedException, "io_uring"):
                    getattr(self.suite, f"{name}_max_disks")(self.node, self.result)
                perf.assert_not_called()
        self.disk.add_data_disk.assert_not_called()

    def test_waits_until_all_disks_are_visible(self) -> None:
        self.disk.get_raw_data_disks.side_effect = [
            ["/dev/data0"],
            [f"/dev/data{i}" for i in range(4)],
        ]
        with patch("lisa.util.sleep") as sleep, patch.object(
            storageperf, "perf_premium_datadisks"
        ) as perf:
            self.suite.perf_premium_datadisks_4k_max_disks(self.node, self.result)

        sleep.assert_called_once_with(5)
        perf.assert_called_once()

    def test_visibility_timeout_prevents_fio_and_cleans_up(self) -> None:
        for visible_count in [3, 5]:
            with self.subTest(visible_count=visible_count), patch.object(
                storageperf,
                "check_till_timeout",
                side_effect=LisaTimeoutException("disks not visible"),
            ) as wait, patch.object(storageperf, "perf_premium_datadisks") as perf:
                self.disk.reset_mock()
                self.disk.get_raw_data_disks.return_value = [
                    f"/dev/data{i}" for i in range(visible_count)
                ]
                with self.assertRaises(LisaTimeoutException):
                    self.suite.perf_premium_datadisks_4k_max_disks(
                        self.node, self.result
                    )
                self.assertFalse(wait.call_args.args[0]())
                perf.assert_not_called()
                self.disk.remove_data_disk.assert_called_once_with(
                    ["added1", "added2", "added3"]
                )

    def test_benchmark_failure_still_removes_added_disks(self) -> None:
        with patch.object(
            storageperf,
            "perf_premium_datadisks",
            side_effect=LisaException("fio failed"),
        ):
            with self.assertRaisesRegex(LisaException, "fio failed"):
                self.suite.perf_premium_datadisks_4k_max_disks(self.node, self.result)
        self.disk.remove_data_disk.assert_called_once_with(
            ["added1", "added2", "added3"]
        )

    def test_partial_attachment_result_fails_and_removes_returned_disks(self) -> None:
        self.disk.add_data_disk.return_value = ["added1"]
        with patch.object(storageperf, "perf_premium_datadisks") as perf:
            with self.assertRaises(AssertionError):
                self.suite.perf_premium_datadisks_4k_max_disks(self.node, self.result)
        perf.assert_not_called()
        self.disk.remove_data_disk.assert_called_once_with(["added1"])

    def test_invalid_disk_count_fails_before_allocation(self) -> None:
        counts: List[search_space.CountSpace] = [0, 5, search_space.IntRange(min=1)]
        for count in counts:
            with self.subTest(count=count):
                self.capability.data_disk_count = count
                with self.assertRaises(AssertionError):
                    with self.suite._max_data_disks(self.node):
                        self.fail("Invalid disk capability was accepted")
        self.disk.add_data_disk.assert_not_called()
