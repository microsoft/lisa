# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, cast
from unittest import TestCase

from marshmallow import ValidationError

from lisa.sut_orchestrator.openvmm.schema import (
    OPENVMM_NETWORK_MODE_TAP,
    OPENVMM_NETWORK_MODE_USER,
    OpenVmmGuestNodeSchema,
    OpenVmmNetworkSchema,
    OpenVmmUefiSchema,
)
from lisa.sut_orchestrator.util.schema import HostDevicePoolType
from lisa.util import LisaException


class OpenVmmSchemaTestCase(TestCase):
    def test_network_schema_accepts_valid_ssh_port(self) -> None:
        network_schema = cast(Any, OpenVmmNetworkSchema).schema()
        network = network_schema.load(
            {
                "mode": OPENVMM_NETWORK_MODE_USER,
                "connection_address": "127.0.0.1",
                "ssh_port": 22,
            }
        )

        self.assertEqual(22, network.ssh_port)

    def test_network_schema_rejects_invalid_ssh_port(self) -> None:
        network_schema = cast(Any, OpenVmmNetworkSchema).schema()
        with self.assertRaises(ValidationError):
            network_schema.load(
                {
                    "mode": OPENVMM_NETWORK_MODE_USER,
                    "connection_address": "127.0.0.1",
                    "ssh_port": 0,
                }
            )

    def test_parent_ssh_proxy_accepts_tap_networking(self) -> None:
        network = OpenVmmNetworkSchema(
            mode=OPENVMM_NETWORK_MODE_TAP,
            tap_name="tap0",
            use_parent_ssh_proxy=True,
        )

        self.assertTrue(network.use_parent_ssh_proxy)

    def test_parent_ssh_proxy_rejects_host_port_forwarding(self) -> None:
        with self.assertRaises(LisaException):
            OpenVmmNetworkSchema(
                mode=OPENVMM_NETWORK_MODE_TAP,
                tap_name="tap0",
                use_parent_ssh_proxy=True,
                forward_ssh_port=True,
                forwarded_port=60022,
            )

    def test_guest_schema_rejects_kernel_arg_with_whitespace(self) -> None:
        with self.assertRaises(LisaException):
            OpenVmmGuestNodeSchema(
                uefi=OpenVmmUefiSchema(firmware_path="/var/tmp/MSVM.fd"),
                disk_img="/var/tmp/guest.raw",
                kernel_command_line_args=["console=ttyAMA0 earlycon"],
            )

    def test_guest_schema_loads_device_passthrough(self) -> None:
        guest_schema = cast(Any, OpenVmmGuestNodeSchema).schema()

        guest = guest_schema.load(
            {
                "uefi": {"firmware_path": "/var/tmp/MSVM.fd"},
                "disk_img": "/var/tmp/guest.raw",
                "device_pools": [
                    {
                        "type": "pci_net",
                        "auto_discover": True,
                    }
                ],
                "device_passthrough": [
                    {
                        "pool_type": "pci_net",
                        "count": 1,
                    }
                ],
            }
        )

        assert guest.device_pools is not None
        assert guest.device_passthrough is not None
        self.assertEqual(HostDevicePoolType.PCI_NIC, guest.device_pools[0].type)
        self.assertTrue(guest.device_pools[0].auto_discover)
        self.assertEqual(
            HostDevicePoolType.PCI_NIC,
            guest.device_passthrough[0].pool_type,
        )
        self.assertEqual(1, guest.device_passthrough[0].count)
