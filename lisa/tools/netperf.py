# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, List, Type, cast

from lisa.executable import Tool
from lisa.operating_system import BSD, CBLMariner, Debian, Posix, Redhat, Suse
from lisa.util import LisaException
from lisa.util.process import Process

from .firewall import Firewall
from .gcc import Gcc
from .git import Git
from .make import Make
from .texinfo import Texinfo


class Netperf(Tool):
    repo = "https://github.com/HewlettPackard/netperf/"
    branch = "netperf-2.7.0"

    @property
    def command(self) -> str:
        return "netperf"

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Gcc, Git, Make, Texinfo]

    def run_as_server(
        self,
        port: int = 30000,
        daemon: bool = True,
        interface_ip: str = "",
    ) -> None:
        cmd = f"netserver -p {port} "
        if not daemon:
            cmd += " -D "
        if interface_ip:
            cmd += f" -L {interface_ip}"
        self.node.execute(
            cmd,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"fail to run {cmd}",
        )

    def run_as_client_async(
        self,
        server_ip: str,
        core_count: int,
        port: int = 30000,
        test_name: str = "TCP_RR",
        seconds: int = 150,
        time_unit: int = 1,
        interface_ip: str = "",
        send_recv_offset: str = "THROUGHPUT, THROUGHPUT_UNITS, MIN_LATENCY, MAX_LATENCY, MEAN_LATENCY, REQUEST_SIZE, RESPONSE_SIZE, STDDEV_LATENCY",  # noqa: E501
    ) -> Process:
        # -H: Specify the target machine and/or local ip and family
        # -L: Specify the IP for client interface to be used
        # -p: Specify netserver port number and/or local port
        # -t: Specify test to perform
        # -n: Set the number of processors for CPU util
        # -l: Specify test duration (>0 secs) (<0 bytes|trans)
        # -D: Display interim results at least every time interval using units as the
        #     initial guess for units per second. A negative value for time will make
        #     heavy use of the system's timestamping functionality
        # -O: Set the remote send,recv buffer offset
        cmd: str = ""
        if interface_ip:
            cmd += f" -L {interface_ip}"
        cmd += (
            f" -H {server_ip} -p {port} -t {test_name} -n {core_count} -l {seconds}"
            f" -D {time_unit} -- -O '{send_recv_offset}'"
        )
        process = self.node.execute_async(f"{self.command} {cmd}", sudo=True)
        return process

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        firewall = self.node.tools[Firewall]
        firewall.stop()

    def _install(self) -> bool:
        if not self._check_exists():
            if isinstance(self.node.os, BSD):
                self.node.os.install_packages("netperf")
            else:
                self._install_from_src()
        return self._check_exists()

    def _install_dep_packages(self) -> None:
        posix_os: Posix = cast(Posix, self.node.os)
        if isinstance(self.node.os, Redhat):
            package_list = ["sysstat", "wget", "automake"]
        elif isinstance(self.node.os, Debian):
            package_list = ["sysstat", "automake"]
        elif isinstance(self.node.os, Suse):
            package_list = ["sysstat", "automake"]
        elif isinstance(self.node.os, CBLMariner):
            package_list = [
                "kernel-headers",
                "binutils",
                "glibc-devel",
                "zlib-devel",
                "perl-CPAN",
                "automake",
                "autoconf",
            ]
        else:
            raise LisaException(
                f"tool {self.command} can't be installed in distro {self.node.os.name}."
            )
        for package in list(package_list):
            if posix_os.is_package_in_repo(package):
                posix_os.install_packages(package)

    def _install_from_src(self) -> None:
        self._install_dep_packages()
        tool_path = self.get_tool_path()
        git = self.node.tools[Git]
        git.clone(self.repo, tool_path, ref=self.branch)
        code_path = tool_path.joinpath("netperf")
        make = self.node.tools[Make]
        if self.node.shell.exists(self.node.get_pure_path(f"{code_path}/autogen.sh")):
            self.node.execute("./autogen.sh", cwd=code_path).assert_exit_code()
        configure_cmd = "./configure"
        arch = self.node.os.get_kernel_information().hardware_platform  # type: ignore
        if arch == "aarch64":
            configure_cmd += f" --build={arch}-unknown-linux-gnu"
        gcc_version = self.node.tools[Gcc].get_version()
        # fix compile issue when gcc version > 10
        if gcc_version >= "10.0.0":
            configure_cmd += " CC=gcc CFLAGS='-std=gnu89 -fcommon' "
        self.node.execute(configure_cmd, cwd=code_path).assert_exit_code()
        make.make_install(code_path)
        self.node.execute(
            "ln -s /usr/local/bin/netperf /usr/bin/netperf", sudo=True, cwd=code_path
        ).assert_exit_code()
        self.node.execute(
            "ln -s /usr/local/bin/netserver /usr/bin/netserver",
            sudo=True,
            cwd=code_path,
        ).assert_exit_code()
