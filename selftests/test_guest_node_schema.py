# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, cast
from unittest import TestCase

from lisa import constants, schema
from lisa.sut_orchestrator.openvmm.schema import (
    OpenVmmGuestNodeSchema,
    OpenVmmNetworkSchema,
    OpenVmmUefiSchema,
)
from lisa.util import LisaException


class GuestNodeSchemaTestCase(TestCase):
    def test_load_typed_guest_node_requires_type(self) -> None:
        with self.assertRaises(LisaException) as context:
            schema.load_typed_guest_node({"distro": "Ubuntu"})

        self.assertIn("missing the required 'type' field", str(context.exception))

    def test_load_typed_guest_node_rejects_unknown_type(self) -> None:
        with self.assertRaises(LisaException) as context:
            schema.load_typed_guest_node({constants.TYPE: "does-not-exist"})

        self.assertIn(
            "cannot find guest node type 'does-not-exist'", str(context.exception)
        )

    def test_load_typed_guest_node_rejects_unknown_fields(self) -> None:
        with self.assertRaises(LisaException) as context:
            schema.load_typed_guest_node(
                {
                    constants.TYPE: "wsl",
                    "distro": "Ubuntu",
                    "unexpected_field": True,
                }
            )

        self.assertIn("found unknown fields", str(context.exception))
        self.assertIn("unexpected_field", str(context.exception))

    def test_load_typed_guest_node_requires_guest_node_schema(self) -> None:
        with self.assertRaises(LisaException) as context:
            schema.load_typed_guest_node(
                {constants.TYPE: constants.ENVIRONMENTS_NODES_LOCAL}
            )

        self.assertIn("must use a GuestNode schema", str(context.exception))

    def test_load_typed_guest_node_returns_guest_subclass_instance(self) -> None:
        runbook = OpenVmmGuestNodeSchema(
            uefi=OpenVmmUefiSchema(firmware_path="/tmp/MSVM.fd"),
            disk_img="/tmp/guest.img",
            network=OpenVmmNetworkSchema(connection_address="127.0.0.1"),
        )

        loaded = schema.load_typed_guest_node(cast(Any, runbook))

        self.assertIs(runbook, loaded)
