# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import pathlib
import inspect
from typing import Any, Dict, List, Optional

from lisa import Logger, Node, notifier
from lisa.environment import Environment
from lisa.messages import DiskPerformanceMessage, DiskSetupType, DiskType
from lisa.schema import NetworkDataPath
from lisa.tools import FIOMODES, Fdisk, Fio, FIOResult, Kill, Mdadm, Sed, Sysctl


def run_perf_test(
    node: Node,
    start_iodepth: int,
    max_iodepth: int,
    filename: str,
    core_count: int,
    disk_count: int,
    disk_setup_type: DiskSetupType,
    disk_type: DiskType,
    environment: Environment,
    test_name: str = "",
    num_jobs: Optional[List[int]] = None,
    block_size: int = 4,
    time: int = 120,
    size_gb: int = 0,
    numjob: int = 0,
    overwrite: bool = False,
    cwd: Optional[pathlib.PurePath] = None,
) -> None:
    fio_result_list: List[FIOResult] = []
    fio = node.tools[Fio]
    numjobiterator = 0
    for mode in FIOMODES:
        iodepth = start_iodepth
        numjobindex = 0
        while iodepth <= max_iodepth:
            if num_jobs:
                numjob = num_jobs[numjobindex]
            fio_result = fio.launch(
                name=f"iteration{numjobiterator}",
                filename=filename,
                mode=mode.name,
                time=time,
                size_gb=size_gb,
                block_size=f"{block_size}K",
                iodepth=iodepth,
                overwrite=overwrite,
                numjob=numjob,
                cwd=cwd,
            )
            fio_result_list.append(fio_result)
            iodepth = iodepth * 2
            numjobindex += 1
            numjobiterator += 1

    other_fields: Dict[str, Any] = {}
    other_fields["core_count"] = core_count
    other_fields["disk_count"] = disk_count
    other_fields["block_size"] = block_size
    other_fields["disk_setup_type"] = disk_setup_type
    other_fields["disk_type"] = disk_type
    if not test_name:
        test_name = inspect.stack()[1][3]
    fio_messages: List[DiskPerformanceMessage] = fio.create_performance_messages(
        fio_result_list,
        test_name=test_name,
        environment=environment,
        other_fields=other_fields,
    )
    for fio_message in fio_messages:
        notifier.notify(fio_message)


def restore_sysctl_setting(
    nodes: List[Node], perf_tuning: Dict[str, List[Dict[str, str]]]
) -> None:
    for node in nodes:
        sysctl = node.tools[Sysctl]
        for variable_list in perf_tuning[node.name]:
            # restore back to the original value after testing
            for variable, value in variable_list.items():
                sysctl.write(variable, value)


def set_systemd_tasks_max(nodes: List[Node], log: Logger) -> None:
    for node in nodes:
        if node.shell.exists(
            node.get_pure_path("/usr/lib/systemd/system/user-.slice.d/10-defaults.conf")
        ):
            node.tools[Sed].substitute(
                regexp="TasksMax.*",
                replacement="TasksMax=122880",
                file="/usr/lib/systemd/system/user-.slice.d/10-defaults.conf",
                sudo=True,
            )
        elif node.shell.exists(node.get_pure_path("/etc/systemd/logind.conf")):
            node.tools[Sed].append(
                "UserTasksMax=122880", "/etc/systemd/logind.conf", sudo=True
            )
        else:
            log.debug(
                "no config file exist for systemd, either there is no systemd"
                " service or the config file location is incorrect."
            )


def get_nic_datapath(node: Node) -> str:
    data_path: str = ""
    assert (
        node.capability.network_interface
        and node.capability.network_interface.data_path
    )
    if isinstance(node.capability.network_interface.data_path, NetworkDataPath):
        data_path = node.capability.network_interface.data_path.value
    return data_path


def cleanup_process(environment: Environment, process_name: str) -> None:
    for node in environment.nodes.list():
        kill = node.tools[Kill]
        kill.by_name(process_name)


def reset_partitions(
    node: Node,
    disk_names: List[str],
) -> List[str]:
    fdisk = node.tools[Fdisk]
    partition_disks: List[str] = []
    for data_disk in disk_names:
        fdisk.delete_partitions(data_disk)
        partition_disks.append(fdisk.make_partition(data_disk, format=False))
    return partition_disks


def stop_raid(node: Node) -> None:
    mdadm = node.tools[Mdadm]
    mdadm.stop_raid()


def reset_raid(node: Node, disk_list: List[str]) -> None:
    stop_raid(node)
    mdadm = node.tools[Mdadm]
    mdadm.create_raid(disk_list)
