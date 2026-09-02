# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
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
    _serial_ip_start_marker = "__LISA_REBOOT_IP_START__"
    _serial_ip_end_marker = "__LISA_REBOOT_IP_END__"
    _serial_ip_regex = re.compile(
        r"(?<![\d.])(?P<ip_addr>(?!127\.)(?:\d{1,3}\.){3}\d{1,3})(?![\d.])",
        re.M,
    )
    _serial_ip_command = (
        "DEV=$(ip -4 -o route show default | "
        "sed -n 's/.* dev \\([^ ]*\\).*/\\1/p' | sed -n '1p'); "
        'if [ -n "$DEV" ]; then '
        'ip -4 -o addr show dev "$DEV" scope global | '
        "sed -n 's/.* inet \\([0-9.]*\\)\\/.*/\\1/p' | sed -n '1p'; "
        "else ip -4 -o addr show scope global | "
        "sed -n 's/.* inet \\([0-9.]*\\)\\/.*/\\1/p' | sed -n '1p'; fi"
    )

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
        except Exception:
            last_boot_time = self.node.tools[Uptime].since_time()
        return last_boot_time

    def _wait_ssh_session_stable(self, time_out: int) -> None:
        from lisa.node import RemoteNode

        timer = create_timer()
        consecutive_successes = 0
        last_error = ""
        remote_node = cast(RemoteNode, self.node)
        while timer.elapsed(False) < time_out:
            try:
                self.node.close()
                self.node.execute(
                    "echo lisa reboot ready",
                    shell=True,
                    timeout=10,
                    no_info_log=True,
                ).assert_exit_code()
                consecutive_successes += 1
                if consecutive_successes >= 2:
                    return
            except Exception as e:
                consecutive_successes = 0
                last_error = str(e)
                self._log.debug(f"waiting for stable ssh session after reboot: {e}")
            remaining = max(0, int(time_out - timer.elapsed(False)))
            if remaining > 0:
                wait_tcp_port_ready(
                    address=remote_node.connection_info[
                        constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS
                    ],
                    port=remote_node.connection_info[
                        constants.ENVIRONMENTS_NODES_REMOTE_PORT
                    ],
                    log=self._log,
                    timeout=min(2, remaining),
                )
        raise LisaException(
            f"cannot get stable ssh session after reboot in {time_out} seconds. "
            f"Last error: {last_error}"
        )

    def _run_reboot_command(self) -> None:
        command_result = self.node.execute(
            "command -v reboot", shell=True, sudo=True, no_info_log=True
        )
        if command_result.exit_code == 0:
            self._command = command_result.stdout.strip()
        self.run(force_run=True, sudo=True, timeout=10)

    def _is_baremetal_node(self) -> bool:
        platform = getattr(self.node.features, "_platform", None)
        return bool(platform and platform.type_name() == "baremetal")

    def _refresh_address_from_serial(self, time_out: int) -> bool:
        from lisa.node import RemoteNode

        if not self.node.features.is_supported(SerialConsole):
            return False

        remote_node = cast(RemoteNode, self.node)
        connection = remote_node.connection_info
        serial_console = self.node.features[SerialConsole]

        previous_output = serial_console.get_console_log(force_run=True)
        deadline = time.time() + max(1, time_out)

        while time.time() < deadline:
            try:
                serial_console.write(
                    f"echo {self._serial_ip_start_marker}; "
                    f"{self._serial_ip_command}; "
                    f"echo {self._serial_ip_end_marker}"
                )
                output = serial_console.get_console_log(force_run=True)
                fresh_output = (
                    output[len(previous_output) :]
                    if output.startswith(previous_output)
                    else output
                )

                marker_start = fresh_output.rfind(self._serial_ip_start_marker)
                marker_end = fresh_output.find(
                    self._serial_ip_end_marker, marker_start + 1
                )
                if marker_start >= 0 and marker_end > marker_start:
                    command_output = fresh_output[
                        marker_start + len(self._serial_ip_start_marker) : marker_end
                    ]
                    matched = self._serial_ip_regex.search(command_output)
                    if matched:
                        new_address = matched.group("ip_addr")
                        if new_address != connection.address:
                            self._log.info(
                                "detected new IP from serial console after reboot: "
                                f"{new_address}"
                            )
                            remote_node.set_connection_info(
                                address=new_address,
                                public_address=new_address,
                                port=connection.port,
                                public_port=connection.port,
                                username=connection.username,
                                password=connection.password or "",
                                private_key_file=connection.private_key_file or "",
                                use_public_address=False,
                            )
                        else:
                            self._log.debug(
                                f"serial console reported unchanged IP: {new_address}"
                            )
                        return True
            except Exception as e:
                self._log.debug(f"ignorable serial IP refresh exception: {e}")

            sleep(2)

        self._log.debug("serial IP refresh timed out, continue with existing address")
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
            # Reconnect because the SSH session may become inactive during the wait.
            self.node.close()
            current_delta = date.current().replace(tzinfo=None) - current_boot_time

        self._log.debug(f"rebooting with boot time: {last_boot_time}")
        try:
            # Reboot is not reliable, and sometime stuck,
            # like SUSE sles-15-sp1-sapcal gen1 2020.10.23.
            # In this case, use timeout to prevent hanging.
            systemctl_result = self.node.execute(
                "command -v systemctl", shell=True, sudo=True, no_info_log=True
            )
            if systemctl_result.exit_code == 0:
                reboot_result = self.node.execute(
                    "systemctl reboot -i",
                    shell=True,
                    sudo=True,
                    timeout=10,
                )
                if reboot_result.exit_code != 0:
                    self._log.debug(
                        "systemctl reboot failed with exit code "
                        f"{reboot_result.exit_code}; falling back to reboot. "
                        f"stdout: {reboot_result.stdout}, "
                        f"stderr: {reboot_result.stderr}"
                    )
                    self._run_reboot_command()
            else:
                self._run_reboot_command()
        except Exception as e:
            # it doesn't matter to exceptions here. The system may reboot fast
            self._log.debug(f"ignorable exception on rebooting: {e}")

        if self._is_baremetal_node():
            baremetal_timeout = max(600, time_out)
            self._refresh_address_from_serial(min(180, baremetal_timeout))
            self._wait_ssh_session_stable(baremetal_timeout)
            self._log.info(f"SSH connection stable after reboot in {timer}")
            return

        connected: bool = False
        # The previous steps may take longer time than time out. After that, it
        # needs to connect at least once.
        tried_times: int = 0
        while (timer.elapsed(False) < time_out) or tried_times < 1:
            tried_times += 1
            try:
                self.node.close()
                current_boot_time = self._get_last_boot_time()
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
                remaining_stability_wait = max(0, time_out - int(timer.elapsed(False)))
                if remaining_stability_wait > 0:
                    self._wait_ssh_session_stable(remaining_stability_wait)
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
