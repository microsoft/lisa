# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import List, Optional

from lisa.executable import Tool
from lisa.util import LisaException


@dataclass
class FstabEntry:
    """
    Represents a single entry in /etc/fstab.
    Format: <device> <mount_point> <fs_type> <options> <dump> <pass>
    Example: UUID=xxx /mnt/data ext4 defaults 0 2
    """

    device: str  # Device name, UUID=xxx, LABEL=xxx, or PARTUUID=xxx
    mount_point: str
    fs_type: str
    options: str
    dump: int
    pass_num: int

    def __str__(self) -> str:
        return (
            f"{self.device} {self.mount_point} {self.fs_type} "
            f"{self.options} {self.dump} {self.pass_num}"
        )


class Fstab(Tool):
    """
    Tool for managing /etc/fstab file entries.
    Provides methods to read, add, remove, and check fstab entries.
    """

    FSTAB_PATH = "/etc/fstab"

    # Regex to parse fstab entries
    # Matches: UUID=xxx /mnt/data ext4 defaults 0 2
    # Also matches: /dev/sda1 /mnt/data ext4 defaults 0 2
    # Ignores comments and blank lines
    _ENTRY_PATTERN = re.compile(
        r"^\s*(?P<device>\S+)\s+(?P<mount_point>\S+)\s+(?P<fs_type>\S+)\s+"
        r"(?P<options>\S+)\s+(?P<dump>\d+)\s+(?P<pass>\d+)\s*$"
    )

    @property
    def command(self) -> str:
        # fstab is a file, not a command
        return "cat"

    def _check_exists(self) -> bool:
        # Check if /etc/fstab exists
        return self.node.shell.exists(PurePath(self.FSTAB_PATH))

    def get_entries(self, force_run: bool = False) -> List[FstabEntry]:
        """
        Read and parse all entries from /etc/fstab.
        Returns list of FstabEntry objects, excluding comments and blank lines.
        """
        from lisa.tools import Cat

        cat = self.node.tools[Cat]
        content = cat.run(self.FSTAB_PATH, sudo=True, force_run=force_run).stdout

        entries: List[FstabEntry] = []
        for line in content.splitlines():
            # Skip comments and blank lines
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            match = self._ENTRY_PATTERN.match(line)
            if match:
                entries.append(
                    FstabEntry(
                        device=match.group("device"),
                        mount_point=match.group("mount_point"),
                        fs_type=match.group("fs_type"),
                        options=match.group("options"),
                        dump=int(match.group("dump")),
                        pass_num=int(match.group("pass")),
                    )
                )

        return entries

    def has_entry(
        self, mount_point: str = "", device: str = "", force_run: bool = False
    ) -> bool:
        """
        Check if an entry exists in fstab.
        Can search by mount_point, device, or both.

        Args:
            mount_point: Mount point to search for (e.g., "/mnt/data")
            device: Device to search for (e.g., "/dev/sda1" or "UUID=xxx")
            force_run: Force re-reading fstab file

        Returns:
            True if matching entry exists, False otherwise
        """
        if not mount_point and not device:
            raise LisaException("Must specify either mount_point or device")

        entries = self.get_entries(force_run=force_run)

        for entry in entries:
            if mount_point and device:
                if entry.mount_point == mount_point and entry.device == device:
                    return True
            elif mount_point:
                if entry.mount_point == mount_point:
                    return True
            elif device:
                if entry.device == device:
                    return True

        return False

    def add_entry(
        self,
        mount_point: str,
        device: Optional[str] = None,
        fs_type: str = "ext4",
        options: str = "defaults",
        dump: int = 0,
        pass_num: int = 2,
        use_uuid: bool = True,
    ) -> None:
        """
        Add a new entry to /etc/fstab.

        Args:
            mount_point: Mount point path (e.g., "/mnt/data")
            device: Device name (e.g., "/dev/sda1").
                If None, will auto-detect from mount_point
            fs_type: Filesystem type (default: ext4)
            options: Mount options (default: defaults)
            dump: Dump field (default: 0)
            pass_num: Pass field (default: 2)
            use_uuid: If True, use UUID instead of device name (default: True)

        Returns:
            None. Returns early without error if entry already exists.

        Raises:
            LisaException: If device cannot be determined
        """
        # Check if entry already exists
        if self.has_entry(mount_point=mount_point, force_run=True):
            self._log.debug(f"Entry for mount point {mount_point} already exists")
            return

        # Auto-detect device if not provided
        if not device:
            from lisa.tools import Lsblk

            lsblk = self.node.tools[Lsblk]
            try:
                disk = lsblk.find_disk_by_mountpoint(mount_point, force_run=True)
                device = disk.device_name
            except LisaException:
                raise LisaException(
                    f"Could not auto-detect device for mount point {mount_point}. "
                    "Please provide device parameter."
                )

        # Convert to UUID if requested
        device_str = device
        if use_uuid and device.startswith("/dev/"):
            from lisa.tools import Blkid

            blkid = self.node.tools[Blkid]
            try:
                partition_info = blkid.get_partition_info_by_name(
                    device, force_run=True
                )
                if partition_info.uuid:
                    device_str = f"UUID={partition_info.uuid}"
                    self._log.debug(f"Using UUID for device {device}: {device_str}")
                else:
                    self._log.warning(
                        f"Could not get UUID for {device}, using device name"
                    )
            except LisaException as e:
                self._log.warning(
                    f"Could not get UUID for {device}: {e}. Using device name"
                )

        # Create fstab entry
        entry = FstabEntry(
            device=device_str,
            mount_point=mount_point,
            fs_type=fs_type,
            options=options,
            dump=dump,
            pass_num=pass_num,
        )

        # Append to fstab
        from lisa.tools import Echo

        echo = self.node.tools[Echo]
        self._log.info(f"Adding fstab entry: {entry}")
        echo.write_to_file(
            str(entry),
            self.node.get_pure_path(self.FSTAB_PATH),
            sudo=True,
            append=True,
            ignore_error=False,
        )

        # Reload fstab configuration
        self.reload()
        self._log.info(
            f"Successfully added fstab entry for persistent mount at {mount_point}"
        )

    def reload(self) -> None:
        """
        Reload /etc/fstab configuration using 'mount -a'.
        This mounts all filesystems defined in fstab that are not already mounted.
        """
        from lisa.tools import Mount

        mount = self.node.tools[Mount]
        mount.reload_fstab_config()
        self._log.debug("Reloaded fstab configuration")

    def ensure_entry(
        self,
        mount_point: str,
        device: Optional[str] = None,
        fs_type: str = "ext4",
        options: str = "defaults",
        dump: int = 0,
        pass_num: int = 2,
        use_uuid: bool = True,
    ) -> bool:
        """
        Ensure an fstab entry exists. If it doesn't exist, add it.
        Returns True if entry was added, False if it already existed.

        Args:
            mount_point: Mount point path (e.g., "/mnt/data")
            device: Device name (e.g., "/dev/sda1"). If None, will auto-detect
            fs_type: Filesystem type (default: ext4)
            options: Mount options (default: defaults)
            dump: Dump field (default: 0)
            pass_num: Pass field (default: 2)
            use_uuid: If True, use UUID instead of device name (default: True)

        Returns:
            True if entry was added, False if already existed
        """
        if self.has_entry(mount_point=mount_point, force_run=True):
            self._log.debug(f"Entry for {mount_point} already exists in fstab")
            return False

        self.add_entry(
            mount_point=mount_point,
            device=device,
            fs_type=fs_type,
            options=options,
            dump=dump,
            pass_num=pass_num,
            use_uuid=use_uuid,
        )
        return True
