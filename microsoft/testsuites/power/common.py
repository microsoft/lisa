# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from decimal import Decimal
from typing import cast

from assertpy import assert_that

from lisa import Environment, Logger, Node, RemoteNode, features
from lisa.features import StartStop
from lisa.features.startstop import VMStatus
from lisa.operating_system import SLES, AlmaLinux, Debian, Redhat, Ubuntu
from lisa.tools import (
    Dmesg,
    Fio,
    HibernationSetup,
    Iperf3,
    KernelConfig,
    Kill,
    Lscpu,
    ResizePartition,
)
from lisa.tools.hwclock import Hwclock
from lisa.tools.who import Who
from lisa.util import LisaException, SkippedException
from lisa.util.perf_timer import create_timer


def is_distro_supported(node: Node) -> None:
    if not node.tools[KernelConfig].is_enabled("CONFIG_HIBERNATION"):
        raise SkippedException(
            f"CONFIG_HIBERNATION is not enabled in current distro {node.os.name}, "
            f"version {node.os.information.version}"
        )

    if not (
        (type(node.os) is Ubuntu and node.os.information.version >= "18.4.0")
        or (type(node.os) is Redhat and node.os.information.version >= "8.3.0")
        or (type(node.os) is Debian and node.os.information.version >= "10.0.0")
        or (type(node.os) is SLES and node.os.information.version >= "15.6.0")
        or (type(node.os) is AlmaLinux and node.os.information.version >= "9.5.0")
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
        resize = node.tools[ResizePartition]
        resize.expand_os_partition()
    hibernation_setup_tool = node.tools[HibernationSetup]
    startstop = node.features[StartStop]
    dmesg = node.tools[Dmesg]
    who = node.tools[Who]

    node_nic = node.nics
    lower_nics_before_hibernation = node_nic.get_lower_nics()
    upper_nics_before_hibernation = node_nic.get_nic_names()
    entry_before_hibernation = hibernation_setup_tool.check_entry()
    exit_before_hibernation = hibernation_setup_tool.check_exit()
    received_before_hibernation = hibernation_setup_tool.check_received()
    uevent_before_hibernation = hibernation_setup_tool.check_uevent()

    # only set up hibernation setup tool for the first time
    hibernation_setup_tool.start()
    # This is a temporary workaround for a bug observed in Redhat Distros
    # where the VM is not able to hibernate immediately after installing
    # the hibernation-setup tool.
    # A sleep(100) also works, but we are unsure of the exact time required.
    # So it is safer to reboot the VM.
    if type(node.os) in (Redhat, AlmaLinux, SLES):
        node.reboot()

    boot_time_before_hibernation = who.last_boot()
    hibfile_offset = hibernation_setup_tool.get_hibernate_resume_offset_from_hibfile()

    try:
        startstop.stop(state=features.StopState.Hibernate)
    except Exception as ex:
        try:
            dmesg.get_output(force_run=True)
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

    boot_time_after_hibernation = who.last_boot()
    log.info(
        f"Last Boot time before hibernation: {boot_time_before_hibernation}, "
        f"Last Boot time after hibernation: {boot_time_after_hibernation}"
    )

    entry_after_hibernation = hibernation_setup_tool.check_entry()
    exit_after_hibernation = hibernation_setup_tool.check_exit()
    received_after_hibernation = hibernation_setup_tool.check_received()
    uevent_after_hibernation = hibernation_setup_tool.check_uevent()

    offset_from_cmd = hibernation_setup_tool.get_hibernate_resume_offset_from_cmd()
    offset_from_sys_power = (
        hibernation_setup_tool.get_hibernate_resume_offset_from_sys_power()
    )

    log.info(
        f"Hibfile resume offset: {hibfile_offset}, "
        f"Resume offset from cmdline: {offset_from_cmd}, "
        f"Resume offset from /sys/power/resume_offset: {offset_from_sys_power}"
    )

    try:
        assert_that(boot_time_before_hibernation).described_as(
            "boot time before hibernation should be equal to boot time "
            "after hibernation"
        ).is_equal_to(boot_time_after_hibernation)
    except AssertionError:
        dmesg.check_kernel_errors(force_run=True, throw_error=True)
        raise

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

    dmesg.check_kernel_errors(force_run=True, throw_error=throw_error)


def run_storage_workload(node: Node) -> Decimal:
    fio = node.tools[Fio]
    fiodata = node.get_pure_path("./fiodata")
    thread_count = node.tools[Lscpu].get_thread_count()
    if node.shell.exists(fiodata):
        node.shell.remove(fiodata)
    fio_result = fio.launch(
        name="workload",
        filename="fiodata",
        mode="readwrite",
        numjob=thread_count,
        iodepth=128,
        time=120,
        block_size="1M",
        overwrite=True,
        size_gb=1,
    )
    return fio_result.iops


def run_network_workload(environment: Environment) -> Decimal:
    assert_that(len(environment.nodes)).described_as(
        "Expected environment to have at least 2 nodes"
    ).is_greater_than_or_equal_to(2)

    client_node = cast(RemoteNode, environment.nodes[0])
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
    hwclock = remote_node.tools[Hwclock]
    hwclock.set_rtc_clock_to_system_time()
    startstop = remote_node.features[StartStop]
    if startstop.get_status() == VMStatus.Deallocated:
        startstop.start()
    for node in environment.nodes.list():
        kill = node.tools[Kill]
        kill.by_name("iperf3")
        kill.by_name("fio")
        kill.by_name("stress-ng")
