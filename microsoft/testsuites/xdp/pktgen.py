# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Any, List, Type

from lisa.base_tools import Wget
from lisa.executable import Tool
from lisa.operating_system import Fedora
from lisa.tools import Modprobe


class PktGen(Tool):
    """
    The pktgen script from Linux kernel code
    """

    _root_url = (
        "https://git.kernel.org/pub/scm/linux/kernel/git"
        "/stable/linux.git/plain/samples/pktgen"
    )
    _version = "v5.7.8"
    _single_thread_entry = "run_single_thread.sh"
    _multi_thread_entry = "run_multiple_threads.sh"
    _scripts = {
        "pktgen_sample02_multiqueue.sh": _multi_thread_entry,
        "pktgen_sample01_simple.sh": _single_thread_entry,
        "functions.sh": "functions.sh",
        "parameters.sh": "parameters.sh",
    }
    _module_name = "pktgen.ko.xz"

    @property
    def command(self) -> str:
        return self._command

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Wget]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        # the command is decided by single or multiple thread. Use single here
        # as placeholder.
        self._tool_path = self.get_tool_path(use_global=True)
        self._command = f"{self._tool_path}/{self._single_thread_entry}"

    def _install(self) -> bool:
        wget = self.node.tools[Wget]
        if isinstance(self.node.os, Fedora):
            # Install pkggen from CentOS for redhat, because there is no free
            # download for Redhat.
            package_file_name = (
                "kernel-plus-modules-internal-4.18.0-305.25.1."
                "el8_4.centos.plus.x86_64.rpm"
            )
            modules_file = wget.get(
                url=f"https://vault.centos.org/centos/8/centosplus/x86_64/os/Packages/"
                f"{package_file_name}",
                file_path=str(self._tool_path),
                filename=package_file_name,
                overwrite=True,
            )
            # extract pktgen.ko.xz
            self.node.execute(
                f"rpm2cpio {modules_file} | "
                f"cpio -iv --to-stdout *{self._module_name} > {self._module_name}",
                shell=True,
                cwd=self._tool_path,
                expected_exit_code=0,
                expected_exit_code_failure_message=f"failed on extract {modules_file}.",
            )
        else:
            # assume other distros have the pktgen inside.
            ...

        # download scripts to run pktgen
        for original_name, new_name in self._scripts.items():
            url = f"{self._root_url}/{original_name}?h={self._version}"
            wget.get(
                url, file_path=str(self._tool_path), filename=new_name, executable=True
            )

        return self._check_exists()

    def send_packets(
        self,
        destination_ip: str,
        destination_mac: str,
        # send 1,000,000 UDP packets need about 11 seconds with synthetic, 1.3
        # seconds with vf
        packet_count_per_thread: int = 1000000,
        nic_name: str = "",
        thread_count: int = 1,
    ) -> int:
        """
        returns the packets count supposes to be sent.
        """
        if isinstance(self.node.os, Fedora):
            module_full_path = self._tool_path / self._module_name
            modprobe = self.node.tools[Modprobe]
            modprobe.remove([str(module_full_path)], ignore_error=True)
            modprobe.load_by_file(str(module_full_path))

        if thread_count == 1:
            command = self._single_thread_entry
        else:
            command = f"{self._multi_thread_entry} -t{thread_count}"
        if not nic_name:
            nic_name = self.node.nics.default_nic
        command = (
            f"./{command} -i {nic_name} -m {destination_mac} "
            f"-d {destination_ip} -v -n{packet_count_per_thread}"
        )

        self.node.execute(
            command,
            cwd=self._tool_path,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail on run pktgen",
        )

        return packet_count_per_thread * thread_count
