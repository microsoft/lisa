# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from importlib import import_module
from importlib.util import find_spec
from typing import Any, cast
from unittest import TestCase, skipUnless

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
