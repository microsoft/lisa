# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from importlib import import_module
from importlib.util import find_spec
from types import SimpleNamespace
from typing import Any, cast
from unittest import TestCase, skipUnless
from unittest.mock import MagicMock, patch

from lisa.features import StartStop


class LibvirtPlatformTestCase(TestCase):
    @skipUnless(
        all(
            find_spec(module_name) is not None
            for module_name in ["libvirt", "libvirtaio", "pycdlib"]
        ),
        "libvirt optional dependencies are not installed",
    )
    def test_node_capability_includes_start_stop(self) -> None:
        platform_module = cast(
            Any, import_module("lisa.sut_orchestrator.libvirt.platform")
        )
        platform_type = platform_module.BaseLibvirtPlatform
        platform = platform_type.__new__(platform_type)
        host_capabilities = platform_module._HostCapabilities()
        host_capabilities.core_count = 8

        node_capabilities = platform._create_node_capabilities(host_capabilities)

        feature_names = {feature.type for feature in node_capabilities.features.items}
        self.assertIn(StartStop.name(), feature_names)

    @skipUnless(
        all(
            find_spec(module_name) is not None
            for module_name in ["libvirt", "libvirtaio", "pycdlib"]
        ),
        "libvirt optional dependencies are not installed",
    )
    def test_restart_closes_stale_console_logger(self) -> None:
        platform_module = cast(
            Any, import_module("lisa.sut_orchestrator.libvirt.platform")
        )
        platform_type = platform_module.BaseLibvirtPlatform
        platform = platform_type.__new__(platform_type)
        domain = MagicMock()
        domain.isActive.return_value = False
        console_logger = MagicMock()
        node_context = SimpleNamespace(
            domain=domain,
            console_logger=console_logger,
        )
        platform._create_domain_and_attach_logger = MagicMock()

        with patch.object(
            platform_module, "get_node_context", return_value=node_context
        ):
            platform.restart_domain_and_attach_logger(MagicMock())

        console_logger.close.assert_called_once_with()
        console_logger.wait_for_close.assert_not_called()
        self.assertIsNone(node_context.console_logger)
        platform._create_domain_and_attach_logger.assert_called_once_with(node_context)
