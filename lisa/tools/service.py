# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Type

from lisa.executable import ExecutableResult, Tool


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

    def stop_service(self, name: str) -> None:
        if self._check_service_running(name):
            cmd_result = self.run(f"{name} stop", shell=True, sudo=True, force_run=True)
            cmd_result.assert_exit_code()

    def restart_service(self, name: str, ignore_exit_code: int = 0) -> None:
        cmd_result = self.run(f"{name} restart", shell=True, sudo=True, force_run=True)
        # optionally ignore exit code if it matches our expected non-zero value

        _check_error_codes(cmd_result, ignore_exit_code)


class Systemctl(Tool):
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
