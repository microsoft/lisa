import time
from copy import deepcopy
from datetime import timedelta
from pathlib import PurePosixPath
from time import sleep
from typing import List, Optional, Union, cast

from assertpy import assert_that

from lisa import (
    LisaException,
    Logger,
    Node,
    RemoteNode,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    UnsupportedCpuArchitectureException,
    create_timer,
)
from lisa.operating_system import CpuArchitecture, Redhat, Suse
from lisa.tools import Cat, Chrony, Dmesg, Hwclock, Ls, Lscpu, Ntp, Ntpstat, Service
from lisa.tools.date import Date
from lisa.tools.lscpu import CpuType
from lisa.util import constants
from lisa.util.shell import wait_tcp_port_ready


def _wait_file_changed(
    node: Node,
    path: str,
    expected_value: Optional[Union[str, List[str]]],
) -> bool:
    timeout = 60
    timout_timer = create_timer()
    while timout_timer.elapsed(False) < timeout:
        cat = node.tools[Cat]
        result = cat.run(path, force_run=True)
        if isinstance(expected_value, list):
            if result.stdout in expected_value:
                return True
        else:
            if result.stdout == expected_value:
                return True
        sleep(0.5)
    return False


@TestSuiteMetadata(
    area="time",
    category="functional",
    description="""
    This test suite is related with time sync.
    """,
)
class TimeSync(TestSuite):
    ptp_registered_msg = "PTP clock support registered"
    hyperv_ptp_udev_rule = "ptp_hyperv"
    chrony_path = [
        "/etc/chrony.conf",
        "/etc/chrony/chrony.conf",
        "/etc/chrony.d/azure.conf",
    ]
    current_clocksource = (
        "/sys/devices/system/clocksource/clocksource0/current_clocksource"
    )
    available_clocksource = (
        "/sys/devices/system/clocksource/clocksource0/available_clocksource"
    )
    unbind_clocksource = (
        "/sys/devices/system/clocksource/clocksource0/unbind_clocksource"
    )
    current_clockevent = "/sys/devices/system/clockevents/clockevent0/current_device"
    unbind_clockevent = "/sys/devices/system/clockevents/clockevent0/unbind_device"

    @TestCaseMetadata(
        description="""
        https://docs.microsoft.com/en-us/azure/virtual-machines/linux/time-sync#check-for-ptp-clock-source # noqa: E501
        This test is to check -
            1. PTP time source is available on Azure guests (newer versions of Linux).
            2. PTP device name is hyperv.
            3. When accelerated network is enabled, multiple PTP devices will
             be available, the names of ptp are changeable, create the symlink
             /dev/ptp_hyperv to whichever /dev/ptp entry corresponds to the Azure host.
            4. Chrony should be configured to use the symlink /dev/ptp_hyperv
             instead of /dev/ptp0 or /dev/ptp1.
        """,
        priority=2,
    )
    def verify_timesync_ptp(self, node: Node) -> None:
        # 1. PTP time source is available on Azure guests (newer versions of Linux).
        dmesg = node.tools[Dmesg]
        assert_that(dmesg.get_output()).contains(self.ptp_registered_msg)

        # 2. PTP device name is hyperv.
        # In some Linux VMs you may see multiple PTP devices listed.
        # One example is for Accelerated Networking the Mellanox mlx5 driver also
        # creates a /dev/ptp device. Because the initialization order can be different
        # each time Linux boots, the PTP device corresponding to the Azure host might
        # be /dev/ptp0 or it might be /dev/ptp1.
        # To determine which PTP device corresponds to the Azure host, you can check the
        # clock_name file. At least one of the PTP devices should have
        # a clock_name of 'hyperv'.
        cat = node.tools[Cat]
        ls = node.tools[Ls]
        ptp_devices = ls.list_dir("/sys/class/ptp")
        ptp_hyperv_device = None
        for ptp_device in ptp_devices:
            clock_name_result = cat.run(
                f"{ptp_device}clock_name", sudo=True, shell=True, force_run=True
            )
            if clock_name_result.stdout == "hyperv":
                ptp_hyperv_device = ptp_device
        assert_that(ptp_hyperv_device).described_as(
            "There should be at least one PTP device with name 'hyperv', more info"
            " please refer https://docs.microsoft.com/en-us/azure/virtual-machines/linux/time-sync#check-for-ptp-clock-source"  # noqa: E501
        ).is_not_none()
        # 3. When accelerated network is enabled, multiple PTP devices will
        #  be available, the names of ptp are changeable, create the symlink
        #  /dev/ptp_hyperv to whichever /dev/ptp entry corresponds to the Azure host.
        assert_that(node.shell.exists(PurePosixPath("/dev/ptp_hyperv"))).described_as(
            "/dev/ptp_hyperv doesn't exist, make sure there is a udev rule to create "
            "symlink /dev/ptp_hyperv to /dev/ptp entry corresponds to the Azure host. "
            "More info please refer "
            "https://docs.microsoft.com/en-us/azure/virtual-machines/linux/time-sync#check-for-ptp-clock-source"  # noqa: E501
        ).is_true()

        # 4. Chrony should be configured to use the symlink /dev/ptp_hyperv
        #  instead of /dev/ptp0 or /dev/ptp1.
        all_chrony_configs: str = ""
        for chrony_config in self.chrony_path:
            if node.shell.exists(PurePosixPath(chrony_config)):
                config_data = cat.run(
                    f"{chrony_config}", sudo=True, shell=True, force_run=True
                )
                all_chrony_configs = all_chrony_configs + config_data.stdout + "\n"
        assert_that(all_chrony_configs).described_as(
            "Chrony config file should use the symlink /dev/ptp_hyperv."
        ).contains(self.hyperv_ptp_udev_rule)

    @TestCaseMetadata(
        description="""
        This test is to check -
            1. Check clock source name is one of hyperv_clocksource_tsc_page,
             lis_hv_clocksource_tsc_page, hyperv_clocksource, tsc,
             arch_sys_counter(arm64).
             (there's a new feature in the AH2021 host that allows Linux guests so use
              the plain "tsc" instead of the "hyperv_clocksource_tsc_page",
              which produces a modest performance benefit when reading the clock.)
            2. Check CPU flag contains constant_tsc from /proc/cpuinfo.
            3. Check clocksource name shown up in dmesg.
            4. Unbind current clock source if there are 2+ clock sources, check current
             clock source can be switched to a different one.
        """,
        priority=2,
    )
    def verify_timesync_unbind_clocksource(self, node: Node, log: Logger) -> None:
        unbind = node.shell.exists(PurePosixPath(self.unbind_clocksource))
        try:
            # 1. Check clock source name is one of hyperv_clocksource_tsc_page,
            #  lis_hv_clocksource_tsc_page, hyperv_clocksource.
            clocksource_map = {
                CpuArchitecture.X64: [
                    "hyperv_clocksource_tsc_page",
                    "lis_hyperv_clocksource_tsc_page",
                    "hyperv_clocksource",
                    "tsc",
                ],
                CpuArchitecture.ARM64: [
                    "arch_sys_counter",
                ],
            }
            lscpu = node.tools[Lscpu]
            arch = lscpu.get_architecture()
            clocksource = clocksource_map.get(arch, None)
            if not clocksource:
                raise UnsupportedCpuArchitectureException(arch)
            cat = node.tools[Cat]
            clock_source_result = cat.run(self.current_clocksource)
            assert_that([clock_source_result.stdout]).described_as(
                f"Expected clocksource name is one of {clocksource},"
                f" but actual it is {clock_source_result.stdout}."
            ).is_subset_of(clocksource)

            # 2. Check CPU flag contains constant_tsc from /proc/cpuinfo.
            if CpuArchitecture.X64 == arch:
                cpu_info_result = cat.run("/proc/cpuinfo")
                if CpuType.Intel == lscpu.get_cpu_type():
                    expected_tsc_str = " constant_tsc "
                elif CpuType.AMD == lscpu.get_cpu_type():
                    expected_tsc_str = " tsc "
                shown_up_times = cpu_info_result.stdout.count(expected_tsc_str)
                assert_that(shown_up_times).described_as(
                    f"Expected {expected_tsc_str} shown up times in cpu flags is"
                    " equal to cpu count."
                ).is_equal_to(lscpu.get_core_count())

            # 3. Check clocksource name shown up in dmesg.
            dmesg = node.tools[Dmesg]
            assert_that(dmesg.get_output()).described_as(
                f"Expected clocksource {clock_source_result.stdout} shown up in dmesg."
            ).contains(f"clocksource {clock_source_result.stdout}")

            # 4. Unbind current clock source if there are 2+ clock sources,
            # check current clock source can be switched to a different one.
            if unbind:
                available_clocksources = cat.run(self.available_clocksource)
                available_clocksources_array = available_clocksources.stdout.split(" ")
                # We can not unbind clock source if there is only one existed.
                if len(available_clocksources_array) > 1:
                    available_clocksources_array.remove(clock_source_result.stdout)
                    cmd_result = node.execute(
                        f"echo {clock_source_result.stdout} >"
                        f" {self.unbind_clocksource}",
                        sudo=True,
                        shell=True,
                    )
                    cmd_result.assert_exit_code()

                    clock_source_result_expected = _wait_file_changed(
                        node, self.current_clocksource, available_clocksources_array
                    )
                    assert_that(clock_source_result_expected).described_as(
                        f"After unbind {clock_source_result.stdout}, current clock"
                        f" source doesn't switch properly."
                    ).is_true()
        finally:
            # after unbind, need reboot vm to bring the previous time clock source back
            if unbind:
                node.reboot()
                remote_node = cast(RemoteNode, node)
                is_ready, _ = wait_tcp_port_ready(
                    remote_node.connection_info[
                        constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS
                    ],
                    remote_node.connection_info[
                        constants.ENVIRONMENTS_NODES_REMOTE_PORT
                    ],
                    log=log,
                    timeout=300,
                )
                if not is_ready:
                    raise LisaException("vm is inaccessible after reboot.")

    @TestCaseMetadata(
        description="""
        This test is to check -
            1. Current clock event name is 'Hyper-V clockevent' for x86,
            'arch_sys_timer' for arm64.
            2. 'Hyper-V clockevent' or 'arch_sys_timer' and 'hrtimer_interrupt'
             show up times in /proc/timer_list should equal to cpu count.
            3. when cpu count is 1 and cpu type is Intel type, unbind current time
             clock event, check current time clock event switch to 'lapic'.
        """,
        priority=2,
    )
    def verify_timesync_unbind_clockevent(self, node: Node) -> None:
        if node.shell.exists(PurePosixPath(self.current_clockevent)):
            # 1. Current clock event name is 'Hyper-V clockevent'.
            clockevent_map = {
                CpuArchitecture.X64: "Hyper-V clockevent",
                CpuArchitecture.ARM64: "arch_sys_timer",
            }
            lscpu = node.tools[Lscpu]
            arch = lscpu.get_architecture()
            clock_event_name = clockevent_map.get(arch, None)
            if not clock_event_name:
                raise UnsupportedCpuArchitectureException(arch)
            cat = node.tools[Cat]
            clock_event_result = cat.run(self.current_clockevent)
            assert_that(clock_event_result.stdout).described_as(
                f"Expected clockevent name is {clock_event_name}, "
                f"but actual it is {clock_event_result.stdout}."
            ).is_equal_to(clock_event_name)

            # 2. 'Hyper-V clockevent' and 'hrtimer_interrupt' show up times in
            #  /proc/timer_list should equal to cpu count.
            event_handler_name = "hrtimer_interrupt"
            timer_list_result = cat.run("/proc/timer_list", sudo=True)
            lscpu = node.tools[Lscpu]
            core_count = lscpu.get_core_count()
            event_handler_times = timer_list_result.stdout.count(
                f"{event_handler_name}"
            )
            assert_that(event_handler_times).described_as(
                f"Expected {event_handler_name} shown up {core_count} times in output "
                f"of /proc/timer_list, but actual it shows up "
                f"{event_handler_times} times."
            ).is_equal_to(core_count)

            clock_event_times = timer_list_result.stdout.count(f"{clock_event_name}")
            assert_that(clock_event_times).described_as(
                f"Expected {clock_event_name} shown up {core_count} times in output "
                f"of /proc/timer_list, but actual it shows up "
                f"{clock_event_times} times."
            ).is_equal_to(core_count)

            # 3. when cpu count is 1 and cpu type is Intel type, unbind current time
            #  clock event, check current time clock event switch to 'lapic'.
            if CpuType.Intel == lscpu.get_cpu_type() and 1 == core_count:
                cmd_result = node.execute(
                    f"echo {clock_event_name} > {self.unbind_clockevent}",
                    sudo=True,
                    shell=True,
                )
                cmd_result.assert_exit_code()

                clock_event_result_expected = _wait_file_changed(
                    node, self.current_clockevent, "lapic"
                )
                assert_that(clock_event_result_expected).described_as(
                    f"After unbind {clock_event_name}, current clock event should "
                    f"equal to [lapic]."
                ).is_true()

    @TestCaseMetadata(
        description="""
        This test is to check, ntp works properly.
            1. Stop systemd-timesyncd if this service exists.
            2. Set rtc clock to system time.
            3. Restart Ntp service.
            4. Check and set server setting in config file.
            5. Restart Ntp service to reload with new config.
            6. Check leap code using `ntpq -c rv`.
            7. Check local time is synchronised with time server using `ntpstat`.
        """,
        priority=2,
    )
    def verify_timesync_ntp(self, node: Node) -> None:
        # On higher distro version, ntp is replaced by chrony. So skip this test.
        if (isinstance(node.os, Redhat) and node.os.information.version >= "8.0.0") or (
            isinstance(node.os, Suse) and node.os.information.version >= "15.0.0"
        ):
            raise SkippedException(
                f"The distro {node.os.name} {node.os.information.version} doesn't "
                "support ntp, because the ntp package is no longer supported and "
                "it is implemented by the chronyd (a daemon that runs in user-space) "
                "which is provided in the chrony package."
            )
        ntp = node.tools[Ntp]
        hwclock = node.tools[Hwclock]
        service = node.tools[Service]
        # 1. Stop systemd-timesyncd if this service exists.
        service.stop_service("systemd-timesyncd")
        # 2. Set rtc clock to system time.
        hwclock.set_rtc_clock_to_system_time()
        # 3. Restart Ntp service.
        ntp.restart()
        # 4. Check and set server setting in config file.
        ntp.set_server_setting()
        # 5. Restart Ntp service to reload with new config.
        ntp.restart()
        # 6. Check leap code using `ntpq -c rv`.
        ntp.check_leap_code()
        ntpstat = node.tools[Ntpstat]
        # 7. Check local time is synchronised with time server using `ntpstat`.
        ntpstat.check_time_sync()

    @TestCaseMetadata(
        description="""
        This test is to check chrony works properly.
            1. Restart chrony service.
            2. Check and set server setting in config file.
            3. Restart chrony service to reload with new config.
            4. Check chrony sources and sourcestats.
            5. Check chrony tracking.
        """,
        priority=2,
    )
    def verify_timesync_chrony(self, node: Node) -> None:
        chrony = node.tools[Chrony]
        # 1. Restart chrony service.
        chrony.restart()
        # 2. Check and set server setting in config file.
        chrony.set_server_setting()
        # 3. Restart chrony service to reload with new config.
        chrony.restart()
        # 4. Check chrony sources and sourcestats.
        chrony.check_sources_and_stats()
        # 5. Check chrony tracking.
        chrony.check_tracking()

    @TestCaseMetadata(
        description="""
        This test is to check "initcall_blacklist=arm_pmu_acpi_init"
        kernel parameter for ARM64 images.

        Since Hyper-V right now doesn't surface a fully functional PMU. It is needed to
        have "initcall_blacklist=arm_pmu_acpi_init" to disable the PMU driver
        temporarily to fall back to a timer-based sampling instead of PMU-event-based
        sampling.
        """,
        priority=1,
    )
    def verify_pmu_disabled_for_arm64(self, node: Node) -> None:
        lscpu = node.tools[Lscpu]
        arch = lscpu.get_architecture()
        if arch != CpuArchitecture.ARM64:
            raise SkippedException(
                f"This test case does not support {arch}. "
                "This validation is only for ARM64."
            )
        # Check pmu is disabled in cmdline for arm64 images
        cat = node.tools[Cat]
        result = cat.run("/proc/cmdline", force_run=True)
        if "initcall_blacklist=arm_pmu_acpi_init" not in result.stdout:
            raise LisaException("PMU is not disabled in kernel cmdline")

    @TestCaseMetadata(
        description="""
        This test is to verify that timedrift is automatically corrected by chrony
        after a time jump.

        Steps:
        1. Set makestep to 1.0 -1 to allow Chrony to make large adjustments.
        Ref: https://learn.microsoft.com/en-us/azure/virtual-machines/linux/time-sync#chrony # noqa: E501
        2. Manually change the system clock to a time in the past.
        3. Verify that Chrony has corrected the time drift.
        """,
        priority=1,
    )
    def verify_timedrift_corrected(self, node: Node, log: Logger) -> None:
        # Initialize chrony
        chrony = node.tools[Chrony]
        chrony.set_makestep("1.0 -1")
        chrony.restart()

        for iteration in range(3):
            is_drift_corrected = False

            # Get current time
            date = node.tools[Date]
            node_time = date.current()
            modified_time = deepcopy(node_time)
            modified_time = modified_time - timedelta(days=2)
            date.set(modified_time)

            # Poll every second and check if the time drift is corrected
            # for 5 minutes
            for poll_iter in range(120):
                time.sleep(1)
                current_time = date.current()
                if current_time > node_time:
                    is_drift_corrected = True
                    break
                if poll_iter % 10 == 0:
                    log.debug(
                        f"Iteration {iteration}: Time drift is not corrected by "
                        "chrony yet. Retrying..."
                    )
            assert_that(is_drift_corrected, "Time drift is not corrected by chrony.")
