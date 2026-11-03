# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import Mock, patch

from lisa import Node, SkippedException
from lisa.features import Disk
from lisa.microsoft.testsuites.vm_spec import vm_spec
from lisa.testsuite import get_cases_metadata
from lisa.tools import Df, Fio, Lscpu
from lisa.util import LisaException


class VmSpecReviewTestCase(TestCase):
    def setUp(self) -> None:
        self.node = Mock(spec=Node)
        self.node.tools = {Df: Mock(), Fio: Mock(), Lscpu: Mock()}
        self.node.tools[Fio].launch.return_value.iops = 1000
        self.node.tools[Lscpu].get_thread_count.return_value = 2

    def test_fio_helpers_are_time_based(self) -> None:
        for helper in [vm_spec._run_fio_iops, vm_spec._run_fio_throughput_mbps]:
            with self.subTest(helper=helper.__name__):
                fio = self.node.tools[Fio]
                fio.reset_mock()
                helper(self.node, Mock(), "vm", ["/dev/sdc"], "disk", 2)
                self.assertEqual(3, fio.launch.call_count)
                for call in fio.launch.call_args_list:
                    self.assertTrue(call.kwargs["time_based"])
                    self.assertEqual(120, call.kwargs["time"])
                    self.assertEqual(8192, call.kwargs["size_gb"])

    def test_small_and_large_resource_disks(self) -> None:
        df = self.node.tools[Df]
        for free_kib, expected_mib in [(7 * 1024**2, 5734), (20 * 1024**2, 8192)]:
            with self.subTest(free_kib=free_kib):
                df.get_partition_by_mountpoint.return_value.available_blocks = free_kib
                self.assertEqual(
                    expected_mib,
                    vm_spec._resource_disk_workload_size_mib(self.node, "/mnt"),
                )
                self.assertLess(expected_mib * 1024, free_kib)

    def test_missing_mount_and_low_space(self) -> None:
        df = self.node.tools[Df]
        df.get_partition_by_mountpoint.return_value = None
        with self.assertRaisesRegex(LisaException, "not mounted"):
            vm_spec._resource_disk_workload_size_mib(self.node, "/mnt")
        for free_kib in [0, 1024, -1]:
            df.get_partition_by_mountpoint.return_value = Mock(
                available_blocks=free_kib
            )
            with self.assertRaises(SkippedException):
                vm_spec._resource_disk_workload_size_mib(self.node, "/mnt")

    def test_mana_and_mellanox_nic_counts(self) -> None:
        case = get_cases_metadata()["VmSpec.verify_vm_max_sriov_nic_count"]
        self.node.nics = Mock()
        with patch.object(vm_spec, "initialize_nic_info"), patch.object(
            vm_spec, "sriov_basic_test"
        ), patch.object(vm_spec, "_expected_max_nic_count", return_value=2):
            for slots in [["0000:00:02.0"] * 2, ["0000:00:02.0", "0000:00:03.0"]]:
                with self.subTest(slots=slots):
                    self.node.nics.get_pci_nics.return_value = ["eth0", "eth1"]
                    self.node.nics.get_device_slots.return_value = slots
                    case._func(Mock(), Mock(), self.node, Mock())
            self.node.nics.get_pci_nics.return_value = ["eth0"]
            with self.assertRaises(AssertionError):
                case._func(Mock(), Mock(), self.node, Mock())
            self.node.nics.get_pci_nics.assert_called_with(exclude_ib=True)

    def test_resource_file_sizing_and_cleanup_on_success_or_failure(self) -> None:
        case = get_cases_metadata()["VmSpec.verify_vm_resource_disk_iops"]
        feature = Mock()
        feature.get_resource_disk_type.return_value = (
            vm_spec.schema.ResourceDiskType.SCSI
        )
        feature.get_resource_disks.return_value = ["/dev/sdb1"]
        feature.get_resource_disk_mount_point.return_value = "/mnt"
        self.node.features = {Disk: feature}
        with patch.object(
            vm_spec,
            "_get_azure_raw_caps",
            return_value={"CombinedTempDiskAndCachedIOPS": "4000"},
        ), patch.object(
            vm_spec, "_resource_disk_workload_size_mib", return_value=5734
        ), patch.object(
            vm_spec, "_run_fio_iops", return_value=1000
        ) as benchmark:
            for fail in [False, True]:
                with self.subTest(fail=fail):
                    self.node.execute.reset_mock()
                    benchmark.side_effect = (
                        LisaException("fio failed") if fail else None
                    )
                    if fail:
                        with self.assertRaisesRegex(LisaException, "fio failed"):
                            case._func(Mock(), Mock(), self.node, Mock())
                    else:
                        case._func(Mock(), Mock(), self.node, Mock())
                    self.assertEqual(5734, benchmark.call_args.kwargs["size_mib"])
                    filename = benchmark.call_args.args[3][0]
                    self.assertTrue(filename.startswith("/mnt/lisa-fio-"))
                    self.node.execute.assert_called_once_with(
                        f"rm -f -- {filename}",
                        sudo=True,
                        expected_exit_code=0,
                        expected_exit_code_failure_message=(
                            "Cannot remove fio test file"
                        ),
                    )

    def test_documented_tolerances_match_constants(self) -> None:
        for name, tolerance in [
            ("verify_vm_memory", vm_spec._MEMORY_TOLERANCE_PERCENT),
            (
                "verify_vm_resource_disk_size",
                vm_spec._RESOURCE_DISK_SIZE_TOLERANCE_PERCENT,
            ),
        ]:
            case = get_cases_metadata()[f"VmSpec.{name}"]
            self.assertIn(f"{tolerance}%", case.description)
            self.assertNotIn("5%", case.description)
