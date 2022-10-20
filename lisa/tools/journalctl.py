# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool


class Journalctl(Tool):
    @property
    def command(self) -> str:
        return "journalctl"

    @property
    def exists(self) -> bool:
        return True

    @property
    def can_install(self) -> bool:
        return False
