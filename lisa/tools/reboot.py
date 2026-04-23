# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import socket
import time
from datetime import datetime, timedelta
from pathlib import Path
from time import sleep
from typing import Any, Optional, Tuple, Type, cast

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

    # who -b doesn't return correct content in Ubuntu 14.04 and 25.10,
    # but uptime works.
    # uptime has no -s parameter in some distros, so not use is as default.
    def _get_last_boot_time(self) -> datetime:
        try:
            last_boot_time = cast(datetime, _who_last(self.node.tools[Who]))
        except FunctionTimedOut as identifier:
            # who -b hung inside the ssh shell; fall back to uptime -s with a
            # bounded command timeout so we don't block the reboot poll loop.
            self._log.debug(f"who -b timed out; using uptime -s: {identifier}")
            last_boot_time = self.node.tools[Uptime].since_time(timeout=30)
        except Exception as identifier:
            self._log.debug(f"who -b failed; using uptime -s: {identifier}")
            last_boot_time = self.node.tools[Uptime].since_time(timeout=30)
        return last_boot_time

    def _resolve_ssh_endpoint(self) -> Tuple[Optional[str], Optional[int]]:
        # Only remote linux nodes have a routable ssh endpoint we can probe
        # with a raw TCP connect. For other node types, skip the probe.
        from lisa.node import RemoteNode

        if not isinstance(self.node, RemoteNode):
            return None, None
        try:
            address = str(
                self.node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS]
            )
            port = int(
                self.node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_PORT]
            )
            return address, port
        except (KeyError, TypeError, ValueError):
            return None, None

    def _is_ssh_port_open(
        self, address: str, port: int, timeout_seconds: float = 3.0
    ) -> bool:
        # Bounded TCP connect probe. connect_ex honors the socket timeout, so
        # a filtered/dropped port returns within timeout_seconds instead of
        # the kernel's default ~2 minute TCP connect timeout.
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout_seconds)
                return sock.connect_ex((address, port)) == 0
        except OSError:
            return False

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
        timer = create_timer()

        last_boot_time = self._get_last_boot_time()
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

        # Resolve the ssh endpoint once. When available we gate the expensive
        # ssh boot-time probe behind a fast TCP reachability check so each
        # poll iteration costs ~seconds while the vm is down, instead of the
        # 30s func_set_timeout budget of _who_last hanging on shell init.
        tcp_address, tcp_port = self._resolve_ssh_endpoint()

        connected: bool = False
        port_opened_once: bool = False
        # The previous steps may take longer time than time out. After that, it
        # needs to connect at least once.
        tried_times: int = 0
        while (timer.elapsed(False) < time_out) or tried_times < 1:
            tried_times += 1
            self.node.close()

            if tcp_address and tcp_port is not None:
                if not self._is_ssh_port_open(tcp_address, tcp_port):
                    # vm is not yet serving ssh; retry cheaply rather than
                    # wasting 30s on a hung shell init.
                    sleep(2)
                    continue
                port_opened_once = True

            try:
                current_boot_time = self._get_last_boot_time()
                connected = True
                self._log.debug(f"reconnected with last boot time: {current_boot_time}")
            except FunctionTimedOut as e:
                # The FunctionTimedOut must be caught separated, or the process
                # will exit.
                self._log.debug(f"ignorable timeout exception: {e}")
            except Exception as e:
                # error is ignorable, as ssh may be closed suddenly.
                self._log.debug(f"ignorable ssh exception: {e}")
            if last_boot_time < current_boot_time:
                break
        if last_boot_time < current_boot_time:
            return
        if connected:
            raise LisaException(
                "timeout to wait reboot, the node may not perform reboot."
            )
        if tcp_address and tcp_port is not None and not port_opened_once:
            raise LisaException(
                f"timeout to wait reboot: ssh endpoint {tcp_address}:{tcp_port} "
                f"was not reachable within {time_out}s after reboot. The vm "
                "likely failed to boot (for guests with passthrough devices, "
                "check the host for qemu/vfio errors and the guest serial log)."
            )
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
