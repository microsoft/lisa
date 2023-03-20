# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from pathlib import PurePath
from typing import Any, Dict, List, Optional, Type

from assertpy import assert_that

from lisa.base_tools import Cat, Wget
from lisa.executable import Tool
from lisa.operating_system import CBLMariner, CoreOs, Redhat
from lisa.tools import Gcc, Modinfo, PowerShell, Uname
from lisa.util import (
    LisaException,
    UnsupportedDistroException,
    UnsupportedKernelException,
    find_patterns_in_lines,
    get_matched_str,
)
from lisa.util.process import ExecutableResult


class Waagent(Tool):
    __version_pattern = re.compile(r"(?<=\-)([^\s]+)")

    # ResourceDisk.MountPoint=/mnt
    # ResourceDisk.EnableSwap=n
    # ResourceDisk.EnableSwap=y
    _key_value_regex = re.compile(r"^\s*(?P<key>\S+)=(?P<value>\S+)\s*$")

    _python_candidates = [
        "python3",
        "python2",
        # for RedHat 8.0
        "/usr/libexec/platform-python",
        # for flatcar
        "/usr/share/oem/python/bin/python3",
    ]

    @property
    def command(self) -> str:
        return self._command

    @property
    def can_install(self) -> bool:
        return False

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        if isinstance(self.node.os, CoreOs):
            self._command = (
                "/usr/share/oem/python/bin/python /usr/share/oem/bin/waagent"
            )
        else:
            self._command = "waagent"
        self._distro_version: Optional[str] = None

    def get_version(self) -> str:
        result = self.run("-version")
        if result.exit_code != 0:
            self._command = "/usr/sbin/waagent"
            result = self.run("-version")
        # When the default command python points to python2,
        # we need specify python3 clearly.
        # e.g. bt-americas-inc diamondip-sapphire-v5 v5-9 9.0.53.
        if result.exit_code != 0:
            self._command = "python3 /usr/sbin/waagent"
            result = self.run("-version")
        return get_matched_str(result.stdout, self.__version_pattern)

    def deprovision(self) -> None:
        # the deprovision doesn't delete user, because the VM may be needed. If
        # the vm need to be exported clearly, it needs to remove the current
        # user with below command:
        # self.run("-deprovision+user --force", sudo=True)
        self.run("-deprovision --force", sudo=True, expected_exit_code=0)

    def get_configuration(self, force_run: bool = False) -> Dict[str, str]:
        if isinstance(self.node.os, CoreOs):
            waagent_conf_file = "/usr/share/oem/waagent.conf"
        else:
            waagent_conf_file = "/etc/waagent.conf"

        config = {}
        cfg = self.node.tools[Cat].run(waagent_conf_file, force_run=force_run).stdout
        for line in cfg.splitlines():
            matched = self._key_value_regex.fullmatch(line)
            if matched:
                config[matched.group("key")] = matched.group("value")

        return config

    def get_root_device_timeout(self) -> int:
        waagent_configuration = self.get_configuration()
        return int(waagent_configuration["OS.RootDeviceScsiTimeout"])

    def get_resource_disk_mount_point(self) -> str:
        waagent_configuration = self.get_configuration()
        return waagent_configuration["ResourceDisk.MountPoint"]

    def is_swap_enabled(self) -> bool:
        waagent_configuration = self.get_configuration()
        is_swap_enabled = waagent_configuration["ResourceDisk.EnableSwap"]
        if is_swap_enabled == "y":
            return True
        elif is_swap_enabled == "n":
            return False
        else:
            raise LisaException(
                f"Unknown value for ResourceDisk.EnableSwap : {is_swap_enabled}"
            )

    def is_rdma_enabled(self) -> bool:
        waagent_configuration = self.get_configuration(force_run=True)
        is_rdma_enabled = waagent_configuration["OS.EnableRDMA"]
        if is_rdma_enabled == "y":
            return True
        elif is_rdma_enabled == "n":
            return False
        else:
            raise LisaException(f"Unknown value for OS.EnableRDMA : {is_rdma_enabled}")

    def get_distro_version(self) -> str:
        """
        This method is to get the same distro version string like WaAgent. It
        tries best to handle different python version and locations.
        """
        if self._distro_version is not None:
            return self._distro_version

        for python_cmd in self._python_candidates:
            python_exists, use_sudo = self.command_exists(command=python_cmd)
            self._log.debug(
                f"{python_cmd} exists: {python_exists}, use sudo: {use_sudo}"
            )
            if python_exists:
                break

        # Try to use waagent code to detect
        result = self.node.execute(
            f'{python_cmd} -c "from azurelinuxagent.common.version import get_distro;'
            "print('-'.join(get_distro()[0:3]))\"",
            sudo=use_sudo,
        )
        if result.exit_code == 0:
            distro_version = result.stdout
        else:
            # try to compat with old waagent versions
            result = self.node.execute(
                f'{python_cmd} -c "import platform;'
                "print('-'.join(platform.linux_distribution(0)))\"",
                sudo=use_sudo,
            )
            if result.exit_code == 0:
                distro_version = result.stdout.strip('"').strip(" ").lower()
            else:
                # nothing right
                distro_version = "Unknown"

        self._distro_version = distro_version

        return self._distro_version


class VmGeneration(Tool):
    """
    This is a virtual tool to detect VM generation of Hyper-V technology.
    """

    @property
    def command(self) -> str:
        return "ls -lt /sys/firmware/efi"

    def _check_exists(self) -> bool:
        return True

    def get_generation(self) -> str:
        cmd_result = self.run()
        if cmd_result.exit_code == 0:
            generation = "2"
        else:
            generation = "1"
        return generation


class LisDriver(Tool):
    """
    This is a virtual tool to detect/install LIS (Linux Integration Services) drivers.
    More info  - https://www.microsoft.com/en-us/download/details.aspx?id=55106
    """

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Wget, Modinfo]

    @property
    def command(self) -> str:
        return "modinfo hv_vmbus"

    @property
    def can_install(self) -> bool:
        if (
            isinstance(self.node.os, Redhat)
            and self.node.os.information.version < "7.8.0"
        ):
            return True

        raise UnsupportedDistroException(
            self.node.os, "lis driver can't be installed on this distro"
        )

    def download(self) -> PurePath:
        if not self.node.shell.exists(self.node.working_path.joinpath("LISISO")):
            wget_tool = self.node.tools[Wget]
            lis_path = wget_tool.get("https://aka.ms/lis", str(self.node.working_path))
            from lisa.tools import Tar

            tar = self.node.tools[Tar]
            tar.extract(file=lis_path, dest_dir=str(self.node.working_path))
        return self.node.working_path.joinpath("LISISO")

    def get_version(self, force_run: bool = False) -> str:
        # in some distro, the vmbus is builtin, the version cannot be gotten.
        modinfo = self.node.tools[Modinfo]
        return modinfo.get_version("hv_vmbus")

    def install_from_iso(self) -> ExecutableResult:
        lis_folder_path = self.download()
        return self.node.execute("./install.sh", cwd=lis_folder_path, sudo=True)

    def uninstall_from_iso(self) -> ExecutableResult:
        lis_folder_path = self.download()
        return self.node.execute("./uninstall.sh", cwd=lis_folder_path, sudo=True)

    def _check_exists(self) -> bool:
        if isinstance(self.node.os, Redhat):
            # currently LIS is only supported with Redhat
            # and its derived distros
            if self.node.os.package_exists(
                "kmod-microsoft-hyper-v"
            ) and self.node.os.package_exists("microsoft-hyper-v"):
                return True
        return False

    def _install(self) -> bool:
        result = self.install_from_iso()
        if "Unsupported kernel version" in result.stdout:
            raise UnsupportedKernelException(self.node.os)
        result.assert_exit_code(
            0,
            f"Unable to install the LIS RPMs! exit_code: {result.exit_code}"
            f"stderr: {result.stderr}",
        )
        self.node.reboot(360)
        return True


class KvpClient(Tool):
    """
    The KVP client is used to check kvp service status.
    """

    _binaries: Dict[str, str] = {
        "x86_64": "https://raw.githubusercontent.com/microsoft/"
        "lis-test/master/WS2012R2/lisa/tools/KVP/kvp_client64",
        "i686": "https://raw.githubusercontent.com/microsoft/"
        "lis-test/master/WS2012R2/lisa/tools/KVP/kvp_client32",
    }
    _command_name = "kvp_client"
    _source_location = (
        "https://raw.githubusercontent.com/microsoft/"
        "lis-test/master/WS2012R2/lisa/tools/KVP/kvp_client.c"
    )
    # Pool is 0
    # Pool is 1
    _pool_pattern = re.compile(r"^Pool is (\d+)\r?$", re.M)
    # Key: HostName; Value: ABC000111222333
    _key_value_pattern = re.compile(
        r"^Key: (?P<key>.*); Value: (?P<value>.*)\r?$", re.M
    )
    # Num records is 16
    _count_record_pattern = re.compile(r"Num records is (\d+)\r?$", re.M)

    @property
    def command(self) -> str:
        return str(self.node.working_path / self._command_name)

    @property
    def can_install(self) -> bool:
        return True

    def get_pool_count(self) -> int:
        output = self.run(
            expected_exit_code=0,
            expected_exit_code_failure_message="failed to run kvp_client",
        ).stdout
        matched_lines = find_patterns_in_lines(output, [self._pool_pattern])
        return len(matched_lines[0])

    def get_pool_records(self, pool_id: int, force_run: bool = False) -> Dict[str, str]:
        result = self.run(
            str(pool_id),
            force_run=force_run,
        )
        # some distro return 4, for example, Ubuntu Server 1804
        assert_that(result.exit_code).described_as("failed to get pool").is_in(0, 4)
        matched_lines = find_patterns_in_lines(result.stdout, [self._key_value_pattern])
        records = {item[0]: item[1] for item in matched_lines[0]}

        count = int(get_matched_str(result.stdout, self._count_record_pattern))

        assert_that(records, "result count is not the same as stats").is_length(count)

        return records

    def get_host_name(self) -> str:
        items = self.get_pool_records(3)
        host_name = items.get("HostName", "")

        return host_name

    def _install(self) -> bool:
        uname = self.node.tools[Uname]
        architecture = uname.get_linux_information().hardware_platform
        binary_location = self._binaries.get(architecture, "")
        if binary_location:
            self._install_by_download(binary_location)
        else:
            self._install_by_build()

        return self._check_exists()

    def _install_by_download(self, binary_location: str) -> None:
        wget = self.node.tools[Wget]
        wget.get(
            url=binary_location,
            file_path=str(self.node.working_path),
            filename=self._command_name,
            executable=True,
        )

    def _install_by_build(self) -> None:
        wget = self.node.tools[Wget]
        source_file = wget.get(
            url=self._source_location,
            file_path=str(self.node.working_path),
        )

        if isinstance(self.node.os, CBLMariner):
            self.node.os.install_packages("kernel-headers glibc-devel binutils")
        gcc = self.node.tools[Gcc]
        # in C90, the status returned is undefined
        # use c99 to make sure the return value is correct
        gcc.compile(
            filename=source_file, output_name=self.command, arguments="-std=c99"
        )


class AzCmdlet(Tool):
    @property
    def command(self) -> str:
        return "powershell"

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [PowerShell]

    @property
    def can_install(self) -> bool:
        return True

    def _check_exists(self) -> bool:
        powershell = self.node.tools[PowerShell]

        try:
            powershell.run_cmdlet("Get-Command Connect-AzAccount")
            exists = True
        except Exception:
            exists = False
        return exists

    def _install(self) -> bool:
        powershell = self.node.tools[PowerShell]
        powershell.install_module("Az")

        return self._check_exists()

    def enable_ssh_on_windows(
        self, resource_group_name: str, vm_name: str, public_key_data: str
    ) -> None:
        powershell = self.node.tools[PowerShell]
        powershell.run_cmdlet(
            f"Invoke-AzVMRunCommand -ResourceGroupName '{resource_group_name}' "
            f"-VMName '{vm_name}' -ScriptPath "
            f"'./lisa/sut_orchestrator/azure/Enable-SSH.ps1' "
            f"-CommandId 'RunPowerShellScript' "
            f"-Parameter @{{'PublicKey'='{public_key_data}'}}"
        )


class Azsecd(Tool):
    @property
    def command(self) -> str:
        return "azsecd"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        self.node.os.install_packages("azure-security")  # type: ignore
        return self._check_exists()
