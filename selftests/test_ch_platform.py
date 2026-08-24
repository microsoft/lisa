# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import importlib
import sys
from types import ModuleType
from unittest import TestCase
from unittest.mock import MagicMock, patch


def _load_ch_platform_module() -> ModuleType:
    for module_name in ("libvirt", "libvirtaio"):
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError as identifier:
            if identifier.name != module_name:
                raise
            module = ModuleType(module_name)
            if module_name == "libvirt":
                module.__dict__.update(
                    {
                        "libvirtError": type("libvirtError", (Exception,), {}),
                        "virConnect": type("virConnect", (), {}),
                        "virDomain": type("virDomain", (), {}),
                        "virStream": type("virStream", (), {}),
                    }
                )
            sys.modules[module_name] = module

    return importlib.import_module("lisa.sut_orchestrator.libvirt.ch_platform")


class CloudHypervisorPlatformTestCase(TestCase):
    def test_restarts_passthrough_domain_after_boot_timeout(self) -> None:
        ch_platform_module = _load_ch_platform_module()
        platform = object.__new__(ch_platform_module.CloudHypervisorPlatform)
        platform.restart_domain_and_attach_logger = MagicMock()

        domain = MagicMock()
        node_context = MagicMock(
            vm_name="lisa-test-0",
            passthrough_devices=[MagicMock()],
            domain=domain,
        )
        node = MagicMock()
        node.get_context.return_value = node_context
        environment = MagicMock()
        environment_context = MagicMock(network_boot_timeout=240)
        environment.get_context.return_value = environment_context
        log = MagicMock()

        with patch.object(
            ch_platform_module.BaseLibvirtPlatform,
            "_get_node_ip_address",
            side_effect=[
                ch_platform_module.GuestBootTimeoutError("boot timeout"),
                "192.0.2.10",
            ],
        ) as get_ip_address, patch.object(
            ch_platform_module.time, "time", return_value=100
        ):
            address = platform._get_node_ip_address(
                environment,
                log,
                node,
                timeout=50,
            )

        self.assertEqual("192.0.2.10", address)
        domain.destroy.assert_called_once_with()
        platform.restart_domain_and_attach_logger.assert_called_once_with(node)
        self.assertEqual(50, get_ip_address.call_args_list[0].args[3])
        self.assertEqual(340, get_ip_address.call_args_list[1].args[3])
        log.warning.assert_called_once()

    def test_does_not_restart_domain_without_passthrough(self) -> None:
        ch_platform_module = _load_ch_platform_module()
        platform = object.__new__(ch_platform_module.CloudHypervisorPlatform)
        platform.restart_domain_and_attach_logger = MagicMock()

        node_context = MagicMock(
            vm_name="lisa-test-0",
            passthrough_devices=[],
        )
        node = MagicMock()
        node.get_context.return_value = node_context

        with patch.object(
            ch_platform_module.BaseLibvirtPlatform,
            "_get_node_ip_address",
            side_effect=ch_platform_module.GuestBootTimeoutError("boot timeout"),
        ):
            with self.assertRaises(ch_platform_module.GuestBootTimeoutError):
                platform._get_node_ip_address(
                    MagicMock(),
                    MagicMock(),
                    node,
                    timeout=50,
                )

        platform.restart_domain_and_attach_logger.assert_not_called()
