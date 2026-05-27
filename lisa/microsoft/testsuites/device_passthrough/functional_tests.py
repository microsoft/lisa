# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import TYPE_CHECKING, Any, Dict, Tuple

from lisa import Environment, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.base_tools import Cat
from lisa.operating_system import Windows
from lisa.sut_orchestrator import CLOUD_HYPERVISOR, OPENVMM
from lisa.testsuite import TestResult, simple_requirement
from lisa.tools import Lspci
from lisa.util import LisaException, SkippedException

if TYPE_CHECKING:
    from lisa.sut_orchestrator.libvirt.schema import DeviceAddressSchema


@TestSuiteMetadata(
    area="device_passthrough",
    category="functional",
    description="""
    This test suite is for testing device passthrough functional tests.
    """,
    requirement=simple_requirement(
        supported_platform_type=[CLOUD_HYPERVISOR, OPENVMM],
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
            the runtime passthrough device context. It will resolve vendor/device
            ids for assigned host devices and check how many matching devices are
            present on the guest.
        """,
        priority=4,
        requirement=simple_requirement(
            supported_platform_type=[CLOUD_HYPERVISOR, OPENVMM],
        ),
    )
    def verify_device_passthrough_on_guest(
        self,
        node: Node,
        environment: Environment,
        result: TestResult,
    ) -> None:
        lspci = node.tools[Lspci]
        node_context = self._get_passthrough_context(node)
        if not node_context.passthrough_devices:
            raise SkippedException("No passthrough devices are assigned to node")

        host_node = getattr(node_context, "host", None)
        if host_node is None and environment.platform is not None:
            host_node = getattr(environment.platform, "host_node", None)
        if host_node is None:
            raise SkippedException(
                "No host node is available for passthrough device validation"
            )

        expected_devices: Dict[Tuple[str, str, str], int] = {}
        for passthrough_context in node_context.passthrough_devices:
            pool_type = str(passthrough_context.pool_type.value)
            if not passthrough_context.device_list:
                raise LisaException(
                    f"No devices assigned to node for pool type: {pool_type}"
                )
            for host_device in passthrough_context.device_list:
                vendor_device_id = self._vendor_device_from_host_device(
                    host_node, host_device
                )
                key = (
                    pool_type,
                    vendor_device_id["vendor_id"],
                    vendor_device_id["device_id"],
                )
                expected_devices[key] = expected_devices.get(key, 0) + 1

        for (pool_type, ven_id, dev_id), expected_count in expected_devices.items():
            devices = lspci.get_devices_by_vendor_device_id(
                vendor_id=ven_id,
                device_id=dev_id,
                force_run=True,
            )
            if len(devices) < expected_count:
                raise LisaException(
                    f"Passthrough device validation failed for "
                    f"pool_type '{pool_type}': Found {len(devices)} "
                    f"device(s) but expected {expected_count}. "
                    f"Vendor/Device ID: {ven_id}:{dev_id}"
                )

    @staticmethod
    def _get_passthrough_context(node: Node) -> Any:
        if node.type_name() == OPENVMM:
            from lisa.sut_orchestrator.openvmm.context import get_node_context

            return get_node_context(node)

        from lisa.sut_orchestrator.libvirt.context import get_node_context

        return get_node_context(node)

    @staticmethod
    def _vendor_device_from_host_device(
        host_node: Node,
        device: "DeviceAddressSchema",
    ) -> Dict[str, str]:
        """Read vendor_id and device_id for an assigned host PCI device."""
        bdf = (f"{device.domain}:{device.bus}:{device.slot}.{device.function}").lower()
        cat = host_node.tools[Cat]
        vendor_raw = cat.read(f"/sys/bus/pci/devices/{bdf}/vendor", sudo=True).strip()
        device_raw = cat.read(f"/sys/bus/pci/devices/{bdf}/device", sudo=True).strip()
        # Normalize to 4-digit lowercase hex used by lspci identifiers.
        vendor_id = vendor_raw.lower().replace("0x", "").zfill(4)
        device_id = device_raw.lower().replace("0x", "").zfill(4)
        return {"vendor_id": vendor_id, "device_id": device_id}
