# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import time
from typing import Any, Dict, List, Optional

from lisa import schema
from lisa.runner import BaseRunner
from lisa.testsuite import TestResult
from lisa.util import constants
from lisa.util.parallel import Task


def _mock_task() -> List[TestResult]:
    time.sleep(5)
    return []


class MockRunner(BaseRunner):
    _is_done = False

    def __init__(
        self, runbook: schema.Runbook, index: int, case_variables: Dict[str, Any]
    ) -> None:
        self._is_done = False
        super().__init__(runbook, index, case_variables)

    @classmethod
    def type_name(cls) -> str:
        return constants.TESTCASE_TYPE_MOCK

    def fetch_task(self) -> Optional[Task[List[TestResult]]]:
        self._is_done = True
        return Task(self.get_unique_task_id(), _mock_task, self._log)

    @property
    def is_done(self) -> bool:
        return self._is_done
