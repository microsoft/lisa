from typing import Any

from lisa.executable import Tool
from lisa.util.perf_timer import create_timer

from .uptime import Uptime


class Reboot(Tool):
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        # timeout to wait
        self.time_out: int = 300

    @property
    def command(self) -> str:
        return "reboot"

    def _check_exists(self) -> bool:
        return True

    def reboot(self) -> None:
        uptime = self.node.tools[Uptime]
        timer = create_timer()
        before_reboot_since_time = uptime.since_time()
        current_since_time = before_reboot_since_time
        self._log.debug(f"rebooting with current uptime: {before_reboot_since_time}")
        self.node.execute(f"sudo {self.command}")
        self.node.shell.close()
        while (
            before_reboot_since_time >= current_since_time
            and timer.elapsed(False) < self.time_out
        ):
            self.node.shell.close()
            current_since_time = uptime.since_time()
            self._log.debug(f"reconnected with uptime: {current_since_time}")
