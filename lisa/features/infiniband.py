# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import Dict, List, Tuple

from assertpy import assert_that

from lisa.feature import Feature

FEATURE_NAME_INFINIBAND = "Infiniband"


class Infiniband(Feature):

    # Example output of ibv_devinfo:
    # hca_id: mlx5_0
    #     transport:                      InfiniBand (0)
    #     fw_ver:                         16.28.4000
    #     node_guid:                      0015:5dff:fe33:ff0c
    #     sys_image_guid:                 0c42:a103:0065:bafe
    #     vendor_id:                      0x02c9
    #     vendor_part_id:                 4120
    #     hw_ver:                         0x0
    #     board_id:                       MT_0000000010
    #     phys_port_cnt:                  1
    #             port:   1
    #                     state:                  PORT_ACTIVE (4)
    #                     max_mtu:                4096 (5)
    #                     active_mtu:             4096 (5)
    #                     sm_lid:                 55
    #                     port_lid:               693
    #                     port_lmc:               0x00
    #                     link_layer:             InfiniBand
    _ib_info_pattern = re.compile(r"(\s*(?P<id>\S*):\s*(?P<value>.*)\n?)")

    def enabled(self) -> bool:
        return True

    @classmethod
    def name(cls) -> str:
        return FEATURE_NAME_INFINIBAND

    @classmethod
    def can_disable(cls) -> bool:
        return True

    def is_over_sriov(self) -> bool:
        raise NotImplementedError

    # nd stands for network direct
    # example SKU: Standard_H16mr
    def is_over_nd(self) -> bool:
        raise NotImplementedError

    def get_ib_interfaces(self) -> List[Tuple[str, str, str]]:
        """Gets the list of Infiniband devices
        excluding any ethernet devices
        and get their cooresponding network interface
        Returns list of tuples in the form (ib_device_name, nic_name, ip_addr)
        Example ("mlx5_ib0", "ib0", "172.16.1.23")"""
        ib_devices = []
        device_info = self._get_ib_device_info()
        for device in device_info:
            if device["link_layer"].strip() == "InfiniBand" and "node_guid" in device:
                device_name = device["hca_id"].strip()
                guid = device["node_guid"].strip()
                # Get the last three bytes of guid
                # Example
                # guid = 0015:5dff:fe33:ff0c
                # mpat = 33:ff:0c (This will match the ib device)
                mpat = f"{guid[12:17]}:{guid[17:19]}"
                for (nic_name, nic_info) in self._node.nics.nics.items():
                    result = self._node.execute(f"/sbin/ip addr show {nic_name}")
                    if mpat in result.stdout and "ib" in nic_name:
                        assert_that(nic_info.ip_addr).described_as(
                            f"NIC {nic_name} does not have an ip address."
                        ).is_not_empty()
                        ib_devices.append((device_name, nic_name, nic_info.ip_addr))

        assert_that(ib_devices).described_as(
            "Failed to get any InfiniBand device / interface pairs"
        ).is_not_empty()
        return ib_devices

    def _get_ib_device_info(self) -> List[Dict[str, str]]:
        device_info = []
        devices = self._get_ib_device_names()
        for device_name in devices:
            result = self._node.execute(
                f"ibv_devinfo -d {device_name}",
                expected_exit_code=0,
                expected_exit_code_failure_message="Failed to get device info from "
                f"ibv_devinfo for infiniband device {device_name}",
            )
            d = {
                match.group("id"): match.group("value")
                for match in self._ib_info_pattern.finditer(result.stdout)
            }
            if "hca_id" in d:
                device_info.append(d)

        assert_that(device_info).described_as(
            "Failed to get device info for any InfiniBand devices"
        ).is_not_empty()
        return device_info

    def _get_ib_device_names(self) -> List[str]:
        node = self._node
        result = node.execute(
            "ls /sys/class/infiniband",
            expected_exit_code=0,
            expected_exit_code_failure_message="Failed to get InfiniBand"
            " devices from /sys/class/infiniband",
        )

        assert_that(result.stdout).described_as(
            "No infiniband devices found in /sys/class/infiniband"
        ).is_not_empty()
        return result.stdout.split()
