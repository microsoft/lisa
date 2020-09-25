import re
from typing import Any, List, Optional

from lisa.executable import Tool
from lisa.util import LisaException
from lisa.util.process import ExecutableResult


class Dmesg(Tool):
    # meet any pattern will be considered as potential panic line.
    __panic_patterns = [
        re.compile(r"^[^[].+$"),
        re.compile("Call Trace"),
        re.compile("rcu_sched self-detected stall on CPU"),
        re.compile("rcu_sched detected stalls on"),
        re.compile("BUG: soft lockup"),
    ]
    # ignore some return lines, which shouldn't be a panic line.
    __panic_ignorable_patterns = [
        re.compile(r"this clock source is slow\. Consider trying other clock sources"),
        re.compile(r"If you want to keep using the local clock\, then add\:"),
        re.compile('"trace_clock=local"'),
        re.compile(r"on the kernel command line"),
    ]

    @property
    def command(self) -> str:
        return "dmesg"

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._cached_result: Optional[ExecutableResult] = None

    def _check_exists(self) -> bool:
        return True

    def check_kernel_panic(
        self, force_run: bool = False, throw_error: bool = True
    ) -> str:
        command_output = self._run(force_run=force_run)
        if command_output.exit_code != 0:
            raise LisaException(f"exit code should be zero: {command_output.exit_code}")
        panic_lines: List[str] = []
        for line in command_output.stdout.splitlines(keepends=False):
            for pattern in self.__panic_patterns:
                if pattern.search(line):
                    for ignorable_pattern in self.__panic_ignorable_patterns:
                        if ignorable_pattern.search(line):
                            break
                    else:
                        panic_lines.append(line)
                        # match one rule, so skip for other patterns
                        break
        result = "\n".join(panic_lines)
        if result:
            error_message = f"dmesg error:\n{result}"
            if throw_error:
                raise LisaException(error_message)
            else:
                self._log.debug(error_message)
        return result

    def _run(self, force_run: bool = True) -> ExecutableResult:
        if not self._cached_result or force_run:
            # sometime it need sudo, we can retry
            # so no_error_log for first time
            result = self.run(no_error_log=True)
            if result.stderr:
                # may need sudo
                result = self.node.execute("sudo dmesg")
        else:
            result = self._cached_result
        return result
