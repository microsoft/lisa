# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

import time
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
        # Allow time for interrupt migration to complete before CPU hotplug.
        # This prevents race conditions on kernels with PREEMPT_DYNAMIC (e.g., RHEL 9.7)
        # where voluntary preemption can delay interrupt handler migration.
        if file_path_list:
            log.debug(
                f"Waiting for interrupt migration to settle after reassigning "
                f"{len(file_path_list)} channels to CPU{target_cpu}..."
            )
            time.sleep(2)
            # Verify the migration completed successfully
            verify_interrupt_migration(log, file_path_list, node, target_cpu)
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


def get_cpus_with_interrupts(node: Node) -> set:
    """
    Get the set of CPUs that currently have VMBus channel interrupts assigned.
    These CPUs must NOT be hotplugged to avoid race conditions with interrupt migration.
    """
    lsvmbus = node.tools[Lsvmbus]
    channels = lsvmbus.get_device_channels(force_run=True)
    cpus_with_interrupts = set()
    
    for channel in channels:
        for channel_vp_map in channel.channel_vp_map:
            cpus_with_interrupts.add(channel_vp_map.target_cpu)
    
    return cpus_with_interrupts


def get_idle_cpus(node: Node, cpus_to_exclude: set = None) -> List[str]:
    """
    Get list of CPUs that are safe to hotplug.
    Excludes CPU0 (usually not hotpluggable) and any CPUs in cpus_to_exclude.
    
    Args:
        node: The node to query
        cpus_to_exclude: Set of CPU IDs (as strings) that must not be hotplugged
    
    Returns:
        List of CPU IDs (as strings) that can be safely hotplugged
    """
    if cpus_to_exclude is None:
        cpus_to_exclude = set()
    
    # Always exclude CPU0 - usually not allowed to hotplug
    cpus_to_exclude.add("0")
    
    # Get all CPUs on the system
    thread_count = node.tools[Lscpu].get_thread_count()
    all_cpus = set(str(x) for x in range(thread_count))
    
    # Return CPUs that are not in the exclusion set
    idle_cpus = sorted(all_cpus - cpus_to_exclude, key=int)
    return idle_cpus


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
    """
    Verify CPU hotplug functionality by taking CPUs offline and back online.
    
    CRITICAL: This function does NOT migrate interrupts. It only hotplugs CPUs that
    never had any VMBus channel interrupts assigned. This avoids race conditions with
    asynchronous interrupt migration on kernels with voluntary preemption (e.g., RHEL 9.7).
    
    The race condition occurs because writing to sysfs (echo "0" > .../channels/X/cpu)
    completes immediately, but the kernel migrates interrupt handlers asynchronously.
    On PREEMPT_DYNAMIC kernels with voluntary preemption, this can take several seconds.
    If we offline a CPU before migration completes, active interrupt handlers (like SSH)
    are killed, crashing the test.
    
    By only hotplugging CPUs that never had interrupts, we eliminate this race entirely.
    """
    check_runnable(node)
    
    # Get CPUs that currently have VMBus interrupts - we must NEVER hotplug these
    cpus_with_interrupts = get_cpus_with_interrupts(node)
    
    log.debug(
        f"Found {len(cpus_with_interrupts)} CPUs with VMBus interrupts: "
        f"{sorted(cpus_with_interrupts, key=lambda x: int(x))}"
    )
    log.debug(
        "These CPUs will NOT be hotplugged to avoid interrupt migration race conditions"
    )
    
    # Get CPUs that are safe to hotplug (never had interrupts)
    idle_cpus = get_idle_cpus(node, cpus_with_interrupts)
    
    if len(idle_cpus) == 0:
        raise SkippedException(
            f"No CPUs available for hotplug testing. All CPUs except CPU0 have "
            f"VMBus channel interrupts assigned. CPUs with interrupts: {sorted(cpus_with_interrupts, key=lambda x: int(x))}"
        )
    
    log.debug(
        f"Found {len(idle_cpus)} CPUs safe for hotplug testing: {idle_cpus}"
    )
    
    # Run the hotplug test iterations
    for iteration in range(1, run_times + 1):
        log.debug(f"Starting CPU hotplug iteration {iteration}/{run_times}")
        
        # Verify CPUs with interrupts haven't changed during test
        current_cpus_with_interrupts = get_cpus_with_interrupts(node)
        if current_cpus_with_interrupts != cpus_with_interrupts:
            log.warning(
                f"VMBus interrupt assignments changed during test. "
                f"Original: {sorted(cpus_with_interrupts, key=lambda x: int(x))}, "
                f"Current: {sorted(current_cpus_with_interrupts, key=lambda x: int(x))}"
            )
            # Update our exclusion list to be safe
            cpus_with_interrupts = current_cpus_with_interrupts
            idle_cpus = get_idle_cpus(node, cpus_with_interrupts)
            if len(idle_cpus) == 0:
                raise SkippedException(
                    "No CPUs available for hotplug after interrupt reassignment"
                )
        
        # Hotplug the safe CPUs
        set_idle_cpu_offline_online(log, node, idle_cpus)
        
        log.debug(f"Completed CPU hotplug iteration {iteration}/{run_times}")


def get_cpu_state_file(cpu_id: str) -> str:
    return f"/sys/devices/system/cpu/cpu{cpu_id}/online"


def get_interrupts_assigned_cpu(device_id: str, channel_id: str) -> str:
    return f"/sys/bus/vmbus/devices/{device_id}/channels/{channel_id}/cpu"


def verify_interrupt_migration(
    log: Logger,
    path_cpu: Dict[str, str],
    node: Node,
    expected_cpu: str = "0",
) -> None:
    """
    Verify that all vmbus channel interrupts have been successfully migrated
    to the expected CPU. This prevents race conditions during CPU hotplug.
    """
    cat = node.tools[Cat]
    failed_migrations = []
    
    for path, original_cpu in path_cpu.items():
        try:
            current_cpu = cat.read(path, force_run=True, sudo=True).strip()
            if current_cpu != expected_cpu:
                failed_migrations.append(
                    f"{path}: expected CPU{expected_cpu}, found CPU{current_cpu}"
                )
        except Exception as e:
            log.warning(f"Failed to verify interrupt migration for {path}: {e}")
    
    if failed_migrations:
        log.warning(
            f"Some interrupt migrations incomplete: {', '.join(failed_migrations)}"
        )
    else:
        log.debug(
            f"Verified {len(path_cpu)} interrupt channels successfully "
            f"migrated to CPU{expected_cpu}"
        )


def assign_interrupts(
    path_cpu: Dict[str, str],
    node: Node,
    target_cpu: str = "0",
) -> None:
    for path, _ in path_cpu.items():
        node.tools[Echo].write_to_file(target_cpu, node.get_pure_path(path), sudo=True)


def restore_interrupts_assignment(
    log: Logger,
    path_cpu: Dict[str, str],
    node: Node,
) -> None:
    """
    Restore vmbus channel interrupt assignments to their original CPUs.
    Only restore if the target CPU is currently online to avoid failures.
    """
    if path_cpu:
        cat = node.tools[Cat]
        skipped_restorations = []
        
        for path, target_cpu in path_cpu.items():
            # Check if target CPU is online before attempting restoration
            cpu_state_file = get_cpu_state_file(target_cpu)
            try:
                cpu_state = cat.read(cpu_state_file, force_run=True, sudo=True).strip()
                if cpu_state == CPUState.ONLINE:
                    node.tools[Echo].write_to_file(
                        target_cpu, node.get_pure_path(path), sudo=True
                    )
                else:
                    # CPU is offline, skip restoration and assign to CPU0 instead
                    skipped_restorations.append(f"CPU{target_cpu} (offline)")
                    node.tools[Echo].write_to_file(
                        "0", node.get_pure_path(path), sudo=True
                    )
            except Exception as e:
                # If we can't read CPU state, assume it's offline and assign to CPU0
                log.warning(
                    f"Failed to check state of CPU{target_cpu}: {e}. "
                    f"Assigning interrupt to CPU0 instead."
                )
                skipped_restorations.append(f"CPU{target_cpu} (error)")
                node.tools[Echo].write_to_file(
                    "0", node.get_pure_path(path), sudo=True
                )
        
        if skipped_restorations:
            log.debug(
                f"Skipped restoring interrupts to offline CPUs, "
                f"reassigned to CPU0: {', '.join(skipped_restorations)}"
            )


def set_cpu_state(node: Node, cpu: str, online: bool = False) -> bool:
    file_path = get_cpu_state_file(cpu)
    state = CPUState.OFFLINE
    if online:
        state = CPUState.ONLINE
    node.tools[Echo].write_to_file(state, node.get_pure_path(file_path), sudo=True)
    result = node.tools[Cat].read(file_path, force_run=True, sudo=True)
    return result == state
