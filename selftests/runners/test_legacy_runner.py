# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass
from typing import Dict, List
from unittest import TestCase

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.messages import TestStatus
from lisa.runners import legacy_runner
from lisa.util import LisaException
from lisa.util.logger import get_logger


@dataclass_json()
@dataclass
class LegacyTestNotifier(schema.TypedSchema):
    ...


log = get_logger("test_legacy")


class ResultStateManagerTestCase(TestCase):
    def test_sequence_running(self) -> None:
        states = legacy_runner.ResultStateManager("legacy", log)
        self._set_check_state(
            states,
            4,
            0,
            0,
            [
                TestStatus.QUEUED,
                TestStatus.QUEUED,
                TestStatus.QUEUED,
                TestStatus.QUEUED,
            ],
        )
        self._set_check_state(
            states,
            4,
            1,
            0,
            [
                TestStatus.RUNNING,
                TestStatus.QUEUED,
                TestStatus.QUEUED,
                TestStatus.QUEUED,
            ],
        )
        self._set_check_state(
            states,
            4,
            1,
            1,
            [
                TestStatus.PASSED,
                TestStatus.QUEUED,
                TestStatus.QUEUED,
                TestStatus.QUEUED,
            ],
        )
        self._set_check_state(
            states,
            4,
            2,
            1,
            [
                TestStatus.PASSED,
                TestStatus.RUNNING,
                TestStatus.QUEUED,
                TestStatus.QUEUED,
            ],
        )
        self._set_check_state(
            states,
            4,
            2,
            2,
            [
                TestStatus.PASSED,
                TestStatus.PASSED,
                TestStatus.QUEUED,
                TestStatus.QUEUED,
            ],
        )
        self._set_check_state(
            states,
            4,
            3,
            2,
            [
                TestStatus.PASSED,
                TestStatus.PASSED,
                TestStatus.RUNNING,
                TestStatus.QUEUED,
            ],
        )
        self._set_check_state(
            states,
            4,
            4,
            3,
            [
                TestStatus.PASSED,
                TestStatus.PASSED,
                TestStatus.PASSED,
                TestStatus.RUNNING,
            ],
        )
        self._set_check_state(
            states,
            4,
            4,
            4,
            [
                TestStatus.PASSED,
                TestStatus.PASSED,
                TestStatus.PASSED,
                TestStatus.PASSED,
            ],
        )

    def _set_check_state(
        self,
        state: legacy_runner.ResultStateManager,
        all_count: int,
        running_count: int,
        completed_count: int,
        expected_statuses: List[TestStatus],
    ) -> None:
        all = self._create_information(all_count, TestStatus.QUEUED)
        running = self._create_information(running_count, TestStatus.RUNNING)
        completed = self._create_information(completed_count, TestStatus.PASSED)
        state.set_states(all, running, completed)
        self.assertListEqual([x.status for x in state._results], expected_statuses)

    def _create_information(
        self, count: int, status: TestStatus
    ) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        for i in range(count):
            result = {"name": f"name{i}"}
            results.append(result)
            if status == TestStatus.QUEUED:
                continue
            result["image"] = f"image{i}"
            result["location"] = f"location{i}"
            if status == TestStatus.RUNNING:
                result["status"] = "RUNNING"
            elif status == TestStatus.PASSED:
                result["status"] = "PASS"
            elif status == TestStatus.FAILED:
                result["status"] = "FAIL"
            elif status == TestStatus.SKIPPED:
                result["status"] = "SKIP"
            else:
                raise LisaException(f"unknown status {status}")
        return results
