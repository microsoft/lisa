# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase

from lisa.microsoft.testsuites.device_passthrough.storage_tests import (
    StoragePassthroughPerfTests,
    _get_disk_safety_issues,
    _get_guest_pci_bdf_from_domain_xml,
)
from lisa.tools.lsblk import DiskInfo, PartitionInfo
from lisa.util import LisaException


class StoragePassthroughTestCase(TestCase):
    def test_resolves_guest_bdf_for_assigned_host_device(self) -> None:
        domain_xml = """
            <domain>
              <devices>
                <hostdev mode="subsystem" type="pci" managed="yes">
                  <source>
                    <address domain="0x0000" bus="0x04" slot="0x00"
                             function="0x0" />
                  </source>
                  <address type="pci" domain="0x0000" bus="0x06"
                           slot="0x00" function="0x0" />
                </hostdev>
              </devices>
            </domain>
        """

        guest_bdf = _get_guest_pci_bdf_from_domain_xml(domain_xml, "0000:04:00.0")

        self.assertEqual("0000:06:00.0", guest_bdf)

    def test_rejects_missing_guest_address(self) -> None:
        domain_xml = """
            <domain>
              <devices>
                <hostdev mode="subsystem" type="pci" managed="yes">
                  <source>
                    <address domain="0x0000" bus="0x04" slot="0x00"
                             function="0x0" />
                  </source>
                </hostdev>
              </devices>
            </domain>
        """

        with self.assertRaisesRegex(
            LisaException, "does not expose a guest PCI address"
        ):
            _get_guest_pci_bdf_from_domain_xml(domain_xml, "0000:04:00.0")

    def test_rejects_ambiguous_guest_addresses(self) -> None:
        host_device = """
            <hostdev mode="subsystem" type="pci" managed="yes">
              <source>
                <address domain="0x0000" bus="0x04" slot="0x00"
                         function="0x0" />
              </source>
              <address type="pci" domain="0x0000" bus="0x06"
                       slot="0x00" function="0x0" />
            </hostdev>
        """
        domain_xml = f"<domain><devices>{host_device}{host_device}</devices></domain>"

        with self.assertRaisesRegex(LisaException, "found 2"):
            _get_guest_pci_bdf_from_domain_xml(domain_xml, "0000:04:00.0")

    def test_rejects_unmatched_host_device(self) -> None:
        domain_xml = "<domain><devices /></domain>"

        with self.assertRaisesRegex(LisaException, "found 0"):
            _get_guest_pci_bdf_from_domain_xml(domain_xml, "0000:04:00.0")

    def test_ignores_non_pci_host_device(self) -> None:
        domain_xml = """
            <domain>
              <devices>
                <hostdev mode="subsystem" type="usb" managed="yes">
                  <source>
                    <address domain="0x0000" bus="0x04" slot="0x00"
                             function="0x0" />
                  </source>
                  <address domain="0x0000" bus="0x06" slot="0x00"
                           function="0x0" />
                </hostdev>
              </devices>
            </domain>
        """

        with self.assertRaisesRegex(LisaException, "found 0"):
            _get_guest_pci_bdf_from_domain_xml(domain_xml, "0000:04:00.0")

    def test_rejects_root_disk(self) -> None:
        disk = DiskInfo(
            name="nvme0n1",
            mountpoint="",
            partitions=[
                PartitionInfo(
                    name="nvme0n1p1",
                    mountpoint="/",
                    dev_type="part",
                )
            ],
        )

        issues = _get_disk_safety_issues(disk, [], [])

        self.assertIn("backs the root or boot filesystem", issues)

    def test_rejects_mounted_and_logical_disk(self) -> None:
        logical_device = PartitionInfo(
            name="dm-0",
            mountpoint="/data",
            dev_type="crypt",
        )
        partition = PartitionInfo(
            name="nvme1n1p1",
            mountpoint="",
            dev_type="part",
            logical_devices=[logical_device],
        )
        disk = DiskInfo(
            name="nvme1n1",
            mountpoint="",
            partitions=[partition],
        )

        issues = _get_disk_safety_issues(disk, [], [])

        self.assertIn("is mounted or has mounted child devices", issues)
        self.assertIn("has unsafe logical block relationships: ['crypt']", issues)

    def test_rejects_swap_and_holders(self) -> None:
        partition = PartitionInfo(
            name="nvme1n1p1",
            mountpoint="",
            dev_type="part",
        )
        disk = DiskInfo(
            name="nvme1n1",
            mountpoint="",
            partitions=[partition],
        )

        issues = _get_disk_safety_issues(
            disk,
            ["/dev/nvme1n1p1"],
            ["/sys/class/block/nvme1n1/holders/dm-0"],
        )

        self.assertTrue(any(issue.startswith("is used for swap") for issue in issues))
        self.assertTrue(
            any(issue.startswith("has active block holders") for issue in issues)
        )

    def test_rejects_inactive_swap_signature(self) -> None:
        disk = DiskInfo(name="nvme1n1", mountpoint="", fstype="swap")

        issues = _get_disk_safety_issues(disk, [], [])

        self.assertIn("is used for swap", issues)

    def test_accepts_unused_namespace(self) -> None:
        disk = DiskInfo(name="nvme1n1", mountpoint="")

        issues = _get_disk_safety_issues(disk, [], [])

        self.assertEqual([], issues)

    def test_rejects_unbounded_fio_configuration(self) -> None:
        with self.assertRaisesRegex(LisaException, "runtime"):
            StoragePassthroughPerfTests._get_fio_testcases(
                {"fio_testcase_list": [{"time": 301}]}
            )

    def test_rejects_invalid_num_jobs_range(self) -> None:
        with self.assertRaisesRegex(LisaException, "Invalid FIO job parameters"):
            StoragePassthroughPerfTests._get_num_jobs(4, 2, 8)
