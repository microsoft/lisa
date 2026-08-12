# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import MagicMock

from lisa.tools import Zstd


class ZstdTestCase(TestCase):
    def test_install_uses_zstd_package(self) -> None:
        zstd = Zstd.__new__(Zstd)
        zstd.node = MagicMock()
        zstd._check_exists = MagicMock(return_value=True)

        self.assertTrue(zstd._install())

        zstd.node.os.install_packages.assert_called_once_with("zstd")

    def test_decompress_runs_expected_command_and_returns_output_path(self) -> None:
        zstd = Zstd.__new__(Zstd)
        zstd.run = MagicMock()

        output_file = zstd.decompress("/tmp/lisa work/hv_netvsc.ko.zst")

        self.assertEqual("/tmp/lisa work/hv_netvsc.ko", output_file)
        zstd.run.assert_called_once_with(
            "-d -f -o '/tmp/lisa work/hv_netvsc.ko' "
            "'/tmp/lisa work/hv_netvsc.ko.zst'",
            shell=False,
            force_run=True,
            sudo=False,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Failed to decompress /tmp/lisa work/hv_netvsc.ko.zst "
                "to /tmp/lisa work/hv_netvsc.ko."
            ),
        )
