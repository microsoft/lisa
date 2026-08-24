# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import importlib
import sys
from types import ModuleType
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.util.process import ExecutableResult


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
    @staticmethod
    def _command_result(
        exit_code: int,
        stdout: str = "",
        stderr: str = "",
        is_timeout: bool = False,
    ) -> ExecutableResult:
        return ExecutableResult(
            stdout,
            stderr,
            exit_code,
            "command",
            "command-id",
            0,
            is_timeout,
        )

    def test_restarts_passthrough_domain_after_boot_timeout(self) -> None:
        ch_platform_module = _load_ch_platform_module()
        platform = object.__new__(ch_platform_module.CloudHypervisorPlatform)
        platform._stop_domain = MagicMock()
        platform.restart_domain_and_attach_logger = MagicMock()

        node_context = MagicMock(
            vm_name="lisa-test-0",
            passthrough_devices=[MagicMock()],
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
        platform._stop_domain.assert_called_once_with(node_context, log)
        platform.restart_domain_and_attach_logger.assert_called_once_with(node)
        self.assertEqual(50, get_ip_address.call_args_list[0].args[3])
        self.assertEqual(340, get_ip_address.call_args_list[1].args[3])
        log.warning.assert_called_once()

    def test_limits_passthrough_boot_restarts(self) -> None:
        ch_platform_module = _load_ch_platform_module()
        platform = object.__new__(ch_platform_module.CloudHypervisorPlatform)
        platform._stop_domain = MagicMock()
        platform.restart_domain_and_attach_logger = MagicMock()

        node_context = MagicMock(
            vm_name="lisa-test-0",
            passthrough_devices=[MagicMock()],
        )
        node = MagicMock()
        node.get_context.return_value = node_context
        environment = MagicMock()
        environment.get_context.return_value = MagicMock(network_boot_timeout=240)

        with patch.object(
            ch_platform_module.BaseLibvirtPlatform,
            "_get_node_ip_address",
            side_effect=ch_platform_module.GuestBootTimeoutError("boot timeout"),
        ), patch.object(ch_platform_module.time, "time", return_value=100):
            with self.assertRaises(ch_platform_module.GuestBootTimeoutError):
                platform._get_node_ip_address(
                    environment,
                    MagicMock(),
                    node,
                    timeout=50,
                )

        self.assertEqual(
            ch_platform_module.PASSTHROUGH_BOOT_RETRY_COUNT,
            platform._stop_domain.call_count,
        )
        self.assertEqual(
            ch_platform_module.PASSTHROUGH_BOOT_RETRY_COUNT,
            platform.restart_domain_and_attach_logger.call_count,
        )

    def test_does_not_restart_domain_without_passthrough(self) -> None:
        ch_platform_module = _load_ch_platform_module()
        platform = object.__new__(ch_platform_module.CloudHypervisorPlatform)
        platform._stop_domain = MagicMock()
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

        platform._stop_domain.assert_not_called()
        platform.restart_domain_and_attach_logger.assert_not_called()

    def test_stops_passthrough_domain_with_bounded_virsh(self) -> None:
        ch_platform_module = _load_ch_platform_module()
        platform = object.__new__(ch_platform_module.CloudHypervisorPlatform)
        platform._run_bounded_domain_stop = MagicMock(
            return_value=self._command_result(0)
        )
        platform._find_domain_process_id = MagicMock(return_value=4321)

        domain = MagicMock()
        node_context = MagicMock(
            vm_name="lisa-test-0",
            passthrough_devices=[MagicMock()],
            domain=domain,
        )

        platform._stop_domain(node_context, MagicMock())

        platform._run_bounded_domain_stop.assert_called_once_with("lisa-test-0")
        domain.destroy.assert_not_called()

    def test_finds_only_exact_cloud_hypervisor_domain_process(self) -> None:
        ch_platform_module = _load_ch_platform_module()
        platform = object.__new__(ch_platform_module.CloudHypervisorPlatform)
        platform.host_node = MagicMock()
        platform.host_node.execute.return_value = self._command_result(
            0,
            stdout="4321",
        )

        process_id = platform._find_domain_process_id("lisa-test-0")

        self.assertEqual(4321, process_id)
        command = platform.host_node.execute.call_args.args[0]
        self.assertIn("/proc/[0-9]*/cmdline", command)
        self.assertIn("lisa-test-0-event-monitor-fifo", command)
        self.assertIn("cloud-hypervisor", command)
        self.assertNotIn("pgrep", command)

    def test_bounded_domain_stop_uses_host_timeout(self) -> None:
        ch_platform_module = _load_ch_platform_module()
        platform = object.__new__(ch_platform_module.CloudHypervisorPlatform)
        platform.host_node = MagicMock()
        platform.host_node.execute.return_value = self._command_result(0)

        platform._run_bounded_domain_stop("lisa-test-0")

        command = platform.host_node.execute.call_args.args[0]
        self.assertIn("timeout --kill-after=5s 30s", command)
        self.assertIn("virsh --connect ch:///system destroy lisa-test-0", command)
        self.assertTrue(platform.host_node.execute.call_args.kwargs["sudo"])
        self.assertTrue(platform.host_node.execute.call_args.kwargs["shell"])

    def test_force_kills_only_exact_domain_after_stop_timeout(self) -> None:
        ch_platform_module = _load_ch_platform_module()
        platform = object.__new__(ch_platform_module.CloudHypervisorPlatform)
        platform._log = MagicMock()
        platform.host_node = MagicMock()
        platform.host_node.execute.return_value = self._command_result(0)

        platform._force_kill_domain_process("lisa-test-0", 4321)

        command = platform.host_node.execute.call_args.args[0]
        self.assertIn("/proc/4321/exe", command)
        self.assertIn("/proc/4321/cmdline", command)
        self.assertIn("lisa-test-0-event-monitor-fifo", command)
        self.assertIn("kill -KILL 4321", command)
        self.assertNotIn("pkill", command)
        self.assertNotIn("killall", command)

    def test_recovers_after_bounded_destroy_timeout(self) -> None:
        ch_platform_module = _load_ch_platform_module()
        platform = object.__new__(ch_platform_module.CloudHypervisorPlatform)
        platform._run_bounded_domain_stop = MagicMock(
            side_effect=[
                self._command_result(124),
                self._command_result(0),
            ]
        )
        platform._find_domain_process_id = MagicMock(return_value=4321)
        platform._capture_domain_process_diagnostics = MagicMock()
        platform._force_kill_domain_process = MagicMock(
            return_value=self._command_result(0)
        )
        replacement_domain = MagicMock()
        platform._lookup_domain = MagicMock(return_value=replacement_domain)

        node_context = MagicMock(
            vm_name="lisa-test-0",
            passthrough_devices=[MagicMock()],
            domain=MagicMock(),
        )
        log = MagicMock()

        with patch.object(ch_platform_module.time, "sleep"):
            platform._stop_domain(node_context, log)

        self.assertEqual(2, platform._run_bounded_domain_stop.call_count)
        platform._force_kill_domain_process.assert_called_once_with(
            "lisa-test-0",
            4321,
        )
        self.assertIs(replacement_domain, node_context.domain)

    def test_fails_when_exact_domain_process_survives_sigkill(self) -> None:
        ch_platform_module = _load_ch_platform_module()
        platform = object.__new__(ch_platform_module.CloudHypervisorPlatform)
        platform._run_bounded_domain_stop = MagicMock(
            return_value=self._command_result(124)
        )
        platform._find_domain_process_id = MagicMock(return_value=4321)
        platform._capture_domain_process_diagnostics = MagicMock()
        platform._force_kill_domain_process = MagicMock(
            return_value=self._command_result(124)
        )

        node_context = MagicMock(
            vm_name="lisa-test-0",
            passthrough_devices=[MagicMock()],
            domain=MagicMock(),
        )

        with self.assertRaises(ch_platform_module.CloudHypervisorDomainStopError):
            platform._stop_domain(node_context, MagicMock())

        self.assertTrue(node_context.domain_stop_failed)
        self.assertEqual(
            2,
            platform._capture_domain_process_diagnostics.call_count,
        )

        platform._run_bounded_domain_stop.reset_mock()
        with self.assertRaises(ch_platform_module.CloudHypervisorDomainStopError):
            platform._stop_domain(node_context, MagicMock())
        platform._run_bounded_domain_stop.assert_not_called()

    def test_fails_if_console_stream_does_not_close_for_restart(self) -> None:
        ch_platform_module = _load_ch_platform_module()
        platform = object.__new__(ch_platform_module.CloudHypervisorPlatform)
        platform._create_domain_and_attach_logger = MagicMock()

        domain = MagicMock()
        domain.isActive.return_value = False
        console_logger = MagicMock()
        console_logger.wait_for_close.return_value = False
        console_logger.close.return_value = False
        node_context = MagicMock(
            vm_name="lisa-test-0",
            domain=domain,
            console_logger=console_logger,
        )
        node = MagicMock()
        node.get_context.return_value = node_context

        with self.assertRaises(ch_platform_module.CloudHypervisorDomainStopError):
            platform.restart_domain_and_attach_logger(node)

        platform._create_domain_and_attach_logger.assert_not_called()

    def test_waiting_start_stop_uses_platform_domain_stop(self) -> None:
        _load_ch_platform_module()
        start_stop_module = importlib.import_module(
            "lisa.sut_orchestrator.libvirt.start_stop"
        )
        platform_interface_module = importlib.import_module(
            "lisa.sut_orchestrator.libvirt.platform_interface"
        )
        start_stop = object.__new__(start_stop_module.StartStop)
        start_stop._platform = MagicMock(
            spec=platform_interface_module.IBaseLibvirtPlatform
        )
        start_stop._node = MagicMock()
        start_stop._node.get_context.return_value = MagicMock(domain=MagicMock())

        start_stop._stop(wait=True)

        start_stop._platform.stop_domain.assert_called_once_with(start_stop._node)
