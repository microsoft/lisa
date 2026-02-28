# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import TYPE_CHECKING, Dict, List, cast

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
                        - vendor_id: xxx   # option A: explicit vendor/device ID
                          device_id: xxx
                    # OR:
                    - type: "pci_net"
                      devices:
                        pci_bdf:           # option B: explicit BDF address
                          - "0000:19:00.0"
                    # OR:
                    - type: "pci_net"
                      devices:
                        enabled: true      # option C: auto-detect a suitable NIC
                        count: 1
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
        from lisa.sut_orchestrator.libvirt.context import NodeContext
        from lisa.sut_orchestrator.libvirt.schema import (
            BaseLibvirtNodeSchema,
            DeviceAddressSchema,
        )

        lspci = node.tools[Lspci]
        platform = cast("CloudHypervisorPlatform", environment.platform)

        node_runbook: "BaseLibvirtNodeSchema" = node.capability.get_extended_runbook(
            BaseLibvirtNodeSchema, CLOUD_HYPERVISOR
        )
        if not node_runbook.device_passthrough:
            raise SkippedException("No device-passthrough is set for node")

        node_context: NodeContext = node.get_context(NodeContext)
        if not node_context.passthrough_devices:
            raise SkippedException("No passthrough devices were assigned to this node")

        # Build a map: pool_type -> list of (vendor_id, device_id) resolved from
        # the BDFs that were actually assigned to this node by the platform.
        # This approach works uniformly regardless of how the pool was configured
        # (vendor/device ID, explicit BDF, or auto-detect) because the platform
        # always records the assigned DeviceAddressSchema in node_context.
        host_lspci = platform.device_pool.host_node.tools[Lspci]  # type: ignore[attr-defined]
        host_devices = host_lspci.get_devices(force_run=True)
        # Build a slot -> PciDevice lookup for fast access
        host_dev_map = {d.slot: d for d in host_devices}

        def _get_vendor_device_id(
            dev_addr: "DeviceAddressSchema",
        ) -> Dict[str, str]:
            bdf = (
                f"{dev_addr.domain}:{dev_addr.bus}:{dev_addr.slot}.{dev_addr.function}"
            )
            host_dev = host_dev_map.get(bdf)
            if host_dev is None:
                raise LisaException(
                    f"Assigned passthrough BDF '{bdf}' not found in host lspci output"
                )
            return {"vendor_id": host_dev.vendor_id, "device_id": host_dev.device_id}

        # Map pool_type -> unique (vendor_id, device_id) pairs expected on guest
        pool_type_ids: Dict[str, List[Dict[str, str]]] = {}
        for ctx in node_context.passthrough_devices:
            pool_type = str(ctx.pool_type.value)
            ids_for_pool = pool_type_ids.setdefault(pool_type, [])
            for dev_addr in ctx.device_list:
                ids_for_pool.append(_get_vendor_device_id(dev_addr))

        for req in node_runbook.device_passthrough:
            pool_type = str(req.pool_type.value)
            if pool_type not in pool_type_ids:
                raise LisaException(
                    f"Pool type '{pool_type}' not found in assigned passthrough devices"
                )
            # For each distinct vendor/device ID in this pool, count how many
            # matching devices appear on the guest and verify the total >= req.count.
            seen: Dict[str, int] = {}
            for id_pair in pool_type_ids[pool_type]:
                key = f"{id_pair['vendor_id']}:{id_pair['device_id']}"
                if key not in seen:
                    devices = lspci.get_devices_by_vendor_device_id(
                        vendor_id=id_pair["vendor_id"],
                        device_id=id_pair["device_id"],
                        force_run=True,
                    )
                    seen[key] = len(devices)
            total_found = sum(seen.values())
            if total_found < req.count:
                raise LisaException(
                    f"Passthrough device validation failed for pool_type "
                    f"'{pool_type}': found {total_found} device(s) on guest "
                    f"but expected {req.count}. "
                    f"Vendor/Device IDs checked: {list(seen.keys())}"
                )
