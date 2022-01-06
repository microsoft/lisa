import math

from assertpy import assert_that

from lisa import Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.sut_orchestrator.azure.tools import VmGeneration
from lisa.tools import Lscpu, Lsvmbus


class VmbusDeviceNames:
    def __init__(self, is_gen1: bool) -> None:
        self.names = [
            "Operating system shutdown",
            "Time Synchronization",
            "Heartbeat",
            "Data Exchange",
            "Synthetic mouse",
            "Synthetic keyboard",
            "Synthetic network adapter",
            "Synthetic SCSI Controller",
        ]
        if is_gen1:
            self.names.append("Synthetic IDE Controller")


@TestSuiteMetadata(
    area="core",
    category="functional",
    description="""
    This test suite is used to check vmbus devices and their associated vmbus channels.
    """,
)
class LsVmBus(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case will
        1. Check expected vmbus device names presented in the lsvmbus output.
            - Operating system shutdown
            - Time Synchronization
            - Heartbeat
            - Data Exchange
            - Synthetic mouse
            - Synthetic keyboard
            - Synthetic network adapter
            - Synthetic SCSI Controller
            - Synthetic IDE Controller (gen1 only)
        2. Check that each netvsc and storvsc SCSI device have correct number of vmbus
            channels created and associated.
            2.1 Check expected channel count of each netvsc is min (num of vcpu, 8).
                2.1.1 Caculate channel count of each netvsc device.
                https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git/tree/drivers/net/hyperv/rndis_filter.c#n1548 # noqa: E501
                2.2.2 Cap of channel count of each netvsc device.
                https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git/tree/drivers/net/hyperv/hyperv_net.h#n877 noqa: E501
                https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git/tree/drivers/net/hyperv/rndis_filter.c#n1551 noqa: E501

            2.2 Check expected channel count of each storvsc SCSI device is min (num of
                 vcpu/4, 64).
                2.2.1 Caculate channel count of each storvsc SCSI device.
                https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git/tree/drivers/scsi/storvsc_drv.c#n368 # noqa: E501
                https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git/tree/drivers/scsi/storvsc_drv.c#n1936 # noqa: E501
                2.2.2 Cap of channel count of each storvsc SCSI device,
                 it is decided by host storage VSP driver.
                https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git/tree/drivers/scsi/storvsc_drv.c#n952 # noqa: E501
        """,
        priority=1,
    )
    def lsvmbus_count_devices_channels(self, node: Node) -> None:
        # 1. Check expected vmbus device names presented in the lsvmbus output.
        vmbus_devices = VmbusDeviceNames(
            "1" == node.tools[VmGeneration].get_generation()
        )
        lsvmbus_tool = node.tools[Lsvmbus]
        vmbus_devices_list = lsvmbus_tool.get_device_channels()
        actual_vmbus_device_names = [x.name for x in vmbus_devices_list]
        assert_that(actual_vmbus_device_names).is_not_none()
        assert_that(vmbus_devices.names).is_subset_of(actual_vmbus_device_names)

        # 2. Check that each netvsc and storvsc SCSI device have correct number of
        #  vmbus channels created and associated.
        lscpu_tool = node.tools[Lscpu]
        core_count = lscpu_tool.get_core_count()
        # Each netvsc device should have "the_number_of_vCPUs" channel(s)
        #  with a cap value of 8.
        expected_network_channel_count = min(core_count, 8)
        # Each storvsc SCSI device should have "the_number_of_vCPUs / 4" channel(s)
        #  with a cap value of 64.
        expected_scsi_channel_count = math.ceil(min(core_count, 256) / 4)
        for vmbus_device in vmbus_devices_list:
            if vmbus_device.name == "Synthetic network adapter":
                assert_that(vmbus_device.channel_vp_map).is_length(
                    expected_network_channel_count
                )
            if vmbus_device.name == "Synthetic SCSI Controller":
                assert_that(vmbus_device.channel_vp_map).is_length(
                    expected_scsi_channel_count
                )
