from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lisa.core.testFactory import TestCaseData

TestStatus = Enum("TestStatus", ["NOTRUN", "RUNNING", "FAILED", "PASSED", "SKIPPED"])


@dataclass
class TestResult:
    case: TestCaseData
    status: TestStatus = TestStatus.NOTRUN
    elapsed: float = 0
    errorMessage: str = ""
