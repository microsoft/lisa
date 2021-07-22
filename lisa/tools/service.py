# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool
from lisa.util.process import ExecutableResult


class Service(Tool):
    @property
    def command(self) -> str:
        return "service"

    def _check_exists(self) -> bool:
        return True

    def _check_service_running(self, name: str) -> bool:
        cmd_result = self.run(f"{name} status", shell=True, sudo=True, force_run=True)
        return cmd_result.exit_code == 0

    def restart_service(self, name: str) -> ExecutableResult:
        return self.run(f"{name} restart", shell=True, sudo=True, force_run=True)
