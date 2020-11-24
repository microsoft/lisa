import re
from typing import Any, Dict

from lisa.executable import Tool
from lisa.util import find_patterns_in_lines
from lisa.util.process import ExecutableResult


class Modinfo(Tool):
    __version_pattern = re.compile(r"^version:[ \t]*([^ \n]*)")

    @property
    def command(self) -> str:
        return self._command

    def _check_exists(self) -> bool:
        return True

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._command = "modinfo"
        self._cached_result: Dict[str, ExecutableResult] = {}

    def get_info(
        self,
        mod_name: str,
        force_run: bool = False,
        no_info_log: bool = True,
        no_error_log: bool = True,
    ) -> str:
        cached_result = self._cached_result.get(mod_name)
        if cached_result is None or force_run:
            cached_result = self.run(
                mod_name, no_info_log=no_info_log, no_error_log=no_error_log
            )
            if cached_result.exit_code != 0:
                # CentOS may not include the path when started,
                # specify path and try again.
                self._command = "/usr/sbin/modinfo"
                cached_result = self.run(
                    mod_name, no_info_log=no_info_log, no_error_log=no_error_log
                )
            self._cached_result[mod_name] = cached_result
        return cached_result.stdout

    def get_version(
        self,
        mod_name: str,
        force_run: bool = False,
        no_info_log: bool = True,
        no_error_log: bool = True,
    ) -> str:
        output = self.get_info(
            mod_name=mod_name,
            force_run=force_run,
            no_info_log=no_info_log,
            no_error_log=no_error_log,
        )
        found_version = find_patterns_in_lines(output, [self.__version_pattern])
        return found_version[0][0] if found_version[0] else ""
