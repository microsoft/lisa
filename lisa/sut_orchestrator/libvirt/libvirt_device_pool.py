# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import xml.etree.ElementTree as ET  # noqa: N817
from itertools import combinations
from typing import Any, Dict, List, Optional, cast

from lisa.node import Node, RemoteNode
from lisa.sut_orchestrator.util.device_pool import BaseDevicePool
from lisa.sut_orchestrator.util.schema import HostDevicePoolSchema, HostDevicePoolType
from lisa.tools import Ls, Lspci, Modprobe
from lisa.util import LisaException, ResourceAwaitableException, find_group_in_lines

from .context import DevicePassthroughContext, NodeContext
from .schema import (
    BaseLibvirtNodeSchema,
    BaseLibvirtPlatformSchema,
    DeviceAddressSchema,
)


class LibvirtDevicePool(BaseDevicePool):
    def __init__(
        self,
        host_node: Node,
        runbook: BaseLibvirtPlatformSchema,
    ) -> None:
        # Mapping of Host Device Passthrough
        self.available_host_devices: Dict[
            HostDevicePoolType, Dict[str, List[DeviceAddressSchema]]
        ] = {}

        self.supported_pool_type = [
            HostDevicePoolType.PCI_NIC,
            HostDevicePoolType.PCI_GPU,
        ]
        self.host_node = host_node
        self.platform_runbook = runbook

    def configure_device_passthrough_pool(
        self,
        device_configs: Optional[List[HostDevicePoolSchema]],
    ) -> None:
        if not device_configs:
            return

        # Check if host support device passthrough
        self._check_passthrough_support(self.host_node)

        super().configure_device_passthrough_pool(
            device_configs=device_configs,
        )

        modprobe = self.host_node.tools[Modprobe]
        allow_unsafe_interrupt = modprobe.load(
            modules="vfio_iommu_type1",
            parameters="allow_unsafe_interrupts=1",
        )
        if not allow_unsafe_interrupt:
            raise LisaException("Allowing unsafe interrupt failed")

    def request_devices(
        self,
        pool_type: HostDevicePoolType,
        count: int,
    ) -> List[DeviceAddressSchema]:
        pool = self.available_host_devices.get(pool_type, {})
        keys = list(pool.keys())
        results = []
        for r in range(1, len(keys) + 1):
            for combo in combinations(keys, r):
                if sum(len(pool.get(key, [])) for key in combo) == count:
                    results.append(combo)
        if not results:
            for r in range(1, len(keys) + 1):
                for combo in combinations(keys, r):
                    if sum(len(pool.get(key, [])) for key in combo) >= count:
                        results.append(combo)
                        break
                if results:
                    break

        if not results:
            raise ResourceAwaitableException(
                f"Pool {pool_type} running out of devices: {pool}, "
                "No IOMMU Group has sufficient count of devices, "
                f"Refer: {pool}"
            )

        devices: List[DeviceAddressSchema] = []
        selected_pools = results[0]
        for iommu_grp in selected_pools:
            devices += pool.pop(iommu_grp)
        self.available_host_devices[pool_type] = pool
        return devices

    def release_devices(
        self,
        node_context: NodeContext,
    ) -> None:
        device_context = node_context.passthrough_devices
        for context in device_context:
            pool_type = context.pool_type
            devices_list = context.device_list
            pool = self.available_host_devices.get(pool_type, {})
            for device in devices_list:
                iommu_grp = self._get_device_iommu_group(device)
                pool_devices = pool.get(iommu_grp, [])
                pool_devices.append(device)
                pool[iommu_grp] = pool_devices
            self.available_host_devices[pool_type] = pool

    def get_primary_nic_id(self) -> List[str]:
        # This is for baremetal. For azure, we have to get private IP
        host_ip = cast(RemoteNode, self.host_node).connection_info.get("address")
        assert host_ip, "Host IP is empty"
        cmd = "ip -o -4 addr show"
        err = f"Can not get interface for IP: {host_ip}"
        result = self.host_node.execute(
            cmd=cmd,
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=err,
        )
        # Output for above command
        # ===============================
        # root [ /home/cloud ]# ip -o -4 addr show
        # 1: lo    inet 127.0.0.1/8
        #   scope host lo\       valid_lft forever preferred_lft forever
        # 3: eth1    inet 10.195.88.216/23 metric 1024 brd 10.195.89.255
        #   scope global dynamic eth1\       valid_lft 7210sec preferred_lft 7210sec
        # 6: eth4    inet 10.10.40.135/22 metric 1024 brd 10.10.43.255
        #   scope global dynamic eth4\       valid_lft 27011sec preferred_lft 27011sec

        interface_name = ""
        for line in result.stdout.strip().splitlines():
            if line.find(host_ip) >= 0:
                interface_name = line.split()[1].strip()

        assert interface_name, "Can not find interface name"
        result = self.host_node.execute(
            cmd=f"find /sys/devices/ -name *{interface_name}*",
            sudo=True,
            shell=True,
        )
        stdout = result.stdout.strip()
        assert len(stdout.splitlines()) == 1
        pci_address_pattern = re.compile(
            r"/(?P<root>[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-9a-fA-F])/"
            r"(?P<id>[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-9a-fA-F])/"
        )
        match = find_group_in_lines(
            lines=stdout,
            pattern=pci_address_pattern,
            single_line=False,
        )
        if match:
            pci_address = match.get("id", "")
            assert pci_address, "Can not get primary NIC IOMMU Group"
            device = DeviceAddressSchema()
            domain, bus, slot, fn = self._parse_pci_address_str(addr=pci_address)
            device.domain = domain
            device.bus = bus
            device.slot = slot
            device.function = fn

            iommu_grp = self._get_device_iommu_group(device)
            return [iommu_grp]
        else:
            raise LisaException(
                f"Can't find pci address of for: {interface_name}, "
                f"stdout for command: {stdout}"
            )

    def create_device_pool(
        self,
        pool_type: HostDevicePoolType,
        vendor_id: str,
        device_id: str,
    ) -> None:
        self.available_host_devices[pool_type] = {}
        lspci = self.host_node.tools[Lspci]
        device_list = lspci.get_devices_by_vendor_device_id(
            vendor_id=vendor_id,
            device_id=device_id,
        )
        bdf_list = [i.slot for i in device_list]
        self._create_pool(pool_type, bdf_list)

    def create_device_pool_from_pci_addresses(
        self,
        pool_type: HostDevicePoolType,
        pci_addr_list: List[str],
    ) -> None:
        self.available_host_devices[pool_type] = {}
        for bdf in pci_addr_list:
            domain, bus, slot, fn = self._parse_pci_address_str(bdf)
            device = self._get_pci_address_instance(domain, bus, slot, fn)
            iommu_group = self._get_device_iommu_group(device)

            # Get all the devices of that iommu group
            iommu_path = f"/sys/kernel/iommu_groups/{iommu_group}/devices"
            bdf_list = [i.strip() for i in self.host_node.tools[Ls].list(iommu_path)]
            bdf_list.append(bdf.strip())  # append the given device in list

            self._create_pool(pool_type, bdf_list)

    def _create_pool(
        self,
        pool_type: HostDevicePoolType,
        bdf_list: List[str],
    ) -> None:
        iommu_grp_of_used_devices = []
        primary_nic_iommu = self.get_primary_nic_id()
        for bdf in bdf_list:
            domain, bus, slot, fn = self._parse_pci_address_str(bdf)
            dev = self._get_pci_address_instance(domain, bus, slot, fn)
            is_vfio_pci = self._is_driver_vfio_pci(dev)
            iommu_group = self._get_device_iommu_group(dev)

            if iommu_group in iommu_grp_of_used_devices:
                # No need to add this device in pool as one of the devices for this
                # iommu group is in use
                continue

            if is_vfio_pci:
                # Do not consider any device for pool if any device of same iommu group
                # is already assigned
                pool = self.available_host_devices.get(pool_type, {})
                pool.pop(iommu_group, [])
                self.available_host_devices[pool_type] = pool
                iommu_grp_of_used_devices.append(iommu_group)
            elif (
                iommu_group not in primary_nic_iommu
                and iommu_group not in iommu_grp_of_used_devices
            ):
                pool = self.available_host_devices.get(pool_type, {})
                devices = pool.get(iommu_group, [])
                if dev not in devices:
                    devices.append(dev)
                pool[iommu_group] = devices
                self.available_host_devices[pool_type] = pool

    def _get_pci_address_instance(
        self,
        domain: str,
        bus: str,
        slot: str,
        fn: str,
    ) -> DeviceAddressSchema:
        device = DeviceAddressSchema()
        device.domain = domain
        device.bus = bus
        device.slot = slot
        device.function = fn

        return device

    def _add_device_passthrough_xml(
        self,
        devices: ET.Element,
        node_context: NodeContext,
    ) -> ET.Element:
        for context in node_context.passthrough_devices:
            for config in context.device_list:
                hostdev = ET.SubElement(devices, "hostdev")
                hostdev.attrib["mode"] = "subsystem"

                assert context.managed
                hostdev.attrib["managed"] = context.managed

                assert context.pool_type
                if "pci" in context.pool_type.value:
                    hostdev.attrib["type"] = "pci"

                    source = ET.SubElement(hostdev, "source")
                    src_addrs = ET.SubElement(source, "address")

                    assert config.domain
                    src_addrs.attrib["domain"] = f"0x{config.domain}"

                    assert config.bus
                    src_addrs.attrib["bus"] = f"0x{config.bus}"

                    assert config.slot
                    src_addrs.attrib["slot"] = f"0x{config.slot}"

                    assert config.function
                    src_addrs.attrib["function"] = f"0x{config.function}"

                    driver = ET.SubElement(hostdev, "driver")
                    driver.attrib["name"] = "vfio"

        return devices

    def _get_pci_address_str(
        self,
        device_addr: DeviceAddressSchema,
        with_domain: bool = True,
    ) -> str:
        bus = device_addr.bus
        slot = device_addr.slot
        fn = device_addr.function
        domain = device_addr.domain
        addr = f"{bus}:{slot}.{fn}"
        if with_domain:
            addr = f"{domain}:{addr}"
        return addr

    def _parse_pci_address_str(
        self,
        addr: str,
        with_domain: bool = True,
    ) -> Any:
        addr_split = addr.strip().split(":")
        idx = 1 if with_domain else 0

        bus = addr_split[idx]
        slot = addr_split[idx + 1].split(".")[0]
        fn = addr_split[idx + 1].split(".")[1]

        if with_domain:
            domain = addr_split[0]
            return domain, bus, slot, fn
        else:
            return bus, slot, fn

    def _verify_device_passthrough_post_boot(
        self,
        node_context: NodeContext,
    ) -> None:
        device_context = node_context.passthrough_devices
        for context in device_context:
            devices = context.device_list
            for device in devices:
                err = f"Kernel driver is not vfio-pci for device: {device}"
                pool_type = context.pool_type.value
                if context.managed == "yes" and "pci" in pool_type:
                    is_vfio_pci = self._is_driver_vfio_pci(device)
                    assert is_vfio_pci, err

    def _check_passthrough_support(self, host_node: Node) -> None:
        ls = host_node.tools[Ls]
        path = "/dev/vfio/vfio"
        err = "Host does not support IOMMU"
        if not ls.path_exists(path=path, sudo=True):
            raise LisaException(f"{err} : {path} does not exist")

        path = "/sys/kernel/iommu_groups/"
        if len(ls.list(path=path, sudo=True)) == 0:
            raise LisaException(f"{err} : {path} does not have any entry")

    def _is_driver_vfio_pci(
        self,
        device_addr: DeviceAddressSchema,
    ) -> bool:
        lspci = self.host_node.tools[Lspci]
        device_addr_str = self._get_pci_address_str(device_addr)
        kernel_module = lspci.get_used_module(device_addr_str)
        return kernel_module == "vfio-pci"

    def _set_device_passthrough_node_context(
        self,
        node_context: NodeContext,
        node_runbook: BaseLibvirtNodeSchema,
    ) -> None:
        if not node_runbook.device_passthrough:
            return
        for config in node_runbook.device_passthrough:
            device_context = DevicePassthroughContext()
            device_context.managed = config.managed
            device_context.pool_type = config.pool_type
            devices = self.request_devices(config.pool_type, config.count)
            device_context.device_list = devices
            node_context.passthrough_devices.append(device_context)

    def _get_device_iommu_group(self, device: DeviceAddressSchema) -> str:
        iommu_pattern = re.compile(r"/sys/kernel/iommu_groups/(?P<id>\d+)/devices/.*")
        device_id = self._get_pci_address_str(device)
        command = "find /sys/kernel/iommu_groups/ -type l"
        err = "Command failed to list IOMMU Groups"
        result = self.host_node.execute(
            cmd=command,
            shell=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=err,
        )

        iommu_grp = ""
        for line in result.stdout.strip().splitlines():
            if line.find(device_id) >= 0:
                iommu_grp_res = find_group_in_lines(
                    lines=line,
                    pattern=iommu_pattern,
                )
                iommu_grp = iommu_grp_res.get("id", "")
                break
        assert iommu_grp, f"Can not get IOMMU group for device: {device}"
        return f"iommu_grp_{iommu_grp}"
