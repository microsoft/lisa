# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import pathlib
from typing import Dict, List, Optional

from lisa import Node, notifier
from lisa.environment import Environment
from lisa.messages import DiskPerformanceMessage, DiskSetupType, DiskType
from lisa.tools import FIOMODES, Fio, FIOResult, Kill
from lisa.util import dict_to_fields


def run_perf_test(
    node: Node,
    start_iodepth: int,
    max_iodepth: int,
    filename: str,
    num_jobs: Optional[List[int]] = None,
    block_size: int = 4,
    time: int = 120,
    size_gb: int = 0,
    numjob: int = 0,
    overwrite: bool = False,
    cwd: Optional[pathlib.PurePath] = None,
) -> List[DiskPerformanceMessage]:
    fio_result_list: List[FIOResult] = []
    fio = node.tools[Fio]
    numjobiterator = 0
    for mode in FIOMODES:
        iodepth = start_iodepth
        numjobindex = 0
        if num_jobs:
            numjob = num_jobs[numjobindex]
        while iodepth <= max_iodepth:
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
    fio_messages: List[DiskPerformanceMessage] = fio.create_performance_messages(
        fio_result_list
    )
    return fio_messages


def handle_and_send_back_results(
    core_count: int,
    disk_count: int,
    environment: Environment,
    disk_setup_type: DiskSetupType,
    disk_type: DiskType,
    test_case_name: str,
    fio_messages: List[DiskPerformanceMessage],
    block_size: int = 4,
) -> None:
    information: Dict[str, str] = environment.get_information()
    for fio_message in fio_messages:
        fio_message = dict_to_fields(information, fio_message)
        fio_message.core_count = core_count
        fio_message.disk_count = disk_count
        fio_message.test_case_name = test_case_name
        fio_message.block_size = block_size
        fio_message.disk_setup_type = disk_setup_type
        fio_message.disk_type = disk_type
        notifier.notify(fio_message)


def cleanup_process(environment: Environment, process_name: str) -> None:
    for node in environment.nodes.list():
        kill = node.tools[Kill]
        kill.by_name(process_name)
