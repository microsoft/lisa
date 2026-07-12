# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import shlex
from types import SimpleNamespace
from typing import Any, cast
from unittest import TestCase
from unittest.mock import MagicMock

from lisa.tools.openvmm import OpenVmm, OpenVmmLaunchConfig


class OpenVmmToolTestCase(TestCase):
    def test_build_command_uses_pci_devices(self) -> None:
        openvmm = OpenVmm(cast(Any, SimpleNamespace(log=MagicMock())))
        openvmm.set_binary_path("/usr/local/bin/openvmm")

        command = openvmm.build_command(
            OpenVmmLaunchConfig(
                uefi_firmware_path="/var/tmp/MSVM.fd",
                hypervisor="kvm",
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
                "--hv",
                "--hypervisor",
                "kvm",
                "--processors",
                "4",
                "--memory",
                "8192MB",
                "--uefi",
                "--uefi-firmware",
                "/var/tmp/MSVM.fd",
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
