# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from typing import Optional
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.executable import ExecutableResult
from lisa.util import LisaException
from lisa.util.constants import SIGINT
from lisa.util.package import _import_root_package


class DpdkShutdownTestCase(TestCase):
    def setUp(self) -> None:
        # DPDK imports use the extension namespace registered by LISA at startup.
        _import_root_package(
            "microsoft", Path(__file__).parents[1] / "lisa" / "microsoft"
        )
        from lisa.microsoft.testsuites.dpdk.dpdktestpmd import DpdkTestpmd

        self.testpmd = DpdkTestpmd.__new__(DpdkTestpmd)
        self.testpmd.set_instance_id("sender")

    def _result(self, output: str, exit_code: Optional[int] = 0) -> ExecutableResult:
        return ExecutableResult(output, "", exit_code, "testpmd", "test", 0)

    def test_clean_shutdown_processes_performance_data(self) -> None:
        result = self._result("TX-dropped: 0\nRX-dropped: 0\n")
        with patch.object(self.testpmd, "populate_performance_data") as populate:
            self.assertEqual(self.testpmd.process_testpmd_output(result), result.stdout)
            self.assertEqual(self.testpmd._last_run_output, result.stdout)
            populate.assert_called_once_with()

    def test_missing_shutdown_statistics_explains_exit_code(self) -> None:
        reasons = (
            (128 + SIGINT, "terminated by SIGINT"),
            (137, "SIGKILLed"),
            (139, "terminated by signal 11"),
            (0, "exited without printing"),
            (None, "exited without printing"),
        )
        output = "\n".join(f"line {index}" for index in range(12))
        for exit_code, reason in reasons:
            with self.subTest(exit_code=exit_code):
                with patch.object(
                    self.testpmd, "populate_performance_data"
                ) as populate:
                    with self.assertRaises(LisaException) as raised:
                        self.testpmd.process_testpmd_output(
                            self._result(output, exit_code)
                        )
                    message = str(raised.exception)
                    self.assertIn("[sender]", message)
                    self.assertIn(reason, message)
                    self.assertIn(f"exit code: {exit_code}", message)
                    self.assertIn("line 2\n", message)
                    self.assertNotIn("line 1\n", message)
                    populate.assert_not_called()

    def test_timed_entry_points_use_foreground_and_process_output(self) -> None:
        self.testpmd.node = MagicMock()
        result = self._result("TX-dropped: 0\nRX-dropped: 0\n")
        timeout = self.testpmd.node.tools.__getitem__.return_value
        timeout.run_with_timeout.return_value = result
        for run in (self.testpmd.run_for_n_seconds, self.testpmd.start_for_n_seconds):
            with self.subTest(run=run.__name__):
                timeout.reset_mock()
                with patch.object(
                    self.testpmd, "process_testpmd_output", return_value=result.stdout
                ) as process:
                    self.assertEqual(run("testpmd", 30), result.stdout)
                    timeout.run_with_timeout.assert_called_once_with(
                        "testpmd", 30, SIGINT, kill_timeout=40, foreground=True
                    )
                    process.assert_called_once_with(result)
