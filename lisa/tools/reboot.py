from typing import Any

from lisa.executable import Tool
from lisa.util import LisaException
from lisa.util.perf_timer import create_timer

from .who import Who


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
        who = self.node.tools[Who]
        timer = create_timer()
        last_boot_time = who.last_boot()
        current_boot_time = last_boot_time
        self._log.debug(f"rebooting with boot time: {last_boot_time}")
        self.node.execute_async(f"sudo {self.command}")
        while (
            last_boot_time >= current_boot_time and timer.elapsed(False) < self.time_out
        ):
            try:
                self.node.close()
                current_boot_time = who.last_boot()
            except Exception as identifier:
                # error is ignorable, as ssh may be closed suddenly.
                self._log.debug(f"ignorable ssh exception: {identifier}")
            self._log.debug(f"reconnected with uptime: {current_boot_time}")
        if timer.elapsed() > self.time_out:
            raise LisaException("timeout to wait reboot")
