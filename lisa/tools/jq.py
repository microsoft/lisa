# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from lisa.executable import Tool

class Jq(Tool):

    @property
    def command(self) -> str:
        return "jq"

    @property
    def can_install(self) -> bool:
        return False
