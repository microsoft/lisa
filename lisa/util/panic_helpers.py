# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
Kernel panic detection and categorization utilities.

This module provides common functionality for detecting, categorizing, and
reporting kernel panics across different test suites.
"""

import re
from typing import Any, List, Optional

from lisa import RemoteNode
from lisa.features import SerialConsole
from lisa.messages import TestStatus, send_sub_test_result_message
from lisa.testsuite import TestResult
from lisa.util import KernelPanicException


def check_panic(
    nodes: List[RemoteNode], test_result: Optional[TestResult] = None
) -> None:
    """
    Check for kernel panic on all nodes and raise exception with panic details.

    Sends detailed panic categorization data to sub-test results for analysis.
    The message includes structured panic information to enable filtering and
    categorization by panic type, error codes, and failure patterns.

    Args:
        nodes: List of nodes to check for kernel panics
        test_result: Optional test result object for sending sub-test results

    Raises:
        KernelPanicException: If a kernel panic is detected on any node
    """
    for node in nodes:
        try:
            node.features[SerialConsole].check_panic(saved_path=None, force_run=True)
        except KernelPanicException as panic_ex:
            # Always log the crash details
            node.log.error(f"CRASH DETECTED on node {node.name}:")
            node.log.error(f"  Error codes/phrases: {panic_ex.panics}")
            node.log.error(f"  Full error: {str(panic_ex)}")

            # Extract panic categorization for database filtering
            panic_type = categorize_panic(panic_ex.panics)
            error_codes = extract_error_codes(panic_ex.panics)

            # Create detailed crash message with categorization
            crash_message_lines = [
                "=== KERNEL PANIC DETECTED ===",
                f"Node: {node.name}",
                f"Panic Type: {panic_type}",
                f"Error Codes: {error_codes}",
                "",
                "Detected Panic Phrases:",
            ]

            # Add panic phrases (truncate if too many)
            for i, panic_phrase in enumerate(panic_ex.panics[:10]):
                crash_message_lines.append(f"  [{i+1}] {panic_phrase}")

            if len(panic_ex.panics) > 10:
                crash_message_lines.append(
                    f"  ... and {len(panic_ex.panics) - 10} more phrases"
                )

            crash_message_lines.append("")
            crash_message_lines.append("Full details available in serial console logs")

            crash_message = "\n".join(crash_message_lines)

            # Send sub-test result if test_result is provided
            if test_result:
                test_case_name = test_result.name if test_result.name else "unknown"
                # Include panic type in test case name for easy categorization
                send_sub_test_result_message(
                    test_result=test_result,
                    test_case_name=f"CRASH_{test_case_name}",
                    test_status=TestStatus.FAILED,
                    test_message=crash_message,
                )

            # Raise the panic to fail the test
            raise panic_ex


def categorize_panic(panics: List[Any]) -> str:
    """
    Categorize panic type based on detected panic phrases.

    This function analyzes panic messages and categorizes them into specific
    types for easier filtering, grouping, and analysis in test databases.

    Args:
        panics: List of panic phrases detected in serial console logs

    Returns:
        A category string representing the panic type. Possible values include:
        - HARDLOCKUP: Hard lockup detector triggered
        - SOFTLOCKUP: Soft lockup detector triggered
        - RCU_STALL: RCU stall warning
        - NULL_DEREF: Null pointer dereference
        - PAGE_FAULT: Page fault panic
        - BUG: Kernel BUG assertion
        - OOPS: Kernel oops
        - OOM: Out of memory
        - ASSERTION: Failed assertion
        - DOUBLE_FAULT: Double fault
        - GENERAL: Other/unclassified panic
    """
    panic_str = " ".join(str(p).upper() for p in panics)

    # Check for specific panic types in order of specificity
    if "HARDLOCKUP" in panic_str or "HARD LOCKUP" in panic_str:
        return "HARDLOCKUP"
    elif "SOFTLOCKUP" in panic_str or "SOFT LOCKUP" in panic_str:
        return "SOFTLOCKUP"
    elif "RCU" in panic_str and "STALL" in panic_str:
        return "RCU_STALL"
    elif "NULL POINTER" in panic_str or "NULL PTR" in panic_str:
        return "NULL_DEREF"
    elif "PAGE FAULT" in panic_str or "UNABLE TO HANDLE" in panic_str:
        return "PAGE_FAULT"
    elif "BUG:" in panic_str or "BUG AT" in panic_str:
        return "BUG"
    elif "OOPS:" in panic_str or "OOPS" in panic_str:
        return "OOPS"
    elif "OUT OF MEMORY" in panic_str or "OOM" in panic_str:
        return "OOM"
    elif "ASSERTION" in panic_str or "ASSERT" in panic_str:
        return "ASSERTION"
    elif "DOUBLE FAULT" in panic_str:
        return "DOUBLE_FAULT"
    else:
        return "GENERAL"


def extract_error_codes(panics: List[Any]) -> str:
    """
    Extract error codes from panic messages.

    Searches panic messages for common error code patterns that can help
    identify the specific cause of the panic.

    Args:
        panics: List of panic phrases detected in serial console logs

    Returns:
        Comma-separated string of extracted error codes, or "None extracted"
        if no recognizable error codes are found.

        Extracted patterns include:
        - Error codes (e.g., "error code: 0x00000004")
        - RIP addresses (instruction pointer)
        - Code bytes
        - CR2 addresses (fault address)
    """
    panic_str = " ".join(str(p) for p in panics)
    error_codes = []

    # Look for error code patterns
    error_code_patterns = [
        r"error code[:\s]+0x[0-9a-fA-F]+",
        r"RIP[:\s]+0x[0-9a-fA-F]+",
        r"Code[:\s]+[0-9a-fA-F\s]+",
        r"CR2[:\s]+0x[0-9a-fA-F]+",
    ]

    for pattern in error_code_patterns:
        matches = re.findall(pattern, panic_str, re.IGNORECASE)
        error_codes.extend(matches[:2])  # Limit to 2 matches per pattern

    if error_codes:
        return ", ".join(error_codes[:5])  # Limit to 5 total codes
    else:
        return "None extracted"
