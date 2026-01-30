# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import TYPE_CHECKING, cast

from lisa import Environment, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.operating_system import Windows
from lisa.sut_orchestrator import CLOUD_HYPERVISOR
from lisa.testsuite import TestResult, simple_requirement
from lisa.tools import Lspci
from lisa.util import LisaException, SkippedException

if TYPE_CHECKING:
    from lisa.sut_orchestrator.libvirt.ch_platform import CloudHypervisorPlatform


@TestSuiteMetadata(
    area="device_passthrough",
    category="functional",
    description="""
    This test suite is for testing device passthrough functional tests.
    """,
    requirement=simple_requirement(
        supported_platform_type=[CLOUD_HYPERVISOR],
        unsupported_os=[Windows],
    ),
)
class DevicePassthroughFunctionalTests(TestSuite):
    @TestCaseMetadata(
        description="""
            Check if passthrough device is visible to guest.
            This testcase support only on CLOUD_HYPERVISOR
            platform of LISA. Please refer below runbook snippet.

            platform:
              - type: cloud-hypervisor
                cloud-hypervisor:
                  device_pools:
                    - type: "pci_net"
                      devices:
                        - vendor_id: xxx
                          device_id: xxx
                requirement:
                  cloud-hypervisor:
                    device_passthrough:
                      - pool_type: "pci_net"
                        managed: "yes"
                        count: 1

            We will check if sufficient devices are visible to guest or not.
            Platform will create device pool based on given device/vendor id.
            'device_passthrough' section will tell platform to create node
            with appropriate num of devices being passthrough. Based on pool_type
            value, platform will try to get devices from pool and assign it to node.

            Testcase will verify if needed devices are present on node by reading
            extended runbook. It will get the vendor/device id based on 'pool_type'
            and check how many devices are present on node for that vendor/device id.
        """,
        priority=4,
        requirement=simple_requirement(
            supported_platform_type=[CLOUD_HYPERVISOR],
        ),
    )
    def verify_device_passthrough_on_guest(
        self,
        node: Node,
        environment: Environment,
        result: TestResult,
    ) -> None:
        lspci = node.tools[Lspci]
        platform = cast("CloudHypervisorPlatform", environment.platform)
        pool_vendor_device_map = {}
        assert platform.platform_runbook.device_pools, "Device pool can't be empty"
        for pool in platform.platform_runbook.device_pools:
            pool_type = str(pool.type.value)
            if not pool.devices:
                raise LisaException(f"No devices defined for pool type: {pool_type}")
            vendor_device_id = {
                "vendor_id": pool.devices[0].vendor_id,
                "device_id": pool.devices[0].device_id,
            }
            pool_vendor_device_map[pool_type] = vendor_device_id

        # Get the node's runbook to check its passthrough requirements
        # Import at runtime to avoid libvirt dependency on non-libvirt platforms
        from lisa.sut_orchestrator.libvirt.schema import BaseLibvirtNodeSchema

        node_runbook: "BaseLibvirtNodeSchema" = node.capability.get_extended_runbook(
            BaseLibvirtNodeSchema, CLOUD_HYPERVISOR
        )
        if not node_runbook.device_passthrough:
            raise SkippedException("No device-passthrough is set for node")

        for req in node_runbook.device_passthrough:
            pool_type = str(req.pool_type.value)
            if pool_type not in pool_vendor_device_map:
                raise LisaException(
                    f"Pool type '{pool_type}' not found in platform device pools"
                )
            ven_dev_id_of_pool = pool_vendor_device_map[pool_type]
            ven_id = ven_dev_id_of_pool["vendor_id"]
            dev_id = ven_dev_id_of_pool["device_id"]
            devices = lspci.get_devices_by_vendor_device_id(
                vendor_id=ven_id,
                device_id=dev_id,
                force_run=True,
            )
            if len(devices) < req.count:
                raise LisaException(
                    f"Passthrough device validation failed for "
                    f"pool_type '{pool_type}': Found {len(devices)} "
                    f"device(s) but expected {req.count}. "
                    f"Vendor/Device ID: {ven_id}:{dev_id}"
                )
