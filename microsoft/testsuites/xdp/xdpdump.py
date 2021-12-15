# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePath
from typing import Any, Callable, Dict, Optional

from lisa import UnsupportedDistroException
from lisa.executable import Tool
from lisa.operating_system import Fedora, Ubuntu
from lisa.tools import Ethtool, Git, Make
from lisa.tools.ethtool import DeviceGroLroSettings


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
        self._gro_lro_settings: Dict[str, DeviceGroLroSettings] = {}

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

    def test(
        self,
        nic_name: str = "",
        timeout: int = 5,
        action: Optional[Callable[..., None]] = None,
    ) -> str:
        if not nic_name:
            nic_name = self.node.nics.default_nic

        try:
            self._disable_lro(nic_name)
            command = f"timeout {timeout} {self.command} -i {nic_name}"

            # if there is an action defined, test it in async mode.
            if action:
                xdpdump_process = self.node.execute_async(
                    command,
                    shell=True,
                    sudo=True,
                    cwd=self._command.parent,
                )
                action()
                result = xdpdump_process.wait_result()
            else:
                result = self.node.execute(
                    command,
                    shell=True,
                    sudo=True,
                    cwd=self._command.parent,
                )
        finally:
            self._restore_lro(nic_name)

        return result.stdout

    def _disable_lro(self, nic_name: str) -> None:
        ethtool = self.node.tools[Ethtool]
        gro_lro_settings = self._get_gro_lro_settings(nic_name)

        if gro_lro_settings.lro_setting is False:
            return

        # disable LRO (RSC), because XDP program cannot run with it. Restore
        # it after test completed.
        ethtool.change_device_gro_lro_settings(
            nic_name,
            gro_setting=gro_lro_settings.gro_setting,
            lro_setting=False,
        )

    def _restore_lro(self, nic_name: str) -> None:
        # recover settings
        ethtool = self.node.tools[Ethtool]
        current_settings = ethtool.get_device_gro_lro_settings(nic_name, force_run=True)
        original_settings = self._get_gro_lro_settings(nic_name)

        if original_settings.lro_setting == current_settings.lro_setting:
            return

        ethtool.change_device_gro_lro_settings(
            nic_name,
            gro_setting=original_settings.gro_setting,
            lro_setting=original_settings.lro_setting,
        )

    def _get_gro_lro_settings(self, nic_name: str) -> DeviceGroLroSettings:
        gro_lro_settings = self._gro_lro_settings.get(nic_name, None)
        ethtool = self.node.tools[Ethtool]

        if gro_lro_settings is None:
            gro_lro_settings = ethtool.get_device_gro_lro_settings(
                nic_name, force_run=True
            )
            self._gro_lro_settings[nic_name] = gro_lro_settings
        return gro_lro_settings
