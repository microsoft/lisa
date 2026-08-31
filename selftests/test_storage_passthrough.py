# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import sys
from types import ModuleType
from typing import Any, cast
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.microsoft.testsuites.device_passthrough.storage_tests import (
    StoragePassthroughPerfTests,
    _get_disk_safety_issues,
    _get_fio_testcases,
    _get_guest_pci_bdf_from_domain_xml,
    _get_num_jobs,
)
from lisa.microsoft.testsuites.performance.common import perf_disk
from lisa.sut_orchestrator.util.schema import HostDevicePoolType
from lisa.tools import Cat, Ls, Lspci
from lisa.tools.lsblk import DiskInfo, PartitionInfo
from lisa.util import LisaException


class StoragePassthroughTestCase(TestCase):
    def test_exposes_only_focused_passthrough_test_cases(self) -> None:
        self.assertTrue(
            hasattr(
                StoragePassthroughPerfTests,
                "verify_storage_passthrough_nvme_visible",
            )
        )
        self.assertTrue(
            hasattr(
                StoragePassthroughPerfTests,
                "perf_storage_passthrough_fio_randread",
            )
        )
        self.assertTrue(
            hasattr(
                StoragePassthroughPerfTests,
                "perf_storage_passthrough_fio_randwrite",
            )
        )
        self.assertFalse(
            hasattr(
                StoragePassthroughPerfTests,
                "perf_storage_passthrough_fio_test",
            )
        )

    def test_perf_disk_runs_only_requested_fio_mode(self) -> None:
        node = MagicMock()
        fio = MagicMock()
        node.tools.__getitem__.return_value = fio
        fio.create_performance_messages.return_value = []

        perf_disk(
            node=node,
            start_iodepth=1,
            max_iodepth=4,
            filename="passthrough_nvme_test",
            core_count=1,
            disk_count=1,
            test_result=MagicMock(),
            num_jobs=[1, 1, 1],
            fio_modes=["randread"],
        )

        self.assertEqual(3, fio.launch.call_count)
        self.assertEqual(
            {"randread"},
            {call.kwargs["mode"] for call in fio.launch.call_args_list},
        )

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

    def test_allows_missing_guest_address(self) -> None:
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

        guest_bdf = _get_guest_pci_bdf_from_domain_xml(domain_xml, "0000:04:00.0")

        self.assertIsNone(guest_bdf)

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

    def test_resolves_unique_guest_nvme_by_pci_ids(self) -> None:
        node = MagicMock()
        expected_device = MagicMock(
            slot="0000:06:00.0", vendor_id="144d", device_id="a821"
        )
        node.tools.__getitem__.return_value.get_devices_by_type.return_value = [
            expected_device
        ]

        suite_class = cast(Any, StoragePassthroughPerfTests).__wrapped__
        device = suite_class._get_guest_nvme_device_by_pci_ids(node, ("144d", "a821"))

        self.assertIs(expected_device, device)

    def test_rejects_missing_guest_nvme_pci_ids(self) -> None:
        node = MagicMock()
        node.tools.__getitem__.return_value.get_devices_by_type.return_value = []

        suite_class = cast(Any, StoragePassthroughPerfTests).__wrapped__
        with self.assertRaisesRegex(LisaException, "found 0"):
            suite_class._get_guest_nvme_device_by_pci_ids(node, ("144d", "a821"))

    def test_rejects_ambiguous_guest_nvme_pci_ids(self) -> None:
        node = MagicMock()
        node.tools.__getitem__.return_value.get_devices_by_type.return_value = [
            MagicMock(slot="0000:06:00.0", vendor_id="144d", device_id="a821"),
            MagicMock(slot="0000:07:00.0", vendor_id="144d", device_id="a821"),
        ]

        suite_class = cast(Any, StoragePassthroughPerfTests).__wrapped__
        with self.assertRaisesRegex(LisaException, "found 2"):
            suite_class._get_guest_nvme_device_by_pci_ids(node, ("144d", "a821"))

    def test_resolves_nvme_when_domain_xml_omits_guest_address(self) -> None:
        domain_xml = """
            <domain>
              <devices>
                <hostdev mode="subsystem" type="pci" managed="yes">
                  <source>
                    <address domain="0x0000" bus="0x3b" slot="0x00"
                             function="0x0" />
                  </source>
                </hostdev>
              </devices>
            </domain>
        """
        assigned_device = MagicMock(domain="0000", bus="3b", slot="00", function="0")
        passthrough_context = MagicMock(
            pool_type=HostDevicePoolType.PCI_NVME,
            requested_count=1,
            device_list=[assigned_device],
        )
        node_context = MagicMock(
            passthrough_devices=[passthrough_context], domain=MagicMock()
        )
        node_context.domain.XMLDesc.return_value = domain_xml

        host_lspci = MagicMock()
        host_lspci.get_devices_by_type.return_value = [MagicMock(slot="0000:3b:00.0")]
        host_cat = MagicMock()
        host_cat.read.side_effect = lambda path, **_: (
            "0x144d" if path.endswith("/vendor") else "0xa821"
        )
        host_node = MagicMock()
        host_node.tools.__getitem__.side_effect = {
            Lspci: host_lspci,
            Cat: host_cat,
        }.__getitem__

        guest_lspci = MagicMock()
        guest_lspci.get_devices_by_type.return_value = [
            MagicMock(slot="0000:06:00.0", vendor_id="144d", device_id="a821")
        ]
        guest_ls = MagicMock()
        guest_ls.list.side_effect = [
            ["/sys/bus/pci/devices/0000:06:00.0/nvme/nvme0"],
            ["/sys/class/nvme/nvme0/nvme0n1"],
        ]
        guest_ls.path_exists.return_value = True
        node = MagicMock()
        node.tools.__getitem__.side_effect = {
            Lspci: guest_lspci,
            Ls: guest_ls,
        }.__getitem__

        environment = MagicMock()
        environment.platform.host_node = host_node
        suite_class = cast(Any, StoragePassthroughPerfTests).__wrapped__
        suite = object.__new__(suite_class)
        context_module = ModuleType("lisa.sut_orchestrator.libvirt.context")
        context_module.__dict__["get_node_context"] = MagicMock(
            return_value=node_context
        )
        with patch.dict(
            sys.modules,
            {"lisa.sut_orchestrator.libvirt.context": context_module},
        ):
            resolved = suite._resolve_passthrough_nvme_namespace(
                node, environment, MagicMock()
            )

        self.assertEqual(("0000:3b:00.0", "0000:06:00.0", "/dev/nvme0n1"), resolved)

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
            _get_fio_testcases({"fio_testcase_list": [{"time": 301}]})

    def test_rejects_invalid_num_jobs_range(self) -> None:
        with self.assertRaisesRegex(LisaException, "Invalid FIO job parameters"):
            _get_num_jobs(4, 2, 8)
