import re
from typing import Any

from lisa.executable import Tool
from lisa.util import find_patterns_in_lines


class Waagent(Tool):
    __version_pattern = re.compile(r"(?<=\-)([^\s]+)")

    @property
    def command(self) -> str:
        return self._command

    def _check_exists(self) -> bool:
        return True

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._command = "waagent"

    def get_version(self) -> str:
        result = self.run("-version")
        found_version = find_patterns_in_lines(result.stdout, [self.__version_pattern])
        return found_version[0][0] if found_version[0] else ""
