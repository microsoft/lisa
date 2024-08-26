# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, List, Type, cast

from assertpy import assert_that

from lisa.executable import Tool
from lisa.messages import TestStatus, send_sub_test_result_message
from lisa.operating_system import Posix
from lisa.testsuite import TestResult
from lisa.tools import Chmod, Git, Ls, Make
from lisa.util import LisaException, find_group_in_lines


@dataclass
class KvmUnitTestResult:
    name: str = ""
    status: TestStatus = TestStatus.QUEUED


class KvmUnitTests(Tool):
    # These tests take some time to finish executing. The default
    # timeout of 600 is not sufficient.
    TIME_OUT = 1200

    # TODO: These failures need to be investigated to figure out the exact
    # cause.
    EXPECTED_FAILURES = [
        "pmu_lbr",
        "svm_pause_filter",
        "vmx",
        "ept",
        "debug",
    ]

    cmd_path: PurePath
    repo_root: PurePath

    repo = "https://gitlab.com/kvm-unit-tests/kvm-unit-tests.git"
    deps = [
        "gcc",
        "make",
        "binutils",
        "qemu-kvm",
        "qemu-system-x86",
    ]

    @property
    def command(self) -> str:
        return str(self.cmd_path)

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git, Make]

    def run_tests(self, test_result: TestResult, failure_logs_path: Path) -> None:
        exec_result = self.run(
            "",
            timeout=self.TIME_OUT,
            sudo=True,
            force_run=True,
            cwd=self.repo_root,
            no_info_log=False,  # print out result of each test
        )

        results = self._parse_results(exec_result.stdout)
        if not results:
            self._save_all_logs(failure_logs_path)
            raise LisaException("Did not find any test results in stdout.")

        failed_tests = []
        for result in results:
            if result.status == TestStatus.FAILED:
                failed_tests.append(result.name)
            send_sub_test_result_message(
                test_result=test_result,
                test_case_name=result.name,
                test_status=result.status,
            )

        self._save_logs(failed_tests, failure_logs_path)
        assert_that(failed_tests, f"Unexpected failures: {failed_tests}").is_empty()

    def _parse_results(self, output: str) -> List[KvmUnitTestResult]:
        lines = output.split("\n")
        results: List[KvmUnitTestResult] = []

        # Each line is printed in this format:
        #
        # PASS kvm (<some additional info...>)
        # |    |
        # |    +-> test name
        # +-> test status (can also be FAIL or SKIP)
        #
        # For now, we don't do anything with the additional info in the
        # parantheses.
        line_regex = re.compile(
            r"(?P<status>PASS|SKIP|FAIL)\s+(?P<test_name>\S+)"
            r"(?:\s+\((?P<extra_info>[^)]+)\))?"
        )
        for line in lines:
            match = find_group_in_lines(lines=line.strip(), pattern=line_regex)
            if not match:
                continue

            result = KvmUnitTestResult()
            result.name = match.get("test_name", "")
            status = match.get("status", "")
            if status == "PASS":
                result.status = TestStatus.PASSED
            elif status == "FAIL":
                if result.name in self.EXPECTED_FAILURES:
                    result.status = TestStatus.ATTEMPTED
                else:
                    result.status = TestStatus.FAILED
            else:
                result.status = TestStatus.SKIPPED

            results.append(result)

        return results

    def _save_logs(self, test_names: List[str], log_path: Path) -> None:
        logs_dir = self.repo_root / "logs"
        self.node.execute(f"chmod a+x {str(logs_dir)}", shell=True, sudo=True)
        self.node.execute(f"chmod -R a+r {str(logs_dir)}", shell=True, sudo=True)
        for test_name in test_names:
            self.node.shell.copy_back(
                self.repo_root / "logs" / f"{test_name}.log",
                log_path / f"{test_name}.failure.log",
            )

    def _save_all_logs(self, log_path: Path) -> None:
        logs_dir = self.repo_root / "logs"
        self.node.tools[Chmod].chmod(
            permission="a+x",
            path=str(logs_dir),
            sudo=True,
        )
        self.node.tools[Chmod].update_folder(
            permission="a+r",
            path=str(logs_dir),
            sudo=True,
        )
        files = self.node.tools[Ls].list(str(logs_dir), sudo=True)
        for f in files:
            f_path = PurePath(f)
            self.node.shell.copy_back(
                f_path,
                log_path / f"{f_path.name}",
            )

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        tool_path = self.get_tool_path(use_global=True)
        self.repo_root = tool_path.joinpath("kvm-unit-tests")
        self.cmd_path = self.repo_root.joinpath("run_tests.sh")

    def _install_dep(self) -> None:
        posix_os: Posix = cast(Posix, self.node.os)
        git = self.node.tools[Git]
        git.clone(self.repo, self.get_tool_path(use_global=True))

        # install dependency packages
        for package in list(self.deps):
            if posix_os.is_package_in_repo(package):
                posix_os.install_packages(package)

    def _install(self) -> bool:
        self._log.debug("Building kvm-unit-tests")
        self._install_dep()
        make = self.node.tools[Make]

        # run ./configure in the repo
        configure_path = self.repo_root.joinpath("configure")
        self.node.execute(str(configure_path), cwd=self.repo_root, expected_exit_code=0)

        # run make in the repo
        make.make("", self.repo_root)

        self._log.debug("Finished building kvm-unit-tests")
        return self._check_exists()
