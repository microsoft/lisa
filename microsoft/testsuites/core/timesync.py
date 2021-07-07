from pathlib import PurePosixPath
from time import sleep
from typing import List, Optional, Union

from assertpy import assert_that

from lisa import Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.tools import Cat, Dmesg, Lscpu
from lisa.tools.lscpu import CpuType
from lisa.util.perf_timer import create_timer


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
    chrony_path = ["/etc/chrony.conf", "/etc/chrony/chrony.conf"]
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
    def timesync_validate_ptp(self, node: Node) -> None:
        # 1. PTP time source is available on Azure guests (newer versions of Linux).
        dmesg = node.tools[Dmesg]
        assert_that(dmesg.get_output()).contains(self.ptp_registered_msg)

        # 2. PTP device name is hyperv.
        cat = node.tools[Cat]
        clock_name_result = cat.run("/sys/class/ptp/ptp0/clock_name")
        assert_that(clock_name_result.stdout).described_as(
            f"ptp clock name should be 'hyperv', meaning the Azure host, "
            f"but it is {clock_name_result.stdout}, more info please refer "
            f"https://docs.microsoft.com/en-us/azure/virtual-machines/linux/time-sync#check-for-ptp-clock-source"  # noqa: E501
        ).is_equal_to("hyperv")

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
        for chrony_config in self.chrony_path:
            if node.shell.exists(PurePosixPath(chrony_config)):
                chrony_results = cat.run(f"{chrony_config}")
                assert_that(chrony_results.stdout).described_as(
                    "Chrony config file should use the symlink /dev/ptp_hyperv."
                ).contains(self.hyperv_ptp_udev_rule)

    @TestCaseMetadata(
        description="""
        This test is to check -
            1. Check clock source name is one of hyperv_clocksource_tsc_page,
             lis_hv_clocksource_tsc_page, hyperv_clocksource.
            2. Check CPU flag contains constant_tsc from /proc/cpuinfo.
            3. Check clocksource name shown up in dmesg.
            4. Unbind current clock source if there are 2+ clock sources, check current
             clock source can be switched to a different one.
        """,
        priority=2,
    )
    def timesync_check_unbind_clocksource(self, node: Node) -> None:
        # 1. Check clock source name is one of hyperv_clocksource_tsc_page,
        #  lis_hv_clocksource_tsc_page, hyperv_clocksource.
        clocksource = [
            "hyperv_clocksource_tsc_page",
            "lis_hyperv_clocksource_tsc_page",
            "hyperv_clocksource",
        ]
        cat = node.tools[Cat]
        clock_source_result = cat.run(self.current_clocksource)
        assert_that([clock_source_result.stdout]).described_as(
            f"Expected clocksource name is one of {clocksource},"
            f" but actual it is {clock_source_result.stdout}."
        ).is_subset_of(clocksource)

        # 2. Check CPU flag contains constant_tsc from /proc/cpuinfo.
        lscpu = node.tools[Lscpu]
        if "x86_64" == lscpu.get_architecture():
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
        if node.shell.exists(PurePosixPath(self.unbind_clocksource)):
            available_clocksources = cat.run(self.available_clocksource)
            available_clocksources_array = available_clocksources.stdout.split(" ")
            # We can not unbind clock source if there is only one existed.
            if len(available_clocksources_array) > 1:
                available_clocksources_array.remove(clock_source_result.stdout)
                cmd_result = node.execute(
                    f"echo {clock_source_result.stdout} > {self.unbind_clocksource}",
                    sudo=True,
                    shell=True,
                )
                cmd_result.assert_exit_code()

                clock_source_result_expected = _wait_file_changed(
                    node, self.current_clocksource, available_clocksources_array
                )
                assert_that(clock_source_result_expected).described_as(
                    f"After unbind {clock_source_result.stdout}, current clock source "
                    f"doesn't switch properly."
                ).is_true()

    @TestCaseMetadata(
        description="""
        This test is to check -
            1. Current clock event name is 'Hyper-V clockevent'.
            2. 'Hyper-V clockevent' and 'hrtimer_interrupt' show up times in
             /proc/timer_list should equal to cpu count.
            3. when cpu count is 1 and cpu type is Intel type, unbind current time
             clock event, check current time clock event switch to 'lapic'.
        """,
        priority=2,
    )
    def timesync_check_unbind_clockevent(self, node: Node) -> None:
        if node.shell.exists(PurePosixPath(self.current_clockevent)):
            # 1. Current clock event name is 'Hyper-V clockevent'.
            clock_event_name = "Hyper-V clockevent"
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
