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
from lisa.operating_system import CentOs, Debian, Fedora
from lisa.tools import Ethtool, Git, Make
from lisa.tools.ethtool import DeviceGroLroSettings
from lisa.util import find_groups_in_lines


def can_install(node: Node) -> bool:

    ethtool = node.tools[Ethtool]
    try:
        statistics = ethtool.get_device_statistics(node.nics.default_nic).counters
    except UnsupportedOperationException as identifier:
        raise UnsupportedDistroException(node.os, str(identifier))

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
    _xdp_tools_tag = "v1.2.0"
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

    def _install(self) -> bool:
        # install dependencies

        config_envs: Dict[str, str] = {}
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
                "llvm libelf-dev libpcap-dev gcc-multilib build-essential "
                "pkg-config m4 tshark"
            ]
            if self.node.os.information.version >= "22.10.0":
                package_list.append("clang-11")
                config_envs.update({"CLANG": "clang-11", "LLC": "llc-11"})
            else:
                package_list.append("clang-10")
                config_envs.update({"CLANG": "clang-10", "LLC": "llc-10"})
            self.node.os.install_packages(package_list)

        elif isinstance(self.node.os, Fedora):
            if self.node.os.information.version >= "9.0.0":
                self.node.os.install_packages(
                    "http://mirror.stream.centos.org/9-stream/AppStream/"
                    "x86_64/os/Packages/libpcap-devel-1.10.0-4.el9.x86_64.rpm"
                )
            else:
                if isinstance(self.node.os, CentOs):
                    self.node.os.install_packages("iproute-tc")
                else:
                    self.node.os.install_packages("tc")
                self.node.os.install_packages(
                    "https://vault.centos.org/centos/8/PowerTools/"
                    "x86_64/os/Packages/libpcap-devel-1.9.1-5.el8.x86_64.rpm"
                )
            self.node.os.install_packages(
                "llvm-toolset elfutils-devel m4 wireshark perf make gcc"
                # pcaplib
            )
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

        # create a default version for exists checking.
        self.node.execute(
            "./configure",
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
        make.make(
            arguments="",
            cwd=self._code_path,
            update_envs={"ARCH": "x86_64"},
            thread_count=1,
        )

        return self._check_exists()
