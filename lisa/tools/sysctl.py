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

    def write(self, varivable: str, value: str) -> None:
        self.run(f"-w {varivable}={value}")
