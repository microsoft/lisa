# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from dataclasses import dataclass
from typing import Any, List, Type, cast

from lisa.base_tools import Wget
from lisa.executable import Tool
from lisa.operating_system import Fedora, Oracle, Posix
from lisa.tools import KernelConfig, Modprobe, Uname
from lisa.util import (
    LisaException,
    UnsupportedKernelException,
    find_patterns_groups_in_lines,
)


@dataclass
class PktgenResult:
    #   13620pps 6Mb/sec (6537600bps) errors: 0
    #   81907pps 39Mb/sec (39315360bps) errors: 0
    _pps_pattern = re.compile(r"^\s+(?P<count>\d+)pps\s.*?$")
    # Result: OK: 1308215(c1307269+d946) usec, 1000000 (60byte,0frags)
    _sent_count_pattern = re.compile(
        r"^Result: OK: \d+\([\w\+]*\) usec, (?P<count>\d+) .*?$"
    )

    @classmethod
    def create(cls, output: str) -> "PktgenResult":
        pps_matches, sent_count_matches = find_patterns_groups_in_lines(
            output, [cls._pps_pattern, cls._sent_count_pattern]
        )
        pps = 0
        sent_count = 0
        for pps_match in pps_matches:
            pps += int(pps_match["count"])
        for sent_count_match in sent_count_matches:
            sent_count += int(sent_count_match["count"])

        return PktgenResult(pps=pps, sent_count=sent_count)

    pps: int = 0
    sent_count: int = 0


class Pktgen(Tool):
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

    def send_packets(
        self,
        destination_ip: str,
        destination_mac: str,
        # send 1,000,000 UDP packets need about 11 seconds with synthetic, 1.3
        # seconds with vf
        packet_count_per_thread: int = 1000000,
        nic_name: str = "",
        thread_count: int = 1,
    ) -> PktgenResult:
        """
        returns the packets count supposes to be sent.
        """
        if isinstance(self.node.os, Fedora):
            if isinstance(self.node.os, Oracle):
                kernel_ver = (
                    self.node.tools[Uname].get_linux_information().kernel_version
                )
                # by default, pktgen.ko.xz exists in Oracle
                # contained in kernel-uek-core-$(uname -r) package
                module_full_path = (
                    f"/usr/lib/modules/{kernel_ver}/kernel/net/core/pktgen.ko.xz"
                )
            else:
                module_full_path = str(self._tool_path / self._module_name)
            modprobe = self.node.tools[Modprobe]
            modprobe.remove([module_full_path], ignore_error=True)
            modprobe.load_by_file(module_full_path)

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

        result = self.node.execute(
            command,
            cwd=self._tool_path,
            expected_exit_code=0,
            expected_exit_code_failure_message="fail on run pktgen",
        )

        return PktgenResult.create(result.stdout)

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        # the command is decided by single or multiple thread. Use single here
        # as placeholder.
        self._tool_path = self.get_tool_path(use_global=True)
        self._command = f"{self._tool_path}/{self._single_thread_entry}"

    def _install(self) -> bool:
        wget = self.node.tools[Wget]
        if isinstance(self.node.os, Fedora) and not isinstance(self.node.os, Oracle):
            self._install_fedora()
        else:
            if not self.node.tools[KernelConfig].is_enabled("CONFIG_NET_PKTGEN"):
                raise UnsupportedKernelException(self.node.os)
        # download scripts to run pktgen
        for original_name, new_name in self._scripts.items():
            url = f"{self._root_url}/{original_name}?h={self._version}"
            wget.get(
                url, file_path=str(self._tool_path), filename=new_name, executable=True
            )

        return self._check_exists()

    def _install_fedora(self) -> None:
        posix = cast(Posix, self.node.os)
        kernel_information = posix.get_kernel_information()

        # TODO: To support more versions if it's needed. Currently, it's only
        # used in xdp, which starts from 8.x.
        if kernel_information.version.finalize_version() < "4.18.0":
            raise UnsupportedKernelException(self.node.os)

        # ['4', '18', '0', '305', '40', '1', 'el8_4', 'x86_64']
        # ['4', '18', '0', '240', 'el8', 'x86_64']
        parts = kernel_information.version_parts[:]

        # Full example:
        # https://repo.almalinux.org/almalinux/9.1/devel/x86_64/os/Packages/
        # kernel-modules-internal-5.14.0-162.12.1.el9_1.x86_64.rpm
        # Full example:
        # https://koji.mbox.centos.org/pkgs/packages/kernel-plus/4.18.0/
        #   240.1.1.el8_3.centos.plus/x86_64/kernel-plus-modules-internal-
        #   4.18.0-240.1.1.el8_3.centos.plus.x86_64.rpm",
        # Full example:
        # https://fbi2.cdn.euro-linux.com/dist/eurolinux/server/8/aarch64/certify-BaseOS
        #   /all/Packages/k/kernel-modules-internal-4.18.0-372.9.1.el8.aarch64.rpm
        rpm_locations = [
            (
                "https://repo.almalinux.org/almalinux/"
                f"{'.'.join(parts[-2].replace('el','').split('_'))}/devel/{parts[-1]}/"
                "os/Packages/kernel-modules-internal-"
                f"{'.'.join(parts[0:3])}-{'.'.join(parts[3:-1])}.{parts[-1]}.rpm"
            ),
            (
                "https://repo.almalinux.org/vault/"
                f"{'.'.join(parts[-2].replace('el','').split('_'))}/devel/{parts[-1]}/"
                "os/Packages/kernel-modules-internal-"
                f"{'.'.join(parts[0:3])}-{'.'.join(parts[3:-1])}.{parts[-1]}.rpm"
            ),
            (
                "https://koji.mbox.centos.org/pkgs/packages/kernel-plus/4.18.0/"
                f"{'.'.join(parts[3:-1])}.centos.plus/{parts[-1]}/"
                "kernel-plus-modules-internal-4.18.0-"
                f"{'.'.join(parts[3:-1])}.centos.plus.{parts[-1]}.rpm"
            ),
            (
                "https://fbi2.cdn.euro-linux.com/dist/eurolinux/server/"
                f"{parts[-2].replace('el','').split('_')[0]}/{parts[-1]}/certify-BaseOS"
                "/all/Packages/k/kernel-modules-internal-"
                f"{'.'.join(parts[0:3])}-{'.'.join(parts[3:-1])}.{parts[-1]}.rpm"
            ),
        ]
        # Install pkggen from CentOS for redhat, because there is no free
        # download for Redhat.
        package_file_name = "kernel-plus-modules-internal.rpm"

        is_download_success = False
        for rpm_location in rpm_locations:
            wget = self.node.tools[Wget]
            try:
                modules_file = wget.get(
                    url=rpm_location,
                    file_path=str(self._tool_path),
                    filename=package_file_name,
                    overwrite=True,
                )
                self.node.log.debug(f"download {rpm_location} successfully")
                is_download_success = True
                break
            except LisaException as ex:
                self.node.log.debug(f"fail to download {rpm_location}, exception {ex}")
                if "cannot find file path" in str(ex):
                    continue
        if not is_download_success:
            raise LisaException(
                "fail to download kernel-plus-modules-internal.rpm from given locations"
                ", please double check"
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
