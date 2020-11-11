import re
from pathlib import Path
from typing import Any, List, Optional, Pattern

from lisa.feature import Feature
from lisa.util import LisaException, find_patterns_in_lines, get_datetime_path

FEATURE_NAME_SERIAL_CONSOLE = "SerialConsole"


class SerialConsole(Feature):
    panic_patterns: List[Pattern[str]] = [
        re.compile(r"^(.*Kernel panic - not syncing:.*)$", re.MULTILINE),
        re.compile(r"^(.*RIP:.*)$", re.MULTILINE),
        re.compile(r"^(.*grub>.*)$", re.MULTILINE),
    ]

    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_SERIAL_CONSOLE

    @classmethod
    def enabled(cls) -> bool:
        # most platform support shutdown
        return True

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

    def get_console_log(
        self, saved_path: Optional[Path], force_run: bool = False
    ) -> str:
        self._node.log.debug("downloading serial log...")
        if saved_path:
            saved_path = saved_path.joinpath(get_datetime_path())
            saved_path.mkdir()
        if self._cached_console_log is None or force_run:
            self._cached_console_log = self._get_console_log(saved_path=saved_path)
        if saved_path:
            log_file_name = saved_path.joinpath("serial_console.log")
            with open(log_file_name, mode="wb") as f:
                f.write(self._cached_console_log)
        return self._cached_console_log.decode("utf-8", errors="ignore")

    def check_panic(self, saved_path: Optional[Path], force_run: bool = False) -> None:
        self._node.log.debug("checking panic in serial log...")
        content: str = self.get_console_log(saved_path=saved_path, force_run=force_run)
        result = find_patterns_in_lines(content, self.panic_patterns)
        errors = [x for x in result if x]
        if errors:
            raise LisaException(f"found panic in serial log: {errors}")
