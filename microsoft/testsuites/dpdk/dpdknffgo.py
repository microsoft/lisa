# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import List, Type

from lisa.executable import Tool
from lisa.operating_system import Debian, Ubuntu
from lisa.tools import Echo, Git, Make, Tar, Wget
from lisa.util import UnsupportedDistroException


class DpdkNffGo(Tool):

    NFF_GO_SRC_LINK = "https://github.com/intel-go/nff-go.git"
    REPO_DIR = "nff-go"
    GO_TAR = "go1.17.6.linux-amd64.tar.gz"

    ubuntu_packages = [
        "lua5.3-dev",
        "libpcap-dev",
        "libelf-dev",
        "hugepages",
        "libnuma-dev",
        "libhyperscan-dev",
        "liblua5.3-dev",
        "libmnl-dev",
        "libibverbs-dev",
    ]

    @property
    def command(self) -> str:
        return "nff-go"

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
        # but this will be tested for during _install function
        return True

    def _install(self) -> bool:
        node = self.node
        os = node.os
        version = os.information.version
        if isinstance(os, Ubuntu):
            if version < "18.4.0":
                raise UnsupportedDistroException(
                    os, "NFF-GO test is not supported on EOL Ubuntu"
                )
        elif isinstance(os, Debian):
            if version < "10.0.0":
                raise UnsupportedDistroException(
                    os, "NFF-GO test is not supported on EOL Debian"
                )
        else:
            raise UnsupportedDistroException(
                os, "NFF-GO test not implemented on this OS"
            )

        git = node.tools[Git]
        echo = node.tools[Echo]
        wget = node.tools[Wget]
        tar = node.tools[Tar]
        make = node.tools[Make]

        # grab the path, a workaround for the issue mentioned below in run_test
        original_path = echo.run(
            "$PATH",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="failure to grab $PATH via echo",
        ).stdout

        self.new_path = f"{original_path}:/usr/local/go/bin/"

        # get nff-go source and go binaries
        self.nff_go_path = git.clone(
            "https://github.com/intel-go/nff-go.git",
            cwd=node.working_path,
            dir_name=self.REPO_DIR,
        )
        go_tar_path = wget.get(
            f"https://go.dev/dl/{self.GO_TAR}",
            file_path=str(node.working_path),
            filename=self.GO_TAR,
        )
        # unpack and add to path
        tar.extract(go_tar_path, "/usr/local", sudo=True)

        # download go modules
        node.execute(
            "go mod download",
            cwd=self.nff_go_path,
            update_envs={"PATH": self.new_path},
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Could not install go modules for nff-go"
            ),
        )
        # install needed libraries
        if isinstance(node.os, Debian):
            node.os.install_packages(
                [
                    "lua5.3-dev",
                    "linux-headers-generic",
                    "libnuma-dev",
                    "libibverbs-dev",
                    "libpcap-dev",
                    "libmnl-dev",
                ]
            )
        else:
            raise UnsupportedDistroException(
                node.os, "nff-go test not implemented on this OS"
            )
        # make main project
        make.make(
            "",
            cwd=self.nff_go_path,
            update_envs={
                "PATH": self.new_path,
                "NFF_GO_NO_BPF_SUPPORT": "1",
            },
        )
        # make dpdk components we need
        make.make(
            "",
            cwd=self.nff_go_path.joinpath("dpdk"),
            update_envs={
                "NFF_GO_NO_BPF_SUPPORT": "1",
            },
        )
        return True

    def run_test(self) -> None:
        # NOTE: make.make and node.execute sudo=True shell=True
        # both have issues with variable expansion and update_env
        # This is a workaround to execute sudo with the right
        # variables and path, at some point if make tool and execute
        # are fixed we can switch back to using the make tool

        # make 'citesting' target
        self.node.execute(
            (f"PATH={self.new_path} " "NFF_GO_NO_BPF_SUPPORT=1 make citesting"),
            sudo=True,
            shell=True,
            cwd=self.nff_go_path,
            expected_exit_code=0,
            expected_exit_code_failure_message="NFF-GO tests failed",
        )
