# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Optional

from lisa.executable import Tool
from lisa.tools.whoami import Whoami


class Usermod(Tool):
    @property
    def command(self) -> str:
        return "usermod"

    @property
    def can_install(self) -> bool:
        return False

    def add_user_to_group(
        self, group: str, user: Optional[str] = None, sudo: bool = False
    ) -> None:
        if not user:
            user = self.node.tools[Whoami].get_username()
        self.run(f"-aG {group} {user}", force_run=True, sudo=sudo, shell=True)
