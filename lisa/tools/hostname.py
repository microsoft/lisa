# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool


class Hostname(Tool):
    @property
    def command(self) -> str:
        return "hostname"

    @property
    def exists(self) -> bool:
        return True

    @property
    def can_install(self) -> bool:
        return False

    def get_hostname(self) -> str:
        return self.run("", shell=True).stdout.strip()
