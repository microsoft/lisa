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
)


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
