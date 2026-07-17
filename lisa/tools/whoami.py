# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool


class Whoami(Tool):
    @property
    def command(self) -> str:
        return "whoami"

    @property
    def exists(self) -> bool:
        return True

    @property
    def can_install(self) -> bool:
        return False

    def get_username(self) -> str:
        # Return the current effective user name reported by `whoami`.
        return self.run("", shell=True).stdout.strip()
