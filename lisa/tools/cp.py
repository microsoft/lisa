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
        recur: bool = False,
        timeout: int = 600,
    ) -> None:
        cmd = f"{src} {dest}"
        if recur:
            cmd = f"-r {cmd}"
        result = self.run(
            cmd,
            force_run=True,
            sudo=sudo,
            cwd=cwd,
            shell=True,
            timeout=timeout,
        )

        # cp copies all the files except folders in the source
        # directory to the destination directory when we do not
        # specify -r when source is a directory. Though it throws
        # an error which we can ignore.
        if "omitting directory" in result.stdout and not recur:
            return
        result.assert_exit_code()
