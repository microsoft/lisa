# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath
from typing import List, Type, cast

from lisa.executable import Tool
from lisa.operating_system import Debian, Posix, Redhat, Suse
from lisa.tools import Echo
from lisa.util import LisaException

from .git import Git
from .make import Make


class Xfstests(Tool):
    repo = "https://git.kernel.org/pub/scm/fs/xfs/xfstests-dev.git"
    common_dep = [
        "acl",
        "attr",
        "automake",
        "bc",
        "cifs-utils",
        "dos2unix",
        "dump",
        "e2fsprogs",
        "gawk",
        "gcc",
        "git",
        "libtool",
        "lvm2",
        "make",
        "parted",
        "quota",
        "sed",
        "xfsdump",
        "xfsprogs",
        "indent",
        "python",
        "fio",
    ]
    debian_dep = [
        "libacl1-dev",
        "libaio-dev",
        "libattr1-dev",
        "libgdbm-dev",
        "libtool-bin",
        "libuuid1",
        "libuuidm-ocaml-dev",
        "sqlite3",
        "uuid-dev",
        "uuid-runtime",
        "xfslibs-dev",
        "zlib1g-dev",
        "btrfs-tools",
    ]
    fedora_dep = [
        "libtool",
        "libuuid-devel",
        "libacl-devel",
        "xfsprogs-devel",
        "epel-release",
        "libaio-devel",
        "libattr-devel",
        "sqlite",
        "xfsdump",
        "xfsprogs-qa-devel",
        "zlib-devel",
        "btrfs-progs-devel",
        "llvm-ocaml-devel",
        "uuid-devel",
    ]
    suse_dep = [
        "btrfsprogs",
        "libacl-devel",
        "libaio-devel",
        "libattr-devel",
        "sqlite",
        "xfsdump",
        "xfsprogs-devel",
        "lib-devel",
    ]

    @property
    def command(self) -> str:
        return "xfstests"

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git, Make]

    def _install_dep(self) -> None:
        posix_os: Posix = cast(Posix, self.node.os)
        tool_path = self.get_tool_path()
        git = self.node.tools[Git]
        git.clone(self.repo, tool_path)
        # install dependency packages
        package_list = []
        package_list.extend(self.common_dep)
        if isinstance(self.node.os, Redhat):
            package_list.extend(self.fedora_dep)
        elif isinstance(self.node.os, Debian):
            package_list.extend(self.debian_dep)
        elif isinstance(self.node.os, Suse):
            package_list.extend(self.suse_dep)
        else:
            raise LisaException(
                f"Current distro {self.node.os.name} doesn't support xfstests."
            )

        # if install the packages in one command, the remain available packages can't
        # be installed if one of packages is not available in that distro,
        # so here install it one by one.
        for package in list(package_list):
            posix_os.install_packages(package)

    def _add_test_users(self) -> None:
        # prerequisite for xfstesting
        # these users are used in the test code
        # refer https://github.com/kdave/xfstests
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
        make.make_install(code_path)
        return True

    def get_xfstests_path(self) -> PurePath:
        tool_path = self.get_tool_path()
        return tool_path.joinpath("xfstests-dev")

    def set_local_config(
        self, scratch_dev: str, scratch_mnt: str, test_dev: str, test_folder: str
    ) -> None:
        xfstests_path = self.get_xfstests_path()
        config_path = xfstests_path.joinpath("local.config")
        if self.node.shell.exists(config_path):
            self.node.shell.remove(config_path)
        echo = self.node.tools[Echo]
        content = "\n".join(
            [
                f"SCRATCH_DEV={scratch_dev}",
                f"SCRATCH_MNT={scratch_mnt}",
                f"TEST_DEV={test_dev}",
                f"TEST_DIR={test_folder}",
            ]
        )
        echo.write_to_file(content, config_path)

    def set_excluded_tests(self, exclude_tests: str) -> None:
        if exclude_tests:
            xfstests_path = self.get_xfstests_path()
            exclude_file_path = xfstests_path.joinpath("exclude.txt")
            if self.node.shell.exists(exclude_file_path):
                self.node.shell.remove(exclude_file_path)
            echo = self.node.tools[Echo]
            echo.write_to_file(exclude_tests, exclude_file_path)
