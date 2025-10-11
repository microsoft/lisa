# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Helpers for detecting and classifying kernel panics."""

from __future__ import annotations

import re
from typing import Iterable, List, Optional

from lisa import RemoteNode
from lisa.features import SerialConsole
from lisa.messages import TestStatus, send_sub_test_result_message
from lisa.testsuite import TestResult
from lisa.util import KernelPanicException

_ERROR_CODE_PATTERNS: List[str] = [
    r"error code[:\s]+0x[0-9a-fA-F]+",
    r"RIP[:\s]+0x[0-9a-fA-F]+",
    r"Code[:\s]+[0-9a-fA-F\s]+",
    r"CR2[:\s]+0x[0-9a-fA-F]+",
]


def check_panic(
    nodes: Iterable[RemoteNode], test_result: Optional[TestResult] = None
) -> None:
    """Check each node for panics and raise with categorized context."""
    for node in nodes:
        try:
            node.features[SerialConsole].check_panic(saved_path=None, force_run=True)
        except KernelPanicException as panic_ex:
            panic_type = categorize_panic(panic_ex.panics)
            error_codes = extract_error_codes(panic_ex.panics)

            _log_crash_details(node, panic_ex, panic_type, error_codes)

            if test_result:
                _emit_sub_test_result(test_result, panic_type, error_codes, node.name)

            raise panic_ex


def categorize_panic(panics: Iterable[object]) -> str:
    """Return a coarse panic classification based on panic text."""
    panic_str = " ".join(str(p).upper() for p in panics)

    if "HARDLOCKUP" in panic_str or "HARD LOCKUP" in panic_str:
        return "HARDLOCKUP"
    if "SOFTLOCKUP" in panic_str or "SOFT LOCKUP" in panic_str:
        return "SOFTLOCKUP"
    if "RCU" in panic_str and "STALL" in panic_str:
        return "RCU_STALL"
    if "NULL POINTER" in panic_str or "NULL PTR" in panic_str:
        return "NULL_DEREF"
    if "PAGE FAULT" in panic_str or "UNABLE TO HANDLE" in panic_str:
        return "PAGE_FAULT"
    if "BUG:" in panic_str or "BUG AT" in panic_str:
        return "BUG"
    if "OOPS:" in panic_str or "OOPS" in panic_str:
        return "OOPS"
    if "OUT OF MEMORY" in panic_str or "OOM" in panic_str:
        return "OOM"
    if "ASSERTION" in panic_str or "ASSERT" in panic_str:
        return "ASSERTION"
    if "DOUBLE FAULT" in panic_str:
        return "DOUBLE_FAULT"
    return "GENERAL"


def extract_error_codes(panics: Iterable[object]) -> str:
    """Return interesting error snippets extracted from panic text."""
    panic_str = " ".join(str(p) for p in panics)
    found: List[str] = []

    for pattern in _ERROR_CODE_PATTERNS:
        matches = re.findall(pattern, panic_str, re.IGNORECASE)
        found.extend(matches[:2])

    if not found:
        return "None extracted"

    seen = set()
    ordered_unique: List[str] = []
    for item in found:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            ordered_unique.append(item)
            if len(ordered_unique) == 5:
                break

    return ", ".join(ordered_unique)


def _log_crash_details(
    node: RemoteNode,
    panic_ex: KernelPanicException,
    panic_type: str,
    error_codes: str,
) -> None:
    """Log a condensed crash report for quick postmortem triage."""
    node.log.error("=== KERNEL PANIC DETECTED ===")
    node.log.error(f"Node: {node.name}")
    node.log.error(f"Panic Type: {panic_type}")
    node.log.error(f"Error Codes: {error_codes}")
    node.log.error("Detected Panic Phrases:")

    for index, panic_phrase in enumerate(panic_ex.panics[:10], start=1):
        node.log.error(f"  [{index}] {panic_phrase}")

    if len(panic_ex.panics) > 10:
        node.log.error(
            "  ... and %d more phrases",
            len(panic_ex.panics) - 10,
        )


def _emit_sub_test_result(
    test_result: TestResult,
    panic_type: str,
    error_codes: str,
    node_name: str,
) -> None:
    """Send a structured sub-test failure with panic metadata."""
    crash_message_lines = [
        "=== KERNEL PANIC DETECTED ===",
        f"Node: {node_name}",
        f"Panic Type: {panic_type}",
        f"Error Codes: {error_codes}",
        "",
        "Full details available in serial console logs.",
    ]

    crash_message = "\n".join(crash_message_lines)
    test_case_name = test_result.name if test_result.name else "unknown"

    send_sub_test_result_message(
        test_result=test_result,
        test_case_name=f"CRASH_{test_case_name}",
        test_status=TestStatus.FAILED,
        test_message=crash_message,
    )
