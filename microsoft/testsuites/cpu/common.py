# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

from typing import Dict, List

from lisa import BadEnvironmentStateException, Logger, Node
from lisa.tools import Cat, Dmesg, Echo, KernelConfig, Lscpu, Lsvmbus, Uname
from lisa.util import SkippedException


class CPUState:
    OFFLINE: str = "0"
    ONLINE: str = "1"


def check_runnable(node: Node) -> None:
    if not node.tools[KernelConfig].is_built_in("CONFIG_HOTPLUG_CPU"):
        raise SkippedException(
            f"the distro {node.os.name} doesn't support cpu hotplug."
        )


def set_interrupts_assigned_cpu(
    log: Logger, node: Node, target_cpu: str = "0"
) -> Dict[str, str]:
    uname = node.tools[Uname]
    kernel_version = uname.get_linux_information().kernel_version
    dmesg = node.tools[Dmesg]
    lsvmbus = node.tools[Lsvmbus]
    vmbus_version = dmesg.get_vmbus_version()
    file_path_list: Dict[str, str] = {}
    # the vmbus interrupt channel reassignment feature is available in 5.8+ kernel and
    # vmbus version in 4.1+, the vmbus version is negotiated with the host.
    if kernel_version >= "5.8.0" and vmbus_version >= "4.1.0":
        # save the raw cpu number for each channel for restoring later.
        channels = lsvmbus.get_device_channels(force_run=True)
        for channel in channels:
            for channel_vp_map in channel.channel_vp_map:
                current_target_cpu = channel_vp_map.target_cpu
                if current_target_cpu == target_cpu:
                    continue
                file_path_list[
                    get_interrupts_assigned_cpu(
                        channel.device_id, channel_vp_map.rel_id
                    )
                ] = current_target_cpu
        # set all vmbus channel interrupts go into cpu target_cpu.
        assign_interrupts(file_path_list, node, target_cpu)
    else:
        # if current distro doesn't support this feature, the backup dict will be empty,
        # there is nothing we can restore later, the case will rely on actual cpu usage
        # on vm, if no idle cpu, then case will be skipped.
        log.debug(
            f"current distro {node.os.name}, os version {kernel_version}, "
            f"vmbus version {vmbus_version} doesn't support "
            "change channels target cpu featue."
        )
    return file_path_list


def get_idle_cpus(node: Node) -> List[str]:
    lsvmbus = node.tools[Lsvmbus]
    channels = lsvmbus.get_device_channels(force_run=True)
    # get all cpu in used from vmbus channels assignment
    cpu_in_used = set()
    for channel in channels:
        for channel_vp_map in channel.channel_vp_map:
            target_cpu = channel_vp_map.target_cpu
            if target_cpu == "0":
                continue
            cpu_in_used.add(target_cpu)

    # get all cpu exclude cpu 0, usually cpu 0 is not allowed to do hotplug
    thread_count = node.tools[Lscpu].get_thread_count()
    all_cpu = list(range(1, thread_count))

    # get the idle cpu by excluding in used cpu from all cpu
    idle_cpu = [str(x) for x in all_cpu if str(x) not in cpu_in_used]
    return idle_cpu


def set_cpu_state_serial(
    log: Logger, node: Node, idle_cpu: List[str], state: str
) -> None:
    for target_cpu in idle_cpu:
        log.debug(f"setting cpu{target_cpu} to {state}.")
        if state == CPUState.ONLINE:
            set_state = set_cpu_state(node, target_cpu, True)
        else:
            set_state = set_cpu_state(node, target_cpu, False)
        if not set_state:
            raise BadEnvironmentStateException(
                (
                    f"Expected cpu{target_cpu} state: {state}."
                    f"The test failed leaving cpu{target_cpu} in a bad state."
                ),
            )


def set_idle_cpu_offline_online(log: Logger, node: Node, idle_cpu: List[str]) -> None:
    for target_cpu in idle_cpu:
        set_offline = set_cpu_state(node, target_cpu, False)
        log.debug(f"set cpu{target_cpu} from online to offline.")
        exception_message = (
            f"expected cpu{target_cpu} state: {CPUState.OFFLINE}(offline), "
            f"actual state: {CPUState.ONLINE}(online)."
        )
        if not set_offline:
            raise BadEnvironmentStateException(
                exception_message,
                f"the test failed leaving cpu{target_cpu} in a bad state.",
            )

        set_online = set_cpu_state(node, target_cpu, True)
        log.debug(f"set cpu{target_cpu} from offline to online.")
        exception_message = (
            f"expected cpu{target_cpu} state: {CPUState.ONLINE}(online), "
            f"actual state: {CPUState.OFFLINE}(offline)."
        )
        if not set_online:
            raise BadEnvironmentStateException(
                exception_message,
                f"the test failed leaving cpu{target_cpu} in a bad state.",
            )


def verify_cpu_hot_plug(log: Logger, node: Node, run_times: int = 1) -> None:
    check_runnable(node)
    file_path_list: Dict[str, str] = {}
    restore_state = False
    try:
        for iteration in range(1, run_times + 1):
            log.debug(f"start the {iteration} time(s) testing.")
            restore_state = False
            # set vmbus channels target cpu into 0 if kernel supports this feature.
            file_path_list = set_interrupts_assigned_cpu(log, node)
            # when kernel doesn't support above feature, we have to rely on current vm's
            # cpu usage. then collect the cpu not in used exclude cpu0.
            idle_cpu = get_idle_cpus(node)
            if 0 == len(idle_cpu):
                raise SkippedException(
                    "all of the cpu are associated vmbus channels,"
                    " no idle cpu can be used to test hotplug."
                )
            # start to take idle cpu from online to offline, then offline to online.
            set_idle_cpu_offline_online(log, node, idle_cpu)
            # when kernel doesn't support set vmbus channels target cpu feature, the
            # dict which stores original status is empty, nothing need to be restored.
            restore_interrupts_assignment(file_path_list, node)
            restore_state = True
    finally:
        if not restore_state:
            restore_interrupts_assignment(file_path_list, node)


def get_cpu_state_file(cpu_id: str) -> str:
    return f"/sys/devices/system/cpu/cpu{cpu_id}/online"


def get_interrupts_assigned_cpu(device_id: str, channel_id: str) -> str:
    return f"/sys/bus/vmbus/devices/{device_id}/channels/{channel_id}/cpu"


def assign_interrupts(
    path_cpu: Dict[str, str],
    node: Node,
    target_cpu: str = "0",
) -> None:
    for path, _ in path_cpu.items():
        node.tools[Echo].write_to_file(target_cpu, node.get_pure_path(path), sudo=True)


def restore_interrupts_assignment(
    path_cpu: Dict[str, str],
    node: Node,
) -> None:
    if path_cpu:
        for path, target_cpu in path_cpu.items():
            node.tools[Echo].write_to_file(
                target_cpu, node.get_pure_path(path), sudo=True
            )


def set_cpu_state(node: Node, cpu: str, online: bool = False) -> bool:
    file_path = get_cpu_state_file(cpu)
    state = CPUState.OFFLINE
    if online:
        state = CPUState.ONLINE
    node.tools[Echo].write_to_file(state, node.get_pure_path(file_path), sudo=True)
    result = node.tools[Cat].read(file_path, force_run=True, sudo=True)
    return result == state
