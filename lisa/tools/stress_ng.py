# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Posix

from .gcc import Gcc
from .git import Git
from .make import Make


class StressNg(Tool):
    repo = "https://github.com/ColinIanKing/stress-ng"
    branch = "V0.14.01"

    @property
    def command(self) -> str:
        return "stress-ng"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        if posix_os.is_package_in_repo("stress-ng"):
            posix_os.install_packages("stress-ng")
        else:
            self._install_from_src()
        return self._check_exists()

    def launch(
        self, num_workers: int = 0, vm_bytes: str = "", timeout_in_seconds: int = 0
    ) -> None:
        # --vm N, start N workers spinning on anonymous mmap
        # --timeout T, timeout after T seconds
        # --vm-bytes N, allocate N bytes per vm worker
        #  (default 256MB)
        cmd = ""
        if num_workers:
            cmd += f" --vm {num_workers} "
        if num_workers:
            cmd += f" --vm-bytes {vm_bytes} "
        if timeout_in_seconds:
            cmd += f" --timeout {timeout_in_seconds} "
        self.run(cmd, force_run=True)

    def _install_from_src(self) -> bool:
        tool_path = self.get_tool_path()
        git = self.node.tools[Git]
        git.clone(self.repo, tool_path, ref=self.branch)
        self.node.tools[Gcc]
        make = self.node.tools[Make]
        code_path = tool_path.joinpath("stress-ng")
        make.make_install(cwd=code_path)
        return self._check_exists()
