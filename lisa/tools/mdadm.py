# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import List, Optional, Type, Union, cast

from lisa.executable import Tool
from lisa.operating_system import CBLMariner, Debian, Fedora, Posix, Suse
from lisa.tools.hyperv import HyperV
from lisa.tools.mount import Mount
from lisa.tools.powershell import PowerShell
from lisa.util import LisaException

from .gcc import Gcc
from .git import Git
from .make import Make


class Mdadm(Tool):
    _repo = "https://github.com/neilbrown/mdadm"

    @property
    def command(self) -> str:
        return "mdadm"

    @property
    def can_install(self) -> bool:
        return True

    def create_raid(
        self,
        disk_list: List[str],
        level: Union[int, str] = 0,
        volume_name: str = "/dev/md0",
        chunk_size: int = 0,
        force_run: bool = False,
        shell: bool = False,
    ) -> None:
        count = len(disk_list)
        disks = " ".join(disk_list)
        if force_run:
            cmd = f"yes | {self.command} "
        else:
            cmd = f"{self.command} "
        cmd += f"--create {volume_name} --level={level} --raid-devices={count} {disks}"
        if chunk_size:
            cmd += " --chunk {chunk_size}"
        self.node.execute(
            cmd,
            sudo=True,
            shell=shell,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"failed to create {volume_name} against disks {disks}"
            ),
        )
        self.node.execute(
            "sync",
            sudo=True,
        )

    def stop_raid(
        self,
        volume_name: str = "/dev/md0",
    ) -> None:
        # Check if the volume is mounted, if so unmount it
        mount_point = self.node.tools[Mount].get_mount_point_for_partition(volume_name)
        if mount_point:
            self.node.tools[Mount].umount(volume_name, mount_point)

        # Stop the raid volume
        self.run(f"--stop {volume_name}", force_run=True, sudo=True)

    @classmethod
    def _windows_tool(cls) -> Optional[Type[Tool]]:
        return WindowsMdadm

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        if posix_os.is_package_in_repo("mdadm"):
            posix_os.install_packages("mdadm")
        else:
            self._install_from_src()
        return self._check_exists()

    def _install_from_src(self) -> None:
        self._install_dep_packages()
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages([Gcc])
        tool_path = self.get_tool_path()
        git = self.node.tools[Git]
        git.clone(self._repo, tool_path)
        make = self.node.tools[Make]
        code_path = tool_path.joinpath("mdadm")
        make.make_install(cwd=code_path)

    def _install_dep_packages(self) -> None:
        posix_os: Posix = cast(Posix, self.node.os)
        if isinstance(self.node.os, CBLMariner):
            package_list = [
                "kernel-headers",
                "binutils",
                "glibc-devel",
                "zlib-devel",
                "cmake",
            ]
        elif (
            isinstance(self.node.os, Fedora)
            or isinstance(self.node.os, Debian)
            or isinstance(self.node.os, Suse)
        ):
            # skip package installation, but no error is raised.
            return
        else:
            raise LisaException(
                f"tool {self.command} can't be installed in distro {self.node.os.name}."
            )
        for package in list(package_list):
            if posix_os.is_package_in_repo(package):
                posix_os.install_packages(package)


class WindowsMdadm(Mdadm):
    @property
    def command(self) -> str:
        return "powershell"

    def _check_exists(self) -> bool:
        return True

    def create_raid(
        self,
        disk_list: List[str],
        level: Union[int, str] = 0,
        volume_name: str = "Raid0-Disk",
        chunk_size: int = 0,
        force_run: bool = False,
        shell: bool = False,
        pool_name: str = "Raid0-Pool",
    ) -> None:
        powershell = self.node.tools[PowerShell]

        # create pool
        # TODO: add support for higher raid types and chunk sizes
        self._create_pool(pool_name)

        # create new virtual disk
        self.node.tools[HyperV].create_virtual_disk(volume_name, pool_name)

        # set raid disk offline
        raid_disk_id = int(
            powershell.run_cmdlet(
                "(Get-Disk "
                f"| Where-Object {{$_.FriendlyName -eq '{volume_name}'}}).Number",
                force_run=True,
            ).strip()
        )
        powershell.run_cmdlet(
            f"Set-Disk {raid_disk_id} -IsOffline $true", force_run=True
        )

    def stop_raid(
        self, volume_name: str = "Raid0-Disk", pool_name: str = "Raid0-Pool"
    ) -> None:
        # delete virtual disk if it exists
        self.node.tools[HyperV].delete_virtual_disk(volume_name)

        # delete storage pool
        self._delete_pool(pool_name)

    def _exists_pool(self, pool_name: str) -> bool:
        output = self.node.tools[PowerShell].run_cmdlet(
            f"Get-StoragePool -FriendlyName {pool_name}",
            fail_on_error=False,
            force_run=True,
        )
        return bool(output.strip() != "")

    def _delete_pool(self, pool_name: str) -> None:
        if self._exists_pool(pool_name):
            self.node.tools[PowerShell].run_cmdlet(
                f"Remove-StoragePool -FriendlyName {pool_name} -confirm:$false",
                force_run=True,
            )

    def _create_pool(self, pool_name: str) -> None:
        # delete pool if exists
        self._delete_pool(pool_name)

        # create pool
        self.node.tools[PowerShell].run_cmdlet(
            "$disks = Get-PhysicalDisk -CanPool  $true; New-StoragePool "
            "-StorageSubSystemFriendlyName 'Windows Storage*' "
            f"-FriendlyName {pool_name} -PhysicalDisks $disks",
            force_run=True,
        )
