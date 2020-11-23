from datetime import datetime

from lisa.executable import Tool
from lisa.util import LisaException


class Date(Tool):
    @property
    def command(self) -> str:
        return "date"

    def _check_exists(self) -> bool:
        return True

    def current(self, no_error_log: bool = True) -> datetime:
        command_result = self.run(no_error_log=no_error_log, timeout=10)
        if command_result.exit_code != 0:
            raise LisaException(
                f"'Date' return non-zero exit code: {command_result.stderr}"
            )
        # Mon Nov 23 00:21:02 UTC 2020
        result = datetime.strptime(command_result.stdout, "%a %b %d %H:%M:%S %Z %Y")
        return result
