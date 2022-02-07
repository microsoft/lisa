# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool


class Sysctl(Tool):
    @property
    def command(self) -> str:
        return "sysctl"

    @property
    def can_install(self) -> bool:
        return False

    def write(self, variable: str, value: str) -> None:
        self.run(f"-w {variable}='{value}'", force_run=True, sudo=True)

    def get(self, variable: str, force_run: bool = True) -> str:
        result = self.run(
            f"-n {variable}",
            force_run=force_run,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"fail to get {variable}'s value",
        )
        return result.stdout
