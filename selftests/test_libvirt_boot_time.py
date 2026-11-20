# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import sys
from contextlib import ExitStack
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa import schema
from lisa.messages import ProvisionBootTimeMessage
from lisa.operating_system import Linux
from lisa.tools import SystemdAnalyze


class LibvirtBootTimeTestCase(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Native bindings and image creation are not needed for node configuration.
        with patch.dict(
            sys.modules,
            {
                "libvirt": MagicMock(),
                "libvirtaio": MagicMock(),
                "pycdlib": MagicMock(),
            },
        ):
            from lisa.sut_orchestrator.libvirt.platform import BaseLibvirtPlatform
            from lisa.sut_orchestrator.libvirt.schema import (
                BaseLibvirtNodeSchema,
                BaseLibvirtPlatformSchema,
            )

        cls._platform_type = BaseLibvirtPlatform
        cls._node_schema = BaseLibvirtNodeSchema
        cls._platform_schema = BaseLibvirtPlatformSchema

    def test_capture_boot_time_enabled_during_deployment(self) -> None:
        self._verify_boot_time_capture(enabled=True)

    def test_capture_boot_time_disabled_during_deployment(self) -> None:
        self._verify_boot_time_capture(enabled=False)

    def _verify_boot_time_capture(self, enabled: bool) -> None:
        platform = self._platform_type(
            runbook=schema.Platform(capture_boot_time=enabled)
        )
        platform.platform_runbook = self._platform_schema()
        requirement = MagicMock(spec=schema.NodeSpace)
        requirement.get_extended_runbook.return_value = self._node_schema(
            disk_img="guest.qcow2"
        )
        environment = MagicMock()
        environment.runbook.nodes_requirement = [requirement, requirement]
        nodes = [MagicMock(), MagicMock()]
        messages = [
            ProvisionBootTimeMessage(kernel_boot_time=1000),
            ProvisionBootTimeMessage(kernel_boot_time=2000),
        ]
        for index, node in enumerate(nodes):
            node.capture_boot_time = False
            node.capture_azure_information = False
            node.is_test_target = True
            node._first_initialize = True
            node.get_information.return_value = {"name": f"guest-{index}"}
            node.tools[SystemdAnalyze].get_boot_time.return_value = messages[index]
        environment.create_node_from_requirement.side_effect = nodes

        def collect_guest_information(environment: MagicMock, log: MagicMock) -> None:
            for node in nodes:
                Linux(node).capture_system_information(Path("captured"))

        with ExitStack() as stack:
            for patcher in (
                patch("os.path.exists", return_value=True),
                patch.object(platform, "_configure_node"),
                patch.object(platform, "_create_nodes"),
                patch.object(
                    platform,
                    "_fill_nodes_metadata",
                    side_effect=collect_guest_information,
                ),
                patch.object(platform, "_expand_nodes_os_partition"),
            ):
                stack.enter_context(patcher)
            notify = stack.enter_context(patch("lisa.operating_system.notifier.notify"))
            platform._deploy_nodes(environment, MagicMock())

        self.assertEqual(2, environment.create_node_from_requirement.call_count)
        self.assertEqual(2 if enabled else 0, notify.call_count)
        for index, node in enumerate(nodes):
            self.assertEqual(enabled, node.capture_boot_time)
            analyze = node.tools[SystemdAnalyze]
            if enabled:
                analyze.get_boot_time.assert_called_once_with()
                self.assertIs(messages[index], notify.call_args_list[index].args[0])
                self.assertEqual(
                    {"name": f"guest-{index}"}, messages[index].information
                )
            else:
                analyze.get_boot_time.assert_not_called()
