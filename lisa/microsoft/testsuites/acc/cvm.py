# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re

from assertpy import assert_that

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.features.security_profile import CvmEnabled
from lisa.operating_system import CpuArchitecture
from lisa.testsuite import simple_requirement
from lisa.tools import Cat, Dmesg, Lscpu, Lsvmbus
from lisa.util import LisaException


@TestSuiteMetadata(
    area="ACC_CVM",
    category="functional",
    description="""
    This test suite ensures correct configuration and allowed devices for CVM
    """,
)
class CVMSuite(TestSuite):
    # [    0.000000] Hyper-V: Isolation Config: Group A 0x1, Group B 0xba2
    __isolation_config_pattern = re.compile(
        r"\[\s+\d+.\d+\]\s+Hyper-V: Isolation Config: Group A."
        r"(?P<config_a>(0x[a-z,A-Z,0-9]+)), Group B.(?P<config_b>(0x[a-z,A-Z,0-9]+))"
    )

    # HYPERV_CPUID_ISOLATION_CONFIG.EAX Structure
    #     UINT32 ParavisorPresent : 1;
    #     UINT32 Reserved0 : 31;
    HV_PARAVISOR_PRESENT_MASK = 0b1

    # HYPERV_CPUID_ISOLATION_CONFIG.EBX Structure
    #     UINT32 IsolationType : 4;
    #     UINT32 Reserved11 : 1;
    #     UINT32 SharedGpaBoundaryActive : 1;
    #     UINT32 SharedGpaBoundaryBits : 6;
    #     UINT32 Reserved12 : 20;
    HV_ISOLATION_TYPE_MASK = 0b1111
    HV_SHARED_GPA_BOUNDARY_ACTIVE_MASK = 0b100000
    HV_SHARED_GPA_BOUNDARY_BITS_MASK = 0b111111000000
    HV_ISOLATION_TYPE_SNP = 2
    HV_ISOLATION_TYPE_TDX = 3

    _current_clockevent = (
        "/sys/devices/system/clockevents/clockevent0/current_device"
    )

    @TestCaseMetadata(
        description="""
        This case verifies that lsvmbus only shows devices
        that are allowed in a CVM guest

        Steps:
        1. Call lsvmbus
        2. Iterate through list returned by lsvmbus to ensure all devices
           listed are included in valid_class_ids
        """,
        priority=1,
        requirement=simple_requirement(
            supported_features=[CvmEnabled()],
        ),
    )
    def verify_lsvmbus(self, log: Logger, node: Node) -> None:
        valid_class_ids = {
            "44c4f61d-4444-4400-9d52-802e27ede19f": "PCI Express pass-through",
            "ba6163d9-04a1-4d29-b605-72e2ffb1dc7f": "Synthetic SCSI Controller",
            "f8615163-df3e-46c5-913f-f2d2f965ed0e": "Synthetic network adapter",
            "9527e630-d0ae-497b-adce-e80ab0175caf": "[Time Synchronization]",
            "57164f39-9115-4e78-ab55-382f3bd5422d": "[Heartbeat]",
            "0e0b6031-5213-4934-818b-38d90ced39db": "[Operating system shutdown]",
        }
        lsvmbus_tool = node.tools[Lsvmbus]
        device_list = lsvmbus_tool.get_device_channels()
        class_id_list = [device.class_id for device in device_list]
        assert_that(class_id_list).is_subset_of(list(valid_class_ids.keys()))

    @TestCaseMetadata(
        description="""
        This case verifies the isolation config on guest

        Steps:
        1. Call dmesg to get output
        2. Find isolation config in output
        3. Check to ensure config a is 0x1
        4. Check to ensure config b is 0xba2
        """,
        priority=1,
        requirement=simple_requirement(
            supported_features=[CvmEnabled()],
        ),
    )
    def verify_isolation_config(self, log: Logger, node: Node) -> None:
        valid_cvm_type = {
            "HV_ISOLATION_TYPE_SNP": 2,
            "HV_ISOLATION_TYPE_TDX": 3,
        }

        dmesg_tool = node.tools[Dmesg]
        dmesg_output = dmesg_tool.get_output()
        isolation_config = re.search(self.__isolation_config_pattern, dmesg_output)
        if isolation_config is not None:
            isolation_config_a = int(isolation_config.group("config_a"), 16)
            isolation_config_b = int(isolation_config.group("config_b"), 16)
            log.debug(
                f"Isolation Config is Group A:{isolation_config_a}, "
                f"Group B:{isolation_config_b}"
            )
        else:
            raise LisaException("No find matched Isolation Config in dmesg")

        cvm_type = isolation_config_b & self.HV_ISOLATION_TYPE_MASK
        assert_that(list(valid_cvm_type.values())).contains(cvm_type)
        if cvm_type == valid_cvm_type["HV_ISOLATION_TYPE_SNP"]:
            if isolation_config_a & self.HV_PARAVISOR_PRESENT_MASK:
                # SNP /w paravisor
                # shared_gpa_boundary_active should be set
                assert_that(
                    isolation_config_b & self.HV_SHARED_GPA_BOUNDARY_ACTIVE_MASK
                ).is_equal_to(0b100000)
                # shared_gpa_boundary_bits should be 101110
                assert_that(
                    isolation_config_b & self.HV_SHARED_GPA_BOUNDARY_BITS_MASK
                ).is_equal_to(0b101110000000)
            else:
                # Fully Enlightened SNP
                # shared_gpa_boundary_active should be clear
                assert_that(
                    isolation_config_b & self.HV_SHARED_GPA_BOUNDARY_ACTIVE_MASK
                ).is_equal_to(0)
                # shared_gpa_boundary_bits should be clear
                assert_that(
                    isolation_config_b & self.HV_SHARED_GPA_BOUNDARY_BITS_MASK
                ).is_equal_to(0)
        elif cvm_type == valid_cvm_type["HV_ISOLATION_TYPE_TDX"]:
            if isolation_config_a & self.HV_PARAVISOR_PRESENT_MASK:
                # These fields are still not yet settled
                pass
            else:
                # Fully Enlightened TDX
                # shared_gpa_boundary_active should be clear
                assert_that(
                    isolation_config_b & self.HV_SHARED_GPA_BOUNDARY_ACTIVE_MASK
                ).is_equal_to(0)
                # shared_gpa_boundary_bits should be clear
                assert_that(
                    isolation_config_b & self.HV_SHARED_GPA_BOUNDARY_BITS_MASK
                ).is_equal_to(0)

    def _get_isolation_config(
        self, node: Node, log: Logger
    ) -> tuple:
        """
        Parse Hyper-V isolation config from dmesg and return
        (isolation_type, has_paravisor) tuple.
        """
        dmesg_output = node.tools[Dmesg].get_output()
        isolation_config = re.search(self.__isolation_config_pattern, dmesg_output)
        if isolation_config is None:
            raise LisaException("No matched Isolation Config found in dmesg")
        config_a = int(isolation_config.group("config_a"), 16)
        config_b = int(isolation_config.group("config_b"), 16)
        isolation_type = config_b & self.HV_ISOLATION_TYPE_MASK
        has_paravisor = bool(config_a & self.HV_PARAVISOR_PRESENT_MASK)
        log.debug(
            f"Isolation type: {isolation_type}, "
            f"has paravisor: {has_paravisor}"
        )
        return isolation_type, has_paravisor

    @TestCaseMetadata(
        description="""
        This case verifies the clockevent device on a CVM guest.

        On a TDX VM without paravisor, the kernel lowers the Hyper-V timer
        rating (to 90) so the local APIC timer (lapic) becomes the default
        clockevent instead of 'Hyper-V clockevent'. This is because the
        Hyper-V TSC page is not enabled in such a VM and the timer depends
        on the slow VM Reference Counter MSR.

        On an SNP CVM or a TDX VM with paravisor, the Hyper-V clockevent
        remains the default (rating 1000).

        Reference: kernel patch "clocksource: hyper-v: Use lapic timer
        in a TDX VM without paravisor"

        Steps:
        1. Parse isolation config from dmesg to determine CVM type
           (SNP vs TDX) and paravisor presence.
        2. Read the current clockevent from sysfs.
        3. Assert that the clockevent matches the expected value:
           - TDX without paravisor (x86): 'lapic'
           - SNP or TDX with paravisor (x86): 'Hyper-V clockevent'
           - ARM64: 'arch_sys_timer'
        4. Verify the clockevent appears in /proc/timer_list the same
           number of times as the CPU thread count.
        """,
        priority=2,
        requirement=simple_requirement(
            supported_features=[CvmEnabled()],
        ),
    )
    def verify_cvm_clockevent(self, log: Logger, node: Node) -> None:
        isolation_type, has_paravisor = self._get_isolation_config(node, log)

        lscpu = node.tools[Lscpu]
        arch = lscpu.get_architecture()
        cat = node.tools[Cat]

        # Determine expected clockevent based on CVM type and architecture
        if arch == CpuArchitecture.X64:
            if (
                isolation_type == self.HV_ISOLATION_TYPE_TDX
                and not has_paravisor
            ):
                # TDX without paravisor: kernel lowers Hyper-V timer rating,
                # lapic becomes default
                expected_clockevent = "lapic"
            else:
                # SNP or TDX with paravisor: Hyper-V clockevent remains default
                expected_clockevent = "Hyper-V clockevent"
        elif arch == CpuArchitecture.ARM64:
            expected_clockevent = "arch_sys_timer"
        else:
            raise LisaException(f"Unsupported CPU architecture: {arch}")

        log.debug(
            f"CVM type: {'TDX' if isolation_type == self.HV_ISOLATION_TYPE_TDX else 'SNP'}, "
            f"paravisor: {has_paravisor}, "
            f"expected clockevent: {expected_clockevent}"
        )

        # Read and verify the actual clockevent
        clock_event_result = cat.run(self._current_clockevent)
        assert_that(clock_event_result.stdout).described_as(
            f"Expected clockevent is '{expected_clockevent}', "
            f"but actual is '{clock_event_result.stdout}'."
        ).is_equal_to(expected_clockevent)

        # Verify clockevent appears in /proc/timer_list once per CPU thread
        thread_count = lscpu.get_thread_count()
        timer_list_result = cat.run("/proc/timer_list", sudo=True)

        clock_event_times = timer_list_result.stdout.count(expected_clockevent)
        assert_that(clock_event_times).described_as(
            f"Expected '{expected_clockevent}' to appear {thread_count} times "
            f"in /proc/timer_list, but it appears {clock_event_times} times."
        ).is_equal_to(thread_count)

        event_handler_name = "hrtimer_interrupt"
        event_handler_times = timer_list_result.stdout.count(event_handler_name)
        assert_that(event_handler_times).described_as(
            f"Expected '{event_handler_name}' to appear {thread_count} times "
            f"in /proc/timer_list, but it appears {event_handler_times} times."
        ).is_equal_to(thread_count)
