# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath, PurePosixPath
from typing import Any, Dict
from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch

from lisa import Node, TestSuiteMetadata, variable
from lisa.features import Disk
from lisa.microsoft.testsuites.performance import common
from lisa.microsoft.testsuites.performance.storageperf import StoragePerformance
from lisa.operating_system import Linux
from lisa.testsuite import TestResult
from lisa.tools import Cat, Echo, Lscpu, Readlink
from lisa.tools.kernel_config import KernelConfig
from lisa.util import LisaException


class StorageQueueLimitTestCase(TestCase):
    def setUp(self) -> None:
        self.node = Mock(spec=Node)
        self.node.os = Mock(spec=Linux)
        self.node.log = Mock()
        self.node.get_pure_path.side_effect = PurePosixPath
        self.node.tools = MagicMock()
        self.node.features = MagicMock()
        self.result = Mock(spec=TestResult)
        self.result.information = {}
        self.disks = ["/dev/sdb", "/dev/nvme0n6"]
        self.paths = [
            "/sys/block/sdb/queue/nr_requests",
            "/sys/block/nvme0n6/queue/nr_requests",
        ]
        self.settings = {self.paths[0]: 256, self.paths[1]: 32}
        self.cat = Mock(spec=Cat)
        self.echo = Mock(spec=Echo)
        self.readlink = Mock(spec=Readlink)
        self.cat.read.side_effect = self._read
        self.echo.write_to_file.side_effect = self._write
        self.readlink.get_canonical_path.side_effect = lambda path, **_: path
        tools = {
            Cat: self.cat,
            Echo: self.echo,
            Readlink: self.readlink,
            Lscpu: Mock(),
            KernelConfig: Mock(),
        }
        self.node.tools.__getitem__.side_effect = tools.__getitem__
        disk = Mock()
        disk.get_raw_data_disks.return_value = self.disks
        self.node.features.__getitem__.side_effect = {Disk: disk}.__getitem__

    def _read(self, path: str, **kwargs: Any) -> str:
        self.assertTrue(kwargs["force_run"])
        if path.endswith("/scheduler"):
            return "[mq-deadline] none\n"
        return str(self.settings[path]) + "\n"

    def _write(self, value: str, file: PurePath, **kwargs: Any) -> None:
        self.assertFalse(kwargs["ignore_error"])
        self.settings[str(file)] = int(value)

    def test_baseline_does_not_read_or_modify_queues(self) -> None:
        with (
            patch.object(common, "reset_partitions", return_value=self.disks),
            patch.object(common, "perf_disk") as perf,
        ):
            for value in (None, 0, "0"):
                with self.subTest(value=value):
                    perf.reset_mock()
                    common.perf_premium_datadisks(
                        self.node,
                        self.result,
                        variables={"fio_nr_requests_limit": value},
                    )
                    perf.assert_called_once()
        self.cat.read.assert_not_called()
        self.echo.write_to_file.assert_not_called()
        self.readlink.get_canonical_path.assert_not_called()
        self.assertEqual(self.result.information, {})

    def test_cap_resolves_aliases_never_increases_and_restores(self) -> None:
        self.readlink.get_canonical_path.side_effect = (
            lambda path, **_: "/dev/sdb" if path == "/dev/disk/by-id/data" else path
        )
        with common._limit_disk_nr_requests(
            self.node, ["/dev/disk/by-id/data", *self.disks], 64
        ) as effective:
            self.assertEqual(self.settings, {self.paths[0]: 64, self.paths[1]: 32})
            self.assertEqual(effective, self.settings)
        self.assertEqual(self.settings, {self.paths[0]: 256, self.paths[1]: 32})
        self.assertEqual(self.echo.write_to_file.call_count, 2)

    def test_string_limit_is_applied_during_fio_and_tagged(self) -> None:
        runbook = {
            "variable": [
                {
                    "name": "fio_nr_requests_limit",
                    "value": None,
                    "is_case_visible": True,
                }
            ]
        }
        with patch.dict("os.environ", {}, clear=True):
            baseline = variable.get_case_variables(variable.load_variables(runbook))
            self.assertIsNone(baseline["fio_nr_requests_limit"])
            variables = variable.get_case_variables(
                variable.load_variables(runbook, ["fio_nr_requests_limit:64"])
            )

        def verify_during_fio(*args: Any, **kwargs: Any) -> None:
            self.assertEqual(self.settings[self.paths[0]], 64)
            self.assertEqual(self.settings[self.paths[1]], 32)

        with (
            patch.object(common, "reset_partitions", return_value=self.disks),
            patch.object(common, "perf_disk", side_effect=verify_during_fio),
        ):
            common.perf_premium_datadisks(self.node, self.result, variables=variables)
        self.assertEqual(self.result.information["fio_nr_requests_limit"], 64)
        self.assertEqual(
            self.result.information["fio_nr_requests_effective"],
            {self.paths[0]: 64, self.paths[1]: 32},
        )
        self.assertEqual(self.settings[self.paths[0]], 256)

    def test_invalid_limit_fails_before_disk_setup(self) -> None:
        for value in (-1, True, False, 1.5, "invalid", "64.0"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(LisaException, "non-negative integer"):
                    common.perf_premium_datadisks(
                        self.node,
                        self.result,
                        variables={"fio_nr_requests_limit": value},
                    )
        self.node.features.__getitem__.assert_not_called()
        self.echo.write_to_file.assert_not_called()

    def test_pipeline_environment_reaches_case_and_zero_disables(self) -> None:
        for value in ("0", "64"):
            with self.subTest(value=value):
                with patch.dict(
                    "os.environ",
                    {"CV_LISA_FIO_NR_REQUESTS_LIMIT": value},
                    clear=True,
                ):
                    variables = variable.get_case_variables(
                        variable.load_variables({}, [])
                    )
                self.assertEqual(variables["fio_nr_requests_limit"], value)
                with (
                    patch.object(common, "reset_partitions", return_value=self.disks),
                    patch.object(common, "perf_disk"),
                ):
                    common.perf_premium_datadisks(
                        self.node, self.result, variables=variables
                    )
                if value == "0":
                    self.cat.read.assert_not_called()
                    self.echo.write_to_file.assert_not_called()
                    self.assertEqual(self.result.information, {})
                else:
                    self.assertEqual(
                        self.result.information["fio_nr_requests_limit"], 64
                    )
                    self.assertEqual(self.settings[self.paths[0]], 256)

    def test_fio_failure_restores_and_preserves_original_error(self) -> None:
        with (
            patch.object(common, "reset_partitions", return_value=self.disks),
            patch.object(common, "perf_disk", side_effect=RuntimeError("fio failed")),
        ):
            with self.assertRaisesRegex(RuntimeError, "fio failed"):
                common.perf_premium_datadisks(
                    self.node, self.result, variables={"fio_nr_requests_limit": 64}
                )
        self.assertEqual(self.settings, {self.paths[0]: 256, self.paths[1]: 32})

    def test_partial_write_failure_restores_every_attempted_disk(self) -> None:
        self.settings[self.paths[1]] = 128

        def fail_after_write(value: str, file: PurePath, **kwargs: Any) -> None:
            self._write(value, file, **kwargs)
            if str(file) == self.paths[1] and value == "64":
                raise LisaException("write failed after mutation")

        self.echo.write_to_file.side_effect = fail_after_write
        with self.assertRaisesRegex(LisaException, "write failed after mutation"):
            with common._limit_disk_nr_requests(self.node, self.disks, 64):
                self.fail("fio must not start after failed setup")
        self.assertEqual(self.settings, {self.paths[0]: 256, self.paths[1]: 128})

    def test_mismatched_readback_fails_and_restores(self) -> None:
        def clamp(value: str, file: PurePath, **kwargs: Any) -> None:
            self._write("32" if value == "64" else value, file, **kwargs)

        self.echo.write_to_file.side_effect = clamp
        with self.assertRaisesRegex(LisaException, "readback mismatch"):
            with common._limit_disk_nr_requests(self.node, self.disks, 64):
                self.fail("fio must not start with an unverified setting")
        self.assertEqual(self.settings, {self.paths[0]: 256, self.paths[1]: 32})

    def test_restoration_failure_is_reported_and_other_disks_restored(self) -> None:
        self.settings[self.paths[1]] = 128

        def fail_restore(value: str, file: PurePath, **kwargs: Any) -> None:
            if str(file) == self.paths[1] and value == "128":
                raise LisaException("restore failed")
            self._write(value, file, **kwargs)

        self.echo.write_to_file.side_effect = fail_restore
        with self.assertRaisesRegex(LisaException, "restore failed"):
            with common._limit_disk_nr_requests(self.node, self.disks, 64):
                pass
        self.assertEqual(self.settings[self.paths[0]], 256)
        self.node.log.exception.assert_called_once()

    def test_all_shared_helper_cases_forward_variables(self) -> None:
        metadata = TestSuiteMetadata(
            area="storage", category="performance", description="queue experiment"
        )
        suite = StoragePerformance(StoragePerformance.__wrapped__, metadata)
        variables: Dict[str, Any] = {"fio_nr_requests_limit": 64}
        cases = (
            "perf_ultra_datadisks_4k",
            "perf_ultra_datadisks_1024k",
            "perf_premiumv2_datadisks_4k",
            "perf_premiumv2_datadisks_1024k",
            "perf_premium_datadisks_4k",
            "perf_premium_datadisks_1024k",
            "perf_premium_datadisks_4k_io_uring",
            "perf_premium_datadisks_1024k_io_uring",
            "perf_standardssd_datadisks_4k",
            "perf_standardssd_datadisks_1024k",
            "perf_premium_datadisks_io",
        )
        with patch(
            "lisa.microsoft.testsuites.performance.storageperf.perf_premium_datadisks"
        ) as perf:
            for name in cases:
                with self.subTest(case=name):
                    perf.reset_mock()
                    getattr(suite, name)(self.node, self.result, variables)
                    perf.assert_called_once()
                    self.assertIs(perf.call_args.kwargs["variables"], variables)

    def test_primary_failure_is_logged_when_restoration_also_fails(self) -> None:
        def fail_restore(value: str, file: PurePath, **kwargs: Any) -> None:
            if value == "256":
                raise LisaException("restore failed")
            self._write(value, file, **kwargs)

        self.echo.write_to_file.side_effect = fail_restore
        with self.assertRaisesRegex(LisaException, "restore failed"):
            with common._limit_disk_nr_requests(self.node, self.disks, 64):
                raise RuntimeError("fio failed")
        messages = [str(c.args[0]) for c in self.node.log.exception.call_args_list]
        self.assertTrue(any("fio failed" in message for message in messages))
        self.assertTrue(any("Failed to restore" in message for message in messages))
