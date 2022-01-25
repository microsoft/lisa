# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import List, Type

from lisa.executable import Tool
from lisa.operating_system import Debian
from lisa.tools import Echo, Git, Make, Tar, Wget

# from lisa.util import UnsupportedDistroException


class DpdkOvs(Tool):
    @property
    def command(self) -> str:
        return "ovs"

    def _check_exists(self) -> bool:
        git_path = self.node.working_path.joinpath(self.REPO_DIR)
        return (
            self.node.execute(f"test -a {git_path.as_posix()}", shell=True).exit_code
            == 0
        )

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Echo, Make, Git, Tar, Wget]

    @property
    def can_install(self) -> bool:
        # nff-go only implemented for debain in lisav2
        return isinstance(self.node.os, Debian)

    def _install(self) -> bool:
        node = self.node
        git = node.tools[Git]
        wget = node.tools[Wget]
        tar = node.tools[Tar]

        # get nff-go source and go binaries
        self.ovs_git = git.clone(
            "https://github.com/openvswitch/ovs.git",
            cwd=node.working_path,
        )

        self.dpdk_tar = wget.get("https://fast.dpdk.org/rel/dpdk-21.11.tar.xz")
        node.log(self.dpdk_tar)
        tar.extract(self.dpdk_tar)

        return True
