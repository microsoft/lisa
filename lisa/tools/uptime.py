from datetime import datetime

from lisa.executable import Tool
from lisa.util import LisaException


class Uptime(Tool):
    @property
    def command(self) -> str:
        return "uptime"

    def _check_exists(self) -> bool:
        return True

    def since_time(self) -> datetime:
        command_result = self.run("-s")
        if command_result.exit_code != 0:
            raise LisaException(
                f"get unexpected non-zero exit code {command_result.exit_code}"
            )
        return datetime.fromisoformat(command_result.stdout)
