# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath
from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.tools import Gcc
from lisa.util import LisaException


class Make(Tool):
    repo = "https://github.com/microsoft/ntttcp-for-linux"

    @property
    def command(self) -> str:
        return "make"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages([self, Gcc])
        return self._check_exists()

    def make_and_install(self, cwd: PurePath) -> None:
        # make/install can happen on different folder with same parameter,
        # so force rerun it.
        make_result = self.run(force_run=True, shell=True, cwd=cwd)
        if make_result.exit_code == 0:
            # install with sudo
            self.node.execute("make install", shell=True, sudo=True, cwd=cwd)
        else:
            raise LisaException(
                f"'make' command got non-zero exit code: {make_result.exit_code}"
            )
