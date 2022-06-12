# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from pathlib import Path
from typing import Any, List, Optional, Pattern

from lisa.feature import Feature
from lisa.util import (
    LisaException,
    find_patterns_in_lines,
    get_datetime_path,
    get_matched_str,
)

FEATURE_NAME_SERIAL_CONSOLE = "SerialConsole"
NAME_SERIAL_CONSOLE_LOG = "serial_console.log"


class SerialConsole(Feature):
    panic_patterns: List[Pattern[str]] = [
        re.compile(r"^(.*Kernel panic - not syncing:.*)$", re.MULTILINE),
        re.compile(r"^(.*RIP:.*)$", re.MULTILINE),
        re.compile(r"^(.*grub>.*)$", re.MULTILINE),
        re.compile(r"^The operating system has halted.$", re.MULTILINE),
    ]

    # ignore some return lines, which shouldn't be a panic line.
    panic_ignorable_patterns: List[Pattern[str]] = [
        re.compile(
            r"^(.*ipt_CLUSTERIP: ClusterIP.*loaded successfully.*)$", re.MULTILINE
        ),
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
        # prevent the log is not ready, invalidata it for next capture.
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
        self, saved_path: Optional[Path], stage: str = "", force_run: bool = False
    ) -> None:
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
            raise LisaException(f"{stage} found panic in serial log: {panics}")

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
