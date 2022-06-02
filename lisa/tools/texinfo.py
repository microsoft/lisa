# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Posix
from lisa.tools import Wget

from .make import Make
from .tar import Tar


class Texinfo(Tool):
    version = "6.7.91"
    source_link = f"http://alpha.gnu.org/gnu/texinfo/texinfo-{version}.tar.xz"

    @property
    def command(self) -> str:
        return "makeinfo"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        if posix_os.is_package_in_repo("texinfo"):
            posix_os.install_packages("texinfo")
        else:
            posix_os.install_packages(["perl", "perl-Data-Dumper"])
            self._install_from_src()
        return self._check_exists()

    def _install_from_src(self) -> None:
        tool_path = self.get_tool_path()
        wget = self.node.tools[Wget]
        tar = self.node.tools[Tar]
        download_path = wget.get(
            url=self.source_link,
            filename=f"texinfo-{self.version}.tar.xz",
            file_path=str(tool_path),
        )
        tar.extract(download_path, dest_dir=str(tool_path))
        code_path = tool_path.joinpath(f"texinfo-{self.version}")
        make = self.node.tools[Make]
        self.node.execute("./configure", cwd=code_path).assert_exit_code()
        make.make_install(code_path)
        self.node.execute(
            "ln -s /usr/local/bin/makeinfo /usr/bin/makeinfo", sudo=True, cwd=code_path
        ).assert_exit_code()
