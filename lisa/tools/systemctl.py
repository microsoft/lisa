# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool


class Systemctl(Tool):
    @property
    def command(self) -> str:
        return "systemctl"

    @property
    def can_install(self) -> bool:
        return False
