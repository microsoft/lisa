# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import TestCase
from unittest.mock import MagicMock

from lisa.microsoft.testsuites.openvmm.openvmm_tests import (
    OpenVmmUpstreamTestSuite,
    _get_openvmm_tests_type,
)
from lisa.microsoft.testsuites.openvmm.openvmm_tests_tool import _JUnitSummary
from lisa.operating_system import Ubuntu
from lisa.tools import Ls, Uname
from lisa.tools.usermod import Usermod
from lisa.util import SkippedException


class OpenVmmTestsSuiteTestCase(TestCase):
    _suite_type = cast(Any, OpenVmmUpstreamTestSuite).__wrapped__

    def _create_host(self, kernel_version_raw: str = "6.8.0-generic") -> MagicMock:
        uname = MagicMock()
        uname.get_linux_information.return_value = SimpleNamespace(
            hardware_platform="x86_64",
            kernel_version_raw=kernel_version_raw,
        )
        host = MagicMock()
        host.tools = {Uname: uname}
        return host

    def test_ensure_vmm_tests_supported_raises_when_mshv_is_not_accessible(
        self,
    ) -> None:
        suite = self._suite_type.__new__(self._suite_type)
        uname = MagicMock()
        uname.get_linux_information.return_value = SimpleNamespace(
            hardware_platform="x86_64"
        )
        ls = MagicMock()
        ls.path_exists.side_effect = lambda path, sudo: path in (
            "/dev/kvm",
            "/dev/mshv",
        )
        usermod = MagicMock()
        host = MagicMock()
        host.tools = {Uname: uname, Ls: ls, Usermod: usermod}
        host.execute.side_effect = [
            SimpleNamespace(exit_code=0),
            SimpleNamespace(exit_code=1),
            SimpleNamespace(exit_code=1),
        ]

        with self.assertRaises(SkippedException) as context:
            suite._ensure_vmm_tests_supported(host)

        self.assertIn("detect /dev/mshv before /dev/kvm", str(context.exception))
        self.assertEqual(usermod.add_user_to_group.call_count, 2)

    def test_ensure_vmm_tests_supported_accepts_accessible_mshv(self) -> None:
        suite = self._suite_type.__new__(self._suite_type)
        uname = MagicMock()
        uname.get_linux_information.return_value = SimpleNamespace(
            hardware_platform="x86_64"
        )
        ls = MagicMock()
        ls.path_exists.side_effect = lambda path, sudo: path == "/dev/mshv"
        usermod = MagicMock()
        host = MagicMock()
        host.tools = {Uname: uname, Ls: ls, Usermod: usermod}
        host.execute.return_value = SimpleNamespace(exit_code=0)

        suite._ensure_vmm_tests_supported(host)

        usermod.add_user_to_group.assert_called_once_with("mshv", sudo=True)

    def test_ensure_vmm_tests_supported_uses_mshv_group_wrapper(self) -> None:
        suite = self._suite_type.__new__(self._suite_type)
        uname = MagicMock()
        uname.get_linux_information.return_value = SimpleNamespace(
            hardware_platform="x86_64"
        )
        ls = MagicMock()
        ls.path_exists.side_effect = lambda path, sudo: path == "/dev/mshv"
        usermod = MagicMock()
        host = MagicMock()
        host.tools = {Uname: uname, Ls: ls, Usermod: usermod}
        host.execute.side_effect = [
            SimpleNamespace(exit_code=1),
            SimpleNamespace(exit_code=0),
        ]

        result = suite._ensure_vmm_tests_supported(host)

        self.assertEqual(result, "mshv")

    def test_ensure_vmm_tests_supported_raises_when_no_backend_is_accessible(
        self,
    ) -> None:
        suite = self._suite_type.__new__(self._suite_type)
        uname = MagicMock()
        uname.get_linux_information.return_value = SimpleNamespace(
            hardware_platform="x86_64"
        )
        ls = MagicMock()
        ls.path_exists.side_effect = lambda path, sudo: path == "/dev/kvm"
        usermod = MagicMock()
        host = MagicMock()
        host.tools = {Uname: uname, Ls: ls, Usermod: usermod}
        host.execute.return_value = SimpleNamespace(exit_code=1)

        with self.assertRaises(SkippedException) as context:
            suite._ensure_vmm_tests_supported(host)

        self.assertIn("cannot open either device", str(context.exception))

    def test_compose_vmm_tests_filter_excludes_pcat_on_native_linux(self) -> None:
        suite = self._suite_type.__new__(self._suite_type)

        result = suite._compose_vmm_tests_filter(
            {"openvmm_vmm_tests_guest_os": "linux"},
            self._create_host(),
        )

        self.assertEqual(
            result,
            "((test(linux_direct) | test(ubuntu) | test(alpine))) & (!test(pcat))",
        )

    def test_compose_vmm_tests_filter_keeps_pcat_on_wsl(self) -> None:
        suite = self._suite_type.__new__(self._suite_type)

        result = suite._compose_vmm_tests_filter(
            {"openvmm_vmm_tests_guest_os": "linux"},
            self._create_host("6.6.87.2-microsoft-standard-WSL2"),
        )

        self.assertEqual(result, "(test(linux_direct) | test(ubuntu) | test(alpine))")

    def test_before_case_initializes_host_before_os_check(self) -> None:
        suite = self._suite_type.__new__(self._suite_type)
        host = MagicMock()
        tool = MagicMock()
        openvmm_tests_type = _get_openvmm_tests_type()
        host.tools = {openvmm_tests_type: tool}

        def initialize_host() -> None:
            host.os = object.__new__(Ubuntu)

        host.initialize.side_effect = initialize_host

        suite.before_case(
            MagicMock(),
            node=host,
            variables={"openvmm_tests_repo": "https://example.com/openvmm.git"},
        )

        host.initialize.assert_called_once()
        self.assertEqual("https://example.com/openvmm.git", tool.repo_url)

    def test_verify_openvmm_upstream_vmm_tests_sets_multiline_summary(self) -> None:
        suite = self._suite_type.__new__(self._suite_type)
        host = MagicMock()
        node = MagicMock()
        node.parent = host
        tool = MagicMock()
        tool.run_vmm_tests.return_value = _JUnitSummary(
            tests=3,
            passed=3,
            skipped=45,
            passed_tests=[
                "multiarch::openvmm_uefi_x64_ubuntu_2404_server_x64_boot",
                "multiarch::ic::openvmm_uefi_x64_ubuntu_2504_server_x64_timesync_ic",
                "multiarch::vmgs::openvmm_uefi_x64_ubuntu_2504_server_x64_default_boot",
            ],
        )
        tool.format_run_summary.return_value = (
            "3 tests run: 3 passed, 0 failed, 45 skipped\n"
            "Passed tests:\n"
            "  - multiarch::openvmm_uefi_x64_ubuntu_2404_server_x64_boot"
        )
        host.tools = {_get_openvmm_tests_type(): tool}

        result = SimpleNamespace(message="")

        suite._get_host_node = MagicMock(return_value=host)
        suite._ensure_vmm_tests_supported = MagicMock(return_value="")
        suite._is_truthy = MagicMock(return_value=True)
        suite._compose_vmm_tests_filter = MagicMock(return_value="")

        suite.verify_openvmm_upstream_vmm_tests(
            node=node,
            log_path=Path("."),
            result=result,
            variables={},
        )

        self.assertIn("upstream vmm_tests:", result.message)
        self.assertIn("3 tests run: 3 passed, 0 failed, 45 skipped", result.message)
