# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


from typing import List, Type

from lisa.base_tools import Mv
from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.tools.gcc import Gcc
from lisa.tools.git import Git
from lisa.tools.python import Pip, Python


class Ninja(Tool):
    _ninja_url = "https://github.com/ninja-build/ninja/"

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Gcc, Python]

    @property
    def command(self) -> str:
        return "ninja"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        node = self.node
        # entirely arbitrary kernel version cutoff
        # to seperate older distros (pre-2020) from newer ones
        # that package recent versions of ninja.
        if (
            isinstance(self.node.os, Posix)
            and self.node.os.get_kernel_information().version >= "5.15.0"
        ):
            self.node.os.install_packages("ninja-build")
            return self._check_exists()
        # otherwise, install a recent version from source
        git_tool = node.tools[Git]
        node.tools[Gcc].install_cpp_compiler()
        ninja_path = git_tool.clone(
            self._ninja_url,
            cwd=node.working_path,
        )
        node.tools[Pip].install_packages("pyelftools")
        node.execute(
            "./configure.py --bootstrap",
            cwd=node.get_pure_path(f"{str(ninja_path)}"),
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Ninja: install failed to run ./configure.py --bootstrap"
            ),
        )
        node.tools[Mv].move(
            f"{ninja_path}/ninja",
            "/usr/bin/ninja",
            overwrite=True,
            sudo=True,
        )

        return self._check_exists()
