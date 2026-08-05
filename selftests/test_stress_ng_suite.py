# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, cast
from unittest import TestCase
from unittest.mock import MagicMock

from lisa.microsoft.testsuites.stress.stress_ng_suite import StressNgTestSuite
from lisa.util import SkippedException


class StressNgSuiteTestCase(TestCase):
    _suite_type = cast(Any, StressNgTestSuite).__wrapped__

    def setUp(self) -> None:
        self.suite = self._suite_type.__new__(self._suite_type)

    def test_normalize_job_files_filters_blank_entries(self) -> None:
        result = self.suite._normalize_job_files("one.job, , two.job ,,")

        self.assertEqual(["one.job", "two.job"], result)

    def test_stress_ng_jobfile_skips_when_missing(self) -> None:
        with self.assertRaises(SkippedException):
            self.suite.stress_ng_jobfile(
                MagicMock(),
                {},
                MagicMock(),
                MagicMock(),
            )

    def test_multi_vm_stress_test_skips_when_only_blank_entries(self) -> None:
        with self.assertRaises(SkippedException):
            self.suite.multi_vm_stress_test(
                MagicMock(),
                {"stress_ng_jobs": " , "},
                MagicMock(),
                MagicMock(),
            )

    def test_multi_vm_stress_test_runs_each_valid_job_file(self) -> None:
        run_job = MagicMock()
        self.suite._run_stress_ng_job = run_job
        environment = MagicMock()
        log = MagicMock()
        result = MagicMock()

        self.suite.multi_vm_stress_test(
            log,
            {"stress_ng_jobs": "one.job, ,two.job"},
            environment,
            result,
        )

        self.assertEqual(
            [
                ("one.job", environment, result, log),
                ("two.job", environment, result, log),
            ],
            [call.args for call in run_job.call_args_list],
        )
