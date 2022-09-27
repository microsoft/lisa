from pathlib import PurePosixPath

from lisa import Logger, RemoteNode
from lisa.operating_system import CentOs
from lisa.sut_orchestrator.azure.tools import Waagent


def get_resource_disk_mount_point(
    log: Logger,
    node: RemoteNode,
) -> str:
    # by default, cloudinit will use /mnt as mount point of resource disk
    # in CentOS, cloud.cfg.d/91-azure_datasource.cfg customize mount point as
    # /mnt/resource
    if (
        node.shell.exists(PurePosixPath("/var/log/cloud-init.log"))
        and node.shell.exists(PurePosixPath("/var/lib/cloud/instance"))
        and not isinstance(node.os, CentOs)
    ):
        log.debug("Disk handled by cloud-init.")
        mount_point = "/mnt"
    else:
        log.debug("Disk handled by waagent.")
        mount_point = node.tools[Waagent].get_resource_disk_mount_point()
    return mount_point
