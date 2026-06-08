# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, cast
from unittest import TestCase

from marshmallow import ValidationError

from lisa.sut_orchestrator.openvmm.schema import (
    OPENVMM_NETWORK_MODE_USER,
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
