# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import List, Optional, cast

from lisa.executable import Process, Tool
from lisa.operating_system import Debian, Posix


class Udevadm(Tool):
    # banner printed by "udevadm monitor" before it starts reporting events
    MONITOR_BANNER = "monitor will print the received events"

    @property
    def command(self) -> str:
        return "udevadm"

    @property
    def can_install(self) -> bool:
        return self.node.os.is_posix

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        if isinstance(posix_os, Debian):
            package_name = "udev"
        else:
            package_name = "systemd-udev"
        posix_os.install_packages(package_name)
        return self._check_exists()

    def monitor_async(
        self,
        kernel: bool = True,
        udev: bool = False,
        properties: bool = True,
        subsystems: Optional[List[str]] = None,
    ) -> Process:
        """Start "udevadm monitor" in the background and return the process.

        kernel/udev select which event sources are reported. The kernel
        uevents arrive first, the udev ones only after udevd processed them.
        properties adds the full KEY=VALUE property list of each event.
        subsystems filters the reported events, note that this drops any
        event whose subsystem is not listed.
        """
        args = ""
        if kernel:
            args += " --kernel"
        if udev:
            args += " --udev"
        if properties:
            args += " --property"
        for subsystem in subsystems or []:
            args += f" --subsystem-match={subsystem}"
        process = self.run_async(args.strip(), sudo=True, force_run=True, shell=True)
        process.wait_output(self.MONITOR_BANNER, timeout=30)
        return process

    def trigger(
        self,
        action: str = "add",
        subsystem: str = "",
        settle: bool = True,
    ) -> None:
        """Re-emit uevents for the matching devices."""
        args = f"trigger --action={action}"
        if subsystem:
            args += f" --subsystem-match={subsystem}"
        if settle:
            args += " --settle"
        self.run(args, sudo=True, force_run=True, expected_exit_code=0)
