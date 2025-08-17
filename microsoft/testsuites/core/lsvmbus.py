import math
import time
from typing import Dict, List

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.feature import Feature
from lisa.features.security_profile import (
    SecurityProfile,
    SecurityProfileSettings,
    SecurityProfileType,
)
from lisa.operating_system import BSD, Windows
from lisa.sut_orchestrator import AZURE, HYPERV
from lisa.sut_orchestrator.azure.tools import VmGeneration
from lisa.tools import Cat, Ls, Lscpu, Lsvmbus
from lisa.tools.lsvmbus import VmBusDevice
from lisa.util import LisaException
from lisa.util.perf_timer import create_timer


class VmbusDeviceNames:
    def __init__(self, is_gen1: bool, node: Node) -> None:
        settings = Feature.get_feature_settings(
            node.features[SecurityProfile].get_settings()
        )
        lcvmbus_device_names = [
            "Operating system shutdown",
            "Time Synchronization",
            "Heartbeat",
            "Synthetic network adapter",
            "Synthetic SCSI Controller",
        ]
        if isinstance(node.os, BSD):
            self.names = [
                "Hyper-V Shutdown",
                "Hyper-V Timesync",
                "Hyper-V Heartbeat",
                "Hyper-V KBD",
                "Hyper-V Network Interface",
                "Hyper-V SCSI",
            ]
        elif isinstance(settings, SecurityProfileSettings) and (
            SecurityProfileType.CVM == settings.security_profile
            or SecurityProfileType.Stateless == settings.security_profile
        ):
            self.names = lcvmbus_device_names
        else:
            self.names = lcvmbus_device_names + [
                "Data Exchange",
                "Synthetic mouse",
                "Synthetic keyboard",
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
        This test case will check expected vmbus device names presented in the lsvmbus
        output for FreeBSD.
            - Hyper-V Shutdown
            - Hyper-V Timesync
            - Hyper-V Heartbeat
            - Hyper-V KBD
            - Hyper-V Network Interface
            - Hyper-V SCSI
        """,
        priority=1,
        requirement=simple_requirement(
            supported_platform_type=[AZURE, HYPERV], supported_os=[BSD]
        ),
    )
    def verify_vmbus_devices_channels_bsd(self, node: Node) -> None:
        self._verify_and_get_lsvmbus_devices(node)

    @TestCaseMetadata(
        description="""
        This test case will
        1. Check expected vmbus device names presented in the lsvmbus output.
            - Operating system shutdown
            - Time Synchronization
            - Heartbeat
            - Synthetic network adapter
            - Synthetic SCSI Controller
            - Synthetic IDE Controller (gen1 only)
            It expects additional three vmbus device names for non-cvm:
            - Data Exchange
            - Synthetic mouse
            - Synthetic keyboard
        2. Check that each netvsc and storvsc SCSI device have correct number of vmbus
            channels created and associated.
            2.1 Check expected channel count of each netvsc device.
                - Legacy logic (before Linux commit 646f071d315b75e87583de290d333478d42ccde1): # noqa: E501
                  2.1.1 Calculate channel count of each netvsc device.
                        https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git/tree/drivers/net/hyperv/rndis_filter.c#n1548 # noqa: E501
                  2.1.2 Cap of channel count of each netvsc device.
                        https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git/tree/drivers/net/hyperv/hyperv_net.h#n877 # noqa: E501
                        https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git/tree/drivers/net/hyperv/rndis_filter.c#n1551 # noqa: E501
                  => Expected channel count = min(num of vCPUs, 8).
                - New logic (after Linux commit 646f071d315b75e87583de290d333478d42ccde1): # noqa: E501
                  2.1.3 If vCPU count <= 16, expected channel count = num of vCPUs.
                  2.1.4 If vCPU count > 16, expected channel count =
                        min(64, max(16, physical core count / 2)).
                  Reference:
                        https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=646f071d315b75e87583de290d333478d42ccde1
                - Test logic:
                  The code will first validate against the legacy rule.
                  If actual channel count does not match, it will then apply the new rule.
            2.2 Check expected channel count of each storvsc SCSI device is min (num of
                 vcpu/4, 64).
                2.2.1 Calculate channel count of each storvsc SCSI device.
                        https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git/tree/drivers/scsi/storvsc_drv.c#n368 # noqa: E501
                        https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git/tree/drivers/scsi/storvsc_drv.c#n1936 # noqa: E501
                2.2.2 Cap of channel count of each storvsc SCSI device,
                      it is decided by host storage VSP driver.
                        https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git/tree/drivers/scsi/storvsc_drv.c#n952 # noqa: E501
        """,
        priority=1,
        requirement=simple_requirement(
            supported_platform_type=[AZURE, HYPERV], unsupported_os=[BSD, Windows]
        ),
    )
    def verify_vmbus_devices_channels(self, node: Node, log: Logger) -> None:
        # 1. Check expected vmbus device names presented in the lsvmbus output.
        vmbus_devices_list = self._verify_and_get_lsvmbus_devices(node)

        # 2. Check that each netvsc and storvsc SCSI device have correct number of
        #  vmbus channels created and associated.
        lscpu_tool = node.tools[Lscpu]
        thread_count = lscpu_tool.get_thread_count()
        # Each netvsc device should have "the_number_of_vCPUs" channel(s)
        #  with a cap value of 8.
        expected_network_channel_count = min(thread_count, 8)
        # Each storvsc SCSI device should have "the_number_of_vCPUs / 4" channel(s)
        #  with a cap value of 64.
        if node.nics.is_mana_device_present():
            expected_scsi_channel_count = min(thread_count, 64)
        else:
            expected_scsi_channel_count = math.ceil(min(thread_count, 256) / 4)
        for vmbus_device in vmbus_devices_list:
            if vmbus_device.name == "Synthetic network adapter":
                actual_channels = len(vmbus_device.channel_vp_map)
                log.info(
                    f"Device '{vmbus_device.name}' actual channels: {actual_channels}"
                )
                # Note: mismatch may occur due to kernel change (commit 646f071d315b).
                # In that case, validate again using the new logic.
                if actual_channels != expected_network_channel_count:
                    if thread_count <= 16:
                        expected_network_channel_count = thread_count
                        log.info(
                            "Applying new logic: expected channels = core_count "
                            f"({thread_count})"
                        )
                    else:
                        core_count = lscpu_tool.get_core_count()
                        expected_network_channel_count = min(
                            64, max(16, core_count // 2)
                        )
                        log.info(
                            "Applying new logic: expected channels = min(64, "
                            "max(16, physical_core_count // 2)) "
                            f"= {expected_network_channel_count}"
                        )
                assert_that(vmbus_device.channel_vp_map).is_length(
                    expected_network_channel_count
                )
            if vmbus_device.name == "Synthetic SCSI Controller":
                assert_that(vmbus_device.channel_vp_map).is_length(
                    expected_scsi_channel_count
                )

    @TestCaseMetadata(
        description="""
        This test case will
            1. Looks for the VMBus heartbeat device properties.
            2. Checks the properties can be read and that the folder structure exists.
            3. Checks that the in_* files are equal to the out_* files
             when read together.
            4. Checks the interrupts and events values are increasing during
             reading them.
        """,
        priority=4,
        requirement=simple_requirement(
            supported_platform_type=[AZURE, HYPERV], unsupported_os=[BSD, Windows]
        ),
    )
    def verify_vmbus_heartbeat_properties(self, node: Node) -> None:
        lsvmbus_tool = node.tools[Lsvmbus]
        ls = node.tools[Ls]
        vmbus_devices_list = lsvmbus_tool.get_device_channels()
        vmbus_heartbeat_device_list = [
            x for x in vmbus_devices_list if x.name == "Heartbeat"
        ]
        assert vmbus_heartbeat_device_list, "no vmbus heartbeat device"
        vmbus_heartbeat_device = vmbus_heartbeat_device_list[0]
        device_path = f"/sys/bus/vmbus/devices/{vmbus_heartbeat_device.device_id}"
        if not ls.path_exists(device_path, sudo=True):
            raise LisaException(f"{device_path} doesn't exist")
        vmbus_driver_files: List[str] = [
            "channel_vp_mapping",
            "class_id",
            "device",
            "device_id",
            "id",
            "in_intr_mask",
            "in_read_bytes_avail",
            "in_read_index",
            "in_write_bytes_avail",
            "in_write_index",
            "modalias",
            "out_intr_mask",
            "out_read_bytes_avail",
            "out_read_index",
            "out_write_bytes_avail",
            "out_write_index",
            "state",
            "uevent",
            "vendor",
        ]
        vmbus_channel_files: List[str] = [
            "cpu",
            "events",
            "in_mask",
            "interrupts",
            "out_mask",
            "read_avail",
            "write_avail",
        ]
        in_out_files: List[str] = [
            "intr_mask",
            "read_bytes_avail",
            "write_bytes_avail",
        ]
        # driver_override file not existing - contain recent commits
        if not ls.path_exists(f"{device_path}/driver_override"):
            vmbus_driver_files += [
                "monitor_id",
                "server_monitor_conn_id",
                "server_monitor_latency",
                "server_monitor_pending",
                "client_monitor_conn_id",
                "client_monitor_latency",
                "client_monitor_pending",
            ]
            vmbus_channel_files += ["latency", "pending"]
        for file in vmbus_driver_files:
            if not ls.path_exists(f"{device_path}/{file}", sudo=True):
                raise LisaException(f"{device_path}/{file} doesn't exist")
        # /sys/bus/vmbus/devices/fd149e91-82e0-4a7d-afa6-2a4166cbd7c0/channels/8
        channels = ls.list_dir(f"{device_path}/channels/", sudo=True)
        for file in vmbus_channel_files:
            for channel in channels:
                if not ls.path_exists(f"{channel}/{file}", sudo=True):
                    raise LisaException(f"{channel}/{file} doesn't exist")
        for in_out_file in in_out_files:
            in_file_value = node.tools[Cat].read(
                f"{device_path}/in_{in_out_file}", force_run=True, sudo=True
            )
            out_file_value = node.tools[Cat].read(
                f"{device_path}/out_{in_out_file}", force_run=True, sudo=True
            )
            assert_that(in_file_value).described_as(
                f"value of {device_path}/in_{in_out_file} is not equal to"
                f" {device_path}/out_{in_out_file}"
            ).is_equal_to(out_file_value)
        origin_interrupts: Dict[str, str] = {}
        origin_events: Dict[str, str] = {}
        for channel in channels:
            origin_interrupts[f"{channel}/interrupts"] = node.tools[Cat].read(
                f"{channel}/interrupts", force_run=True, sudo=True
            )
            origin_events[f"{channel}/events"] = node.tools[Cat].read(
                f"{channel}/events", force_run=True, sudo=True
            )
        for channel in channels:
            timeout = 60
            timer = create_timer()
            while timeout > timer.elapsed(False):
                current_interrupts = node.tools[Cat].read(
                    f"{channel}/interrupts", force_run=True, sudo=True
                )
                current_events = node.tools[Cat].read(
                    f"{channel}/events", force_run=True, sudo=True
                )
                if int(origin_interrupts[f"{channel}/interrupts"]) < int(
                    current_interrupts
                ) and int(origin_events[f"{channel}/events"]) < int(current_events):
                    break
                time.sleep(1)

            if timeout < timer.elapsed():
                raise LisaException(
                    f"{channel}/interrupts or {channel}/events did not increase after"
                    f" timeout"
                )

    def _verify_and_get_lsvmbus_devices(self, node: Node) -> List[VmBusDevice]:
        # Check expected vmbus device names presented in the lsvmbus output.
        vmbus_devices = VmbusDeviceNames(
            "1" == node.tools[VmGeneration].get_generation(), node
        )
        vmbus_devices_list = node.tools[Lsvmbus].get_device_channels()
        actual_vmbus_device_names = [x.name for x in vmbus_devices_list]
        assert_that(actual_vmbus_device_names).is_not_none()
        assert_that(vmbus_devices.names).is_subset_of(actual_vmbus_device_names)

        return vmbus_devices_list
