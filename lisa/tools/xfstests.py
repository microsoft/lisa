# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath
from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Debian, Fedora, Posix

from .git import Git
from .make import Make


class Xfstests(Tool):
    repo = "https://git.kernel.org/pub/scm/fs/xfs/xfstests-dev.git"

    @property
    def command(self) -> str:
        return "xfstests"

    @property
    def can_install(self) -> bool:
        return True

    def _install_dep(self) -> None:
        posix_os: Posix = cast(Posix, self.node.os)
        tool_path = self.get_tool_path()
        self.node.shell.mkdir(tool_path, exist_ok=True)
        git = self.node.tools[Git]
        git.clone(self.repo, tool_path)
        # install dependency packages
        if isinstance(self.node.os, Fedora):
            posix_os.install_packages(
                [
                    "acl",
                    "attr",
                    "automake",
                    "bc",
                    "dbench",
                    "dump",
                    "e2fsprogs",
                    "fio",
                    "gawk",
                    "indent",
                    "libtool",
                    "lvm2",
                    "psmisc",
                    "quota",
                    "sed",
                    "xfsdump",
                    "xfsprogs",
                    "libacl-devel",
                    "libaio-devel",
                    "libuuid-devel",
                    "xfsprogs-devel",
                    "btrfs-progs-devel",
                    "python",
                    "sqlite",
                    "libcap-devel",
                    "liburing-dev",
                ]
            )
        elif isinstance(self.node.os, Debian):
            posix_os.install_packages(
                [
                    "xfslibs-dev",
                    "uuid-dev",
                    "libtool-bin",
                    "e2fsprogs",
                    "automake",
                    "libuuid1",
                    "quota",
                    "attr",
                    "libacl1-dev",
                    "libaio-dev",
                    "xfsprogs",
                    "libgdbm-dev",
                    "gawk",
                    "fio",
                    "dbench",
                    "uuid-runtime",
                    "python",
                    "sqlite3",
                ]
            )

    def _add_test_users(self) -> None:
        self.node.execute("useradd -m fsgqa", sudo=True)
        self.node.execute("groupadd fsgqa", sudo=True)
        self.node.execute("useradd 123456-fsgqa", sudo=True)
        self.node.execute("useradd fsgqa2", sudo=True)

    def _install(self) -> bool:
        self._add_test_users()
        self._install_dep()
        tool_path = self.get_tool_path()
        make = self.node.tools[Make]
        code_path = tool_path.joinpath("xfstests-dev")
        make.make_and_install(code_path)
        return True

    def get_xfstests_config_path(self) -> PurePath:
        tool_path = self.get_tool_path()
        return tool_path.joinpath("xfstests-dev/local.config")
