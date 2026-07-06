# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple, Union, cast

from lisa import Environment, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.base_tools import Cat
from lisa.operating_system import Windows
from lisa.platform_ import Platform
from lisa.sut_orchestrator import CLOUD_HYPERVISOR, HYPERV, OPENVMM
from lisa.testsuite import TestResult, simple_requirement
from lisa.tools import Lspci
from lisa.util import LisaException, SkippedException

if TYPE_CHECKING:
    from lisa.sut_orchestrator.hyperv.schema import (
        DeviceAddressSchema as HypervDeviceAddressSchema,
    )
    from lisa.sut_orchestrator.libvirt.ch_platform import CloudHypervisorPlatform
    from lisa.sut_orchestrator.libvirt.schema import (
        DeviceAddressSchema as LibvirtDeviceAddressSchema,
    )
    from lisa.sut_orchestrator.openvmm.context import (
        DeviceAddressSchema as OpenVmmDeviceAddressSchema,
    )

    HostDeviceAddressSchema = Union[
        HypervDeviceAddressSchema,
        LibvirtDeviceAddressSchema,
        OpenVmmDeviceAddressSchema,
    ]

SUPPORTED_PASSTHROUGH_PLATFORMS = [CLOUD_HYPERVISOR, HYPERV, OPENVMM]


@TestSuiteMetadata(
    area="device_passthrough",
    category="functional",
    description="""
    This test suite is for testing device passthrough functional tests.
    """,
    requirement=simple_requirement(
        supported_platform_type=SUPPORTED_PASSTHROUGH_PLATFORMS,
        unsupported_os=[Windows],
    ),
)
class DevicePassthroughFunctionalTests(TestSuite):
    @TestCaseMetadata(
        description="""
            Check if all passthrough devices requested in the runbook are visible
            to the guest.

            This testcase supports the CLOUD_HYPERVISOR, HYPERV, and OPENVMM
            platforms of LISA. Please refer below runbook snippet.

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
            The 'device_passthrough' section tells the platform how many devices
            to assign. Based on the pool_type value, the platform gets devices
            from the pool and assigns them to the node.
            The count can be any positive value supported by the device pool.

            Testcase verifies every device assigned by the platform. It reads the
            runtime passthrough device context, resolves the vendor/device ids for
            all assigned host devices, and checks that the guest contains at least
            the same number of matching devices.
        """,
        priority=4,
        requirement=simple_requirement(
            supported_platform_type=SUPPORTED_PASSTHROUGH_PLATFORMS,
        ),
    )
    def verify_device_passthrough_on_guest(
        self,
        node: Node,
        environment: Environment,
        result: TestResult,
    ) -> None:
        lspci = node.tools[Lspci]
        platform = environment.platform
        if platform is None:
            raise SkippedException(
                "Device passthrough validation requires a LISA platform context. "
                "Verify the runbook uses cloud-hypervisor, hyperv, or openvmm."
            )
        platform_name = self._get_platform_name(platform, node)
        node_context = self._get_passthrough_context(node, platform_name)

        if not node_context.passthrough_devices:
            raise SkippedException("No passthrough devices are assigned to node")

        host_node = getattr(node_context, "host", None)
        if host_node is None and environment.platform is not None:
            host_node = getattr(environment.platform, "host_node", None)
        if host_node is None and platform_name != HYPERV:
            raise SkippedException(
                "No host node is available for passthrough device validation"
            )

        expected_devices: Dict[Tuple[str, str], Dict[str, int]] = {}
        pool_counts: Dict[str, Dict[str, int]] = {}
        for passthrough_context in node_context.passthrough_devices:
            pool_type = str(passthrough_context.pool_type.value)
            requested_count = passthrough_context.requested_count
            assigned_count = len(passthrough_context.device_list)
            if requested_count <= 0:
                raise LisaException(
                    f"Invalid requested device count '{requested_count}' for "
                    f"pool type '{pool_type}'. Set device_passthrough.count to "
                    "a positive value in the runbook."
                )
            if assigned_count < requested_count:
                raise LisaException(
                    f"Passthrough device allocation for pool type '{pool_type}' "
                    f"requested {requested_count} device(s), but assigned "
                    f"{assigned_count}. Inspect the platform device-allocation logs."
                )
            counts = pool_counts.setdefault(
                pool_type,
                {"requested": 0, "assigned": 0},
            )
            counts["requested"] += requested_count
            counts["assigned"] += assigned_count
            for host_device in passthrough_context.device_list:
                vendor_device_id = self._vendor_device_from_host_device(
                    platform_name, platform, host_node, host_device
                )
                key = (
                    vendor_device_id["vendor_id"],
                    vendor_device_id["device_id"],
                )
                expected_pool_counts = expected_devices.setdefault(key, {})
                expected_pool_counts[pool_type] = (
                    expected_pool_counts.get(pool_type, 0) + 1
                )

        for (ven_id, dev_id), expected_pool_counts in expected_devices.items():
            expected_count = sum(expected_pool_counts.values())
            devices = lspci.get_devices_by_vendor_device_id(
                vendor_id=ven_id,
                device_id=dev_id,
                force_run=True,
            )
            matching_guest_count = len(devices)
            if matching_guest_count < expected_count:
                pool_details = ", ".join(
                    f"{pool_type}={count}"
                    for pool_type, count in sorted(expected_pool_counts.items())
                )
                raise LisaException(
                    f"Passthrough device validation failed: Found "
                    f"{matching_guest_count} device(s) but expected "
                    f"{expected_count} for Vendor/Device ID {ven_id}:{dev_id}. "
                    f"Assigned pool counts: {pool_details}."
                )

        result.message = "Passthrough devices tested: " + "; ".join(
            f"{pool_type}: requested={counts['requested']}, "
            f"assigned={counts['assigned']}, "
            f"verified={counts['assigned']}"
            for pool_type, counts in sorted(pool_counts.items())
        )

    @staticmethod
    def _get_platform_name(platform: Platform, node: Node) -> str:
        node_type = node.type_name()
        if node_type == OPENVMM:
            return node_type

        return platform.type_name()

    @staticmethod
    def _get_passthrough_context(node: Node, platform_name: str) -> Any:
        if platform_name == OPENVMM:
            from lisa.sut_orchestrator.openvmm.context import (
                get_node_context as get_openvmm_node_context,
            )

            return get_openvmm_node_context(node)

        if platform_name == CLOUD_HYPERVISOR:
            from lisa.sut_orchestrator.libvirt.context import (
                get_node_context as get_libvirt_node_context,
            )

            return get_libvirt_node_context(node)

        if platform_name == HYPERV:
            from lisa.sut_orchestrator.hyperv.context import (
                get_node_context as get_hyperv_node_context,
            )

            return get_hyperv_node_context(node)

        raise SkippedException(
            f"Device passthrough validation is not supported on '{platform_name}'"
        )

    @staticmethod
    def _vendor_device_from_host_device(
        platform_name: str,
        platform: Platform,
        host_node: Optional[Node],
        device: "HostDeviceAddressSchema",
    ) -> Dict[str, str]:
        if platform_name == HYPERV:
            hyperv_device = cast("HypervDeviceAddressSchema", device)
            instance_id = hyperv_device.instance_id
            match = re.search(
                r"VEN_(?P<vendor_id>[0-9A-Fa-f]{4})&"
                r"DEV_(?P<device_id>[0-9A-Fa-f]{4})",
                instance_id,
            )
            if not match:
                raise LisaException(
                    f"Cannot resolve vendor/device id from Hyper-V host device "
                    f"instance id: {instance_id}"
                )
            return {
                "vendor_id": match.group("vendor_id").lower(),
                "device_id": match.group("device_id").lower(),
            }

        if platform_name not in [CLOUD_HYPERVISOR, OPENVMM]:
            raise LisaException(
                f"Device passthrough host device lookup is not supported on "
                f"'{platform_name}'. Use a cloud-hypervisor, hyperv, or openvmm "
                "platform."
            )

        if host_node is None:
            raise LisaException(
                "No host node is available for passthrough device vendor lookup"
            )
        if platform_name == CLOUD_HYPERVISOR:
            cloud_hypervisor = cast("CloudHypervisorPlatform", platform)
            host_node = cloud_hypervisor.host_node
        pci_device = cast(Any, device)
        bdf = (
            f"{pci_device.domain}:{pci_device.bus}:"
            f"{pci_device.slot}.{pci_device.function}"
        ).lower()
        cat = host_node.tools[Cat]
        vendor_raw = cat.read(f"/sys/bus/pci/devices/{bdf}/vendor", sudo=True).strip()
        device_raw = cat.read(f"/sys/bus/pci/devices/{bdf}/device", sudo=True).strip()
        # Normalize to 4-digit lowercase hex used by lspci identifiers.
        vendor_id = vendor_raw.lower().replace("0x", "").zfill(4)
        device_id = device_raw.lower().replace("0x", "").zfill(4)
        return {"vendor_id": vendor_id, "device_id": device_id}
