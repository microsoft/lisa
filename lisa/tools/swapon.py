# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool


class SwapOn(Tool):
    @property
    def command(self) -> str:
        return "swapon"
