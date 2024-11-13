# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from lisa.executable import Tool
from lisa.operating_system import CpuArchitecture, Oracle, Redhat, Suse, Ubuntu
from lisa.tools.gcc import Gcc
from lisa.tools.git import Git
from lisa.util import UnsupportedDistroException


class Modetest(Tool):
    repo = "https://github.com/grate-driver/libdrm"

    @property
    def command(self) -> str:
        return "modetest"

    @property
    def can_install(self) -> bool:
        return True

    def is_status_connected(self, driver_name: str) -> bool:
        cmd_result = self.run(
            f"-M {driver_name}", sudo=True, shell=True, force_run=True
        )
        # output segment
        # Connectors:
        # id encoder status          name             size (mm)       modes   encoders
        # 31 35      connected       Virtual-1        0x0             24      35
        return any("connected" in line for line in cmd_result.stdout.splitlines())

    def _install(self) -> bool:
        if isinstance(self.node.os, Ubuntu):
            self.node.os.install_packages("libdrm-tests")
        if isinstance(self.node.os, Redhat) or isinstance(self.node.os, Suse):
            self._install_from_src()
        return self._check_exists()

    def _install_dep_packages(self) -> None:
        if isinstance(self.node.os, Redhat):
            arch = self.node.os.get_kernel_information().hardware_platform
            libpciaccess = f"libpciaccess-devel.{arch}"
            if arch == CpuArchitecture.ARM64:
                # skip libpciaccess-devel installation for aarch64
                libpciaccess = ""
            self.node.os.install_packages(
                (
                    "make",
                    "autoconf",
                    "automake",
                    libpciaccess,
                    "libtool",
                    f"http://mirror.stream.centos.org/9-stream/CRB/{arch}/os/Packages/xorg-x11-util-macros-1.19.3-4.el9.noarch.rpm",  # noqa: E501
                )
            )
            if isinstance(self.node.os, Oracle):
                major = self.node.os.information.version.major
                self.node.os.install_packages(
                    (
                        "ninja-build",
                        "meson",
                    ),
                    extra_args=[f"--enablerepo=ol{major}_codeready_builder"],
                )
            else:
                self.node.os.install_packages(
                    (
                        f"http://mirror.stream.centos.org/9-stream/CRB/{arch}/os/Packages/ninja-build-1.10.2-6.el9.{arch}.rpm",  # noqa: E501
                        f"http://mirror.stream.centos.org/9-stream/CRB/{arch}/os/Packages/meson-0.58.2-1.el9.noarch.rpm",  # noqa: E501
                    )
                )
        elif isinstance(self.node.os, Suse):
            arch = self.node.os.get_kernel_information().hardware_platform
            os_version = self.node.os.information.release.split(".")
            self.node.os.install_packages(
                (
                    Gcc,
                    "make",
                    "autoconf",
                    "automake",
                    "libtool",
                    "meson",
                    "libpciaccess-devel",
                    f"https://rpmfind.net/linux/opensuse/distribution/leap/{os_version[0]}.{os_version[1]}/repo/oss/{arch}/util-macros-devel-1.19.1-1.22.{arch}.rpm",  # noqa: E501
                )
            )
        else:
            raise UnsupportedDistroException(self.node.os)

    def _install_from_src(self) -> None:
        self._install_dep_packages()
        tool_path = self.get_tool_path()
        self.node.tools[Git].clone(self.repo, tool_path)
        code_path = tool_path.joinpath("libdrm")
        self.node.execute(
            "./autogen.sh --enable-install-test-programs", cwd=code_path
        ).assert_exit_code()
        self.node.execute(
            "meson builddir/", cwd=code_path, sudo=True
        ).assert_exit_code()
        self.node.execute(
            "ninja -C builddir/ install", cwd=code_path, sudo=True
        ).assert_exit_code()
        self.node.execute(
            f"ln -s {code_path}/builddir/tests/modetest/modetest /usr/bin/modetest",
            sudo=True,
            cwd=code_path,
        ).assert_exit_code()
