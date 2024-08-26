# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import List

from lisa.executable import Tool
from lisa.operating_system import CBLMariner, Debian, Redhat, Suse
from lisa.util import LisaException

from .gcc import Gcc
from .git import Git
from .make import Make


class Vdsotest(Tool):
    repo = "https://github.com/nlynch-mentor/vdsotest"
    branch = "master"

    @property
    def command(self) -> str:
        return "vdsotest-all"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        self._install_from_src()
        return self._check_exists()

    def run_benchmark(self) -> None:
        vdso_results = self.run(sudo=True)
        if vdso_results.exit_code != 0:
            raise LisaException(
                (
                    f"vdso test run with failure {vdso_results.stdout}, "
                    "probably there is a kernel bug."
                )
            )

    def _install_from_src(self) -> bool:
        package_list: List[str] = []
        if isinstance(self.node.os, Redhat):
            package_list.extend(["autoconf", "automake", "libtool"])
        elif isinstance(self.node.os, Debian):
            package_list.extend(["dh-autoreconf"])
        elif isinstance(self.node.os, Suse):
            package_list.extend(["autoconf", "libtool", "automake"])
        elif isinstance(self.node.os, CBLMariner):
            package_list.extend(
                [
                    "diffutils",
                    "autoconf",
                    "libtool",
                    "automake",
                    "gettext",
                    "binutils",
                    "glibc-devel",
                    "kernel-headers",
                    "perl-CPAN",
                ]
            )
        else:
            raise LisaException(
                f"Current distro {self.node.os.name} doesn't support vdsotest."
            )
        self.node.os.install_packages(package_list)
        tool_path = self.get_tool_path()
        git = self.node.tools[Git]
        git.clone(self.repo, tool_path, ref=self.branch)
        self.node.tools.get(Gcc)
        make = self.node.tools[Make]
        code_path = tool_path.joinpath("vdsotest")
        self.node.execute("./autogen.sh", cwd=code_path).assert_exit_code()
        self.node.execute("./configure", cwd=code_path).assert_exit_code()
        make.make_install(cwd=code_path)
        return self._check_exists()
