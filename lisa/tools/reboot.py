from typing import Any

from spur.ssh import ConnectionError  # type: ignore

from lisa.executable import Tool
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
        self.node.shell.close()
        while (
            last_boot_time >= current_boot_time and timer.elapsed(False) < self.time_out
        ):
            self.node.shell.close()
            try:
                current_boot_time = who.last_boot()
            except ConnectionError as identifier:
                # error is ignorable, as ssh may be closed suddenly.
                self._log.debug(f"ignorable ssh exception: {identifier}")
                pass
            self._log.debug(f"reconnected with uptime: {current_boot_time}")
