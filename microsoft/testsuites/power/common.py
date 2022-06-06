# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from decimal import Decimal
from typing import cast

from assertpy import assert_that

from lisa import Environment, Logger, RemoteNode, features
from lisa.features import StartStop
from lisa.operating_system import Redhat, Suse, Ubuntu
from lisa.tools import Fio, HibernationSetup, Iperf3, Kill, Lscpu
from lisa.util import LisaException, SkippedException
from lisa.util.perf_timer import create_timer
from lisa.util.shell import wait_tcp_port_ready


def is_distro_supported(node: RemoteNode) -> None:
    if (
        (isinstance(node.os, Redhat) and node.os.information.version < "8.3.0")
        or (isinstance(node.os, Ubuntu) and node.os.information.version < "18.4.0")
        or (isinstance(node.os, Suse) and node.os.information.version < "15.3.0")
    ):
        raise SkippedException(
            f"hibernation setup tool doesn't support current distro {node.os.name}, "
            f"version {node.os.information.version}"
        )


def verify_hibernation(node: RemoteNode, log: Logger) -> None:
    node_nic = node.nics
    lower_nics_before_hibernation = node_nic.get_lower_nics()
    upper_nics_before_hibernation = node_nic.get_upper_nics()
    hibernation_setup_tool = node.tools[HibernationSetup]
    entry_before_hibernation = hibernation_setup_tool.check_entry()
    exit_before_hibernation = hibernation_setup_tool.check_exit()
    received_before_hibernation = hibernation_setup_tool.check_received()
    uevent_before_hibernation = hibernation_setup_tool.check_uevent()
    startstop = node.features[StartStop]
    hibernation_setup_tool.start()
    startstop.stop(state=features.StopState.Hibernate)
    is_ready = True
    timeout = 900
    timer = create_timer()
    while timeout > timer.elapsed(False):
        is_ready, _ = wait_tcp_port_ready(
            node.public_address,
            node.public_port,
            log=log,
            timeout=10,
        )
        if not is_ready:
            break
    if is_ready:
        raise LisaException("VM still can be accessed after hibernation")
    startstop.start()
    entry_after_hibernation = hibernation_setup_tool.check_entry()
    exit_after_hibernation = hibernation_setup_tool.check_exit()
    received_after_hibernation = hibernation_setup_tool.check_received()
    uevent_after_hibernation = hibernation_setup_tool.check_uevent()
    assert_that(
        entry_after_hibernation - entry_before_hibernation,
        "not find 'hibernation entry'.",
    ).is_equal_to(1)
    assert_that(
        exit_after_hibernation - exit_before_hibernation,
        "not find 'hibernation exit'.",
    ).is_equal_to(1)
    assert_that(
        received_after_hibernation - received_before_hibernation,
        "not find 'Hibernation request received'.",
    ).is_equal_to(1)
    assert_that(
        uevent_after_hibernation - uevent_before_hibernation,
        "not find 'Sent hibernation uevent'.",
    ).is_equal_to(1)

    node_nic = node.nics
    node_nic.initialize()
    lower_nics_after_hibernation = node_nic.get_lower_nics()
    upper_nics_after_hibernation = node_nic.get_upper_nics()
    assert_that(
        len(lower_nics_after_hibernation),
        "sriov nics count changes after hibernation.",
    ).is_equal_to(len(lower_nics_before_hibernation))
    assert_that(
        len(upper_nics_after_hibernation),
        "synthetic nics count changes after hibernation.",
    ).is_equal_to(len(upper_nics_before_hibernation))


def run_storage_workload(node: RemoteNode) -> Decimal:
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
    startstop.start()
    for node in environment.nodes.list():
        kill = node.tools[Kill]
        kill.by_name("iperf3")
        kill.by_name("fio")
        kill.by_name("stress-ng")
