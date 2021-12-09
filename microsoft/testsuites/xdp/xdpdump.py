# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath
from typing import Any

from lisa.executable import Tool
from lisa.operating_system import Fedora, Ubuntu
from lisa.tools import Ethtool, Git, Make
from lisa.util import UnsupportedDistroException


class XdpDump(Tool):
    _bpf_samples_repo = "https://github.com/LIS/bpf-samples.git"

    @property
    def command(self) -> str:
        return str(self._command)

    @property
    def can_install(self) -> bool:
        ethtool = self.node.tools[Ethtool]
        statistics = ethtool.get_device_statistics(self.node.nics.default_nic)

        # check if xdp supported on nic
        if not any("xdp_drop" in x for x in statistics):
            raise UnsupportedDistroException(
                self.node.os,
                "Cannot find xdp_drop in ethotool statistics. "
                "It means it doesn't support XDP.",
            )

        return True

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._command: PurePath = PurePath("xdpdump")

    def _install(self) -> bool:
        # install dependencies
        if isinstance(self.node.os, Ubuntu):
            if self.node.os.information.version < "18.4.0":
                raise UnsupportedDistroException(self.node.os)

            self.node.os.add_repository(
                repo=(
                    f"deb http://apt.llvm.org/{self.node.os.information.codename}/ "
                    f"llvm-toolchain-{self.node.os.information.codename}-6.0 "
                    "main"
                ),
                key_location="https://apt.llvm.org/llvm-snapshot.gpg.key",
            )

            self.node.os.install_packages(
                "clang llvm libelf-dev build-essential libbpfcc-dev"
            )
        elif isinstance(self.node.os, Fedora):
            self.node.os.install_packages("git llvm clang elfutils-devel make")
        else:
            raise UnsupportedDistroException(self.node.os)

        git = self.node.tools[Git]
        cloned_path = git.clone(self._bpf_samples_repo, cwd=self.get_tool_path())
        git.init_submodules(cwd=cloned_path)
        make = self.node.tools[Make]
        make.make(arguments="", cwd=cloned_path / "xdpdump", sudo=False)
        self._command = cloned_path / "xdpdump" / "xdpdump"

        return self._check_exists()

    def test(self, timeout: int = 10) -> str:
        ethtool = self.node.tools[Ethtool]
        gro_lro_settings = ethtool.get_device_gro_lro_settings(
            self.node.nics.default_nic, force_run=True
        )

        try:
            # disable LRO (RSC), because XDP program cannot run with it. Restore
            # it after test completed.
            ethtool.change_device_gro_lro_settings(
                self.node.nics.default_nic,
                gro_setting=gro_lro_settings.gro_setting,
                lro_setting=False,
            )

            result = self.node.execute(
                f"timeout {timeout} {self.command} -i {self.node.nics.default_nic}",
                shell=True,
                sudo=True,
                cwd=self._command.parent,
            )

        finally:
            # recover settings
            ethtool.change_device_gro_lro_settings(
                self.node.nics.default_nic,
                gro_setting=gro_lro_settings.gro_setting,
                lro_setting=gro_lro_settings.lro_setting,
            )
        return result.stdout
