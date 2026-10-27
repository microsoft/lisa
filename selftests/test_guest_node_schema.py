# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from types import SimpleNamespace
from typing import Any, Dict, List, Type, cast
from unittest import TestCase
from unittest.mock import patch

from lisa import constants, schema
from lisa.environment import Environment, Environments, EnvironmentSpace
from lisa.feature import Feature
from lisa.platform_ import Platform
from lisa.sut_orchestrator.openvmm.node import OpenVmmGuestNode
from lisa.sut_orchestrator.openvmm.schema import (
    OpenVmmGuestNodeSchema,
    OpenVmmNetworkSchema,
    OpenVmmUefiSchema,
)
from lisa.testsuite import simple_requirement
from lisa.util import LisaException, plugin_manager
from lisa.util.logger import Logger


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

    def test_platform_expands_object_guest_node_count(self) -> None:
        runbook = OpenVmmGuestNodeSchema(
            uefi=OpenVmmUefiSchema(firmware_path="/tmp/MSVM.fd"),
            disk_img="/tmp/guest.img",
            network=OpenVmmNetworkSchema(connection_address="127.0.0.1"),
        )
        runbook.capability.node_count = 2

        platform = schema.Platform(guests=[runbook])

        self.assertEqual(2, len(platform.guests))
        self.assertTrue(
            all(isinstance(guest, OpenVmmGuestNodeSchema) for guest in platform.guests)
        )
        self.assertEqual(
            [1, 1], [guest.capability.node_count for guest in platform.guests]
        )


class _GuestTestPlatform(Platform):
    @classmethod
    def type_name(cls) -> str:
        return "guest-count-test"

    @classmethod
    def supported_features(cls) -> List[Type[Feature]]:
        return []

    def _prepare_environment(self, environment: Environment, log: Logger) -> bool:
        return True

    def _deploy_environment(self, environment: Environment, log: Logger) -> None:
        assert environment.runbook.nodes_requirement
        for requirement in environment.runbook.nodes_requirement:
            environment.create_node_from_requirement(requirement)


class GuestNodeCountTestCase(TestCase):
    def test_guest_count_follows_source_requirement_when_enabled(self) -> None:
        platform = self._guest_platform(2, requirement_driven=True)
        for required_count in (1, 2, 1):
            with self.subTest(required_count=required_count):
                environment = self._guest_environment(required_count)
                platform.prepare_environment(environment)
                platform.deploy_environment(environment)

                guests = list(environment.get_guest_environment().nodes.list())
                self.assertEqual(required_count, len(guests))
                self.assertEqual(2, len(platform.runbook.guests))
                for guest in guests:
                    self.assertIsInstance(guest, OpenVmmGuestNode)
                    self.assertEqual(2, guest.capability.core_count)
                    self.assertEqual(2048, guest.capability.memory_mb)

    def test_explicit_guest_counts_are_not_reduced_by_default(self) -> None:
        for configured_count in (2, 4, 12):
            with self.subTest(configured_count=configured_count):
                platform = self._guest_platform(configured_count)
                environment = self._guest_environment(1)
                platform.prepare_environment(environment)
                platform.deploy_environment(environment)

                self.assertEqual(
                    configured_count,
                    len(environment.get_guest_environment().nodes),
                )

    def test_requirement_guest_count_rejects_invalid_topology_before_deploy(
        self,
    ) -> None:
        for invalid in ("capacity", "source", "parents", "empty"):
            with self.subTest(invalid=invalid):
                platform = self._guest_platform(2, requirement_driven=True)
                environment = self._guest_environment(
                    3 if invalid == "capacity" else 1,
                    parent_count=2 if invalid == "parents" else 1,
                )
                if invalid == "source":
                    environment.source_test_result = None
                elif invalid == "empty":
                    assert environment.source_test_result
                    requirement = (
                        environment.source_test_result.runtime_data.requirement
                    )
                    requirement.environment = None
                messages = {
                    "capacity": "test requires 3 guests, but only 2 are configured",
                    "source": "requires a generated environment",
                    "parents": "requires exactly one parent node",
                    "empty": "requires a nonempty test environment requirement",
                }
                with patch.object(platform, "_deploy_environment") as deploy:
                    with self.assertRaisesRegex(LisaException, messages[invalid]):
                        platform.deploy_environment(environment)
                    deploy.assert_not_called()

    def _guest_platform(
        self, count: int, requirement_driven: bool = False
    ) -> _GuestTestPlatform:
        data: Dict[str, Any] = {
            constants.TYPE: "guest-count-test",
            "guest_enabled": True,
            "guests": [
                {
                    constants.TYPE: "openvmm",
                    "uefi": {"firmware_path": "/firmware.fd"},
                    "disk_img": "/guest.raw",
                    "use_parent_capability": False,
                    "capability": {
                        "node_count": count,
                        "core_count": 2,
                        "memory_mb": 2048,
                    },
                }
            ],
        }
        if requirement_driven:
            data["guest_count_from_requirement"] = True
        platform = _GuestTestPlatform(schema.load_by_type(schema.Platform, data))
        self.addCleanup(plugin_manager.unregister, plugin=platform)
        platform.initialize()
        return platform

    def _guest_environment(
        self, required_count: int, parent_count: int = 1
    ) -> Environment:
        environment = Environments().from_requirement(
            EnvironmentSpace(
                nodes=[schema.NodeSpace(node_count=parent_count, core_count=16)]
            )
        )
        assert environment
        environment.source_test_result = cast(
            Any,
            SimpleNamespace(
                runtime_data=SimpleNamespace(
                    requirement=simple_requirement(min_count=required_count)
                )
            ),
        )
        return environment
