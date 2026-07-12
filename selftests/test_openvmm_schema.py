# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, cast
from unittest import TestCase

from marshmallow import ValidationError

from lisa.sut_orchestrator.openvmm.schema import (
    OPENVMM_CONNECTION_MODE_HOST_PROXY,
    OPENVMM_NETWORK_MODE_TAP,
    OPENVMM_NETWORK_MODE_USER,
    OpenVmmGuestNodeSchema,
    OpenVmmNetworkSchema,
    OpenVmmUefiSchema,
)
from lisa.sut_orchestrator.util.schema import HostDevicePoolType
from lisa.tools.openvmm import (
    OPENVMM_DISK_DEVICE_VIRTIO_BLK,
    OPENVMM_NETWORK_DEVICE_VIRTIO,
)
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

    def test_network_schema_accepts_valid_queue_count(self) -> None:
        network_schema = cast(Any, OpenVmmNetworkSchema).schema()
        network = network_schema.load({"queue_count": 1})

        self.assertEqual(1, network.queue_count)

    def test_network_schema_rejects_invalid_queue_count(self) -> None:
        network_schema = cast(Any, OpenVmmNetworkSchema).schema()
        with self.assertRaises(ValidationError):
            network_schema.load({"queue_count": 0})

    def test_guest_schema_splits_extra_args_string(self) -> None:
        guest_schema = cast(Any, OpenVmmGuestNodeSchema).schema()
        guest = guest_schema.load(
            {
                "uefi": {"firmware_path": "/firmware"},
                "disk_img": "/disk.raw",
                "extra_args": "--foo 'bar baz'",
            }
        )

        self.assertEqual(["--foo", "bar baz"], guest.extra_args)

    def test_guest_schema_accepts_virtio_devices(self) -> None:
        guest_schema = cast(Any, OpenVmmGuestNodeSchema).schema()
        guest = guest_schema.load(
            {
                "uefi": {"firmware_path": "/firmware"},
                "disk_img": "/disk.raw",
                "disk_device": OPENVMM_DISK_DEVICE_VIRTIO_BLK,
                "network": {"device": OPENVMM_NETWORK_DEVICE_VIRTIO},
            }
        )

        self.assertEqual(OPENVMM_DISK_DEVICE_VIRTIO_BLK, guest.disk_device)
        self.assertEqual(OPENVMM_NETWORK_DEVICE_VIRTIO, guest.network.device)

    def test_host_proxy_connection_mode_disables_forwarded_port(self) -> None:
        network_schema = cast(Any, OpenVmmNetworkSchema).schema()
        network = network_schema.load(
            {
                "mode": OPENVMM_NETWORK_MODE_TAP,
                "connection_mode": OPENVMM_CONNECTION_MODE_HOST_PROXY,
                "tap_name": "tap0",
                "forwarded_port": 60022,
            }
        )

        self.assertFalse(network.forward_ssh_port)
        self.assertEqual(0, network.forwarded_port)

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
