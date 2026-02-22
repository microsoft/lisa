# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from decimal import Decimal
from typing import Any, List, cast

from assertpy import assert_that

from lisa import Environment, Logger, Node, RemoteNode, features
from lisa.features import StartStop
from lisa.features.startstop import VMStatus
from lisa.operating_system import BSD, SLES, AlmaLinux, Debian, Redhat, Ubuntu, Windows
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.tools import (
    Cat,
    Df,
    Dmesg,
    Fio,
    Free,
    HibernationSetup,
    Hwclock,
    Iperf3,
    KernelConfig,
    Kill,
    Ls,
    Lscpu,
    ResizePartition,
    Who,
)
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


def check_hibernation_disk_requirements(node: Node) -> None:
    """
    Check if the VM has sufficient disk space for hibernation.
    Hibernation requires disk space based on RAM size using the formula:
    - 2 × RAM if RAM ≤ 8 GB
    - 1.5 × RAM if 8 < RAM ≤ 64 GB
    - RAM if 64 < RAM ≤ 256 GB
    - Not supported if RAM > 256 GB
    """
    free_tool = node.tools[Free]
    df_tool = node.tools[Df]

    # Get total memory in GB
    total_memory_gb = float(free_tool.get_total_memory_gb())

    # Skip hibernation check for VMs with > 256 GB RAM
    if total_memory_gb > 256:
        raise SkippedException(
            f"Hibernation is not supported for VMs with RAM > 256 GB. "
            f"Current RAM: {total_memory_gb:.2f} GB"
        )

    # Calculate required disk space based on RAM size
    if total_memory_gb <= 8:
        required_space_gb = 2 * total_memory_gb
        formula = "2*RAM"
    elif total_memory_gb <= 64:
        required_space_gb = 1.5 * total_memory_gb
        formula = "1.5*RAM"
    else:
        required_space_gb = total_memory_gb
        formula = "RAM"

    root_partition = df_tool.get_partition_by_mountpoint("/", force_run=True)
    assert root_partition is not None, "Unable to determine root partition disk space"

    # available_blocks is in 1K blocks, convert to GB
    available_space_gb = root_partition.available_blocks / 1024 / 1024

    if available_space_gb < required_space_gb:
        raise LisaException(
            "Insufficient disk space for hibernation. "
            f"Memory size: {total_memory_gb:.2f} GB, "
            f"Available space: {available_space_gb:.2f} GB, "
            f"Required space: {required_space_gb:.2f} GB ({formula}). "
            "Please increase 'osdisk_size_in_gb'."
        )


def _prepare_hibernation_environment(node: Node) -> None:
    """
    Prepare the hibernation environment by handling OS-specific requirements.
    """
    if isinstance(node.os, Redhat):
        # Hibernation tests are run with higher os disk size.
        # In case of LVM enabled Redhat images, increasing the os disk size
        # does not increase the root partition. It requires growpart to grow the
        # partition size.
        resize = node.tools[ResizePartition]
        resize.expand_os_partition()


def hibernation_before_case(node: Node, log: Logger) -> None:
    """
    Common before_case logic for hibernation tests.
    Validates OS support and prepares the environment.
    """
    if isinstance(node.os, BSD) or isinstance(node.os, Windows):
        raise SkippedException(f"{node.os} is not supported.")

    # Expand OS partition first (needed for RHEL/LVM before checking disk space)
    _prepare_hibernation_environment(node)

    check_hibernation_disk_requirements(node)


def _perform_hibernation_cycle(
    node: Node, log: Logger, throw_error: bool = True
) -> tuple[Any, Any]:
    """
    Common hibernation cycle logic shared by both hibernation methods.
    Returns (boot_time_before, boot_time_after) for verification.
    """

    # This is a temporary workaround for a bug observed in Redhat Distros
    # where the VM is not able to hibernate immediately after installing
    # the hibernation-setup tool.
    # A sleep(100) also works, but we are unsure of the exact time required.
    # So it is safer to reboot the VM.
    if type(node.os) in (Redhat, AlmaLinux, SLES):
        node.reboot()

    startstop = node.features[StartStop]
    dmesg = node.tools[Dmesg]
    who = node.tools[Who]

    boot_time_before_hibernation = who.last_boot()

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

    return boot_time_before_hibernation, boot_time_after_hibernation


def _verify_common_hibernation_requirements(
    node: Node,
    log: Logger,
    boot_time_before: Any,
    boot_time_after: Any,
    lower_nics_before: List[Any],
    upper_nics_before: List[str],
    throw_error: bool = True,
) -> None:
    """
    Common hibernation verification logic shared by both hibernation methods.
    """
    dmesg = node.tools[Dmesg]

    try:
        assert_that(boot_time_before).described_as(
            "boot time before hibernation should be equal to boot time "
            "after hibernation"
        ).is_equal_to(boot_time_after)
    except AssertionError:
        dmesg.check_kernel_errors(force_run=True, throw_error=True)
        raise

    node_nic = node.nics
    node_nic.initialize()
    lower_nics_after_hibernation = node_nic.get_all_pci_nics()
    upper_nics_after_hibernation = node_nic.get_nic_names()

    assert_that(len(lower_nics_after_hibernation)).described_as(
        "sriov nics count changes after hibernation."
    ).is_equal_to(len(lower_nics_before))
    assert_that(len(upper_nics_after_hibernation)).described_as(
        "synthetic nics count changes after hibernation."
    ).is_equal_to(len(upper_nics_before))

    dmesg.check_kernel_errors(force_run=True, throw_error=throw_error)


def verify_hibernation_by_tool(
    node: Node, log: Logger, throw_error: bool = True, verify_using_logs: bool = True
) -> None:
    """
    Verify hibernation using the hibernation-setup-tool.

    This method installs and configures hibernation-setup-tool,
    then verifies hibernation through tool-specific logs and metrics.
    """
    node_nic = node.nics
    lower_nics_before_hibernation = node_nic.get_all_pci_nics()
    upper_nics_before_hibernation = node_nic.get_nic_names()

    hibernation_setup_tool = node.tools[HibernationSetup]

    # Get initial counts before hibernation
    entry_before_hibernation = hibernation_setup_tool.check_entry()
    exit_before_hibernation = hibernation_setup_tool.check_exit()
    received_before_hibernation = hibernation_setup_tool.check_received()
    uevent_before_hibernation = hibernation_setup_tool.check_uevent()

    # only set up hibernation setup tool for the first time
    hibernation_setup_tool.start()

    hibfile_offset = hibernation_setup_tool.get_hibernate_resume_offset_from_hibfile()

    # Perform hibernation cycle
    boot_time_before, boot_time_after = _perform_hibernation_cycle(
        node, log, throw_error
    )

    # Verify hibernation-specific logs and metrics
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

    # Verify hibernation logs if requested
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

    # Perform common hibernation verification
    _verify_common_hibernation_requirements(
        node,
        log,
        boot_time_before,
        boot_time_after,
        lower_nics_before_hibernation,
        upper_nics_before_hibernation,
        throw_error,
    )


def verify_hibernation_by_vm_extension(
    node: Node, log: Logger, throw_error: bool = True
) -> None:
    """
    Verify hibernation using the LinuxHibernateExtension.

    This method installs and configures the LinuxHibernateExtension,
    then verifies hibernation through boot time consistency and
    network interface verification.
    """
    azure_extension = node.features[AzureExtension]
    extension_name = "LinuxHibernateExtension"

    try:
        # Install LinuxHibernateExtension
        log.info("Installing LinuxHibernateExtension...")
        extension_result = azure_extension.create_or_update(
            type_="LinuxHibernateExtension",
            name=extension_name,
            publisher="Microsoft.CPlat.Core",
            type_handler_version="1.0",
            auto_upgrade_minor_version=True,
            timeout=60 * 15,
        )

        log.debug(f"Extension installation result: {extension_result}")
        provisioning_state = extension_result["provisioning_state"]
        assert_that(provisioning_state).described_as(
            "Expected the extension to succeed"
        ).is_equal_to("Succeeded")

    except Exception:
        check_os_disk_space(node, log)
        collect_hibernation_extension_logs(node, log)
        log.info("Marking node as dirty due to hibernation extension test failure")
        node.mark_dirty()
        raise

    node_nic = node.nics
    lower_nics_before_hibernation = node_nic.get_all_pci_nics()
    upper_nics_before_hibernation = node_nic.get_nic_names()

    # Perform hibernation cycle
    boot_time_before, boot_time_after = _perform_hibernation_cycle(
        node, log, throw_error
    )

    # Perform common hibernation verification
    _verify_common_hibernation_requirements(
        node,
        log,
        boot_time_before,
        boot_time_after,
        lower_nics_before_hibernation,
        upper_nics_before_hibernation,
        throw_error,
    )


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


def verify_hibernation(
    node: Node,
    log: Logger,
    throw_error: bool = True,
    verify_using_logs: bool = True,
    use_hibernation_setup_tool: bool = True,
) -> None:
    # Delegate to the appropriate hibernation method
    if use_hibernation_setup_tool:
        verify_hibernation_by_tool(node, log, throw_error, verify_using_logs)
    else:
        verify_hibernation_by_vm_extension(node, log, throw_error)


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


def check_os_disk_space(node: Node, log: Logger) -> None:
    df = node.tools[Df]
    root_partition = df.get_partition_by_mountpoint("/")
    if root_partition:
        available_gb = (
            root_partition.available_blocks / 1024 / 1024
        )  # Convert from KB to GB
        used_percent = root_partition.percentage_blocks_used
        total_gb = root_partition.total_blocks / 1024 / 1024  # Convert from KB to GB

        log.info(
            f"OS Disk Space (/) - Total: {total_gb:.2f}GB, "
            f"Used: {used_percent}%, Available: {available_gb:.2f}GB"
        )
        # Check if low disk space might be causing issues
        if available_gb < 1.0:  # Less than 1GB available
            log.info(
                f"LOW DISK SPACE WARNING: Only {available_gb:.2f}GB "
                f"available on OS disk"
            )
        elif used_percent > 90:  # More than 90% used
            log.info(f"HIGH DISK USAGE WARNING: {used_percent}% of OS disk is used")
    else:
        log.debug("Could not get root partition space information")


def collect_hibernation_extension_logs(node: Node, log: Logger) -> None:
    """Collect and print LinuxHibernateExtension logs for debugging"""
    extension_log_dir = "/var/log/azure/Microsoft.CPlat.Core.LinuxHibernateExtension"
    extension_log_path = node.get_pure_path(extension_log_dir)

    # Check if the log directory exists
    if not node.shell.exists(extension_log_path):
        log.info(f"Extension log directory {extension_log_path} does not exist")
        return
    ls = node.tools[Ls]
    cat = node.tools[Cat]

    log_files = ls.list(extension_log_dir, sudo=True)
    log_files.sort()

    if not log_files:
        log.info("No extension log files found")
        return

    log.debug(f"Found {len(log_files)} extension log files: {', '.join(log_files)}")

    # Print contents of each log file
    for log_file in log_files:
        if not log_file.strip():
            continue

        log_file_path = log_file.strip()

        # Check if it's a directory and skip it
        if not ls.is_file(node.get_pure_path(log_file_path), sudo=True):
            log.debug(f"Skipping {log_file_path} (directory)")
            continue

        # Extract just the filename for display
        log_filename = log_file_path.split("/")[-1]
        log.info(f"=== Contents of {log_filename} ===")

        try:
            content = cat.read(log_file_path, sudo=True)
            log.info(f"{log_filename} content:\n{content}")
        except Exception as cat_ex:
            log.debug(f"Failed to read {log_file_path}: {cat_ex}")

        log.info(f"=== End of {log_filename} ===")
