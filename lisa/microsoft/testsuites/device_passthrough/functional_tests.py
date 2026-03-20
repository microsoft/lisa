# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import TYPE_CHECKING, Dict, cast

from lisa import Environment, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.base_tools import Cat
from lisa.operating_system import Windows
from lisa.sut_orchestrator import CLOUD_HYPERVISOR
from lisa.testsuite import TestResult, simple_requirement
from lisa.tools import Lspci
from lisa.util import LisaException, SkippedException

if TYPE_CHECKING:
    from lisa.sut_orchestrator.libvirt.ch_platform import CloudHypervisorPlatform
    from lisa.sut_orchestrator.util.schema import HostDevicePoolType


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
        pool_vendor_device_map: Dict[str, Dict[str, str]] = {}
        if not platform.platform_runbook.device_pools:
            raise SkippedException("device_pools is not configured in the runbook")

        from lisa.sut_orchestrator.util.schema import (
            PciAddressIdentifier,
            VendorDeviceIdIdentifier,
        )

        for pool in platform.platform_runbook.device_pools:
            pool_type = str(pool.type.value)
            if not pool.devices:
                raise LisaException(f"No devices defined for pool type: {pool_type}")
            if isinstance(pool.devices, list):
                first: VendorDeviceIdIdentifier = pool.devices[0]
                vendor_device_id = {
                    "vendor_id": first.vendor_id,
                    "device_id": first.device_id,
                }
            elif isinstance(pool.devices, PciAddressIdentifier):
                # Resolve vendor/device IDs from host sysfs for BDF pools.
                if not pool.devices.pci_bdf:
                    raise LisaException(f"Pool '{pool_type}' has no pci_bdf entries")
                vendor_device_id = self._vendor_device_from_host_bdf(
                    platform, pool.type, pool.devices.pci_bdf[0]
                )
            elif isinstance(pool.devices, dict):
                # dataclasses_json fallback: raw dict form from runbook.
                if "pci_bdf" in pool.devices:
                    bdf_list = pool.devices["pci_bdf"]
                    if not bdf_list:
                        raise LisaException(f"Pool '{pool_type}' pci_bdf list is empty")
                    vendor_device_id = self._vendor_device_from_host_bdf(
                        platform, pool.type, bdf_list[0]
                    )
                elif "vendor_id" in pool.devices and "device_id" in pool.devices:
                    vendor_device_id = {
                        "vendor_id": pool.devices["vendor_id"],
                        "device_id": pool.devices["device_id"],
                    }
                else:
                    raise LisaException(
                        f"Pool '{pool_type}' devices dict has neither 'pci_bdf' "
                        f"nor 'vendor_id'/'device_id' keys: {pool.devices}"
                    )
            else:
                raise LisaException(
                    f"Pool '{pool_type}' has unrecognised devices type: "
                    f"{type(pool.devices)}"
                )
            pool_vendor_device_map[pool_type] = vendor_device_id

        # Import at runtime to avoid libvirt dependency on other platforms.
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

    @staticmethod
    def _vendor_device_from_host_bdf(
        platform: "CloudHypervisorPlatform",
        pool_type: "HostDevicePoolType",
        bdf: str,
    ) -> Dict[str, str]:
        """Read vendor_id and device_id for a BDF from host sysfs."""
        resolved_bdf = platform.device_pool.resolve_requested_pci_address(
            pool_type, bdf.strip()
        )
        cat = platform.host_node.tools[Cat]
        vendor_raw = cat.read(
            f"/sys/bus/pci/devices/{resolved_bdf}/vendor", sudo=True
        ).strip()
        device_raw = cat.read(
            f"/sys/bus/pci/devices/{resolved_bdf}/device", sudo=True
        ).strip()
        # Normalize to 4-digit lowercase hex used by lspci identifiers.
        vendor_id = vendor_raw.lower().replace("0x", "").zfill(4)
        device_id = device_raw.lower().replace("0x", "").zfill(4)
        return {"vendor_id": vendor_id, "device_id": device_id}
