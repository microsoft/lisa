# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import time
from datetime import datetime, timedelta
from pathlib import Path
from time import sleep
from typing import Any, Optional, Type, cast

from func_timeout import FunctionTimedOut, func_set_timeout

from lisa.executable import Tool
from lisa.features import SerialConsole
from lisa.tools.powershell import PowerShell
from lisa.util import (
    BadEnvironmentStateException,
    LisaException,
    TcpConnectionException,
    constants,
)
from lisa.util.perf_timer import create_timer
from lisa.util.shell import wait_tcp_port_ready

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

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        return WindowsReboot

    def _check_exists(self) -> bool:
        return True

    def reboot_and_check_panic(self, log_path: Path) -> None:
        try:
            self.reboot()
        except Exception as e:
            if self.node.features.is_supported(SerialConsole):
                # if there is any panic, fail before partial pass
                serial_console = self.node.features[SerialConsole]
                serial_console.check_panic(
                    saved_path=log_path,
                    stage="reboot",
                )
            # if node cannot be connected after reboot, it should be failed.
            if isinstance(e, TcpConnectionException):
                raise BadEnvironmentStateException(f"after reboot, {e}")
            raise e

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
            # Reboot is not reliable, and sometime stuck,
            # like SUSE sles-15-sp1-sapcal gen1 2020.10.23.
            # In this case, use timeout to prevent hanging.
            self.run(force_run=True, sudo=True, timeout=10)
        except Exception as e:
            # it doesn't matter to exceptions here. The system may reboot fast
            self._log.debug(f"ignorable exception on rebooting: {e}")

        connected: bool = False
        # The previous steps may take longer time than time out. After that, it
        # needs to connect at least once.
        tried_times: int = 0
        while (timer.elapsed(False) < time_out) or tried_times < 1:
            tried_times += 1
            try:
                self.node.close()
                current_boot_time = _who_last(who)
                connected = True
            except FunctionTimedOut as e:
                # The FunctionTimedOut must be caught separated, or the process
                # will exit.
                self._log.debug(f"ignorable timeout exception: {e}")
            except Exception as e:
                # error is ignorable, as ssh may be closed suddenly.
                self._log.debug(f"ignorable ssh exception: {e}")
            self._log.debug(f"reconnected with uptime: {current_boot_time}")
            if last_boot_time < current_boot_time:
                break
        if last_boot_time == current_boot_time:
            if connected:
                raise LisaException(
                    "timeout to wait reboot, the node may not perform reboot."
                )
            else:
                raise LisaException(
                    "timeout to wait reboot, the node may stuck on reboot command."
                )


class WindowsReboot(Reboot):
    @property
    def command(self) -> str:
        return "powershell"

    def _check_exists(self) -> bool:
        return True

    def reboot(self, time_out: int = 600) -> None:
        last_boot_time = self.node.tools[Uptime].since_time()
        self.node.tools[PowerShell].run_cmdlet(
            "Restart-Computer -Force", force_run=True
        )

        # wait for nested vm ssh connection to be ready
        from lisa.node import RemoteNode

        remote_node = cast(RemoteNode, self.node)

        timeout_start = time.time()
        is_ready = False
        self._log.debug("Waiting for VM to reboot")
        while time.time() - timeout_start < time_out:
            try:
                # check that vm has accessible ssh port
                connected, _ = wait_tcp_port_ready(
                    address=remote_node.connection_info[
                        constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS
                    ],
                    port=remote_node.connection_info[
                        constants.ENVIRONMENTS_NODES_REMOTE_PORT
                    ],
                    log=self._log,
                    timeout=20,
                )

                if not connected:
                    node_ssh_port = remote_node.connection_info[
                        constants.ENVIRONMENTS_NODES_REMOTE_PORT
                    ]
                    raise LisaException(
                        f"failed to connect to {remote_node.name} on port"
                        f" {node_ssh_port} after reboot"
                    )

                self.node.close()

                # check that vm has changed last uptime
                current_boot_time = self.node.tools[Uptime].since_time(timeout=20)
                if last_boot_time < current_boot_time:
                    self._log.debug("VM has rebooted")
                    is_ready = True
                    break

            except Exception as e:
                self._log.debug(f"Waiting for VM to reboot: {e}")
                sleep(2)

        if not is_ready:
            raise LisaException(
                "timeout to wait reboot, the node may not perform reboot."
            )
