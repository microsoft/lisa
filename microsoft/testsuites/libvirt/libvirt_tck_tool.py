# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import xml.etree.ElementTree as ETree
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, List, Type, cast

from assertpy.assertpy import assert_that

from lisa import Environment, notifier
from lisa.executable import Tool
from lisa.messages import CommunityTestMessage, TestStatus, create_test_result_message
from lisa.operating_system import Posix
from lisa.testsuite import TestResult
from lisa.tools import Git


@dataclass
class LibvirtTckTestResult:
    name: str = ""
    status: TestStatus = TestStatus.QUEUED


class LibvirtTck(Tool):
    TIME_OUT = 3600

    # The failures in these tests need to be investigated and fixed. Until then, treat
    # them as expected failures.
    EXPECTED_FAILURES = [
        "100-apply-verify-host_t",
        "220-no-ip-spoofing_t",
        "230-no-mac-broadcast_t",
    ]

    repo = "https://gitlab.com/libvirt/libvirt-tck.git"
    deps = [
        "expat-devel",
        "gcc",
        "libguestfs-tools",
        "libsys-virt-perl",
        "libtest-xml-perl",
        "libvirt-daemon-system",
        "libvirt-dev",
        "make",
        "perl",
        "qemu-kvm",
        "qemu-system-x86",
    ]

    repo_root: PurePath

    @property
    def command(self) -> str:
        return "libvirt-tck"

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git]

    def run_tests(
        self,
        test_result: TestResult,
        environment: Environment,
        log_path: Path,
    ) -> None:
        result = self.run(
            "--force --format junit -a results.tar.gz",
            timeout=self.TIME_OUT,
            force_run=True,
            cwd=self.repo_root,
            sudo=True,
            shell=True,
        )

        results = self._extract_test_results(result.stdout)
        failures = [r.name for r in results if r.status == TestStatus.FAILED]
        expected_fails = [r.name for r in results if r.status == TestStatus.ATTEMPTED]
        if not failures and not expected_fails:
            result.assert_exit_code()

        for r in results:
            self._send_community_test_msg(
                test_result.id_,
                environment,
                r.name,
                r.status,
            )

        self.node.shell.copy_back(
            self.repo_root / "results.tar.gz",
            log_path / "libvirt_tck_results.tar.gz",
        )
        assert_that(failures, f"Unexpected failures: {failures}").is_empty()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        tool_path = self.get_tool_path(use_global=True)
        self.repo_root = tool_path / "libvirt-tck"

    def _install_dep(self) -> None:
        posix_os: Posix = cast(Posix, self.node.os)
        git = self.node.tools[Git]
        git.clone(self.repo, self.get_tool_path(use_global=True), fail_on_exists=False)

        # install dependency packages
        for package in list(self.deps):
            if posix_os.is_package_in_repo(package):
                posix_os.install_packages(package)

    def _install(self) -> bool:
        self._install_dep()

        modules_to_install = " ".join(
            [
                "Module::Build",
                "IO::Interface::Simple",
                "Net::OpenSSH",
            ]
        )
        self.node.execute(
            f"PERL_MM_USE_DEFAULT=1 cpan install {modules_to_install}",
            sudo=True,
            shell=True,
            timeout=self.TIME_OUT,
        )
        self.node.execute("perl Build.PL", cwd=self.repo_root, expected_exit_code=0)
        self.node.execute(
            "./Build installdeps",
            cwd=self.repo_root,
            sudo=True,
            expected_exit_code=0,
            timeout=self.TIME_OUT,
        )
        self.node.execute(
            "./Build install", cwd=self.repo_root, sudo=True, expected_exit_code=0
        )

        return self._check_exists()

    def _is_expected_failure(self, name: str) -> bool:
        # The test name in the output appears with its full path. Whereas the
        # self.EXPECTED_FAILURES contain just the test names. That's why
        # endswith() is used here.
        return len([f for f in self.EXPECTED_FAILURES if name.endswith(f)]) > 0

    def _extract_test_results(self, output: str) -> List[LibvirtTckTestResult]:
        results: List[LibvirtTckTestResult] = []

        # output follows the JUnit XML schema
        testsuites = ETree.fromstring(output)
        for testsuite in testsuites:
            result = LibvirtTckTestResult()

            result.name = testsuite.attrib["name"]
            skipped = int(testsuite.attrib["tests"]) == 0
            failed = int(testsuite.attrib["failures"]) > 0
            if failed:
                if self._is_expected_failure(result.name):
                    result.status = TestStatus.ATTEMPTED
                else:
                    result.status = TestStatus.FAILED
            elif skipped:
                result.status = TestStatus.SKIPPED
            else:
                result.status = TestStatus.PASSED

            results.append(result)

        return results

    def _send_community_test_msg(
        self,
        test_id: str,
        environment: Environment,
        test_name: str,
        test_status: TestStatus,
    ) -> None:
        community_msg = create_test_result_message(
            CommunityTestMessage,
            test_id,
            environment,
            test_name,
            test_status,
        )

        notifier.notify(community_msg)
