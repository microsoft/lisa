# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from inspect import signature, unwrap
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa import schema, search_space
from lisa.messages import DiskType
from lisa.microsoft.testsuites.performance import common, storageperf
from lisa.microsoft.testsuites.performance.common import perf_premium_datadisks
from lisa.sut_orchestrator.azure.features import AzureDiskOptionSettings
from lisa.testsuite import get_cases_metadata
from lisa.tools.fio import IoEngine
from lisa.util import NotMeetRequirementException, SkippedException


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
        self.node = MagicMock()
        self.disk = self.node.features.__getitem__.return_value
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
                iops = 6000 if standard else 5000
                self.assertEqual(disk_type, disk.data_disk_type)
                self.assertEqual(disk_type, disk.os_disk_type)
                self.assertEqual(search_space.IntRange(min=iops), disk.data_disk_iops)
                self.assertEqual(
                    search_space.IntRange(min=1, choose_max_value=True),
                    disk.data_disk_count,
                )
                self.assertEqual(
                    search_space.SetSpace(is_allow_set=True, items=["azure"]),
                    requirement.platform_type,
                )

                disk_requirement = AzureDiskOptionSettings(
                    data_disk_type=disk_type,
                    data_disk_iops=disk.data_disk_iops,
                    data_disk_count=disk.data_disk_count,
                )
                for max_count in [1, 4, 16, 32, 64]:
                    with self.subTest(max_count=max_count):
                        capability = AzureDiskOptionSettings(
                            data_disk_type=disk_type,
                            data_disk_iops=search_space.IntRange(max=20000),
                            data_disk_size=search_space.IntRange(max=32767),
                            data_disk_count=search_space.IntRange(max=max_count),
                            max_data_disk_count=max_count,
                        )
                        for selection_requirement in [
                            disk_requirement,
                            disk_requirement.intersect(capability),
                        ]:
                            resolved = selection_requirement.choose_value(capability)
                            assert isinstance(resolved.data_disk_iops, int)
                            self.assertGreaterEqual(resolved.data_disk_iops, iops)
                            self.assertEqual(max_count, resolved.data_disk_count)
                            self.assertEqual(max_count, resolved.max_data_disk_count)
                            self.assertEqual(
                                32767 if standard else 1024, resolved.data_disk_size
                            )

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

    def test_variants_preserve_fio_parameters_without_hot_add(self) -> None:
        for name in self._case_names:
            with self.subTest(case=name), patch.object(
                storageperf, "perf_premium_datadisks"
            ) as perf:
                self.disk.reset_mock()
                standard = "standardssd" in name
                getattr(self.suite, f"{name}_max_disks")(self.node, self.result)

                self.disk.add_data_disk.assert_not_called()
                self.disk.remove_data_disk.assert_not_called()
                perf.assert_called_once()
                bound = signature(perf_premium_datadisks).bind(
                    *perf.call_args.args, **perf.call_args.kwargs
                )
                bound.apply_defaults()
                self.assertIs(self.node, bound.arguments["node"])
                self.assertIs(self.result, bound.arguments["test_result"])
                self.assertTrue(bound.arguments["verify_max_disks"])
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
        self.node.capability.disk = schema.DiskOptionSettings(max_data_disk_count=64)
        devices = [f"/dev/data{i}" for i in range(64)]
        self.disk.get_raw_data_disks.return_value = devices
        self.node.tools.__getitem__.return_value.get_thread_count.return_value = 4
        with patch.object(
            common, "reset_partitions", return_value=devices
        ) as partition, patch.object(common, "perf_disk") as perf:
            self.suite.perf_premium_datadisks_4k_max_disks(self.node, self.result)

        partition.assert_called_once_with(self.node, devices)
        self.assertEqual(":".join(devices), perf.call_args.args[3])
        self.assertEqual(64, perf.call_args.kwargs["disk_count"])
        self.assertEqual(
            "perf_premium_datadisks_4k_max_disks", perf.call_args.kwargs["test_name"]
        )
        self.disk.add_data_disk.assert_not_called()
        self.disk.remove_data_disk.assert_not_called()

    def test_maximum_disk_mismatch_fails_before_partitioning(self) -> None:
        self.node.capability.disk = schema.DiskOptionSettings(max_data_disk_count=4)
        for name in self._case_names:
            for count in [0, 3, 5]:
                with self.subTest(case=name, visible_count=count), patch.object(
                    common, "reset_partitions"
                ) as partition, patch.object(common, "perf_disk") as perf:
                    self.disk.get_raw_data_disks.return_value = [
                        f"/dev/data{i}" for i in range(count)
                    ]
                    with self.assertRaisesRegex(AssertionError, "VM's maximum"):
                        getattr(self.suite, f"{name}_max_disks")(self.node, self.result)
                    partition.assert_not_called()
                    perf.assert_not_called()
        self.disk.add_data_disk.assert_not_called()
        self.disk.remove_data_disk.assert_not_called()

    def test_unresolved_maximum_fails_before_partitioning(self) -> None:
        self.node.capability.disk = schema.DiskOptionSettings(
            max_data_disk_count=search_space.IntRange()
        )
        self.disk.get_raw_data_disks.return_value = ["/dev/data0"]
        with patch.object(common, "reset_partitions") as partition, patch.object(
            common, "perf_disk"
        ) as perf:
            with self.assertRaisesRegex(AssertionError, "resolved positive maximum"):
                self.suite.perf_premium_datadisks_4k_max_disks(self.node, self.result)
            partition.assert_not_called()
            perf.assert_not_called()

    def test_original_variants_do_not_require_maximum_disks(self) -> None:
        self.node.capability.disk = schema.DiskOptionSettings(max_data_disk_count=64)
        devices = [f"/dev/data{i}" for i in range(16)]
        self.disk.get_raw_data_disks.return_value = devices
        self.node.tools.__getitem__.return_value.get_thread_count.return_value = 4
        for name in self._case_names:
            with self.subTest(case=name), patch.object(
                common, "reset_partitions", return_value=devices
            ) as partition, patch.object(common, "perf_disk") as perf:
                getattr(self.suite, name)(self.node, self.result)
                partition.assert_called_once_with(self.node, devices)
                perf.assert_called_once()
                self.assertEqual(16, perf.call_args.kwargs["disk_count"])

    def test_io_uring_skip_happens_before_fio(self) -> None:
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

    def test_maximum_disk_requirement_rejects_zero_or_unbounded_capacity(self) -> None:
        requirement = AzureDiskOptionSettings(
            data_disk_type=schema.DiskType.PremiumSSDLRS,
            data_disk_count=search_space.IntRange(min=1, choose_max_value=True),
        )
        for disk_count in [
            search_space.IntRange(max=0),
            search_space.IntRange(),
        ]:
            with self.subTest(disk_count=disk_count):
                capability = AzureDiskOptionSettings(
                    data_disk_type=schema.DiskType.PremiumSSDLRS,
                    data_disk_count=disk_count,
                )
                with self.assertRaises(NotMeetRequirementException):
                    requirement.choose_value(capability)
