# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Posix


class Nm(Tool):
    @property
    def command(self) -> str:
        return "nm"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("binutils")
        return self._check_exists()

    def get_symbol_table(self, file: str) -> str:
        result = self.run(
            file,
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to extract file.",
        )

        return result.stdout
