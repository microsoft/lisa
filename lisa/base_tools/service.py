# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from time import sleep
from typing import Optional, Type, Any

from assertpy import assert_that

from lisa import schema
from lisa.executable import ExecutableResult, Tool
from lisa.tools.powershell import PowerShell
from lisa.util import (
    LisaException,
    UnsupportedDistroException,
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
        raise NotImplementedError()


class WindowsService(Tool):
    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._command = ""
        self._powershell = self.node.tools[PowerShell]

    @property
    def can_install(self) -> bool:
        return False

    @property
    def command(self) -> str:
        return self._command

    def _check_exists(self) -> bool:
        return True

    def restart_service(self, name: str, ignore_exit_code: int = 0) -> None:
        self._powershell.run_cmdlet(
            f"Restart-service {name}",
            force_run=True,
        )
        self.wait_for_service_start(name)

    def wait_for_service_start(self, name: str) -> None:
        for _ in range(10):
            service_status = self._powershell.run_cmdlet(
                f"Get-Service {name}",
                force_run=True,
                output_json=True,
            )
            if schema.WindowsServiceStatus.RUNNING == schema.WindowsServiceStatus(
                service_status["Status"]
            ):
                return

            self._log.debug(
                f"service '{name}' is not ready yet, retrying... after 5 seconds"
            )
            sleep(5)

        raise LisaException(f"service '{name}' failed to start")

    def _get_status(self, name: str = "") -> schema.WindowsServiceStatus:
        service_status = self._powershell.run_cmdlet(
            f"Get-Service {name}",
            force_run=True,
            output_json=True,
        )
        if not service_status:
            raise LisaException(f"service '{name}' does not exist")
        return schema.WindowsServiceStatus(service_status["Status"])

    def stop_service(self, name: str) -> None:
        self._powershell.run_cmdlet(
            f"Stop-Service {name} -Force",
            force_run=True,
            output_json=True,
        )
        assert_that(self._get_status(name)).described_as(
            f"Failed to stop service {name}"
        ).is_not_equal_to(schema.WindowsServiceStatus.RUNNING)

    def enable_service(self, name: str) -> None:
        raise NotImplementedError()

    def check_service_status(self, name: str) -> bool:
        return self._get_status(name) == schema.WindowsServiceStatus.RUNNING

    def check_service_exists(self, name: str) -> bool:
        try:
            self._get_status(name)
            return True
        except LisaException:
            return False

    def is_service_inactive(self, name: str) -> bool:
        return self._get_status(name) == schema.WindowsServiceStatus.STOPPED

    # Check if service is running
    def is_service_running(self, name: str) -> bool:
        return self._get_status(name) == schema.WindowsServiceStatus.RUNNING


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


def _check_error_codes(cmd_result: ExecutableResult, error_code: int = 0) -> None:
    cmd_result.assert_exit_code(expected_exit_code=[0, error_code])
