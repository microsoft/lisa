# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import List, cast

from lisa.executable import Tool
from lisa.operating_system import Posix


class Mdadm(Tool):
    @property
    def command(self) -> str:
        return "mdadm"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("mdadm")
        return self._check_exists()

    def create_raid(
        self,
        disk_list: List[str],
        level: int = 0,
        volume_name: str = "/dev/md0",
        chunk_size: int = 0,
    ) -> None:
        count = len(disk_list)
        disks = " ".join(disk_list)
        cmd = f"--create {volume_name} --level {level} --raid-devices {count} {disks}"
        if chunk_size:
            cmd += " --chunk {chunk_size}"
        self.run(
            cmd,
            sudo=True,
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"failed to create {volume_name} against disks {disks}"
            ),
        )

    def stop_raid(
        self,
        volume_name: str = "/dev/md0",
    ) -> None:
        self.run(f"--stop {volume_name}", force_run=True, sudo=True)
