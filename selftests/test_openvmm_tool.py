# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase

from lisa.tools.openvmm import (
    OPENVMM_DISK_DEVICE_VIRTIO_BLK,
    OPENVMM_IOMMU_INTEL,
    OPENVMM_NETWORK_DEVICE_VIRTIO,
    OpenVmm,
    OpenVmmLaunchConfig,
)


class OpenVmmToolTestCase(TestCase):
    def _create_tool(self) -> OpenVmm:
        tool = OpenVmm.__new__(OpenVmm)
        tool.set_binary_path("openvmm")
        return tool

    def test_build_command_uses_default_devices(self) -> None:
        command = self._create_tool().build_command(
            OpenVmmLaunchConfig(
                uefi_firmware_path="/firmware/MSVM.fd",
                disk_img_path="/disks/guest.raw",
                network_mode="tap",
                tap_name="tap0",
                serial_path="/logs/console.log",
            )
        )

        self.assertIn("--vmbus-scsi id=lisa_scsi0", command)
        self.assertIn("--disk file:/disks/guest.raw,on=lisa_scsi0,lun=0", command)
        self.assertIn("--net tap:tap0", command)
        self.assertNotIn("--pcie-root-complex", command)
        self.assertNotIn("--virtio-blk", command)
        self.assertNotIn("--virtio-net", command)
        self.assertNotIn("queues=", command)

    def test_build_command_uses_virtio_devices_over_pcie(self) -> None:
        command = self._create_tool().build_command(
            OpenVmmLaunchConfig(
                uefi_firmware_path="/firmware/MSVM.fd",
                disk_img_path="/disks/guest.raw",
                disk_device=OPENVMM_DISK_DEVICE_VIRTIO_BLK,
                iommu=OPENVMM_IOMMU_INTEL,
                dvd_disk_paths=["/disks/cloud-init.iso"],
                network_mode="tap",
                network_device=OPENVMM_NETWORK_DEVICE_VIRTIO,
                network_queue_count=1,
                tap_name="tap0",
                serial_path="/logs/console.log",
            )
        )

        self.assertIn("--pcie-root-complex lisa_virtio_rc0", command)
        self.assertIn("--intel-vtd lisa_virtio_rc0", command)
        self.assertIn("--pcie-root-port lisa_virtio_rc0:lisa_virtio_disk", command)
        self.assertIn("--pcie-root-port lisa_virtio_rc0:lisa_virtio_net", command)
        self.assertIn(
            "--virtio-blk file:/disks/guest.raw,pcie_port=lisa_virtio_disk",
            command,
        )
        self.assertIn(
            "--virtio-net pcie_port=lisa_virtio_net:queues=1:tap:tap0", command
        )
        self.assertIn("--vmbus-scsi id=lisa_scsi0", command)
        self.assertIn(
            "--disk file:/disks/cloud-init.iso,on=lisa_scsi0,lun=1,dvd", command
        )
        self.assertNotIn("--disk file:/disks/guest.raw,on=lisa_scsi0,lun=0", command)
        self.assertNotIn("--net tap:tap0", command)
