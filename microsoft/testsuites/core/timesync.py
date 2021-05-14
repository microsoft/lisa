from pathlib import PurePosixPath

from assertpy import assert_that

from lisa import Environment, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.operating_system import Windows
from lisa.testsuite import simple_requirement
from lisa.tools import Cat, Dmesg


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
        requirement=simple_requirement(unsupported_os=[Windows]),
    )
    def timesync_validate_ptp(self, environment: Environment, node: Node) -> None:
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
            "/dev/ptp_hyperv should exist, make sure there is a udev rule to create "
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
