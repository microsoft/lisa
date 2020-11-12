import re
from datetime import datetime

from lisa.executable import Tool
from lisa.util import LisaException, get_matched_str


class Who(Tool):
    last_time_pattern = re.compile(r"^[ ]*system boot[ ]*(?P<time>.+)$")

    @property
    def command(self) -> str:
        return "who"

    @property
    def can_install(self) -> bool:
        return False

    def last_boot(self, no_error_log: bool = True) -> datetime:
        command_result = self.run("-b", no_error_log=no_error_log)
        if command_result.exit_code != 0:
            raise LisaException(
                f"'last' return non-zero exit code: {command_result.stderr}"
            )
        datetime_output = get_matched_str(command_result.stdout, self.last_time_pattern)
        try:
            result = datetime.fromisoformat(datetime_output)
        except ValueError:
            # ValueError: Invalid isoformat string: 'Nov 10 20:54'
            result = datetime.strptime(datetime_output, "%b %d %H:%M")

        return result
