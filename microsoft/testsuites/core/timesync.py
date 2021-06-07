import time
from pathlib import PurePosixPath

from assertpy import assert_that

from lisa import Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.tools import Cat, Dmesg, Lscpu
from lisa.util.perf_timer import create_timer


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

    @TestCaseMetadata(
        description="""
        https://docs.microsoft.com/en-us/azure/virtual-machines/linux/time-sync#check-for-ptp-clock-source # noqa: E501
        This test is to check -
            1. PTP time source is available on Azure guests (newer versions of Linux).
            2. PTP device name is hyperv.
            3. When accelerated network is enabled, muiltple PTP devices will
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

        # 3. When accelerated network is enabled, muiltple PTP devices will
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
        priority=1,
    )
    def timesync_check_clocksource(self, node: Node) -> None:
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
            assert_that(cpu_info_result.stdout).described_as(
                "Expected 'constant_tsc' shown up in cpu flags."
            ).contains("constant_tsc")

        # 3. Check clocksource name shown up in dmesg.
        dmesg = node.tools[Dmesg]
        assert_that(dmesg.get_output()).described_as(
            f"Expected clocksource {clock_source_result.stdout} shown up in dmesg."
        ).contains(f"clocksource {clock_source_result.stdout}")

        # 4. Unbind current clock source if there are 2+ clock sources,
        # check current clock source can be switched to a different one.
        if node.shell.exists(PurePosixPath(f"{self.unbind_clocksource}")):
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
                assert_that(cmd_result.exit_code).described_as(
                    f"Fail to execute command "
                    f"[echo {clock_source_result.stdout} > {self.unbind_clocksource}]."
                ).is_equal_to(0)
                timout_timer = create_timer()
                timeout = 30
                while timout_timer.elapsed(False) < timeout:
                    current_clock_source_result = cat.run(
                        self.current_clocksource, force_run=True
                    )
                    if (
                        current_clock_source_result.stdout
                        in available_clocksources_array
                    ):
                        break
                    time.sleep(0.5)
                assert_that(available_clocksources_array).described_as(
                    f"After unbind {clock_source_result.stdout}, current clock source "
                    f"{current_clock_source_result.stdout} should be contained"
                    f"in {available_clocksources_array}."
                ).contains(current_clock_source_result.stdout)
