# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa.base_tools.cat import Cat
from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Debian, Oracle, Posix, Suse

import re
from pathlib import PosixPath, PurePath
from typing import List, Type

from assertpy import assert_that

from lisa.executable import Tool
from lisa.operating_system import CentOs, Redhat, Ubuntu
from lisa.tools import Git, Lspci, Wget, Gcc, Tar
from lisa.util import LisaException, SkippedException


class SysCallBenchmark(Tool):
    _syscall_benchmark_github = "https://github.com/arkanis/syscall-benchmark.git"

    _common_packages = ["yasm", "dos2unix"]

    _fedora_type_package = []

    _ubuntu_packages = []

    _suse_type_packages = []

    @property
    def command(self) -> str:
        return "./bench.sh"

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git, Gcc, Wget, Tar, Cat]

    def get_benchmark(self) -> None:
        self.run(cwd=self._repo_path / self._repo_name)
        result = self.node.tools[Cat].run(
            "results.log", cwd=self._repo_path / self._repo_name
        )
        return result.stdout

    def __execute_assert_zero(self, cmd: str, cwd: PurePath, timeout: int = 600) -> str:
        result = self.node.execute(cmd, sudo=True, shell=True, cwd=cwd, timeout=timeout)
        assert_that(result.exit_code).is_zero()
        return result.stdout

    def _install(self) -> bool:
        self._repo_name = "syscall-benchmark"

        self._repo_path = self.node.working_path
        self._install_dependencies()
        node = self.node
        git_tool = node.tools[Git]
        git_tool.clone(self._syscall_benchmark_github, cwd=self._repo_path)
        self.__execute_assert_zero(
            f"./compile.sh", cwd=self._repo_path / self._repo_name
        )
        return True

    def _install_dependencies(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        if isinstance(self.node.os, Redhat) or isinstance(self.node.os, Oracle):
            package_name = "epel-release"
            try:
                self.node.os.install_packages(package_name)
            except:
                if re.match("^6.", self.node.os.information.version):
                    epel_rpm_url = "https://dl.fedoraproject.org/pub/epel/epel-release-latest-6.noarch.rpm"
                elif re.match("^7.", self.node.os.information.version):
                    epel_rpm_url = "https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm"
                elif re.match("8.0.", self.node.os.information.version):
                    epel_rpm_url = "https://dl.fedoraproject.org/pub/epel/epel-release-latest-8.noarch.rpm"
                else:
                    raise LisaException(
                        "Unsupported version to install epel repository"
                    )
                self.__execute_assert_zero(f"rpm -ivh {epel_rpm_url}")
        elif isinstance(self.node.os, Suse):
            pass
        elif isinstance(self.node.os, Ubuntu) or isinstance(self.node.os, Debian):
            pass
        else:
            raise SkippedException("Unknown distribution...")
        posix_os.install_packages(list(self._common_packages))
