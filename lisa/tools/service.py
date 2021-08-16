# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Type

from lisa.executable import Tool


class Service(Tool):
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

    def restart_service(self, name: str) -> None:
        self._internal_tool.restart_service(name)  # type: ignore

    def stop_service(self, name: str) -> None:
        self._internal_tool.stop_service(name)  # type: ignore

    def enable_service(self, name: str) -> None:
        self._internal_tool.enable_service(name)  # type: ignore

    def check_service_status(self, name: str) -> bool:
        return self._internal_tool._check_service_running(name)  # type: ignore


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

    def restart_service(self, name: str) -> None:
        cmd_result = self.run(f"{name} restart", shell=True, sudo=True, force_run=True)
        cmd_result.assert_exit_code()


class Systemctl(Tool):
    @property
    def command(self) -> str:
        return "systemctl"

    @property
    def can_install(self) -> bool:
        return False

    def _check_exists(self) -> bool:
        return True

    def _check_service_exists(self, name: str) -> bool:
        cmd_result = self.run(f"status {name}", shell=True, sudo=True, force_run=True)
        if "could not be found" in cmd_result.stdout:
            return False
        return True

    def _check_service_running(self, name: str) -> bool:
        cmd_result = self.run(f"status {name}", shell=True, sudo=True, force_run=True)
        return (
            "could not be found" not in cmd_result.stdout and 0 == cmd_result.exit_code
        )

    def stop_service(self, name: str) -> None:
        if self._check_service_running(name):
            cmd_result = self.run(f"stop {name}", shell=True, sudo=True, force_run=True)
            cmd_result.assert_exit_code()

    def restart_service(self, name: str) -> None:
        cmd_result = self.run(f"restart {name}", shell=True, sudo=True, force_run=True)
        cmd_result.assert_exit_code()

    def enable_service(self, name: str) -> None:
        cmd_result = self.run(f"enable {name}", shell=True, sudo=True, force_run=True)
        cmd_result.assert_exit_code()
