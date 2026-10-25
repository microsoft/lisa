# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import MagicMock

from lisa.operating_system import CBLMariner, Debian
from lisa.tools.stress_ng import StressNg
from lisa.util import LisaException


class StressNgTestCase(TestCase):
    def setUp(self) -> None:
        self.os = MagicMock(spec=CBLMariner)
        self.tool = StressNg.__new__(StressNg)
        self.tool.node = MagicMock(os=self.os)
        self.log = MagicMock()
        self.tool._log = self.log
        self.required_packages = [
            "gcc",
            "glibc-devel",
            "kernel-headers",
            "binutils",
            "make",
        ]

    def test_source_dependencies_without_apparmor(self) -> None:
        self.os.is_package_in_repo.return_value = False

        self.tool._install_required_packages()

        self.os.is_package_in_repo.assert_called_once_with("libapparmor-devel")
        self.os.install_packages.assert_called_once_with(self.required_packages)
        self.log.info.assert_called_once()
        self.assertIn("AppArmor", self.log.info.call_args.args[0])

    def test_source_dependencies_with_apparmor(self) -> None:
        self.os.is_package_in_repo.return_value = True

        self.tool._install_required_packages()

        self.os.install_packages.assert_called_once_with(
            self.required_packages + ["libapparmor-devel"]
        )
        self.log.info.assert_not_called()

    def test_required_package_install_failure_propagates(self) -> None:
        self.os.is_package_in_repo.return_value = False
        self.os.install_packages.side_effect = LisaException("required package failed")

        with self.assertRaisesRegex(LisaException, "required package failed"):
            self.tool._install_required_packages()

    def test_available_package_install_failure_propagates(self) -> None:
        self.os.is_package_in_repo.return_value = True
        self.os.install_packages.side_effect = LisaException("transaction failed")

        with self.assertRaisesRegex(LisaException, "transaction failed"):
            self.tool._install_required_packages()

    def test_repository_query_failure_propagates(self) -> None:
        self.os.is_package_in_repo.side_effect = LisaException("repository failed")

        with self.assertRaisesRegex(LisaException, "repository failed"):
            self.tool._install_required_packages()

        self.os.install_packages.assert_not_called()

    def test_debian_dependencies_unchanged(self) -> None:
        debian = MagicMock(spec=Debian)
        self.tool.node.os = debian

        self.tool._install_required_packages()

        debian.install_packages.assert_called_once_with("libapparmor-dev")
        debian.is_package_in_repo.assert_not_called()
