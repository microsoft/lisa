import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Pattern

from lisa.messages import TestResultMessage, TestStatus
from lisa.util import get_matched_str
from lisa.util.logger import get_logger


@dataclass
class Failure:
    id: int = 0
    pattern: Dict[str, Pattern[str]] = field(default_factory=dict)
    action: Dict[str, str] = field(default_factory=dict)
    case_id: int = -1
    priority: int = 100
    updated_date: Optional[datetime] = None

    # fields for information
    category: str = ""
    reason: str = ""
    description: str = ""
    bug_url: str = ""


@dataclass
class FieldDescriber:
    name: str
    setter: Callable[[str], Any]


class Triage:
    # name in action field, which will be apply to fields in TestResultMessage
    _action_field_map: Dict[str, FieldDescriber] = {
        "status": FieldDescriber(name="status", setter=TestStatus.__getitem__),
        "Status": FieldDescriber(name="status", setter=TestStatus.__getitem__),
    }

    def __init__(
        self,
        test_project_name: str,
        test_pass_name: str,
        failures: List[Dict[str, Any]],
    ) -> None:
        self._log = get_logger("triage")

        self._failures = self._load_failures(failures)
        self._test_project_name = test_project_name
        self._test_pass_name = test_pass_name

    def match_test_failure(
        self,
        result_message: TestResultMessage,
        case_id: int = 0,
    ) -> Optional[Failure]:
        # When the argument case_id equals 0, it means the test case id is
        # unknown, so only apply default rules.
        failures = [x for x in self._failures if x.case_id == case_id or x.case_id == 0]
        matched_failure = None
        for failure in failures:
            failure_patterns = failure.pattern
            is_matched = True
            for name, pattern in failure_patterns.items():
                if name == "message":
                    value = result_message.message
                elif name == "test_project":
                    value = self._test_project_name
                elif name == "test_pass":
                    value = self._test_pass_name
                elif name == "status":
                    value = result_message.status.name
                else:
                    value = result_message.information.get(name, "")

                if value:
                    result = get_matched_str(value, pattern)
                else:
                    result = ""

                if not result:
                    is_matched = False
                    break
            if is_matched:
                matched_failure = failure
                # mark for updating date, if the notifier supports it.
                failure.updated_date = datetime.utcnow()

                # take action
                self._apply_action(failure, result_message)
                break
        return matched_failure

    def get_failures(self) -> List[Failure]:
        return self._failures

    def _apply_action(
        self, failure: Failure, result_message: TestResultMessage
    ) -> None:
        action = failure.action
        for name, value in action.items():
            if name in self._action_field_map:
                describer = self._action_field_map[name]
                setattr(result_message, describer.name, describer.setter(value))
            else:
                self._log.error(f"unknown action name: {name}")

    def _load_failures(self, raw_failures: List[Dict[str, Any]]) -> List[Failure]:
        results: List[Failure] = []

        for raw_failure in raw_failures:
            failure = Failure(
                id=raw_failure["id"],
                case_id=raw_failure["case_id"],
                priority=raw_failure["priority"],
                category=raw_failure["category"],
                reason=raw_failure["reason"],
                description=raw_failure["description"],
                bug_url=raw_failure["bug_url"],
            )
            action = raw_failure.get("action", None)
            if action:
                failure.action = json.loads(action)

            patterns: Dict[str, Pattern[str]] = dict()
            raw_pattern = str(raw_failure.get("pattern"))
            try:
                # new format of message is json type
                loaded_patterns = json.loads(raw_pattern)
                for name, value in loaded_patterns.items():
                    patterns[name] = re.compile(value.replace("(?i)", ""), re.I)
            except ValueError as e:
                # to compatible previous string type of message
                self._log.debug(
                    f"error on parsing pattern {failure.id}, "
                    f"use as a whole message pattern. "
                    f"error: '{e}', pattern: {raw_pattern}"
                )
                patterns = {
                    "message": re.compile(raw_pattern.replace("(?i)", ""), re.I)
                }
            failure.pattern = patterns
            results.append(failure)

        results = sorted(results, key=lambda x: x.priority)

        return results
