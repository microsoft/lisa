# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from enum import Enum
from typing import Any, Dict, Optional

from assertpy import assert_that

from lisa import Node, UnsupportedDistroException
from lisa.executable import ExecutableResult, Tool
from lisa.nic import NicInfo
from lisa.operating_system import CBLMariner, Fedora, Ubuntu
from lisa.tools import Ethtool, Git, Make, Ping, Sed
from lisa.tools.ethtool import DeviceGroLroSettings
from lisa.util.process import Process
from microsoft.testsuites.xdp.xdptools import can_install


class BuildType(str, Enum):
    ACTION_TX = "ACTION_TX"
    ACTION_DROP = "ACTION_DROP"
    ACTION_ABORTED = "ACTION_ABORTED"
    TX_FWD = "TX_FWD"
    PERF_DROP = "PERF_DROP"
    PERF = "PERF"


class XdpDump(Tool):
    """
    This repo is a copy of bpf samples from
    https://github.com/Netronome/bpf-samples, it's to keep a stable version.
    This sample lib is easy to cover more test scenarios than official samples.
    """

    _bpf_samples_repo = "https://github.com/LIS/bpf-samples.git"

    @property
    def command(self) -> str:
        return str(self._code_path / "xdpdump")

    @property
    def can_install(self) -> bool:
        return can_install(self.node)

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._gro_lro_settings: Dict[str, DeviceGroLroSettings] = {}
        self._code_path = (
            self.get_tool_path(use_global=True) / "bpf-samples" / "xdpdump"
        )

    def _check_exists(self) -> bool:
        return self.node.shell.exists(self._code_path)

    def _install(self) -> bool:
        # install dependencies
        if isinstance(self.node.os, Ubuntu):
            if self.node.os.information.version < "18.4.0":
                raise UnsupportedDistroException(self.node.os)
            else:
                toolchain = f"llvm-toolchain-{self.node.os.information.codename}-18"

            self.node.os.add_repository(
                repo=(
                    f"deb http://apt.llvm.org/{self.node.os.information.codename}/ "
                    f"{toolchain} main"
                ),
                keys_location=["https://apt.llvm.org/llvm-snapshot.gpg.key"],
            )

            self.node.os.install_packages(
                "clang llvm libelf-dev build-essential libbpfcc-dev"
            )
        elif isinstance(self.node.os, Fedora):
            self.node.os.install_packages("git llvm clang elfutils-devel make gcc")
        elif isinstance(self.node.os, CBLMariner):
            self.node.os.install_packages(
                "git llvm clang elfutils-devel make gcc kernel-headers binutils "
                "glibc-devel zlib-devel cmake clang-devel"
            )
        else:
            raise UnsupportedDistroException(self.node.os)

        git = self.node.tools[Git]
        code_path = git.clone(
            self._bpf_samples_repo, cwd=self.get_tool_path(use_global=True)
        )
        assert_that(code_path).described_as(
            "xdpdump cloned path is inconsistent with pre-configured"
        ).is_equal_to(self._code_path.parent)
        git.init_submodules(cwd=self._code_path)

        # This workaround addresses a discrepancy in the bpf_perf_event_read_simple
        # function declaration and definition detected by the latest version of
        # the clang C compiler. Specifically, the return value is incorrectly specified
        # as an int in the .h file but as an enum in the C file.
        sed = self.node.tools[Sed]
        sed.substitute(
            "LIBBPF_API int bpf_perf_event_read_simple",
            "LIBBPF_API enum bpf_perf_event_ret bpf_perf_event_read_simple",
            f"{self._code_path.parent}/libbpf/src/libbpf.h",
            sudo=True,
        )

        # create a default version for exists checking.
        make = self.node.tools[Make]
        make.make(
            arguments="",
            cwd=self._code_path,
        )

        return self._check_exists()

    def start_async(self, nic_name: str = "", timeout: int = 5) -> Process:
        try:
            self._disable_lro(nic_name)
            command = "ulimit -l unlimited && "
            if timeout > 0:
                command += f"timeout {timeout}"
            command = f"{command} {self.command} -i {nic_name}"
            xdpdump_process = self.node.execute_async(
                command,
                shell=True,
                sudo=True,
                cwd=self._code_path,
            )
        except Exception as e:
            self._restore_lro(nic_name)
            raise e

        # wait to receive at least one packet or 1 second to make sure the
        # process started.
        xdpdump_process.wait_output("IP", timeout=1, error_on_missing=False)

        return xdpdump_process

    def start(self, nic_name: str = "", timeout: int = 5) -> ExecutableResult:
        process = self.start_async(nic_name=nic_name, timeout=timeout)
        return self.wait_result(nic_name=nic_name, process=process)

    def wait_result(self, nic_name: str, process: Process) -> ExecutableResult:
        try:
            result = process.wait_result()
        finally:
            self._restore_lro(nic_name)
        return result

    def test_by_ping(
        self,
        nic_name: str = "",
        timeout: int = 5,
        build_type: Optional[BuildType] = None,
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

        self.make_by_build_type(build_type=build_type)

        # if there is an remote address defined, test it in async mode, and
        # check the ping result.

        if remote_address:
            ping = ping_source_node.tools[Ping]

        xdpdump_process = self.start_async(nic_name=nic_name, timeout=timeout)

        if remote_address:
            is_success = ping.ping(
                remote_address,
                nic_name=nic_name,
                ignore_error=True,
                package_size=ping_package_size,
            )
            assert_that(is_success).described_as(
                "ping result is not expected."
            ).is_equal_to(expected_ping_success)

        result = self.wait_result(nic_name=nic_name, process=xdpdump_process)

        return result.stdout

    def make_by_build_type(self, build_type: Optional[BuildType] = None) -> None:
        env_variables: Dict[str, str] = {}

        # if no build type specified, rebuild it with default behavior.
        if build_type:
            cflags = f"-D __{build_type.name}__ -I../libbpf/src/root/usr/include"

            # no output log to improve perf with high volume data.
            if build_type in [BuildType.PERF_DROP, BuildType.TX_FWD, BuildType.PERF]:
                cflags = f"{cflags} -D __PERF__"
            env_variables["CFLAGS"] = cflags

        make = self.node.tools[Make]
        make.make(
            arguments="",
            cwd=self._code_path,
            is_clean=True,
            update_envs=env_variables,
        )

        # discard local changes after built, it's used to cleanup changes from
        # the forwarder role.
        git = self.node.tools[Git]
        git.discard_local_changes(cwd=self._code_path)

    def make_on_forwarder_role(
        self,
        forwarder_nic: NicInfo,
        receiver_nic: NicInfo,
    ) -> None:
        sed = self.node.tools[Sed]
        # replace hard code mac and ip addresses in code, the changes will be
        # reset after built.
        forwarder_mac = self._convert_mac_to_c_style(forwarder_nic.mac_addr)
        forwarder_ip = self._convert_ip_to_c_style(forwarder_nic.ip_addr)
        receiver_mac = self._convert_mac_to_c_style(receiver_nic.mac_addr)
        receiver_ip = self._convert_ip_to_c_style(receiver_nic.ip_addr)

        sed.substitute(
            regexp=r"unsigned char newethsrc \[\] = "
            "{ 0x00, 0x22, 0x48, 0x4c, 0xc4, 0x4d };",
            replacement=r"unsigned char newethsrc \[\] = {" + forwarder_mac + "};",
            file=f"{self._code_path}/xdpdump_kern.c",
        )
        sed.substitute(
            regexp=r"unsigned char newethdest \[\] = "
            "{ 0x00, 0x22, 0x48, 0x4c, 0xc0, 0xfd };",
            replacement=r"unsigned char newethdest \[\] = {" + receiver_mac + "};",
            file=f"{self._code_path}/xdpdump_kern.c",
        )
        sed.substitute(
            regexp=r"__u8 newsrc \[\] = { 10, 0, 1, 5 };",
            replacement=r"__u8 newsrc \[\] = {" + forwarder_ip + "};",
            file=f"{self._code_path}/xdpdump_kern.c",
        )
        sed.substitute(
            regexp=r"__u8 newdest \[\] = { 10, 0, 1, 4 };",
            replacement=r"__u8 newdest \[\] = {" + receiver_ip + "};",
            file=f"{self._code_path}/xdpdump_kern.c",
        )

        self.make_by_build_type(build_type=BuildType.TX_FWD)

    def _convert_mac_to_c_style(self, mac: str) -> str:
        """
        convert 00:22:48:7a:ed:28 to 0x00, 0x22, 0x48, 0x7a, 0xed, 0x28
        """
        bytes_list = [f"0x{x}" for x in mac.split(":")]
        return ", ".join(bytes_list)

    def _convert_ip_to_c_style(self, ip: str) -> str:
        """
        convert 10.0.0.1 to 10, 0, 0, 1
        """
        return ", ".join(ip.split("."))

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
