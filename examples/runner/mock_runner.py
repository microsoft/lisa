# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from dataclasses_json import dataclass_json
from marshmallow import validate

from lisa import schema
from lisa.parameter_parser.runbook import RunbookBuilder
from lisa.runner import BaseRunner
from lisa.schema import BaseTestCaseFilter
from lisa.util import field_metadata
from lisa.util.parallel import Task

TYPE_MOCK = "mock"


def _mock_task() -> None:
    time.sleep(5)


@dataclass_json()
@dataclass
class MockTestCase(BaseTestCaseFilter):
    type: str = field(
        default=TYPE_MOCK,
        metadata=field_metadata(
            required=True,
            validate=validate.OneOf([TYPE_MOCK]),
        ),
    )

    @classmethod
    def type_name(cls) -> str:
        return TYPE_MOCK


class MockRunner(BaseRunner):
    _is_done = False

    def __init__(
        self,
        runbook_builder: RunbookBuilder,
        runbook: schema.Runbook,
        index: int,
        case_variables: Dict[str, Any],
    ) -> None:
        self._is_done = False
        super().__init__(runbook_builder, runbook, index, case_variables)

    @classmethod
    def type_name(cls) -> str:
        return TYPE_MOCK

    def fetch_task(self) -> Optional[Task[None]]:
        self._is_done = True
        return Task(self.generate_task_id(), _mock_task, self._log)

    @property
    def is_done(self) -> bool:
        return self._is_done
