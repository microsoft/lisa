# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import MagicMock

from lisa.operating_system import CBLMariner, Debian, Ubuntu
from lisa.tools.stress_ng import StressNg


class StressNgTestCase(TestCase):
    def test_debian_build_requires_libc_headers(self) -> None:
        for distro in (Debian, Ubuntu):
            with self.subTest(distro=distro.__name__):
                tool = StressNg.__new__(StressNg)
                tool.node = MagicMock()
                tool.node.os = MagicMock(spec=distro)

                tool._install_required_packages()

                tool.node.os.install_packages.assert_called_once_with(
                    ["libc6-dev", "libapparmor-dev"]
                )

    def test_mariner_build_packages_are_unchanged(self) -> None:
        tool = StressNg.__new__(StressNg)
        tool.node = MagicMock()
        tool.node.os = MagicMock(spec=CBLMariner)

        tool._install_required_packages()

        tool.node.os.install_packages.assert_called_once_with(
            [
                "gcc",
                "glibc-devel",
                "kernel-headers",
                "binutils",
                "make",
                "libapparmor-devel",
            ]
        )
