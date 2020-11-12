import re
from typing import Any, List, Optional

from lisa.executable import Tool
from lisa.util import LisaException
from lisa.util.process import ExecutableResult


class Dmesg(Tool):
    # meet any pattern will be considered as potential error line.
    __errors_patterns = [
        re.compile("Call Trace"),
        re.compile("rcu_sched self-detected stall on CPU"),
        re.compile("rcu_sched detected stalls on"),
        re.compile("BUG: soft lockup"),
    ]

    @property
    def command(self) -> str:
        return "dmesg"

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._cached_result: Optional[ExecutableResult] = None

    def _check_exists(self) -> bool:
        return True

    def get_output(self, force_run: bool = False) -> str:
        command_output = self._run(force_run=force_run)
        return command_output.stdout

    def check_kernel_errors(
        self,
        force_run: bool = False,
        throw_error: bool = True,
    ) -> str:
        command_output = self._run(force_run=force_run)
        if command_output.exit_code != 0:
            raise LisaException(f"exit code should be zero: {command_output.exit_code}")
        matched_lines: List[str] = []
        for line in command_output.stdout.splitlines(keepends=False):
            for pattern in self.__errors_patterns:
                if pattern.search(line):
                    matched_lines.append(line)
                    # match one rule, so skip for other patterns
                    break
        result = "\n".join(matched_lines)
        if result:
            # log first line only, in case it's too long
            error_message = (
                f"dmesg error with {len(matched_lines)} lines, "
                f"first line: '{matched_lines[0]}'"
            )
            if throw_error:
                raise LisaException(error_message)
            else:
                self._log.debug(error_message)
        return result

    def _run(self, force_run: bool = True) -> ExecutableResult:
        if self._cached_result is None or force_run:
            # sometime it need sudo, we can retry
            # so no_error_log for first time
            result = self.run(no_error_log=True)
            if result.stderr:
                # may need sudo
                result = self.node.execute("sudo dmesg")
            self._cached_result = result
        else:
            result = self._cached_result
        return result
