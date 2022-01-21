# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from enum import Enum
from pathlib import PurePath
from typing import Any, Dict, Optional

from assertpy import assert_that

from lisa import Node, UnsupportedDistroException
from lisa.executable import Tool
from lisa.operating_system import Fedora, Ubuntu
from lisa.tools import Ethtool, Git, Make, Ping
from lisa.tools.ethtool import DeviceGroLroSettings
from microsoft.testsuites.xdp.xdptools import can_install


class ActionType(str, Enum):
    TX = "TX"
    DROP = "DROP"
    ABORTED = "ABORTED"


class XdpDump(Tool):
    """
    This repo is a copy of bpf samples from
    https://github.com/Netronome/bpf-samples, it's to keep a stable version.
    This sample lib is easy to cover more test scenarios than official samples.
    """

    _bpf_samples_repo = "https://github.com/LIS/bpf-samples.git"

    @property
    def command(self) -> str:
        return str(self._command)

    @property
    def can_install(self) -> bool:
        return can_install(self.node)

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._command: PurePath = PurePath("xdpdump")
        self._gro_lro_settings: Dict[str, DeviceGroLroSettings] = {}

    def _install(self) -> bool:
        # install dependencies
        if isinstance(self.node.os, Ubuntu):
            if self.node.os.information.version < "18.4.0":
                raise UnsupportedDistroException(self.node.os)
            elif self.node.os.information.version == "18.4.0":
                toolchain = f"llvm-toolchain-{self.node.os.information.codename}-6.0"
            else:
                toolchain = f"llvm-toolchain-{self.node.os.information.codename}"

            self.node.os.add_repository(
                repo=(
                    f"deb http://apt.llvm.org/{self.node.os.information.codename}/ "
                    f"{toolchain} main"
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
        self._code_path = git.clone(self._bpf_samples_repo, cwd=self.get_tool_path())
        self._code_path = self._code_path / "xdpdump"
        git.init_submodules(cwd=self._code_path)
        self._command = self._code_path / "xdpdump"

        # create a default version for exists checking.
        make = self.node.tools[Make]
        make.make(
            arguments="",
            cwd=self._code_path,
        )

        return self._check_exists()

    def test(
        self,
        nic_name: str = "",
        timeout: int = 5,
        action_type: Optional[ActionType] = None,
        remote_address: str = "",
        expected_ping_success: bool = True,
        ping_package_size: Optional[int] = None,
        # the ping command can be triggered from different node
        ping_source_node: Optional[Node] = None,
    ) -> str:
        """
        Test with ICMP ping packets
        """
        if not nic_name:
            nic_name = self.node.nics.default_nic
        if not ping_source_node:
            ping_source_node = self.node

        self._make_by_action_type(action_type=action_type)

        try:
            self._disable_lro(nic_name)
            command = f"timeout {timeout} {self.command} -i {nic_name}"

            # if there is an remote address defined, test it in async mode, and
            # check the ping result.

            if remote_address:
                ping = ping_source_node.tools[Ping]

                xdpdump_process = self.node.execute_async(
                    command,
                    shell=True,
                    sudo=True,
                    cwd=self._command.parent,
                )

                is_success = ping.ping(
                    remote_address,
                    nic_name=nic_name,
                    ignore_error=True,
                    package_size=ping_package_size,
                )
                assert_that(is_success).described_as(
                    "ping result is not expected."
                ).is_equal_to(expected_ping_success)

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

    def _make_by_action_type(self, action_type: Optional[ActionType] = None) -> None:
        env_variables: Dict[str, str] = {}

        # if no action type specified, rebuild it with default behavior.
        if action_type:
            env_variables[
                "CFLAGS"
            ] = f"-D __ACTION_{action_type.name}__ -I../libbpf/src/root/usr/include"

        make = self.node.tools[Make]
        make.make(
            arguments="",
            cwd=self._code_path,
            is_clean=True,
            update_envs=env_variables,
        )

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
