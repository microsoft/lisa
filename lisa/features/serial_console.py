# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional, Pattern

from lisa.feature import Feature
from lisa.util import (
    KernelPanicException,
    LisaException,
    find_patterns_in_lines,
    get_datetime_path,
    get_matched_str,
)

if TYPE_CHECKING:
    from lisa.testsuite import TestResult

FEATURE_NAME_SERIAL_CONSOLE = "SerialConsole"
NAME_SERIAL_CONSOLE_LOG = "serial_console.log"


@dataclass
class PanicInfo:
    """Structured information about a detected kernel panic."""

    panic_type: str  # e.g., "HARDLOCKUP", "SOFTLOCKUP", "NULL_DEREF", "GENERAL"
    error_codes: str  # Extracted error codes (RIP, CR2, etc.)
    panic_phrases: List[str]  # Raw panic phrases from console
    console_log_path: Optional[str]  # Relative path to serial_console.log for reference


class SerialConsole(Feature):
    panic_patterns: List[Pattern[str]] = [
        re.compile(r"^(.*Kernel panic - not syncing:.*)$", re.MULTILINE),
        re.compile(r"^(.*RIP:.*)$", re.MULTILINE),
        re.compile(r"^(.*grub>.*)$", re.MULTILINE),
        re.compile(r"^The operating system has halted.$", re.MULTILINE),
        # Synchronous Exception at 0x000000003FD04000
        re.compile(r"^(.*Synchronous Exception at.*)$", re.MULTILINE),
        # Lockup patterns
        re.compile(r"^(.*soft lockup.*)$", re.MULTILINE | re.IGNORECASE),
        re.compile(r"^(.*hard lockup.*)$", re.MULTILINE | re.IGNORECASE),
        # BUG and kernel errors
        re.compile(r"^(.*BUG:.*)$", re.MULTILINE),
        re.compile(r"^(.*kernel NULL pointer.*)$", re.MULTILINE | re.IGNORECASE),
        re.compile(r"^(.*unable to handle.*)$", re.MULTILINE | re.IGNORECASE),
        # Hung tasks and watchdog
        re.compile(r"^(.*hung task.*)$", re.MULTILINE | re.IGNORECASE),
        # RCU stalls
        re.compile(r"^(.*rcu_sched.*)$", re.MULTILINE | re.IGNORECASE),
    ]

    # ignore some return lines, which shouldn't be a panic line.
    panic_ignorable_patterns: List[Pattern[str]] = [
        re.compile(
            r"^(.*ipt_CLUSTERIP: ClusterIP.*loaded successfully.*)$", re.MULTILINE
        ),
        # This is a known issue with Hyper-V when running on AMD processors.
        # The problem occurs in VM sizes that have 16 or more vCPUs which means 2 or
        # more NUMA nodes on AMD processors.
        # The call trace is annoying but does not affect correct operation of the VM.
        re.compile(r"(.*RIP: 0010:topology_sane.isra.*)$", re.MULTILINE),
        re.compile(
            r"(.*WARNING:.*topology_sane.isra.*)$", re.MULTILINE
        ),
    ]

    # Patterns for extracting error codes from panic messages
    # Examples:
    #   "error code: 0x00000000"
    #   "RIP: 0010:[<ffffffff81234567>]"
    #   "Code: 0f 1f 44 00 00 48 89 f8 48 89 f7 48 89 d6"
    #   "CR2: 0000000000000008"
    error_code_patterns: List[Pattern[str]] = [
        re.compile(r"error code[:\s]+0x[0-9a-fA-F]+", re.IGNORECASE),
        re.compile(r"RIP[:\s]+0x[0-9a-fA-F]+", re.IGNORECASE),
        re.compile(r"Code[:\s]+[0-9a-fA-F\s]+", re.IGNORECASE),
        re.compile(r"CR2[:\s]+0x[0-9a-fA-F]+", re.IGNORECASE),
    ]

    # blk_update_request: I/O error, dev sdc, sector 0
    # ata1.00: exception Emask 0x0 SAct 0x0 SErr 0x0 action 0x0
    # Failure: File system check of the root filesystem failed
    # We can use these patterns to show more information in result's 'Message'
    filesystem_exception_patterns: List[Pattern[str]] = [
        re.compile(r"^(.*blk_update_request: I/O error.*)$", re.MULTILINE),
        re.compile(r"^(.*exception.*)$", re.MULTILINE),
        re.compile(
            r"^(.*Failure: File system check of the root filesystem failed.*)$",
            re.MULTILINE,
        ),
    ]

    # (initramfs)
    initramfs_patterns: List[Pattern[str]] = [
        re.compile(r"^(.*\(initramfs\))", re.MULTILINE),
    ]

    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_SERIAL_CONSOLE

    @classmethod
    def can_disable(cls) -> bool:
        # no reason to disable it, it can not be used
        return False

    def _normalize_category(self, panic_phrases: List[str]) -> str:
        """Categorize panic based on panic text patterns."""
        panic_str = " ".join(str(p).upper() for p in panic_phrases)

        # Map panic patterns to categories (order matters - most specific first)
        panic_patterns = [
            (("HARDLOCKUP", "HARD LOCKUP"), "HARDLOCKUP"),
            (("SOFTLOCKUP", "SOFT LOCKUP"), "SOFTLOCKUP"),
            (("RCU", "STALL"), "RCU_STALL"),  # Both must be present
            (("NULL POINTER", "NULL PTR"), "NULL_DEREF"),
            (("PAGE FAULT", "UNABLE TO HANDLE"), "PAGE_FAULT"),
            (("BUG:", "BUG AT"), "BUG"),
            (("OOPS:", "OOPS"), "OOPS"),
            (("OUT OF MEMORY", "OOM"), "OOM"),
            (("ASSERTION", "ASSERT"), "ASSERTION"),
            (("DOUBLE FAULT",), "DOUBLE_FAULT"),
        ]

        for patterns, category in panic_patterns:
            if category == "RCU_STALL":
                # Special case: both RCU and STALL must be present
                if all(p in panic_str for p in patterns):
                    return category
            elif any(p in panic_str for p in patterns):
                return category

        return "GENERAL"

    def _extract_error_codes(self, panic_phrases: List[str]) -> str:
        """Extract error codes and important values from panic text."""
        panic_str = " ".join(str(p) for p in panic_phrases)
        found: List[str] = []

        # Limit to first 2 matches per pattern to avoid log spam
        # while capturing key diagnostic info (e.g., RIP and CR2)
        for pattern in self.error_code_patterns:
            matches = pattern.findall(panic_str)
            found.extend(matches[:2])

        if not found:
            return "None extracted"

        # Remove duplicates while preserving order
        seen = set()
        ordered_unique: List[str] = []
        for item in found:
            key = item.lower()
            if key not in seen:
                seen.add(key)
                ordered_unique.append(item)
                # Limit to 5 total codes for readability in test results
                # Typically includes: error code, RIP, Code snippet, CR2, etc.
                if len(ordered_unique) == 5:
                    break

        return ", ".join(ordered_unique)

    def _get_console_log(self, saved_path: Optional[Path]) -> bytes:
        """
        there may be another logs like screenshot can be saved, so pass path into
        """
        raise NotImplementedError()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._cached_console_log: Optional[bytes] = None

    def enabled(self) -> bool:
        # most platform support shutdown
        return True

    def invalidate_cache(self) -> None:
        # sometime, if the serial log accessed too early, it may be empty.
        # invalidate it for next run.
        self._node.log.debug(
            f"invalidate serial log cache, current size: "
            f"{len(self._cached_console_log) if self._cached_console_log else None}"
        )
        self._cached_console_log = None

    def get_matched_str(self, pattern: Pattern[str]) -> str:
        # first_match is False, since serial log may log multiple reboots. take
        # latest result.
        result = get_matched_str(
            self.get_console_log(),
            pattern,
            first_match=False,
        )
        # prevent the log is not ready, invalidate it for next capture.
        if not result:
            self._node.log.debug(
                "no matched content in serial log, invalidate the cache."
            )
            self.invalidate_cache()
        else:
            self._node.log.debug(f"captured in serial log: {result}")

        return result

    def get_console_log(
        self, saved_path: Optional[Path] = None, force_run: bool = False
    ) -> str:
        if saved_path:
            saved_path = saved_path.joinpath(get_datetime_path())
            saved_path.mkdir()

        if self._cached_console_log is None or force_run:
            self._node.log.debug("downloading serial log...")
            log_path = self._node.local_log_path / get_datetime_path()
            log_path.mkdir(parents=True, exist_ok=True)

            self._cached_console_log = self._get_console_log(saved_path=log_path)
            self._node.log.debug(
                f"downloaded serial log size: {len(self._cached_console_log)}"
            )
            # anyway save to node log_path for each time it's real queried
            log_file_name = log_path / NAME_SERIAL_CONSOLE_LOG
            with open(log_file_name, mode="wb") as f:
                f.write(self._cached_console_log)
        else:
            self._node.log.debug("load cached serial log")

        if saved_path:
            # save it again, if it's asked to save.
            log_file_name = saved_path / NAME_SERIAL_CONSOLE_LOG
            with open(log_file_name, mode="wb") as f:
                f.write(self._cached_console_log)

        return self._cached_console_log.decode("utf-8", errors="ignore")

    def check_panic(
        self,
        saved_path: Optional[Path] = None,
        stage: str = "",
        force_run: bool = False,
        test_result: Optional["TestResult"] = None,
    ) -> Optional[PanicInfo]:
        """
        Check for kernel panic in serial console log.

        Args:
            saved_path: Path to save console log
            force_run: Force re-fetch console log
            test_result: TestResult to attach panic info and auto-raise exception

        Returns:
            PanicInfo if panic detected with categorization and error codes,
            None if no panic detected.

        Raises:
            KernelPanicException if panic detected and stage or test_result provided.
        """
        self._node.log.debug("checking panic in serial log...")

        content: str = self.get_console_log(saved_path=saved_path, force_run=force_run)

        ignored_candidates = [
            x
            for sublist in find_patterns_in_lines(
                content, self.panic_ignorable_patterns
            )
            for x in sublist
            if x
        ]
        panics = [
            x
            for sublist in find_patterns_in_lines(content, self.panic_patterns)
            for x in sublist
            if x and x not in ignored_candidates
        ]

        if panics:
            # Categorize and extract error codes
            panic_type = self._normalize_category(panics)
            error_codes = self._extract_error_codes(panics)

            panic_info = PanicInfo(
                panic_type=panic_type,
                error_codes=error_codes,
                panic_phrases=panics,
                console_log_path=None,
            )

            # Auto-handle panic: log details, attach to test result, and raise
            if test_result is not None:
                self.log_panic_details(panic_info)
                self.attach_panic_to_test_result(test_result, panic_info)
                # Pass empty list to avoid duplicate
                # "Detected Panic phrases:" in exception message
                raise KernelPanicException("", [])

            # For backward compatibility: raise exception if stage is provided
            if stage:
                raise KernelPanicException(stage, panics)

            return panic_info

        return None

    def log_panic_details(self, panic_info: PanicInfo) -> None:
        """Log a condensed crash report for quick postmortem triage."""
        self._node.log.error("=== KERNEL PANIC DETECTED ===")
        self._node.log.error(f"Node: {self._node.name}")
        self._node.log.error(f"Panic Type: {panic_info.panic_type}")
        self._node.log.error(f"Error Codes: {panic_info.error_codes}")

        if panic_info.console_log_path:
            self._node.log.error(f"Console Log: {panic_info.console_log_path}")

        self._node.log.error("Detected Panic Phrases:")

        for index, panic_phrase in enumerate(panic_info.panic_phrases[:10], start=1):
            self._node.log.error(f"  [{index}] {panic_phrase}")

        if len(panic_info.panic_phrases) > 10:
            self._node.log.error(
                "  ... and %d more phrases",
                len(panic_info.panic_phrases) - 10,
            )

    def attach_panic_to_test_result(
        self, test_result: "TestResult", panic_info: PanicInfo
    ) -> None:
        """
        Attach panic information directly to test result message.

        Summary including panic type, error codes, and stack traces
        is appended to the test message for easy visibility.
        """
        panic_summary = (
            f"KERNEL PANIC DETECTED on {self._node.name}\n"
            f"Panic Type: {panic_info.panic_type}\n"
            f"Error Codes: {panic_info.error_codes}\n"
        )

        # Append panic summary to test message
        if test_result.message:
            test_result.message += f"\n\n{panic_summary}"
        else:
            test_result.message = panic_summary

    def check_initramfs(
        self, saved_path: Optional[Path], stage: str = "", force_run: bool = False
    ) -> None:
        self._node.log.debug("checking initramfs in serial log...")
        content: str = self.get_console_log(saved_path=saved_path, force_run=force_run)

        filesystem_exception_logs = [
            x
            for sublist in find_patterns_in_lines(
                content, self.filesystem_exception_patterns
            )
            for x in sublist
            if x
        ]

        initramfs_logs = [
            x
            for sublist in find_patterns_in_lines(content, self.initramfs_patterns)
            for x in sublist
            if x
        ]

        if initramfs_logs:
            raise LisaException(
                f"{stage} found initramfs in serial log: "
                f"{initramfs_logs} {filesystem_exception_logs}"
            )

    def read(self) -> str:
        raise NotImplementedError

    def write(self, data: str) -> None:
        raise NotImplementedError

    def close(self) -> None:
        # it's not required to implement close method.
        pass
