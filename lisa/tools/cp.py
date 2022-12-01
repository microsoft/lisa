# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import PurePath
from typing import Optional

from lisa.executable import Tool


class Cp(Tool):
    @property
    def command(self) -> str:
        return "cp"

    @property
    def can_install(self) -> bool:
        return False

    def copy(
        self,
        src: PurePath,
        dest: PurePath,
        sudo: bool = False,
        cwd: Optional[PurePath] = None,
    ) -> None:
        result = self.run(
            f"{src} {dest}",
            force_run=True,
            expected_exit_code=0,
            sudo=sudo,
            cwd=cwd,
        )
        result.assert_exit_code()
