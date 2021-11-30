# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from datetime import datetime, timedelta
from pathlib import Path
from time import sleep
from typing import Any

from func_timeout import FunctionTimedOut, func_set_timeout  # type: ignore

from lisa.executable import Tool
from lisa.features import SerialConsole
from lisa.util import LisaException
from lisa.util.perf_timer import create_timer

from .date import Date
from .uptime import Uptime
from .who import Who


# this method is easy to stuck on reboot, so use timeout to recycle it faster.
@func_set_timeout(30)  # type: ignore
def _who_last(who: Who) -> datetime:
    return who.last_boot()


class Reboot(Tool):
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        # timeout to wait
        self._command = "/sbin/reboot"

    @property
    def command(self) -> str:
        return self._command

    def _check_exists(self) -> bool:
        return True

    def reboot_and_check_panic(self, log_path: Path) -> None:
        try:
            self.reboot()
        except Exception as identifier:
            if self.node.features.is_supported(SerialConsole):
                # if there is any panic, fail before partial pass
                serial_console = self.node.features[SerialConsole]
                serial_console.check_panic(
                    saved_path=log_path,
                    stage="reboot",
                )
            # if node cannot be connected after reboot, it should be failed.
            if isinstance(identifier, LisaException) and str(identifier).startswith(
                "cannot connect to TCP port"
            ):
                raise LisaException(f"after reboot, {identifier}")
            raise identifier

    def reboot(self, time_out: int = 300) -> None:
        who = self.node.tools[Who]
        timer = create_timer()

        # who -b doesn't return correct content in Ubuntu 14.04, but uptime works.
        # uptime has no -s parameter in some distros, so not use is as default.
        try:
            last_boot_time = who.last_boot()
        except Exception:
            uptime = self.node.tools[Uptime]
            last_boot_time = uptime.since_time()
        current_boot_time = last_boot_time

        # who -b returns time without seconds.
        # so if the node rebooted in one minute, the who -b is not changed.
        # The reboot will wait forever.
        # in this case, verify the time is wait enough to prevent this problem.
        date = self.node.tools[Date]
        # boot time has no tzinfo, so remove from date result to avoid below error.
        # TypeError: can't subtract offset-naive and offset-aware datetimes
        current_delta = date.current().replace(tzinfo=None) - current_boot_time
        self._log.debug(f"delta time since last boot: {current_delta}")
        while current_delta < timedelta(minutes=1):
            # wait until one minute
            wait_seconds = 60 - current_delta.seconds + 1
            self._log.debug(f"waiting {wait_seconds} seconds before rebooting")
            sleep(wait_seconds)
            current_delta = date.current().replace(tzinfo=None) - current_boot_time

        # Get reboot execution path
        # Not all distros have the same reboot execution path
        command_result = self.node.execute(
            "command -v reboot", shell=True, sudo=True, no_info_log=True
        )
        if command_result.exit_code == 0:
            self._command = command_result.stdout
        self._log.debug(f"rebooting with boot time: {last_boot_time}")
        try:
            # Reboot is not reliable, and sometime stucks,
            # like SUSE sles-15-sp1-sapcal gen1 2020.10.23.
            # In this case, use timeout to prevent hanging.
            self.run(force_run=True, sudo=True, timeout=10)
        except Exception as identifier:
            # it doesn't matter to exceptions here. The system may reboot fast
            self._log.debug(f"ignorable exception on rebooting: {identifier}")

        connected: bool = False
        while last_boot_time == current_boot_time and timer.elapsed(False) < time_out:
            try:
                self.node.close()
                current_boot_time = _who_last(who)
                connected = True
            except FunctionTimedOut as identifier:
                # The FunctionTimedOut must be caught separated, or the process
                # will exit.
                self._log.debug(f"ignorable timeout exception: {identifier}")
            except Exception as identifier:
                # error is ignorable, as ssh may be closed suddenly.
                self._log.debug(f"ignorable ssh exception: {identifier}")
            self._log.debug(f"reconnected with uptime: {current_boot_time}")
        if timer.elapsed() > time_out:
            if connected:
                raise LisaException(
                    "timeout to wait reboot, the node may not perform reboot."
                )
            else:
                raise LisaException(
                    "timeout to wait reboot, the node may stuck on reboot command."
                )
