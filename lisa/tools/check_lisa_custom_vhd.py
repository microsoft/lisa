# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.executable import Tool
from lisa.util.constants import LISA_KERNEL_BUILD_SENTINEL


class CustomKernelBuildCheck(Tool):
    @property
    def command(self) -> str:
        return f""

    @property
    def exists(self) -> bool:
        return True

    @property
    def can_install(self) -> bool:
        return False

    def was_kernel_built_by_lisa(self) -> bool:
        return (
            self.node.execute(
                f"test -f {LISA_KERNEL_BUILD_SENTINEL}", shell=True, sudo=True
            ).exit_code
            == 0
        )
