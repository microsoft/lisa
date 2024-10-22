# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import math
import re
from pathlib import PurePath, PurePosixPath
from time import sleep
from typing import TYPE_CHECKING, Any, List, Type

from semver import VersionInfo

from lisa.base_tools import Cat, Sed, Service, Wget
from lisa.executable import Tool
from lisa.operating_system import CBLMariner, Debian, Oracle, Posix, Redhat, Suse
from lisa.tools import Find, Gcc
from lisa.tools.lsblk import Lsblk
from lisa.tools.lscpu import Lscpu
from lisa.tools.make import Make
from lisa.tools.sysctl import Sysctl
from lisa.tools.tar import Tar
from lisa.util import LisaException, UnsupportedDistroException

from .kernel_config import KernelConfig

if TYPE_CHECKING:
    from lisa.node import Node


class Kexec(Tool):
    """
    kexec - directly boot into a new kernel
    kexec is a system call that enables you to load and boot into another
    kernel from the currently running kernel. The primary difference between
    a standard system boot and a kexec boot is that the hardware initialization
    normally performed by the BIOS or firmware (depending on architecture)
    is not performed during a kexec boot. This has the effect of reducing the
    time required for a reboot.

    This tool is used for managing the installation of kexec.
    """

    # kexec-tools 2.0.16
    __pattern_kexec_version_info = re.compile(
        r"^kexec\S+\s+(?P<major>\d+).(?P<minor>\d+).(?P<patch>\d+)"
    )

    # Existed bug for kexec-tools 2.0.14
    # https://bugs.launchpad.net/ubuntu/+source/kexec-tools/+bug/1713940
    # If the version of kexec-tools is lower than 2.0.15, we install kexec from source
    _target_kexec_version = "2.0.15"

    # If install kexec from source, we choose 2.0.18 version for it is stable for most
    # Debian distros
    _kexec_repo = (
        "https://mirrors.edge.kernel.org/pub/linux/utils/kernel/kexec/"
        "kexec-tools-2.0.18.tar.gz"
    )

    @property
    def command(self) -> str:
        return "kexec"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        assert isinstance(self.node.os, Posix)
        self.node.os.install_packages("kexec-tools")
        if isinstance(self.node.os, Debian):
            version = self._get_version()
            if version < self._target_kexec_version:
                self._install_from_src()
        return self._check_exists()

    def _get_version(self) -> VersionInfo:
        result = self.run(
            "-v",
            force_run=False,
            no_error_log=True,
            no_info_log=True,
            sudo=True,
            shell=False,
        )
        result.assert_exit_code(message=result.stderr)
        raw_version = re.finditer(self.__pattern_kexec_version_info, result.stdout)
        for version in raw_version:
            matched_version = self.__pattern_kexec_version_info.match(version.group())
            if matched_version:
                major = matched_version.group("major")
                minor = matched_version.group("minor")
                patch = matched_version.group("patch")
                self._log.info(f"kexec version is {major}.{minor}.{patch}")
                return VersionInfo(int(major), int(minor), int(patch))
        raise LisaException("No find matched kexec version")

    def _install_from_src(self) -> None:
        tool_path = self.get_tool_path()
        wget = self.node.tools[Wget]
        kexec_tar = wget.get(self._kexec_repo, str(tool_path))
        tar = self.node.tools[Tar]
        tar.extract(kexec_tar, str(tool_path))
        find_tool = self.node.tools[Find]
        kexec_source_folder = find_tool.find_files(
            tool_path, name_pattern="kexec-tools*", file_type="d"
        )
        code_path = tool_path.joinpath(kexec_source_folder[0])
        self.node.tools.get(Gcc)  # Ensure gcc is installed
        make = self.node.tools[Make]
        self.node.execute(
            "./configure",
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Fail to run configure when compiling kexec-tools from source code"
            ),
            cwd=code_path,
            sudo=True,
        )
        make.make_install(cwd=code_path, sudo=True)
        self.node.execute(
            "yes | cp -f /usr/local/sbin/kexec /sbin/",
            expected_exit_code=0,
            expected_exit_code_failure_message=("It is failed to copy kexec to /sbin/"),
            sudo=True,
            shell=True,
        )


class Makedumpfile(Tool):
    """
    makedumpfile - make a small dumpfile of kdump
    With kdump, the memory image of the first kernel can be taken as vmcore
    while the second kernel is running. makedumpfile makes a small DUMPFILE by
    compressing dump data or by excluding unnecessary pages for analysis, or both.

    This tool is used for managing the installation of makedumpfile.
    """

    @property
    def command(self) -> str:
        return "makedumpfile"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        assert isinstance(self.node.os, Posix)
        if isinstance(self.node.os, Redhat) or isinstance(self.node.os, CBLMariner):
            self.node.os.install_packages("kexec-tools")
        else:
            self.node.os.install_packages("makedumpfile")
        return self._check_exists()


class KdumpBase(Tool):
    """
    kdump is a feature of the Linux kernel that creates crash dumps in the event of a
    kernel crash. When triggered, kdump exports a memory image (also known as vmcore)
    that can be analyzed for the purposes of debugging and determining the cause of a
    crash.

    kdump tool manages the kdump feature of the Linux kernel. Different distro os has
    different kdump tool.

    KdumpBase is a basic class, it returns sub instance according to distros. We can
    support Redhat, Suse, Debian family distro now.
    """

    # If the file /sys/kernel/kexec_crash_loaded does not exist. This means that the
    # currently running kernel either was not configured to support kdump, or that a
    # crashkernel= commandline parameter was not used when the currently running kernel
    # booted. Value "1" means crash kernel is loaded, otherwise not loaded.
    #
    # It also has /sys/kernel/kexec_crash_size file, which record the crash kernel size
    # of memory reserved. We don't need to check this file in our test case.
    kexec_crash = "/sys/kernel/kexec_crash_loaded"

    # This file shows you the current map of the system's memory for each physical
    # device. We can check /proc/iomem file for memory reserved for crash kernel.
    iomem = "/proc/iomem"

    # Following are the configuration setting required for system and dump-capture
    # kernels for enabling kdump support.
    required_kernel_config = [
        "CONFIG_CRASH_DUMP",
        "CONFIG_PROC_VMCORE",
    ]

    kexec_kernel_configs = [
        "CONFIG_KEXEC",
        "CONFIG_KEXEC_FILE",
    ]

    dump_path = "/var/crash"

    @classmethod
    def create(cls, node: "Node", *args: Any, **kwargs: Any) -> Tool:
        # FreeBSD image doesn't support kdump since the kernel has no DDB option
        if isinstance(node.os, Redhat):
            return KdumpRedhat(node)
        elif isinstance(node.os, Debian):
            return KdumpDebian(node)
        elif isinstance(node.os, Suse):
            return KdumpSuse(node)
        elif isinstance(node.os, CBLMariner):
            return KdumpCBLMariner(node)
        else:
            raise UnsupportedDistroException(os=node.os)

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Kexec, Makedumpfile]

    @property
    def command(self) -> str:
        raise NotImplementedError()

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        raise NotImplementedError()

    def check_required_kernel_config(self) -> None:
        kexec_config_present = False
        for config in self.kexec_kernel_configs:
            if self.node.tools[KernelConfig].is_built_in(config):
                kexec_config_present = True
                break
        if not kexec_config_present:
            raise LisaException(
                "The kernel config CONFIG_KEXEC or CONFIG_KEXEC_FILE is not set. "
                "Kdump is not supported."
            )
        for config in self.required_kernel_config:
            if not self.node.tools[KernelConfig].is_built_in(config):
                raise LisaException(
                    "The kernel config {config} is not set. Kdump is not supported."
                )

    def calculate_crashkernel_size(self, total_memory: str) -> str:
        # Ubuntu, Redhat and Suse have different proposed crashkernel settings
        # Please see below refrences:
        # Ubuntu: https://ubuntu.com/server/docs/kernel-crash-dump
        # Redhat: https://access.redhat.com/documentation/en-us/red_hat_enterprise_
        #         linux/7/html/kernel_administration_guide/kernel_crash_dump_guide
        # SUSE: https://www.suse.com/support/kb/doc/?id=000016171
        # We combine their configuration to set an empirical value
        arch = self.node.os.get_kernel_information().hardware_platform  # type: ignore
        if (
            "G" in total_memory
            and float(total_memory.strip("G")) < 1
            or "M" in total_memory
            and float(total_memory.strip("M")) < 1024
        ):
            if arch == "x86_64":
                crash_kernel = "64M"
            else:
                # For arm64 with page size == 4k, the memory "section size" is 128MB,
                # that's the granularity of memory hotplug and also the minimal size of
                # manageable memory if SPARSEMEM is selected. More memory is needed for
                # kdump kernel
                crash_kernel = "256M"
        elif (
            "G" in total_memory
            and float(total_memory.strip("G")) < 2
            or "M" in total_memory
            and float(total_memory.strip("M")) < 2048
        ):
            crash_kernel = "256M"
        elif "T" in total_memory and float(total_memory.strip("T")) > 1:
            crash_kernel = "1G"
        else:
            crash_kernel = "512M"
        return crash_kernel

    def _get_crashkernel_cfg_file(self) -> str:
        """
        This method returns the path of cfg file where we configure crashkernel memory.
        If distro has a different cfg file path, override it.
        """
        return "/etc/default/grub"

    def _get_crashkernel_cfg_cmdline(self) -> str:
        """
        This method returns the cmdline string where we can configure crashkernel memory
        in the file _get_crashkernel_cfg_file returns.
        If distro has a different cmdline, override it.
        """
        return "GRUB_CMDLINE_LINUX"

    def _get_crashkernel_update_cmd(self, crashkernel: str) -> str:
        """
        After setting crashkernel into grub cfg file, need updating grub configuration.
        This function returns the update command string. If distro has a different
        command, override this method.
        """
        return "grub2-mkconfig -o /boot/grub2/grub.cfg"

    def _get_kdump_service_name(self) -> str:
        """
        This method returns the name of kdump service. If distro has a different name,
        needs override it.
        """
        return "kdump"

    def config_crashkernel_memory(
        self,
        crashkernel: str,
    ) -> None:
        if not crashkernel:
            # If the crashkernel is empty, use the default setting.
            # No need to config again
            return
        # For Redhat 8 and later version, the cfg_file should be None.
        cfg_file = self._get_crashkernel_cfg_file()
        cmdline = self._get_crashkernel_cfg_cmdline()
        if cfg_file:
            self.node.execute(
                f"ls -lt {cfg_file}",
                expected_exit_code=0,
                expected_exit_code_failure_message=f"{cfg_file} doesn't exist",
                sudo=True,
            )
            cat = self.node.tools[Cat]
            sed = self.node.tools[Sed]
            result = cat.run(cfg_file, sudo=True, force_run=True)
            if "crashkernel" in result.stdout:
                sed.substitute(
                    match_lines=f"^{cmdline}",
                    regexp='crashkernel=[^[:space:]"]*',
                    replacement=f"crashkernel={crashkernel}",
                    file=cfg_file,
                    sudo=True,
                )
            else:
                sed.substitute(
                    match_lines=f"^{cmdline}",
                    regexp='"$',
                    replacement=f' crashkernel={crashkernel}"',
                    file=cfg_file,
                    sudo=True,
                )
            # Check if crashkernel is insert in cfg file
            result = cat.run(cfg_file, sudo=True, force_run=True)
            if f"crashkernel={crashkernel}" not in result.stdout:
                raise LisaException(
                    f'No find "crashkernel={crashkernel}" in {cfg_file} after'
                    "insert. Please double check the grub config file and insert"
                    "process"
                )

        # Update grub
        update_cmd = self._get_crashkernel_update_cmd(crashkernel)
        result = self.node.execute(update_cmd, sudo=True, shell=True)
        result.assert_exit_code(message="Failed to update grub")

    def config_resource_disk_dump_path(self, dump_path: str) -> None:
        """
        If the system memory size is bigger than 1T, the default size of /var/crash
        may not be enough to store the dump file, need to configure the dump path.
        The distro which may not have enough space, need override this method.
        """
        return

    def enable_kdump_service(self) -> None:
        """
        This method enables the kdump service.
        """
        service = self.node.tools[Service]
        service.enable_service(self._get_kdump_service_name())

    def restart_kdump_service(self) -> None:
        """
        This method restarts the kdump service.
        """
        service = self.node.tools[Service]
        service.restart_service(self._get_kdump_service_name())

    def check_kdump_service(self) -> None:
        """
        This method checks the kdump service status.
        """
        service = self.node.tools[Service]
        service.check_service_status(self._get_kdump_service_name())

    def set_unknown_nmi_panic(self) -> None:
        """
        /proc/sys/kernel/unknown_nmi_panic:
        The value in this file affects behavior of handling NMI. When the value is
        non-zero, unknown NMI is trapped and then panic occurs. If need to dump the
        crash, the value should be set 1. Some architectures don't provide architected
        NMIs,such as ARM64, the system doesn't have this file, we don't need to set
        either.
        """
        nmi_panic_file = PurePath("/proc/sys/kernel/unknown_nmi_panic")
        if self.node.shell.exists(nmi_panic_file):
            sysctl = self.node.tools[Sysctl]
            sysctl.write("kernel.unknown_nmi_panic", "1")

    def _check_kexec_crash_loaded(self) -> None:
        """
        Sometimes it costs a while to load the value, so retry to check many times
        """
        # If the dump_path is not "/var/crash", for example it is "/mnt/crash",
        # the kdump service may start before the /mnt is mounted. That will cause
        # "Dump path /mnt/crash does not exist" error. We need to restart it.
        if self.dump_path != "/var/crash":
            self.restart_kdump_service()
        cat = self.node.tools[Cat]
        max_tries = 60
        for tries in range(max_tries):
            result = cat.run(self.kexec_crash, force_run=True)
            if "1" == result.stdout:
                break
            elif "1" != result.stdout and tries == max_tries - 1:
                self.check_kdump_service()
                raise LisaException(f"{self.kexec_crash} file's value is not 1.")
            else:
                sleep(2)

    def _check_crashkernel_in_cmdline(self, crashkernel_memory: str) -> None:
        cat = self.node.tools[Cat]
        result = cat.run("/proc/cmdline", force_run=True)
        if f"crashkernel={crashkernel_memory}" not in result.stdout:
            raise LisaException(
                f"crashkernel={crashkernel_memory} boot parameter is not present in"
                "kernel cmdline"
            )

    def _check_crashkernel_memory_reserved(self) -> None:
        cat = self.node.tools[Cat]
        result = cat.run(self.iomem, force_run=True)
        if "Crash kernel" not in result.stdout:
            raise LisaException(
                f"No find 'Crash kernel' in {self.iomem}. Memory isn't reserved for"
                "crash kernel"
            )

    def check_crashkernel_loaded(self, crashkernel_memory: str) -> None:
        if crashkernel_memory:
            # Check crashkernel parameter in cmdline
            self._check_crashkernel_in_cmdline(crashkernel_memory)

        # Check crash kernel loaded
        if not self.node.shell.exists(PurePosixPath(self.kexec_crash)):
            raise LisaException(
                f"{self.kexec_crash} file doesn't exist. Kexec crash is not loaded."
            )
        self._check_kexec_crash_loaded()

        # Check if memory is reserved for crash kernel
        self._check_crashkernel_memory_reserved()

    def capture_info(self) -> None:
        # Override this method to print additional info before panic
        return


class KdumpRedhat(KdumpBase):
    @property
    def command(self) -> str:
        return "kdumpctl"

    def _install(self) -> bool:
        assert isinstance(self.node.os, Redhat)
        self.node.os.install_packages("kexec-tools")
        return self._check_exists()

    def _get_crashkernel_cfg_file(self) -> str:
        if (
            self.node.os.information.version >= "8.0.0-0"
            and not isinstance(self.node.os, Oracle)
        ) or (
            isinstance(self.node.os, Oracle)
            and self.node.os.information.version >= "9.0.0-0"
        ):
            # For Redhat 8 and later version or oracle 9.
            # We can use grubby command to config crashkernel.
            # No need to get the crashkernel cfg file
            return ""
        else:
            return "/etc/default/grub"

    def _get_crashkernel_update_cmd(self, crashkernel: str) -> str:
        if (
            self.node.os.information.version >= "8.0.0-0"
            and not isinstance(self.node.os, Oracle)
        ) or (
            isinstance(self.node.os, Oracle)
            and self.node.os.information.version >= "9.0.0-0"
        ):
            return (
                "grubby --update-kernel=/boot/vmlinuz-$(uname -r)"
                f' --args="crashkernel={crashkernel}"'
            )
        else:
            arch = self.node.os.get_kernel_information().hardware_platform  # type: ignore  # noqa: E501
            if (
                self.node.shell.exists(PurePosixPath("/sys/firmware/efi"))
                and arch == "x86_64"
            ):
                # System with UEFI firmware
                grub_file_path = self.node.execute(
                    "find /boot/efi/EFI/* -name grub.cfg", shell=True, sudo=True
                )
                return f"grub2-mkconfig -o {grub_file_path}"
            else:
                # System with BIOS firmware Or ARM64 CentOS 7
                return "grub2-mkconfig -o /boot/grub2/grub.cfg"

    def config_resource_disk_dump_path(self, dump_path: str) -> None:
        """
        If the system memory size is bigger than 1T, the default size of /var/crash
        may not be enough to store the dump file, need to change the dump path
        """
        kdump_conf = "/etc/kdump.conf"
        self.node.execute(
            f"mkdir -p {dump_path}",
            expected_exit_code=0,
            expected_exit_code_failure_message=(f"Fail to create dir {dump_path}"),
            shell=True,
            sudo=True,
        )
        self.dump_path = dump_path
        # Change dump path in kdump conf
        sed = self.node.tools[Sed]
        sed.substitute(
            match_lines="^path",
            regexp="path",
            replacement="#path",
            file=kdump_conf,
            sudo=True,
        )
        sed.append(f"path {self.dump_path}", kdump_conf, sudo=True)


class KdumpDebian(KdumpBase):
    @property
    def command(self) -> str:
        return "kdump-config"

    def _install(self) -> bool:
        assert isinstance(self.node.os, Debian)
        self.node.os.install_packages("kdump-tools")
        return self._check_exists()

    def calculate_crashkernel_size(self, total_memory: str) -> str:
        # If the function returns empty string, it means using the default crash kernel
        # size. Currently, for x86 Ubuntu,Debian, the default setting is "512M-:192M",
        # for arm64, "2G-4G:320M,4G-32G:512M,32G-64G:1024M,64G-128G:2048M,128G-:4096M"
        arch = self.node.os.get_kernel_information().hardware_platform  # type: ignore
        if (
            "G" in total_memory
            and float(total_memory.strip("G")) < 2
            or "M" in total_memory
            and float(total_memory.strip("M")) < 2048
        ):
            if arch == "x86_64":
                return "192M"
            else:
                # For arm64 with page size == 4k, the memory "section size" is 128MB,
                # that's the granularity of memory hotplug and also the minimal size of
                # manageable memory if SPARSEMEM is selected. More memory is needed for
                # kdump kernel
                return "256M"
        else:
            if arch == "x86_64":
                return "512M"
            else:
                # Use the default crash kernel size
                return ""

    def _get_crashkernel_cfg_file(self) -> str:
        return "/etc/default/grub.d/kdump-tools.cfg"

    def _get_crashkernel_update_cmd(self, crashkernel: str) -> str:
        return "update-grub"

    def _get_kdump_service_name(self) -> str:
        return "kdump-tools"


class KdumpSuse(KdumpBase):
    @property
    def command(self) -> str:
        return "kdumptool"

    def _install(self) -> bool:
        assert isinstance(self.node.os, Suse)
        self.node.os.install_packages("kdump")
        return self._check_exists()


class KdumpCBLMariner(KdumpBase):
    @property
    def command(self) -> str:
        return "kdumpctl"

    def _install(self) -> bool:
        assert isinstance(self.node.os, CBLMariner)
        self.node.os.install_packages("kexec-tools")
        return self._check_exists()

    def enable_kdump_service(self) -> None:
        """
        This method enables the kdump service.
        """
        kdump_conf = "/etc/kdump.conf"
        sed = self.node.tools[Sed]
        # Remove force_no_rebuild=1 if present
        sed.substitute(
            match_lines="^force_no_rebuild",
            regexp="force_no_rebuild",
            replacement="#force_no_rebuild",
            file=kdump_conf,
            sudo=True,
        )
        # Set mariner_2_initrd_use_suffix. Otherwise it will replace
        # the original initrd file which will cause a reboot-loop
        sed.substitute(
            match_lines="mariner_2_initrd_use_suffix",
            regexp="#mariner_2_initrd_use_suffix",
            replacement="mariner_2_initrd_use_suffix",
            file=kdump_conf,
            sudo=True,
        )

        # Check for sufficient core numbers
        self.ensure_nr_cpus()

        super().enable_kdump_service()

    def ensure_nr_cpus(self) -> None:
        lscpu = self.node.tools[Lscpu]
        core_count = lscpu.get_core_count()
        preferred_nr_cpus = math.ceil(core_count / 56)
        conf_file = "/etc/sysconfig/kdump"
        sed = self.node.tools[Sed]
        # replace nr_cpus=<whatever> to nr_cpus=preferred_nr_cpus
        sed.substitute(
            match_lines="^KDUMP_COMMANDLINE_APPEND",
            regexp="nr_cpus=[^[:space:]]*",
            replacement=f"nr_cpus={preferred_nr_cpus}",
            file=conf_file,
            sudo=True,
        )

    def calculate_crashkernel_size(self, total_memory: str) -> str:
        # For x86 and arm64 Mariner, the default setting is 256M
        return ""

    def _get_crashkernel_cfg_file(self) -> str:
        if self.node.os.information.version.major >= 3:
            return "/etc/default/grub.d/51_kexec_tools.cfg"
        else:
            return "/boot/mariner.cfg"

    def _get_crashkernel_cfg_cmdline(self) -> str:
        return "mariner_cmdline"

    def _get_crashkernel_update_cmd(self, crashkernel: str) -> str:
        return ""

    def config_resource_disk_dump_path(self, dump_path: str) -> None:
        """
        If the system memory size is bigger than 1T, the default size of /var/crash
        may not be enough to store the dump file, need to change the dump path
        """
        self.node.execute(
            f"mkdir -p {dump_path}",
            expected_exit_code=0,
            expected_exit_code_failure_message=(f"Fail to create dir {dump_path}"),
            shell=True,
            sudo=True,
        )
        self.dump_path = dump_path
        # Change dump path in kdump conf
        kdump_conf = "/etc/kdump.conf"
        sed = self.node.tools[Sed]
        sed.substitute(
            match_lines="^path",
            regexp="path",
            replacement="#path",
            file=kdump_conf,
            sudo=True,
        )
        sed.append(f"path {self.dump_path}", kdump_conf, sudo=True)

    def capture_info(self) -> None:
        # print /proc/cmdline
        cat = self.node.tools[Cat]
        result = cat.run("/proc/cmdline", force_run=True, sudo=True)
        self._log.info(f"Current kernel command line: {result.stdout}")
        # print /etc/default/grub.d/51_kexec_tools.cfg
        result = cat.run(self._get_crashkernel_cfg_file(), force_run=True, sudo=True)
        self._log.info(f"Current kernel cmdline in config file: {result.stdout}")
        # print /etc/sysconfig/kdump
        result = cat.run("/etc/sysconfig/kdump", force_run=True, sudo=True)
        self._log.info(f"Current kdump configuration: {result.stdout}")
        # print /proc/sys/kernel/sysrq
        result = cat.run("/proc/sys/kernel/sysrq", force_run=True, sudo=True)
        self._log.info(f"Current sysrq value: {result.stdout}")
        # print lsblk -l output
        lsblk = self.node.tools[Lsblk]
        result = lsblk.run("-l", force_run=True)
        self._log.info(f"Current disk partitions: {result.stdout}")
        # print /etc/fstab
        result = cat.run("/etc/fstab", force_run=True, sudo=True)
        self._log.info(f"Current fstab: {result.stdout}")
        # print /etc/kdump.conf
        result = cat.run("/etc/kdump.conf", force_run=True, sudo=True)
        self._log.info(f"Current kdump configuration: {result.stdout}")
        return
