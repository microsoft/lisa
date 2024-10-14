# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from decimal import Decimal
from typing import cast

from assertpy import assert_that

from lisa import Environment, Logger, Node, RemoteNode, features
from lisa.base_tools.cat import Cat
from lisa.features import StartStop
from lisa.features.startstop import VMStatus
from lisa.operating_system import Redhat, Suse, Ubuntu, CBLMariner
from lisa.tools import (
    Dmesg,
    Fio,
    HibernationSetup,
    Iperf3,
    KernelConfig,
    Kill,
    Lscpu,
    Mount,
)
from lisa.tools.uptime import Uptime
from lisa.util import (
    LisaException,
    SkippedException,
    UnsupportedDistroException,
    find_group_in_lines,
)
from lisa.util.perf_timer import create_timer


def is_distro_supported(node: Node) -> None:
    if not node.tools[KernelConfig].is_enabled("CONFIG_HIBERNATION"):
        raise SkippedException(
            f"CONFIG_HIBERNATION is not enabled in current distro {node.os.name}, "
            f"version {node.os.information.version}"
        )

    if (
        (isinstance(node.os, Redhat) and node.os.information.version < "8.3.0")
        or (isinstance(node.os, Ubuntu) and node.os.information.version < "18.4.0")
        or (isinstance(node.os, Suse) and node.os.information.version < "15.3.0")
        or (isinstance(node.os, CBLMariner))
    ):
        raise SkippedException(
            f"hibernation setup tool doesn't support current distro {node.os.name}, "
            f"version {node.os.information.version}"
        )


def verify_hibernation(
    node: Node, log: Logger, throw_error: bool = True, verify_using_logs: bool = True
) -> None:
    if isinstance(node.os, Redhat):
        # Hibernation tests are run with higher os disk size.
        # In case of LVM enabled Redhat images, increasing the os disk size
        # does not increase the root partition. It requires growpart to grow the
        # partition size.
        _expand_os_partition(node, log)
    hibernation_setup_tool = node.tools[HibernationSetup]
    startstop = node.features[StartStop]
    cat = node.tools[Cat]

    node_nic = node.nics
    lower_nics_before_hibernation = node_nic.get_lower_nics()
    upper_nics_before_hibernation = node_nic.get_nic_names()
    entry_before_hibernation = hibernation_setup_tool.check_entry()
    exit_before_hibernation = hibernation_setup_tool.check_exit()
    received_before_hibernation = hibernation_setup_tool.check_received()
    uevent_before_hibernation = hibernation_setup_tool.check_uevent()

    # only set up hibernation setup tool for the first time
    hibernation_setup_tool.start()

    boot_time_before_hibernation = node.execute(
        "echo \"$(last reboot -F | head -n 1 | awk '{print $5, $6, $7, $8, $9}')\"",
        sudo=True,
        shell=True,
    ).stdout

    hibfile_offset = hibernation_setup_tool.get_hibernate_resume_offset_from_hibfile()

    try:
        startstop.stop(state=features.StopState.Hibernate)
    except Exception as ex:
        try:
            node.tools[Dmesg].get_output(force_run=True)
        except Exception as e:
            log.debug(f"error on get dmesg output: {e}")
        raise LisaException(f"fail to hibernate: {ex}")

    is_ready = True
    timeout = 900
    timer = create_timer()
    while timeout > timer.elapsed(False):
        if startstop.get_status() == VMStatus.Deallocated:
            is_ready = False
            break
    if is_ready:
        raise LisaException("VM is not in deallocated status after hibernation")

    startstop.start()

    boot_time_after_hibernation = node.execute(
        "echo \"$(last reboot -F | head -n 1 | awk '{print $5, $6, $7, $8, $9}')\"",
        sudo=True,
        shell=True,
    ).stdout

    log.info(
        f"Boot time before hibernation: {boot_time_before_hibernation},"
        f"boot time after hibernation: {boot_time_after_hibernation}"
    )
    assert_that(boot_time_before_hibernation).described_as(
        "boot time before hibernation should be equal to boot time after hibernation"
    ).is_equal_to(boot_time_after_hibernation)

    dmesg = node.tools[Dmesg]
    dmesg.check_kernel_errors(force_run=True, throw_error=throw_error)

    offset_from_cmd = hibernation_setup_tool.get_hibernate_resume_offset_from_cmd()
    offset_from_sys_power = cat.read("/sys/power/resume_offset")

    log.info(
        f"Hibfile resume offset: {hibfile_offset}, "
        f"Resume offset from cmdline: {offset_from_cmd}"
    )

    log.info(f"Resume offset from /sys/power/resume_offset: {offset_from_sys_power}")

    entry_after_hibernation = hibernation_setup_tool.check_entry()
    exit_after_hibernation = hibernation_setup_tool.check_exit()
    received_after_hibernation = hibernation_setup_tool.check_received()
    uevent_after_hibernation = hibernation_setup_tool.check_uevent()
    if verify_using_logs:
        assert_that(entry_after_hibernation - entry_before_hibernation).described_as(
            "not find 'hibernation entry'."
        ).is_equal_to(1)
        assert_that(exit_after_hibernation - exit_before_hibernation).described_as(
            "not find 'hibernation exit'."
        ).is_equal_to(1)
        assert_that(
            received_after_hibernation - received_before_hibernation
        ).described_as("not find 'Hibernation request received'.").is_equal_to(1)
        assert_that(uevent_after_hibernation - uevent_before_hibernation).described_as(
            "not find 'Sent hibernation uevent'."
        ).is_equal_to(1)

    node_nic = node.nics
    node_nic.initialize()
    lower_nics_after_hibernation = node_nic.get_lower_nics()
    upper_nics_after_hibernation = node_nic.get_nic_names()

    assert_that(len(lower_nics_after_hibernation)).described_as(
        "sriov nics count changes after hibernation."
    ).is_equal_to(len(lower_nics_before_hibernation))
    assert_that(len(upper_nics_after_hibernation)).described_as(
        "synthetic nics count changes after hibernation."
    ).is_equal_to(len(upper_nics_before_hibernation))


def run_storage_workload(node: Node) -> Decimal:
    fio = node.tools[Fio]
    fiodata = node.get_pure_path("./fiodata")
    core_count = node.tools[Lscpu].get_core_count()
    if node.shell.exists(fiodata):
        node.shell.remove(fiodata)
    fio_result = fio.launch(
        name="workload",
        filename="fiodata",
        mode="readwrite",
        numjob=core_count,
        iodepth=128,
        time=120,
        block_size="1M",
        overwrite=True,
        size_gb=1,
    )
    return fio_result.iops


def run_network_workload(environment: Environment) -> Decimal:
    client_node = cast(RemoteNode, environment.nodes[0])
    if len(environment.nodes) >= 2:
        server_node = cast(RemoteNode, environment.nodes[1])
    iperf3_server = server_node.tools[Iperf3]
    iperf3_client = client_node.tools[Iperf3]
    iperf3_server.run_as_server_async()
    iperf3_client_result = iperf3_client.run_as_client_async(
        server_ip=server_node.internal_address,
        parallel_number=8,
        run_time_seconds=120,
    )
    result_before_hb = iperf3_client_result.wait_result()
    kill = server_node.tools[Kill]
    kill.by_name("iperf3")
    return iperf3_client.get_sender_bandwidth(result_before_hb.stdout)


def cleanup_env(environment: Environment) -> None:
    remote_node = cast(RemoteNode, environment.nodes[0])
    startstop = remote_node.features[StartStop]
    if startstop.get_status() == VMStatus.Deallocated:
        startstop.start()
    for node in environment.nodes.list():
        kill = node.tools[Kill]
        kill.by_name("iperf3")
        kill.by_name("fio")
        kill.by_name("stress-ng")


def _expand_os_partition(node: Node, log: Logger) -> None:
    if isinstance(node.os, Redhat):
        pv_result = node.execute("pvscan -s", sudo=True, shell=True).stdout
        # The output of pvscan -s is like below.:
        #  /dev/sda4
        #  Total: 1 [299.31 GiB] / in use: 1 [299.31 GiB] / in no VG: 0 [0   ]
        pattern = re.compile(r"(?P<disk>.*)(?P<number>[\d]+)$", re.M)
        matched = find_group_in_lines(pv_result, pattern)
        if not matched:
            log.debug("No physical volume found. Does not require partition resize.")
            return
        disk = matched.get("disk")
        number = matched.get("number")
        node.execute(f"growpart {disk} {number}", sudo=True)
        node.execute(f"pvresize {pv_result.splitlines()[0]}", sudo=True)
        root_partition = node.tools[Mount].get_partition_info("/")[0]
        device_name = root_partition.name
        device_type = root_partition.type
        cmd_result = node.execute(f"lvdisplay {device_name}", sudo=True)
        if cmd_result.exit_code == 0:
            node.execute(f"lvextend -l 100%FREE {device_name}", sudo=True, shell=True)
            if device_type == "xfs":
                node.execute(f"xfs_growfs {device_name}", sudo=True)
            elif device_type == "ext4":
                node.execute(f"resize2fs {device_name}", sudo=True)
            else:
                raise LisaException(f"Unknown partition type: {device_type}")
        else:
            log.debug("No LV found. Does not require LV resize.")
            return
    else:
        raise UnsupportedDistroException(node.os, "OS Partition Resize not supported")
