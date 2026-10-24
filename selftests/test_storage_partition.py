# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict, Type, cast
from unittest import TestCase
from unittest.mock import MagicMock

from lisa.feature import Feature
from lisa.features.security_profile import (
    SecurityProfile,
    SecurityProfileSettings,
    SecurityProfileType,
)
from lisa.microsoft.testsuites.core.storage import Storage
from lisa.node import RemoteNode
from lisa.tools import Blkid, Cat, Dmesg, Mount
from lisa.tools.blkid import PartitionInfo
from lisa.tools.journalctl import Journalctl
from lisa.tools.mount import PartitionInfo as MountedPartitionInfo
from lisa.util import LisaException


class StoragePartitionTestCase(TestCase):
    def setUp(self) -> None:
        suite_class = cast(Any, Storage).__wrapped__
        self.suite = object.__new__(suite_class)
        self.node = MagicMock(spec=RemoteNode)
        self.node.features = MagicMock()
        self.node.tools = MagicMock()
        self.log = MagicMock()
        self.features: Dict[Type[Feature], MagicMock] = {}
        self.node.features.__getitem__.side_effect = self.features.__getitem__
        self.node.features.is_supported.side_effect = (
            lambda feature_type: feature_type in self.features
        )

        self.partition = PartitionInfo(
            name="/dev/vda1",
            label="cloudimg-rootfs",
            uuid="11111111-2222-3333-4444-555555555555",
            part_uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )
        self.mount = MagicMock(spec=Mount)
        self.mount.get_partition_info.return_value = [
            MountedPartitionInfo("/dev/vda1", "/", "ext4", [])
        ]
        self.blkid = MagicMock(spec=Blkid)
        self.blkid.get_partition_info_by_name.return_value = self.partition
        self.dmesg = MagicMock(spec=Dmesg)
        self.dmesg.run.return_value.stdout = (
            f"BOOT_IMAGE=/boot/vmlinuz root=UUID={self.partition.uuid}"
        )
        self.cat = MagicMock(spec=Cat)
        self.cat.run.return_value.stdout = (
            f"UUID={self.partition.uuid} / ext4 defaults 0 1"
        )
        self.journal = MagicMock(spec=Journalctl)
        self.journal.first_n_logs_from_boot.return_value = ""
        tools = {
            Mount: self.mount,
            Blkid: self.blkid,
            Dmesg: self.dmesg,
            Cat: self.cat,
            Journalctl: self.journal,
        }
        self.node.tools.__getitem__.side_effect = tools.__getitem__

    def test_identity_checks_run_without_cloud_features(self) -> None:
        self.suite.verify_os_partition_identifier(log=self.log, node=self.node)

        self.mount.get_partition_info.assert_called_once_with("/")
        self.blkid.get_partition_info_by_name.assert_called_once_with("/dev/vda1")

    def test_mismatched_boot_partition_fails(self) -> None:
        self.dmesg.run.return_value.stdout = (
            "BOOT_IMAGE=/boot/vmlinuz root=UUID=another-partition"
        )

        with self.assertRaisesRegex(LisaException, "dmesg/journalctl"):
            self.suite.verify_os_partition_identifier(log=self.log, node=self.node)

    def test_mismatched_fstab_partition_fails(self) -> None:
        self.cat.run.return_value.stdout = "UUID=another-partition / ext4 defaults 0 1"

        with self.assertRaisesRegex(LisaException, "present in fstab"):
            self.suite.verify_os_partition_identifier(log=self.log, node=self.node)

    def test_fstab_accepts_matching_root_identifiers(self) -> None:
        for source in (
            self.partition.name,
            f"UUID={self.partition.uuid}",
            f"PARTUUID={self.partition.part_uuid}",
            f"LABEL={self.partition.label}",
        ):
            with self.subTest(source=source):
                self.cat.run.return_value.stdout = (
                    f"{source}\t/\t ext4\tdiscard,errors=remount-ro\t0 1\n"
                    "LABEL=UEFI /boot/efi vfat umask=0077 0 1\n"
                )

                self.suite.verify_os_partition_identifier(log=self.log, node=self.node)

    def test_fstab_rejects_comments_other_mounts_and_wrong_labels(self) -> None:
        for entry in (
            f"# UUID={self.partition.uuid} / ext4 defaults 0 1",
            f"UUID={self.partition.uuid} /boot ext4 defaults 0 1",
            "LABEL=another-filesystem / ext4 defaults 0 1",
        ):
            with self.subTest(entry=entry):
                self.cat.run.return_value.stdout = entry

                with self.assertRaisesRegex(LisaException, "present in fstab"):
                    self.suite.verify_os_partition_identifier(
                        log=self.log, node=self.node
                    )

    def test_cvm_identity_checks_still_use_security_profile(self) -> None:
        profile = MagicMock(spec=SecurityProfile)
        profile.get_settings.return_value = SecurityProfileSettings(
            security_profile=SecurityProfileType.CVM
        )
        self.features[SecurityProfile] = profile
        self.dmesg.run.return_value.stdout = (
            f"snapd_recovery_mode={self.partition.label}"
        )

        self.suite.verify_os_partition_identifier(log=self.log, node=self.node)
