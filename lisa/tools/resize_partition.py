# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re

from lisa.executable import Tool
from lisa.operating_system import CBLMariner, Redhat, Ubuntu
from lisa.tools import Mount
from lisa.util import LisaException, UnsupportedDistroException, find_group_in_lines


class ResizePartition(Tool):
    @property
    def command(self) -> str:
        return ""

    @property
    def can_install(self) -> bool:
        return False

    def _check_exists(self) -> bool:
        return True

    def expand_os_partition(self) -> None:
        if isinstance(self.node.os, Redhat):
            pv_result = self.node.execute("pvscan -s", sudo=True, shell=True).stdout
            # The output of pvscan -s is like below.:
            #  /dev/sda4
            #  Total: 1 [299.31 GiB] / in use: 1 [299.31 GiB] / in no VG: 0 [0   ]
            pattern = re.compile(r"(?P<disk>.*)(?P<number>[\d]+)$", re.M)
            matched = find_group_in_lines(pv_result, pattern)
            if not matched:
                self._log.debug(
                    "No physical volume found. Does not require partition resize."
                )
                return
            disk = matched.get("disk")
            number = matched.get("number")
            self.node.execute(f"growpart {disk} {number}", sudo=True)
            self.node.execute(f"pvresize {pv_result.splitlines()[0]}", sudo=True)
            root_partition = self.node.tools[Mount].get_partition_info("/")[0]
            device_name = root_partition.name
            device_type = root_partition.type
            cmd_result = self.node.execute(f"lvdisplay {device_name}", sudo=True)
            if cmd_result.exit_code == 0:
                self.node.execute(
                    cmd=f"lvextend -l 100%FREE {device_name}",
                    sudo=True,
                    shell=True,
                )
                if device_type == "xfs":
                    self.node.execute(f"xfs_growfs {device_name}", sudo=True)
                elif device_type == "ext4":
                    self.node.execute(f"resize2fs {device_name}", sudo=True)
                else:
                    raise LisaException(f"Unknown partition type: {device_type}")
            else:
                self._log.debug("No LV found. Does not require LV resize.")
                return
        elif isinstance(self.node.os, Ubuntu) or isinstance(self.node.os, CBLMariner):
            # Get the root partition info
            # The root partition is the one that has the mount point "/"
            # sample root partition info: name: /dev/sda2, disk: sda,
            # mount_point: /, type: ext4, options: ('rw', 'relatime')
            root_partition = self.node.tools[Mount].get_partition_info("/")[0]
            device_name = root_partition.name
            partition = root_partition.disk
            # for root partition name: /dev/sda2, partition is "sda" and
            # we need to extract the partition number i.e. 2
            root_part_num = re.findall(r"\d+", device_name)[0]
            # Grow the partition and resize the filesystem
            cmd_result = self.node.execute(
                cmd=f"growpart /dev/{partition} {root_part_num}",
                sudo=True,
            )

            # In case the partition is already expanded to full disk size, the
            # command will print "NOCHANGE: partition 2 is size <size>. it cannot
            # be grown". In this case, it returns exit code 1 which we can ignore
            if cmd_result.exit_code != 0:
                if "NOCHANGE" in cmd_result.stdout:
                    self._log.debug("No change has been made to root partition")
                    return
                raise LisaException(f"Failed to grow partition: {cmd_result.stdout}")
            self.node.execute(
                cmd=f"resize2fs {device_name}",
                sudo=True,
                expected_exit_code=0,
            )
        else:
            raise UnsupportedDistroException(
                self.node.os,
                "OS Partition Resize not supported",
            )
