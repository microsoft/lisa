# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from enum import Enum
from time import sleep
from typing import Optional, Type

from lisa.executable import ExecutableResult, Tool
from lisa.tools.dmesg import Dmesg
from lisa.tools.journalctl import Journalctl
from lisa.tools.powershell import PowerShell
from lisa.util import (
    LisaException,
    UnsupportedDistroException,
    create_timer,
    filter_ansi_escape,
    find_group_in_lines,
)


class Service(Tool):
    # exit codes for systemd are documented:
    # https://manpages.debian.org/buster/systemd/systemd.exec.5.en.html

    SYSTEMD_EXIT_NOPERMISSION = 4

    @property
    def command(self) -> str:
        return "systemctl"

    @property
    def can_install(self) -> bool:
        return False

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        return WindowsService

    def _check_exists(self) -> bool:
        cmd_result = self.node.execute(
            "ls -lt /run/systemd/system", shell=True, sudo=True
        )
        service_type: Type[object]
        if 0 == cmd_result.exit_code:
            service_type = Systemctl
        else:
            service_type = ServiceInternal
        self._internal_tool = self.node.tools[service_type]
        return True

    def restart_service(self, name: str, ignore_exit_code: int = 0) -> None:
        self._internal_tool.restart_service(name, ignore_exit_code)  # type: ignore

    def start_service(self, name: str, ignore_exit_code: int = 0) -> None:
        self._internal_tool.start_service(name, ignore_exit_code)  # type: ignore

    def stop_service(self, name: str) -> None:
        self._internal_tool.stop_service(name)  # type: ignore

    def enable_service(self, name: str) -> None:
        self._internal_tool.enable_service(name)  # type: ignore

    def check_service_status(self, name: str) -> bool:
        return self._internal_tool._check_service_running(name)  # type: ignore

    def check_service_exists(self, name: str) -> bool:
        return self._internal_tool._check_service_exists(name)  # type: ignore

    def is_service_inactive(self, name: str) -> bool:
        return self._internal_tool._is_service_inactive(name)  # type: ignore

    def is_service_running(self, name: str) -> bool:
        return self._internal_tool._check_service_running(name)  # type: ignore

    def wait_for_service_start(self, name: str) -> None:
        raise NotImplementedError("'wait_for_service_start' is not implemented")


class ServiceInternal(Tool):
    @property
    def command(self) -> str:
        return "service"

    @property
    def can_install(self) -> bool:
        return False

    def _check_exists(self) -> bool:
        return True

    def _check_service_exists(self, name: str) -> bool:
        cmd_result = self.run(f"{name} status", shell=True, sudo=True, force_run=True)
        if "unrecognized service" in cmd_result.stdout:
            return False
        return True

    def _check_service_running(self, name: str) -> bool:
        cmd_result = self.run(f"{name} status", shell=True, sudo=True, force_run=True)
        return (
            "unrecognized service" not in cmd_result.stdout
            and 0 == cmd_result.exit_code
        )

    def _is_service_inactive(self, name: str) -> bool:
        cmd_result = self.run(f"{name} status", shell=True, sudo=True, force_run=True)
        return "Active: inactive" in cmd_result.stdout

    def stop_service(self, name: str) -> None:
        if self._check_service_running(name):
            cmd_result = self.run(f"{name} stop", shell=True, sudo=True, force_run=True)
            cmd_result.assert_exit_code()

    def restart_service(self, name: str, ignore_exit_code: int = 0) -> None:
        cmd_result = self.run(f"{name} restart", shell=True, sudo=True, force_run=True)
        # optionally ignore exit code if it matches our expected non-zero value

        _check_error_codes(cmd_result, ignore_exit_code)

    def is_service_running(self, name: str) -> bool:
        cmd_result = self.run(f"{name} status", shell=True, sudo=True, force_run=True)
        return "Active: active" in cmd_result.stdout


class Systemctl(Tool):
    __STATE_PATTERN = re.compile(r"^(\s+)State:(\s+)(?P<state>.*)", re.M)
    __NOT_FOUND = re.compile(r"not found", re.M)

    @property
    def command(self) -> str:
        return "systemctl"

    @property
    def can_install(self) -> bool:
        return False

    def stop_service(self, name: str) -> None:
        if self._check_service_running(name):
            cmd_result = self.run(f"stop {name}", shell=True, sudo=True, force_run=True)
            cmd_result.assert_exit_code()

    def restart_service(self, name: str, ignore_exit_code: int = 0) -> None:
        cmd_result = self.run(f"restart {name}", shell=True, sudo=True, force_run=True)
        if cmd_result.exit_code != 0 and cmd_result.exit_code != ignore_exit_code:
            self._collect_logs(name)
        _check_error_codes(cmd_result, ignore_exit_code)

    def start_service(self, name: str, ignore_exit_code: int = 0) -> None:
        cmd_result = self.run(f"start {name}", shell=True, sudo=True, force_run=True)
        if cmd_result.exit_code != 0 and cmd_result.exit_code != ignore_exit_code:
            self._collect_logs(name)
        _check_error_codes(cmd_result, ignore_exit_code)

    def enable_service(self, name: str) -> None:
        cmd_result = self.run(f"enable {name}", shell=True, sudo=True, force_run=True)
        cmd_result.assert_exit_code()

    def hibernate(self) -> None:
        self.run_async("hibernate", sudo=True, force_run=True)

    def state(self) -> str:
        cmd_result = self.run(
            "status --no-page",
            shell=True,
            sudo=True,
            force_run=True,
        )
        if cmd_result.exit_code != 0 and self.__NOT_FOUND.findall(cmd_result.stdout):
            raise UnsupportedDistroException(
                os=self.node.os, message=f"command not find {self.command}"
            )
        group = find_group_in_lines(
            filter_ansi_escape(cmd_result.stdout), self.__STATE_PATTERN
        )
        return group["state"]

    def mask(self, unit_name: str) -> None:
        self.run(
            f"mask {unit_name}",
            shell=True,
            sudo=True,
            force_run=True,
            expected_exit_code=0,
        )

    def daemon_reload(self) -> None:
        self.run(
            "daemon-reload", shell=True, sudo=True, force_run=True, expected_exit_code=0
        )

    def is_service_running(self, name: str) -> bool:
        cmd_result = self.run(
            f"--full --no-pager status {name}", shell=True, sudo=True, force_run=True
        )
        return "Active: active" in cmd_result.stdout

    def _check_exists(self) -> bool:
        return True

    def _check_service_exists(self, name: str) -> bool:
        cmd_result = self.run(
            f"--full --no-pager status {name}", shell=True, sudo=True, force_run=True
        )
        if (
            "could not be found" in cmd_result.stdout
            or "not-found" in cmd_result.stdout
        ):
            return False
        return True

    def _is_service_inactive(self, name: str) -> bool:
        cmd_result = self.run(
            f"is-active {name}", shell=True, sudo=True, force_run=True
        )
        return "inactive" == cmd_result.stdout

    def _check_service_running(self, name: str) -> bool:
        cmd_result = self.run(
            f"--full --no-pager status {name}", shell=True, sudo=True, force_run=True
        )
        return (
            "could not be found" not in cmd_result.stdout
            or "not-found" in cmd_result.stdout
        ) and 0 == cmd_result.exit_code

    def _collect_logs(self, service_name: str) -> None:
        self._log.info(f"Collecting logs for service '{service_name}'.")

        # Get detailed status from systemctl status
        status_cmd = f"status {service_name} --no-pager -n 100"
        try:
            _ = self.run(status_cmd, shell=True, sudo=True, force_run=True)
        except Exception as e_status:
            self._log.info(f"Failed to get status for {service_name}: {e_status}")

        try:
            journal_tail_lines = 50
            journalctl_tool = self.node.tools[Journalctl]
            journal_output = journalctl_tool.logs_for_unit(unit_name=service_name)
            journal_lines = journal_output.splitlines()
            tail_lines = "\n".join(journal_lines[-journal_tail_lines:])
            self._log.info(
                f"Last {journal_tail_lines} journal logs for unit '{service_name}':\n"
                f"{tail_lines}"
            )
        except Exception as e_journal:
            self._log.info(
                f"Could not retrieve or process journal logs for {service_name}: "
                f"{e_journal}"
            )

        try:
            dmesg_tail_lines = 25
            dmesg = self.node.tools[Dmesg]
            dmesg_out = dmesg.get_output(
                force_run=True, no_debug_log=True, tail_lines=dmesg_tail_lines
            )
            self._log.info(
                f"Last {dmesg_tail_lines} lines of dmesg output:\n{dmesg_out}"
            )
        except Exception as e_dmesg:
            self._log.info(f"Could not retrieve dmesg output: {e_dmesg}")


def _check_error_codes(cmd_result: ExecutableResult, error_code: int = 0) -> None:
    cmd_result.assert_exit_code(expected_exit_code=[0, error_code])


class WindowsServiceStatus(int, Enum):
    CONTINUE_PENDING = 5
    PAUSE_PENDING = 6
    PAUSED = 7
    RUNNING = 4
    START_PENDING = 2
    STOP_PENDING = 3
    STOPPED = 1
    NOT_FOUND = 0


class WindowsService(Tool):
    @property
    def can_install(self) -> bool:
        return False

    @property
    def command(self) -> str:
        return ""

    def enable_service(self, name: str) -> None:
        pass

    def restart_service(self, name: str, ignore_exit_code: int = 0) -> None:
        self.node.tools[PowerShell].run_cmdlet(
            f"Restart-service {name}",
            force_run=True,
        )
        self.wait_for_service_start(name)

    def stop_service(self, name: str) -> None:
        self.node.tools[PowerShell].run_cmdlet(
            f"Stop-Service {name} -Force",
            force_run=True,
        )
        self.wait_for_service_stop(name)

    def wait_for_service_start(self, name: str) -> None:
        self._wait_for_service(name, WindowsServiceStatus.RUNNING)

    def wait_for_service_stop(self, name: str) -> None:
        self._wait_for_service(name, WindowsServiceStatus.STOPPED)

    def check_service_exists(self, name: str) -> bool:
        if (
            self._get_status(name, fail_on_error=False)
            == WindowsServiceStatus.NOT_FOUND
        ):
            return False
        return True

    def _check_exists(self) -> bool:
        return True

    def _get_status(
        self, name: str = "", fail_on_error: bool = True
    ) -> WindowsServiceStatus:
        try:
            service_status = self.node.tools[PowerShell].run_cmdlet(
                f"Get-Service {name}",
                force_run=True,
                output_json=True,
            )
        except LisaException as e:
            if "Cannot find any service with service name" in str(e):
                if fail_on_error:
                    raise LisaException(f"service '{name}' does not exist")
                return WindowsServiceStatus.NOT_FOUND
            raise e
        return WindowsServiceStatus(int(service_status["Status"]))

    def _wait_for_service(
        self, name: str, status: WindowsServiceStatus, timeout: int = 30
    ) -> None:
        timer = create_timer()
        self._log.debug(f"waiting for service '{name}' to be in '{status}' state")
        while timeout > timer.elapsed(False):
            current_service_status = self._get_status(name)
            if status == current_service_status:
                return
            sleep(0.5)

        if timeout < timer.elapsed():
            raise LisaException(
                f"service '{name}' still in '{current_service_status}' state"
                f"after '{timeout}' seconds"
            )
