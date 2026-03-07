# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Pattern, Type, cast

from dataclasses_json import dataclass_json

from lisa import messages, notifier, schema
from lisa.messages import TestResultMessage, TestStatus
from lisa.util import constants

oops_regex_patterns: List[Pattern[str]] = [
    re.compile(r"Oops: [0-9]+ \[\#.*\]"),  # Basic Oops Detection
    re.compile(
        r"BUG: unable to handle kernel NULL pointer dereference at (0x)?[0-9a-fA-F]+"
    ),  # Null Pointer Dereference
    re.compile(
        r"BUG: unable to handle kernel paging request at (0x)?[0-9a-fA-F]+"
    ),  # Invalid Memory Access
    re.compile(
        r"RIP: [0-9a-fA-F]+:([a-zA-Z0-9_]+)\+[0-9a-fA-Fx]+/[0-9a-fA-Fx]+"
    ),  # RIP in Trace
    re.compile(r"Call Trace:\s*(.*)"),  # Kernel Call Trace
    re.compile(r"general protection fault: [0-9]+ \[#.*\]"),  # General Fault Errors
    re.compile(r"Kernel panic - not syncing: (.*)"),  # Kernel Panic Information
    re.compile(r"Process: ([a-zA-Z0-9_]+)\s*\(pid:\s*\d+\)"),  # Process Details
    re.compile(r"Stack:\s*(.*)"),  # Stack Dump
    re.compile(r"Code:\s*(.*)"),  # Code Dump
]


@dataclass_json
@dataclass
class DmsgOopsSchema(schema.Notifier):
    log_level: str = logging.getLevelName(logging.DEBUG)
    output_file: str = "dmesg_errors.json"


class DmsgOops(notifier.Notifier):
    """
    A sample notifier to check for Panics/OOPs Errors in the DMesg Logs.
    """

    dmesg_errors: Dict[str, Dict[str, List[List[str]]]]

    @classmethod
    def type_name(cls) -> str:
        return "dmsg_oops_notifier"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return DmsgOopsSchema

    def save_results(self) -> None:
        file_path = Path(self.runbook.output_file)
        if not file_path.is_absolute():
            file_path = constants.RUN_LOCAL_LOG_PATH / file_path
        self._log.info(f"Writing output to file {file_path}")
        with open(file_path, "w") as f:
            f.write(str(self.dmesg_errors))

    def check_kernel_oops(self, dmesg_logs: str, context_lines: int = 4) -> List[str]:
        oops_list = []
        lines = dmesg_logs.splitlines()
        for i, line in enumerate(lines):
            for pattern in oops_regex_patterns:
                if pattern.search(line):
                    start = max(i - context_lines, 0)
                    end = min(i + context_lines + 1, len(lines))
                    context = lines[start:end]
                    oops_list.append("\n".join(context))
                    break
        return oops_list

    def dmesg_error_check(self, test_name: str, dmesg_logs: str) -> None:
        oops_list = self.check_kernel_oops(dmesg_logs)
        self.dmesg_errors["oops"].setdefault(test_name, []).append(oops_list)
        self._log.info("DMesg logs check completed")

    def process_serial_logs(
        self, test_name: str, file_path: Path, pattern_start: str, pattern_end: str
    ) -> None:
        with open(file_path, "r") as file:
            buffer = file.read()
        while True:
            start_index = buffer.find(pattern_start)
            end_index = buffer.find(pattern_end, start_index + len(pattern_start))
            if start_index == -1 or end_index == -1:
                break
            data_segment = buffer[start_index + len(pattern_start) : end_index]
            self.dmesg_error_check(test_name, data_segment)
            buffer = buffer[end_index + len(pattern_end) :]

    def process_test_result_message(self, message: TestResultMessage) -> None:
        if message.log_file and message.status in [
            TestStatus.PASSED,
            TestStatus.FAILED,
            TestStatus.SKIPPED,
            TestStatus.ATTEMPTED,
        ]:
            local_file_path = constants.RUN_LOCAL_LOG_PATH / message.log_file
            local_absolute_file_path = local_file_path.absolute()
            try:
                self.process_serial_logs(
                    message.name,
                    local_absolute_file_path,
                    "cmd: ['sudo', 'dmesg']",
                    "execution time:",
                )
            except Exception as e:
                self._log.error(f"Error while Processing Serial Console Logs : {e}")

            self.save_results()

    def _received_message(self, message: messages.MessageBase) -> None:
        if isinstance(message, TestResultMessage):
            self.process_test_result_message(message=message)

    def _subscribed_message_type(self) -> List[Type[messages.MessageBase]]:
        return [TestResultMessage]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        runbook = cast(DmsgOopsSchema, self.runbook)
        self._log_level = runbook.log_level
        self.dmesg_errors = {"oops": {}}

    def __init__(self, runbook: DmsgOopsSchema) -> None:
        notifier.Notifier.__init__(self, runbook)
