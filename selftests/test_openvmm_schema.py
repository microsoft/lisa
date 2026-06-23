# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, cast
from unittest import TestCase

from marshmallow import ValidationError

from lisa.sut_orchestrator.openvmm.schema import (
    OPENVMM_HYPERVISOR_KVM,
    OPENVMM_NETWORK_MODE_USER,
    OpenVmmGuestNodeSchema,
    OpenVmmNetworkSchema,
    OpenVmmUefiSchema,
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

    def test_guest_schema_accepts_kvm_hypervisor(self) -> None:
        guest = OpenVmmGuestNodeSchema(
            uefi=OpenVmmUefiSchema(firmware_path="/tmp/MSVM.fd"),
            disk_img="/tmp/guest.img",
            hypervisor="KVM",
            network=OpenVmmNetworkSchema(connection_address="127.0.0.1"),
        )

        self.assertEqual(OPENVMM_HYPERVISOR_KVM, guest.hypervisor)

    def test_guest_schema_rejects_invalid_hypervisor(self) -> None:
        with self.assertRaisesRegex(LisaException, "hypervisor 'bad' is not supported"):
            OpenVmmGuestNodeSchema(
                uefi=OpenVmmUefiSchema(firmware_path="/tmp/MSVM.fd"),
                disk_img="/tmp/guest.img",
                hypervisor="bad",
                network=OpenVmmNetworkSchema(connection_address="127.0.0.1"),
            )
