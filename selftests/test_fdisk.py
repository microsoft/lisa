# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import MagicMock, Mock

from lisa.tools.fdisk import Fdisk
from lisa.util import LisaException


class FdiskTestCase(TestCase):
    def setUp(self) -> None:
        self.fdisk = Fdisk.__new__(Fdisk)
        self.node = MagicMock()
        self.fdisk.node = self.node

    def test_make_partition_ignores_sibling_nvme_namespaces(self) -> None:
        self.node.execute.side_effect = [
            Mock(stdout=""),
            Mock(
                stdout=(
                    "brw-rw---- 1 root disk 259, 18 Sep 12 16:40 /dev/nvme1n18\n"
                    "brw-rw---- 1 root disk 259, 66 Sep 12 16:39 /dev/nvme1n18p1\n"
                    "brw-rw---- 1 root disk 259, 65 Sep 12 16:39 /dev/nvme1n1p1\n"
                )
            ),
        ]

        self.assertEqual(
            self.fdisk.make_partition("/dev/nvme1n1", format_=False),
            "/dev/nvme1n1p1",
        )

    def test_make_partition_fails_when_only_sibling_namespaces_exist(self) -> None:
        self.node.execute.side_effect = [
            Mock(stdout=""),
            Mock(stdout="/dev/nvme1n18\n/dev/nvme1n18p1\n"),
        ]

        with self.assertRaisesRegex(LisaException, "fail to find partition"):
            self.fdisk.make_partition("/dev/nvme1n1", format_=False)

    def test_partition_discovery_matches_complete_partition_names(self) -> None:
        for disk_name, separator, sibling in (
            ("/dev/nvme1n1", "p", "/dev/nvme1n18p1"),
            ("/dev/sdc", "", "/dev/sdca1"),
            ("/dev/xvdb", "", "/dev/xvdba1"),
        ):
            with self.subTest(disk_name=disk_name):
                first = f"{disk_name}{separator}1"
                twelfth = f"{disk_name}{separator}12"
                self.node.execute.return_value = Mock(
                    stdout="\n".join(
                        [
                            disk_name,
                            sibling,
                            f"prefix{first}",
                            f"{first}suffix",
                            first,
                            twelfth,
                        ]
                    )
                )

                self.assertEqual(
                    self.fdisk._get_partitions(disk_name), [first, twelfth]
                )
