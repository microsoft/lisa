# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import shlex
from types import SimpleNamespace
from typing import Any, cast
from unittest import TestCase
from unittest.mock import MagicMock

from lisa.tools.openvmm import OpenVmm, OpenVmmLaunchConfig
from lisa.util import LisaException


class OpenVmmToolTestCase(TestCase):
    def test_build_command_uses_pci_devices(self) -> None:
        openvmm = OpenVmm(cast(Any, SimpleNamespace(log=MagicMock())))
        openvmm.set_binary_path("/usr/local/bin/openvmm")

        command = openvmm.build_command(
            OpenVmmLaunchConfig(
                uefi_firmware_path="/var/tmp/MSVM.fd",
                with_hv=False,
                hypervisor="kvm",
                vmgs_path="/var/tmp/openvmm.vmgs",
                create_vmgs=True,
                auto_restart_on_guest_reset=True,
                disk_img_path="/var/tmp/root.raw",
                dvd_disk_paths=["/var/tmp/cloud-init.iso"],
                processors=4,
                memory_mb=8192,
                network_mode="tap",
                tap_name="tap0",
                serial_mode="file",
                serial_path="/var/tmp/console.log",
                use_pci_devices=True,
            )
        )

        self.assertEqual(
            [
                "/usr/local/bin/openvmm",
                "--hypervisor",
                "kvm",
                "--processors",
                "4",
                "--memory",
                "8192MB",
                "--uefi",
                "--uefi-firmware",
                "/var/tmp/MSVM.fd",
                "--uefi-console-mode",
                "com1",
                "--vmgs",
                "file:/var/tmp/openvmm.vmgs;create=VMGS_DEFAULT,fmt-on-fail",
                "--guest-reset-action",
                "exit:42",
                "--guest-shutdown-action",
                "exit",
                "--no-vmbus",
                "--pcie-root-complex",
                "rc0",
                "--pcie-root-port",
                "rc0:disk",
                "--pcie-root-port",
                "rc0:dvd0",
                "--pcie-root-port",
                "rc0:net",
                "--nvme-pci",
                "id=nvme-disk,pcie_port=disk",
                "--disk",
                "file:/var/tmp/root.raw,on=nvme-disk",
                "--virtio-blk",
                "file:/var/tmp/cloud-init.iso,ro,pcie_port=dvd0",
                "--virtio-net",
                "pcie_port=net:tap:tap0",
                "--default-boot-always-attempt",
                "--com1",
                "file=/var/tmp/console.log",
            ],
            shlex.split(command),
        )

    def test_build_command_reuses_existing_vmgs(self) -> None:
        openvmm = OpenVmm(cast(Any, SimpleNamespace(log=MagicMock())))
        openvmm.set_binary_path("/usr/local/bin/openvmm")

        command = openvmm.build_command(
            OpenVmmLaunchConfig(
                uefi_firmware_path="/var/tmp/MSVM.fd",
                vmgs_path="/var/tmp/openvmm.vmgs",
                serial_path="/var/tmp/console.log",
            )
        )

        self.assertIn(
            "file:/var/tmp/openvmm.vmgs,fmt-on-fail",
            shlex.split(command),
        )
        self.assertNotIn("create=VMGS_DEFAULT", command)

    def test_auto_restart_supervisor_reuses_existing_vmgs(self) -> None:
        openvmm = OpenVmm(cast(Any, SimpleNamespace(log=MagicMock())))
        openvmm.set_binary_path("/usr/local/bin/openvmm")
        config = OpenVmmLaunchConfig(
            uefi_firmware_path="/var/tmp/MSVM.fd",
            hypervisor="kvm",
            vmgs_path="/var/tmp/openvmm.vmgs",
            create_vmgs=True,
            auto_restart_on_guest_reset=True,
            serial_path="/var/tmp/console.log",
            stdout_path="/var/tmp/launcher.log",
            stderr_path="/var/tmp/launcher.stderr.log",
        )

        command = openvmm.build_command(config)
        shell_command = openvmm._build_launch_shell_command(command, config)

        self.assertEqual(2, shell_command.count("create=VMGS_DEFAULT"))
        self.assertEqual(
            2,
            shell_command.count("file:/var/tmp/openvmm.vmgs,fmt-on-fail"),
        )
        self.assertIn('"$exit_code" -eq 42', shell_command)
        self.assertIn('"$restart_count" -lt 8', shell_command)
        self.assertIn("supervisor_pid", shell_command)
        self.assertIn("tail -f /dev/null >", shell_command)
        self.assertNotIn("| script -qefc", shell_command)
        self.assertIn("/var/tmp/launcher.log.feeder.pid", shell_command)

    def test_launch_failure_includes_launcher_logs_and_command(self) -> None:
        node = SimpleNamespace(
            log=MagicMock(),
            execute=MagicMock(
                side_effect=[
                    SimpleNamespace(
                        exit_code=1,
                        stdout="OpenVMM supervisor did not record a child PID.",
                        stderr="",
                    ),
                    SimpleNamespace(
                        exit_code=0,
                        stdout="launcher output",
                        stderr="",
                    ),
                    SimpleNamespace(
                        exit_code=0,
                        stdout="failed to open VFIO group",
                        stderr="",
                    ),
                ]
            ),
        )
        openvmm = OpenVmm(cast(Any, node))
        openvmm.set_binary_path("/usr/local/bin/openvmm")
        config = OpenVmmLaunchConfig(
            uefi_firmware_path="/var/tmp/MSVM.fd",
            serial_path="/var/tmp/console.log",
            stdout_path="/var/tmp/launcher.log",
            stderr_path="/var/tmp/launcher.stderr.log",
        )

        with self.assertRaises(LisaException) as error:
            openvmm.launch_vm(config, sudo=True)

        message = str(error.exception)
        self.assertIn("exit code: 1", message)
        self.assertIn("launcher stdout tail: launcher output", message)
        self.assertIn(
            "launcher stderr tail: failed to open VFIO group",
            message,
        )
        self.assertIn("command: /usr/local/bin/openvmm", message)

        log_tail_calls = node.execute.call_args_list[1:]
        self.assertEqual(2, len(log_tail_calls))
        self.assertTrue(all(call.kwargs["sudo"] for call in log_tail_calls))
