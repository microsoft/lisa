# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from pathlib import PurePath
from typing import Any, Dict

from lisa import (
    LisaException,
    Node,
    UnsupportedDistroException,
    UnsupportedOperationException,
)
from lisa.executable import Tool
from lisa.operating_system import AlmaLinux, CentOs, Debian, Fedora
from lisa.tools import Ethtool, Git, Make
from lisa.tools.ethtool import DeviceGroLroSettings
from lisa.util import find_groups_in_lines


def can_install(node: Node) -> bool:
    ethtool = node.tools[Ethtool]
    try:
        statistics = ethtool.get_device_statistics(node.nics.default_nic).counters
    except UnsupportedOperationException as e:
        raise UnsupportedDistroException(node.os, str(e))

    # check if xdp supported on nic
    if not any("xdp_drop" in x for x in statistics):
        raise UnsupportedDistroException(
            node.os,
            "Cannot find xdp_drop in ethtool statistics. "
            "It means this distro doesn't support XDP.",
        )

    return True


class XdpTool(Tool):
    """
    The community xdp tools, it's used to verify XDP by community test cases.
    """

    _xdp_tools_repo = "https://github.com/xdp-project/xdp-tools.git"
    _default_command = "xdptool"

    #     [test_ether_deny]             PASS
    #     [test_python_basic]           SKIPPED
    _xdp_test_result_pattern = re.compile(
        r"^\s+\[(?P<name>\w+)]\s+(?P<result>\w+)\r?$", re.M
    )

    @property
    def command(self) -> str:
        return str(self._command)

    @property
    def can_install(self) -> bool:
        return can_install(self.node)

    def run_full_test(self) -> None:
        """
        run full test of xdp tools repo
        """
        result = self.node.execute(
            "make test", sudo=True, cwd=self._code_path, timeout=800
        )

        abnormal_results: Dict[str, str] = {}
        for item in find_groups_in_lines(
            result.stdout, pattern=self._xdp_test_result_pattern
        ):
            if item["result"] not in ["PASS", "SKIPPED"]:
                abnormal_results[item["name"]] = item["result"]
        if abnormal_results:
            raise LisaException(f"found failed tests: {abnormal_results}")
        result.assert_exit_code(
            0, "unknown error on xdp tests, please check log for more details."
        )

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._command: PurePath = PurePath(self._default_command)
        self._gro_lro_settings: Dict[str, DeviceGroLroSettings] = {}
        # v1.6.3 is the first release that builds against glibc 2.43 and
        # gcc 15 (Ubuntu 26.04). Older tags fail on missing <limits.h> and
        # _GNU_SOURCE declarations. It also needs clang-11 or later.
        self._xdp_tools_tag = "v1.6.3"
        if (
            isinstance(self.node.os, Debian)
            and self.node.os.information.version <= "18.4.0"
        ):
            self._xdp_tools_tag = "v1.2.0"

    def _install(self) -> bool:
        # install dependencies

        config_envs: Dict[str, str] = {}
        arch = self.node.os.get_kernel_information().hardware_platform  # type: ignore
        if isinstance(self.node.os, Debian):
            if self.node.os.information.version < "18.4.0":
                raise UnsupportedDistroException(self.node.os)
            elif self.node.os.information.version == "18.4.0":
                self.node.os.add_repository("ppa:ubuntu-toolchain-r/test")
            else:
                toolchain = f"llvm-toolchain-{self.node.os.information.codename}"
                self.node.os.add_repository(
                    repo=(
                        f"deb http://apt.llvm.org/{self.node.os.information.codename}/ "
                        f"{toolchain} main"
                    ),
                    keys_location=["https://apt.llvm.org/llvm-snapshot.gpg.key"],
                )
            package_list = [
                "libelf-dev libpcap-dev build-essential pkg-config m4 tshark "
                "netcat-openbsd tcpdump iputils-ping ethtool nftables socat "
                "ndisc6 iputils-arping"
            ]
            if arch == "aarch64":
                for package in [
                    "gobjc-arm-linux-gnueabihf",
                    "gobjc-multilib-arm-linux-gnueabihf",
                ]:
                    if self.node.os.is_package_in_repo(package):
                        package_list.append(package)
            else:
                package_list.append("gcc-multilib")
            # Pick a clang/llvm pair of the same major version. The unversioned
            # "llvm" metapackage must not be used: the rolling
            # llvm-toolchain-<codename> repository makes it resolve to the
            # latest LLVM major version, whose runtime packages are not
            # installable alongside the versioned clang selected below.
            min_llvm_version = 10 if self._xdp_tools_tag == "v1.2.0" else 11
            for ver in range(18, min_llvm_version - 1, -1):
                clang_pkg = f"clang-{ver}"
                llvm_pkg = f"llvm-{ver}"
                if self.node.os.is_package_in_repo(
                    clang_pkg
                ) and self.node.os.is_package_in_repo(llvm_pkg):
                    package_list.append(clang_pkg)
                    package_list.append(llvm_pkg)
                    config_envs.update({"CLANG": clang_pkg, "LLC": f"llc-{ver}"})
                    break
            else:
                raise UnsupportedDistroException(
                    self.node.os,
                    f"No matching clang/llvm package pair for xdp-tools "
                    f"{self._xdp_tools_tag} (clang-18/llvm-18 through "
                    f"clang-{min_llvm_version}/llvm-{min_llvm_version}) found. "
                    "Check the configured APT repositories and package indexes; "
                    "ensure they provide both versioned packages of a matching "
                    "pair in this range.",
                )
            self.node.os.install_packages(package_list)

        elif isinstance(self.node.os, Fedora):
            if self.node.os.information.version >= "9.0.0":
                self.node.os.install_packages(
                    "http://mirror.stream.centos.org/9-stream/AppStream/"
                    f"{arch}/os/Packages/libpcap-devel-1.10.0-4.el9.{arch}.rpm"
                )
            else:
                if isinstance(self.node.os, CentOs) or isinstance(
                    self.node.os, AlmaLinux
                ):
                    self.node.os.install_packages("iproute-tc")
                else:
                    self.node.os.install_packages("tc")
                self.node.os.install_packages(
                    "https://vault.centos.org/centos/8/PowerTools/"
                    f"{arch}/os/Packages/libpcap-devel-1.9.1-5.el8.{arch}.rpm"
                )
            self.node.os.install_packages(
                "llvm-toolset elfutils-devel m4 wireshark perf make gcc nc tcpdump"
                # pcaplib
            )
            self._install_fedora_test_dependencies(self.node.os)
        else:
            raise UnsupportedDistroException(self.node.os)

        git = self.node.tools[Git]
        # use super() to prevent duplicate build.
        code_root_path = git.clone(
            self._xdp_tools_repo, cwd=super().get_tool_path(), ref=self._xdp_tools_tag
        )
        self._code_path = code_root_path
        # use xdpdump to detect if the tool is installed or not.
        self._command = self._code_path / "xdp-dump" / "xdpdump"

        configure_cmd = "./configure"
        if arch == "aarch64":
            configure_cmd += f" --build={arch}-unknown-linux-gnu"
        # create a default version for exists checking.
        self.node.execute(
            configure_cmd,
            cwd=code_root_path,
            update_envs=config_envs,
            expected_exit_code=0,
            expected_exit_code_failure_message="failed on configure xdp "
            "tools before make.",
        )
        make = self.node.tools[Make]
        # Errors happen if built with multi-threads. The program may not be
        # ready for concurrent build, but our make tool use multi-thread by
        # default. So set thread count to 1.
        if arch == "aarch64":
            update_envs = {"C_INCLUDE_PATH": "/usr/include/aarch64-linux-gnu/"}
        else:
            update_envs = {"ARCH": "x86_64"}
        # xdp-tools and its vendored libbpf submodule are built with "-Werror",
        # so a newer host compiler turns any new warning into a build failure.
        # gcc 15 on Ubuntu 26.04 hits this twice: "discarded-qualifiers" in the
        # libbpf pinned by xdp-tools v1.4.1, and "calloc-transposed-args" in
        # lib/util/params.c. Every host compile rule of both projects appends
        # CPPFLAGS after CFLAGS, so "-Wno-error" wins and keeps those
        # diagnostics as warnings. The BPF programs are unaffected and still
        # built with "-Werror", because the clang rules don't use CPPFLAGS.
        update_envs["CPPFLAGS"] = "-Wno-error"
        make.make(
            arguments="",
            cwd=self._code_path,
            update_envs=update_envs,
            thread_count=1,
        )

        return self._check_exists()

    def _install_fedora_test_dependencies(self, os: Fedora) -> None:
        # Extra tools required by the xdp-tools test runner. They are
        # probed individually because the package names are not available
        # on every Fedora derivative, and a missing one must not abort
        # the whole installation.
        for package in ["ethtool", "nftables", "socat", "ndisc6", "iputils"]:
            if os.is_package_in_repo(package):
                os.install_packages(package)
