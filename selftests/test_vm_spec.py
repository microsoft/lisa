# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any
from unittest import TestCase
from unittest.mock import Mock, patch

from lisa import Node, SkippedException, schema, search_space
from lisa.features import Disk, Nvme
from lisa.microsoft.testsuites.vm_spec import vm_spec
from lisa.operating_system import CpuArchitecture
from lisa.testselector import select_testcases
from lisa.testsuite import TestCaseRuntimeData, get_suites_metadata
from lisa.tools import Df, Fio, Lsblk, Lscpu
from lisa.util import LisaException

# Other selftests clear the global registries after test discovery.
_SUITE_METADATA = get_suites_metadata()["VmSpec"]
_CASE_METADATA = {case.full_name: case for case in _SUITE_METADATA.cases}


class VmSpecReviewTestCase(TestCase):
    def test_preview_maturity_is_inherited_and_requires_opt_in(self) -> None:
        suite = _SUITE_METADATA
        self.assertEqual("preview", suite.maturity)
        self.assertEqual(18, len(suite.cases))
        for case in suite.cases:
            self.assertEqual("preview", case.maturity)
            self.assertEqual("preview", TestCaseRuntimeData(case).maturity)
        self.assertEqual([], select_testcases(init_cases=suite.cases))
        selected = select_testcases(
            filters=[
                schema.TestCase(
                    criteria=schema.Criteria(area="vm_spec", maturity="preview")
                )
            ],
            init_cases=suite.cases,
        )
        self.assertEqual(
            {case.full_name for case in suite.cases},
            {case.metadata.full_name for case in selected},
        )

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
                    self.assertEqual("randread", call.kwargs["mode"])
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
        case = _CASE_METADATA["VmSpec.verify_vm_max_sriov_nic_count"]
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
        case = _CASE_METADATA["VmSpec.verify_vm_resource_disk_iops"]
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
            case = _CASE_METADATA[f"VmSpec.{name}"]
            self.assertIn(f"{tolerance}%", case.description)
            self.assertNotIn("5%", case.description)


class StandardSsdPerformanceTestCase(TestCase):
    def test_disk_performance_cases_require_fresh_environments(self) -> None:
        names = {
            "verify_vm_premium_ssd_iops",
            "verify_vm_standard_ssd_iops",
            "verify_vm_premium_ssd_throughput",
            "verify_vm_standard_ssd_throughput",
            "verify_vm_resource_disk_iops",
        }
        cases = _SUITE_METADATA.cases
        performance_cases = [
            case for case in cases if case.name.endswith(("_iops", "_throughput"))
        ]
        self.assertEqual(names, {case.name for case in performance_cases})
        for case in performance_cases:
            with self.subTest(case=case.name):
                self.assertTrue(case.use_new_environment)
                self.assertTrue(TestCaseRuntimeData(case).use_new_environment)

    def setUp(self) -> None:
        self.node = Mock(spec=Node)
        self.node.capability = schema.NodeSpace(
            disk=schema.DiskOptionSettings(
                data_disk_type=schema.DiskType.StandardSSDLRS,
                data_disk_count=2,
                max_data_disk_count=8,
                data_disk_iops=500,
                data_disk_throughput=60,
            )
        )

    def test_exact_capacity_is_sufficient(self) -> None:
        vm_spec._require_disk_performance(self.node, 1000, 120_000_000)

    def test_insufficient_capacity_skips(self) -> None:
        for iops, throughput in [(1001, 120_000_000), (1000, 120_000_001)]:
            with self.subTest(iops=iops, throughput=throughput):
                with self.assertRaisesRegex(SkippedException, "cannot validate"):
                    vm_spec._require_disk_performance(self.node, iops, throughput)

    def test_missing_disk_capability_skips(self) -> None:
        self.node.capability.disk = None
        with self.assertRaisesRegex(SkippedException, "capability is unavailable"):
            vm_spec._require_disk_performance(self.node, 1, 1)

    def test_invalid_or_unresolved_capacity_skips(self) -> None:
        for count in [0, -1, search_space.IntRange(min=1)]:
            with self.subTest(count=count):
                self.node.capability.disk.data_disk_count = count
                with self.assertRaises(SkippedException):
                    vm_spec._require_disk_performance(self.node, 1, 1)

    def test_standard_ssd_cases_validate_before_benchmarking(self) -> None:
        scenarios = [
            ("throughput", "UncachedDiskBytesPerSecond", 1_048_577, 2, 1_048_577),
        ]
        for metric, key, target, iops, throughput in scenarios:
            with self.subTest(metric=metric):
                case = _CASE_METADATA[f"VmSpec.verify_vm_standard_ssd_{metric}"]
                self.assertEqual(4, case.priority)
                suite, environment, log = Mock(), Mock(), Mock()
                benchmark = getattr(suite, f"_verify_data_disk_{metric}")
                with patch.object(
                    vm_spec,
                    "_get_azure_raw_caps",
                    return_value={key: str(target)},
                ), patch.object(vm_spec, "_require_disk_performance") as capacity:
                    case._func(suite, environment, self.node, log)
                    capacity.assert_called_once_with(self.node, iops, throughput)
                    benchmark.assert_called_once_with(environment, self.node, log)
                    benchmark.reset_mock()
                    capacity.side_effect = SkippedException("insufficient capacity")
                    with self.assertRaises(SkippedException):
                        case._func(suite, environment, self.node, log)
                    benchmark.assert_not_called()

    def test_standard_ssd_iops_uses_max_disk_count(self) -> None:
        case = _CASE_METADATA["VmSpec.verify_vm_standard_ssd_iops"]
        suite, environment, log = Mock(), Mock(), Mock()
        with patch.object(vm_spec, "_get_azure_raw_caps") as caps:
            case._func(suite, environment, self.node, log)
        caps.assert_not_called()
        suite._verify_data_disk_iops.assert_called_once_with(
            environment, self.node, log, expected_iops=4000
        )

    def test_standard_ssd_iops_invalid_capability_skips(self) -> None:
        case = _CASE_METADATA["VmSpec.verify_vm_standard_ssd_iops"]
        for field in ["data_disk_iops", "max_data_disk_count"]:
            for value in [0, -1, search_space.IntRange(min=1)]:
                with self.subTest(field=field, value=value):
                    self.setUp()
                    setattr(self.node.capability.disk, field, value)
                    suite = Mock()
                    with self.assertRaises(SkippedException):
                        case._func(suite, Mock(), self.node, Mock())
                    suite._verify_data_disk_iops.assert_not_called()
        self.node.capability.disk = None
        with self.assertRaisesRegex(SkippedException, "capability is unavailable"):
            case._func(Mock(), Mock(), self.node, Mock())

    def test_iops_override_applies_tolerance_without_sku_lookup(self) -> None:
        self.node.features = {Disk: Mock()}
        self.node.features[Disk].get_raw_data_disks.return_value = ["/dev/sdc"]
        self.node.tools = {Lscpu: Mock()}
        self.node.tools[Lscpu].get_thread_count.return_value = 4
        suite_class = _SUITE_METADATA.test_class
        verify_iops = suite_class._verify_data_disk_iops
        with patch.object(vm_spec, "_get_azure_raw_caps") as caps, patch.object(
            vm_spec, "_vm_size", return_value="test_vm"
        ), patch.object(vm_spec, "_run_fio_iops") as fio:
            fio.return_value = 3720
            verify_iops(Mock(), Mock(), self.node, Mock(), expected_iops=4000)
            fio.return_value = 3719
            with self.assertRaises(AssertionError):
                verify_iops(Mock(), Mock(), self.node, Mock(), expected_iops=4000)
            caps.assert_not_called()
            caps.return_value = {"UncachedDiskIOPS": "500"}
            fio.return_value = 465
            verify_iops(Mock(), Mock(), self.node, Mock())
            caps.assert_called_once()

    def test_premium_ssd_cases_still_use_shared_benchmarks(self) -> None:
        for metric in ["iops", "throughput"]:
            with self.subTest(metric=metric):
                case = _CASE_METADATA[f"VmSpec.verify_vm_premium_ssd_{metric}"]
                suite, environment, log = Mock(), Mock(), Mock()
                case._func(suite, environment, self.node, log)
                getattr(suite, f"_verify_data_disk_{metric}").assert_called_once_with(
                    environment, self.node, log
                )


class VmHardwareSpecificationTestCase(TestCase):
    def setUp(self) -> None:
        self.node = Mock(spec=Node)
        self.node.capability = schema.NodeSpace(
            disk=schema.DiskOptionSettings(
                disk_controller_type=schema.DiskControllerType.SCSI,
                data_disk_count=2,
                data_disk_size=4,
            )
        )
        self.node.features = {Disk: Mock(), Nvme: Mock()}
        self.node.features[Disk].get_raw_data_disks.return_value = [
            "/dev/sdc",
            "/dev/sdd",
        ]
        self.node.features[
            Disk
        ].get_os_disk_controller_type.return_value = schema.DiskControllerType.SCSI
        self.node.features[
            Disk
        ].get_disk_type.return_value = schema.StorageInterfaceType.SCSI
        self.node.features[Nvme].get_raw_nvme_disks.return_value = [
            "/dev/nvme1n1",
            "/dev/nvme2n1",
        ]
        self.node.tools = {Lsblk: Mock(), Lscpu: Mock()}
        self.node.tools[Lsblk].run.return_value.stdout = str(4 * 1024**3)
        self.node.tools[Lscpu].get_architecture.return_value = CpuArchitecture.X64
        self.caps = {
            "CpuArchitectureType": "x64",
            "DiskControllerTypes": "SCSI,NVMe",
            "NvmeSizePerDiskInMiB": "1537",
            "NvmeDiskSizeInMiB": "3074",
        }
        caps_patch = patch.object(
            vm_spec, "_get_azure_raw_caps", return_value=self.caps
        )
        caps_patch.start()
        self.addCleanup(caps_patch.stop)
        size_patch = patch.object(vm_spec, "_vm_size", return_value="test_vm")
        size_patch.start()
        self.addCleanup(size_patch.stop)

    def _run_case(self, name: str, **kwargs: Any) -> None:
        _CASE_METADATA[f"VmSpec.{name}"]._func(
            Mock(), node=self.node, log=Mock(), **kwargs
        )

    def test_cpu_architectures(self) -> None:
        for raw, actual in [
            ("x64", CpuArchitecture.X64),
            (" Arm64 ", CpuArchitecture.ARM64),
        ]:
            with self.subTest(architecture=raw):
                self.caps["CpuArchitectureType"] = raw
                self.node.tools[Lscpu].get_architecture.return_value = actual
                self._run_case("verify_vm_cpu_architecture", environment=Mock())

    def test_cpu_architecture_mismatch_fails(self) -> None:
        self.node.tools[Lscpu].get_architecture.return_value = CpuArchitecture.ARM64
        with self.assertRaises(AssertionError):
            self._run_case("verify_vm_cpu_architecture", environment=Mock())

    def test_cpu_unknown_or_missing_architecture_skips(self) -> None:
        for raw in ["", "unsupported"]:
            with self.subTest(architecture=raw):
                self.caps["CpuArchitectureType"] = raw
                with self.assertRaises(SkippedException):
                    self._run_case("verify_vm_cpu_architecture", environment=Mock())
        del self.caps["CpuArchitectureType"]
        with self.assertRaises(SkippedException):
            self._run_case("verify_vm_cpu_architecture", environment=Mock())

    def test_scsi_and_nvme_controllers(self) -> None:
        for controller in schema.DiskControllerType:
            with self.subTest(controller=controller):
                self.node.capability.disk.disk_controller_type = controller
                feature = self.node.features[Disk]
                feature.get_os_disk_controller_type.return_value = controller
                feature.get_disk_type.return_value = schema.StorageInterfaceType(
                    controller.value
                )
                self._run_case("verify_vm_disk_controller_type", environment=Mock())

    def test_controller_mismatch_fails_for_os_and_data(self) -> None:
        feature = self.node.features[Disk]
        for method in ["get_os_disk_controller_type", "get_disk_type"]:
            with self.subTest(method=method):
                mock_method = getattr(feature, method)
                original = mock_method.return_value
                mock_method.return_value = schema.DiskControllerType.NVME
                with self.assertRaises(AssertionError):
                    self._run_case("verify_vm_disk_controller_type", environment=Mock())
                mock_method.return_value = original

    def test_controller_unsupported_by_sku_fails(self) -> None:
        self.caps["DiskControllerTypes"] = "NVMe"
        with self.assertRaises(AssertionError):
            self._run_case("verify_vm_disk_controller_type", environment=Mock())

    def test_controller_missing_expected_values_skips(self) -> None:
        self.caps.pop("DiskControllerTypes")
        with self.assertRaises(SkippedException):
            self._run_case("verify_vm_disk_controller_type", environment=Mock())
        self.caps["DiskControllerTypes"] = "SCSI,NVMe"
        self.node.capability.disk.disk_controller_type = None
        with self.assertRaises(SkippedException):
            self._run_case("verify_vm_disk_controller_type", environment=Mock())
        self.node.capability.disk = None
        with self.assertRaises(SkippedException):
            self._run_case("verify_vm_disk_controller_type", environment=Mock())

    def test_data_disk_size_uses_exact_bytes_for_every_disk(self) -> None:
        self._run_case("verify_vm_data_disk_size")
        self.assertEqual(2, self.node.tools[Lsblk].run.call_count)
        self.node.tools[Lsblk].run.side_effect = [
            Mock(stdout=str(4 * 1024**3)),
            Mock(stdout=str(4 * 1024**3 - 1)),
        ]
        with self.assertRaises(AssertionError):
            self._run_case("verify_vm_data_disk_size")

    def test_missing_data_disks_fail(self) -> None:
        self.node.features[Disk].get_raw_data_disks.return_value = []
        for name in ["verify_vm_data_disk_size", "verify_vm_disk_controller_type"]:
            with self.subTest(case=name), self.assertRaises(AssertionError):
                if name == "verify_vm_data_disk_size":
                    self._run_case(name)
                else:
                    self._run_case(name, environment=Mock())

    def test_data_disk_invalid_size_skips(self) -> None:
        for size in [0, -1, search_space.IntRange(min=1)]:
            with self.subTest(size=size):
                self.node.capability.disk.data_disk_size = size
                with self.assertRaises(SkippedException):
                    self._run_case("verify_vm_data_disk_size")
        self.node.capability.disk = None
        with self.assertRaises(SkippedException):
            self._run_case("verify_vm_data_disk_size")

    def test_nvme_capacity_per_device_and_total(self) -> None:
        self.node.tools[Lsblk].run.return_value.stdout = str(1537 * 1024**2)
        self._run_case("verify_vm_nvme_disk_capacity", environment=Mock())
        self.assertEqual(2, self.node.tools[Lsblk].run.call_count)
        self.node.features[Disk].get_raw_data_disks.assert_not_called()
        self.caps["NvmeDiskSizeInMiB"] = "4611"
        with self.assertRaises(AssertionError):
            self._run_case("verify_vm_nvme_disk_capacity", environment=Mock())

    def test_nvme_capacity_one_byte_mismatch_fails(self) -> None:
        self.node.tools[Lsblk].run.return_value.stdout = str(1537 * 1024**2 - 1)
        with self.assertRaises(AssertionError):
            self._run_case("verify_vm_nvme_disk_capacity", environment=Mock())

    def test_nvme_missing_devices_fail(self) -> None:
        self.node.features[Nvme].get_raw_nvme_disks.return_value = []
        with self.assertRaises(AssertionError):
            self._run_case("verify_vm_nvme_disk_capacity", environment=Mock())

    def test_nvme_missing_or_invalid_capabilities_skip(self) -> None:
        for key in ["NvmeSizePerDiskInMiB", "NvmeDiskSizeInMiB"]:
            original = self.caps[key]
            for value in ["", "0", "-1", "unknown"]:
                with self.subTest(key=key, value=value):
                    self.caps[key] = value
                    with self.assertRaises(SkippedException):
                        self._run_case(
                            "verify_vm_nvme_disk_capacity", environment=Mock()
                        )
            del self.caps[key]
            with self.assertRaises(SkippedException):
                self._run_case("verify_vm_nvme_disk_capacity", environment=Mock())
            self.caps[key] = original

    def test_raw_size_errors_are_not_hidden(self) -> None:
        for output in ["", "0", "-1", "1G", "4096\n4096"]:
            with self.subTest(output=output):
                self.node.tools[Lsblk].run.return_value.stdout = output
                with self.assertRaises(LisaException):
                    vm_spec._disk_size_in_bytes(self.node, "/dev/sdc")
        self.node.tools[Lsblk].run.side_effect = LisaException("lsblk failed")
        with self.assertRaisesRegex(LisaException, "lsblk failed"):
            vm_spec._disk_size_in_bytes(self.node, "/dev/sdc")

    def test_raw_size_command_requests_bytes_and_checks_exit_code(self) -> None:
        self.assertEqual(
            4 * 1024**3,
            vm_spec._disk_size_in_bytes(self.node, "/dev/sdc"),
        )
        self.node.tools[Lsblk].run.assert_called_once_with(
            "--bytes --nodeps --noheadings --output SIZE /dev/sdc",
            force_run=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Cannot read raw size of /dev/sdc",
        )
