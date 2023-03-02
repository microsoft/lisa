import os
import re
from dataclasses import dataclass
from pathlib import PurePath, PurePosixPath
from typing import Any, Dict, List

from assertpy import assert_that

from lisa import Environment, notifier
from lisa.base_tools.uname import Uname
from lisa.executable import Tool
from lisa.messages import SubTestMessage, TestStatus, create_test_result_message
from lisa.node import Node
from lisa.operating_system import CBLMariner
from lisa.testsuite import TestResult
from lisa.tools import Cp, Git, Ls, Make, RemoteCopy, Tar
from lisa.tools.whoami import Whoami
from lisa.util import LisaException, UnsupportedDistroException, find_groups_in_lines


@dataclass
class KselftestResult:
    name: str = ""
    status: TestStatus = TestStatus.QUEUED
    exit_value: int = 0


class Kselftest(Tool):
    _MARINER_KERNEL_SRC_REPO = "https://github.com/microsoft/CBL-Mariner-Linux-Kernel"
    _KERNEL_REPO_NAME = "CBL-Mariner-Linux-Kernel"
    _KSELFTEST_TAR_PATH = (
        "/build/kselftest/kselftest_install/kselftest-packages/kselftest.tar.gz"
    )

    # kselftest result log has "ok" and "not ok" prefixes, use regex to filter them
    # example skip test log: "ok 6 selftests: cgroup: test_stress.sh # SKIP"
    # example failed test log: "not ok 52 selftests: net: veth.sh # exit=1"
    # example passed test log: "ok 2 selftests: breakpoints: breakpoint_test"
    # example timeout test log: "not ok 8 selftests: netfilter: nft_concat_range.sh
    # # TIMEOUT 45 seconds"
    _RESULT_KSELFTEST_OK_REGEX = re.compile(
        r"^(?P<status>(not ok|ok))\s+\d+\s+selftests:\s+\S+:\s+(?P<name>\S+)\s*(?:# (?:exit=)?(?P<reason>SKIP|TIMEOUT\d+).*)?(?:# exit=(?P<exit>\d+))?"  # noqa: E501
    )

    @property
    def command(self) -> str:
        return str(self._command)

    @property
    def can_install(self) -> bool:
        return True

    def _check_exists(self) -> bool:
        return self.node.tools[Ls].path_exists(str(self._remote_tar_path), sudo=True)

    def __init__(
        self, node: Node, kselftest_file_path: str, *args: Any, **kwargs: Any
    ) -> None:
        super().__init__(node, *args, **kwargs)

        # tar file path specified in yml
        self._tar_file_path = kselftest_file_path
        if self._tar_file_path:
            self._remote_tar_path = self.get_tool_path(
                use_global=True
            ) / os.path.basename(self._tar_file_path)
        else:
            self._remote_tar_path = (
                self.get_tool_path(use_global=True)
                / f"{self._KERNEL_REPO_NAME}{self._KSELFTEST_TAR_PATH}"
            )

        # command to run kselftests
        if not self._tar_file_path:
            self._command = self.get_tool_path(use_global=True) / "run_kselftest.sh"
        else:
            self._command = (
                self.get_tool_path(use_global=True)
                / "kselftest-packages/run_kselftest.sh"
            )

    # install common dependencies
    def _install(self) -> bool:
        if not isinstance(self.node.os, CBLMariner):
            raise UnsupportedDistroException(
                self.node.os, "kselftests are supported on Mariner VMs only."
            )

        if self._tar_file_path:
            self.node.shell.copy(PurePath(self._tar_file_path), self._remote_tar_path)
        else:
            # clone kernel, build kernel, then build kselftests
            self.node.os.install_packages(
                [
                    "bison",
                    "flex",
                    "build-essential",
                    "openssl-devel",
                    "bc",
                    "dwarves",
                    "rsync",
                    "libcap-devel",
                    "libcap-ng-devel",
                    "fuse",
                    "fuse-devel",
                    "popt-devel",
                    "numactl-devel",
                    "libmnl-devel",
                    "libinput",
                    "mesa-libgbm-devel",
                    "glibc-static",
                    "clang",
                ]
            )

            uname = self.node.tools[Uname]
            uname_result = uname.get_linux_information(force_run=False)
            version = uname_result.kernel_version
            git = self.node.tools[Git]

            # If version.patch is zero, clone major.minor kernel from
            # upstream stable kernel. If version.patch is non-zero, clone
            # major.minor.patch kernel corresponding to the distro in use
            branch = "rolling-lts/mariner-2/"
            branch += f"{version.major}.{version.minor}.{version.patch}.1"
            branch_to_clone = f"{self._MARINER_KERNEL_SRC_REPO} -b {branch} --depth 1"
            kernel_path = git.clone(
                branch_to_clone,
                self.get_tool_path(use_global=True),
                fail_on_exists=False,
            )
            self.node.tools[Cp].copy(
                src=self.node.get_pure_path(
                    f"/boot/config-{uname_result.kernel_version_raw}"
                ),
                dest=PurePath(".config"),
                cwd=kernel_path,
                sudo=True,
            )

            # build kselftests
            self.node.tools[Make].run(
                "KBUILD_OUTPUT=build -C tools/testing/selftests gen_tar",
                cwd=kernel_path,
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message="could not generate kselftest tar.",
            ).assert_exit_code()

        tool_path = self.get_tool_path(use_global=True)
        self.node.tools[Tar].extract(
            str(self._remote_tar_path), str(tool_path), sudo=True
        )
        self._log.debug(f"Extracted tar from path {self._remote_tar_path}!")

        return self._check_exists()

    def run_all(
        self, test_result: TestResult, environment: Environment, log_path: str
    ) -> List[KselftestResult]:
        self.run(
            " 2>&1 | tee kselftest-results.txt",
            force_run=True,
            sudo=True,
            shell=True,
            timeout=5000,
        )

        # get username
        username = self.node.tools[Whoami].get_username()

        # Allow read permissions for "others" to remote copy the file
        # kselftest-results.txt
        self.node.execute(
            f"chmod 644 /home/{username}/kselftest-results.txt", sudo=True
        )

        # copy kselftest-results.txt from remote to local node for processing results
        remote_copy = self.node.tools[RemoteCopy]
        remote_copy.copy_to_local(
            PurePosixPath(f"/home/{username}/kselftest-results.txt"), PurePath(log_path)
        )

        local_kselftest_results_path = PurePath(log_path) / "kselftest-results.txt"

        # parse results from local_kselftest_results_path file
        # read the file
        with open(local_kselftest_results_path, encoding="utf8") as f:
            result_output = f.read()
            results = self._parse_results(result_output)

        if not results:
            raise LisaException("tests did not run, kselftest-results.txt is empty")

        # assert that all tests passed
        failed_tests = []
        for result in results:
            if result.status == TestStatus.FAILED:
                failed_tests.append(result.name)

            # create test result message
            info: Dict[str, Any] = {}
            info["information"] = {}
            info["information"]["exit_value"] = result.exit_value
            subtest_message = create_test_result_message(
                SubTestMessage,
                test_result,
                environment,
                result.name,
                result.status,
                other_fields=info,
            )

            # notify subtest result
            notifier.notify(subtest_message)

        # assert that none of the tests failed
        assert_that(failed_tests).described_as("kselftests failed").is_empty()

        return results

    def _parse_results(self, result: str) -> List[KselftestResult]:
        parsed_result: List[KselftestResult] = []

        lines_list = result.splitlines()

        for line in lines_list:
            line_str = "".join(line)
            matched = find_groups_in_lines(line_str, self._RESULT_KSELFTEST_OK_REGEX)

            # get testcase data
            if matched:
                # example parsed_result: name='breakpoint_test_arm64',
                # status=<TestStatus.FAILED: 4>, exit_value='1'
                parsed_result.append(
                    KselftestResult(
                        name=matched[0]["name"],
                        status=self._parse_status_to_test_status(matched),
                        exit_value=self._parse_exit_val_to_test_status(matched),
                    )
                )

        return parsed_result

    def _parse_status_to_test_status(
        self, result_list: List[Dict[str, str]]
    ) -> TestStatus:
        # example result_list for failing test
        # [{'status': 'not ok', 'name': 'test_kmem', 'reason': None, 'exit': '126'}]
        status = result_list[0]["status"]

        # passed or skipped tests
        if status == "ok":
            if result_list[0]["reason"] == "SKIP":
                return TestStatus.SKIPPED
            else:
                return TestStatus.PASSED

        # failed or timed out tests
        return TestStatus.FAILED

    def _parse_exit_val_to_test_status(self, result_list: List[Dict[str, str]]) -> int:
        # example result_list for failing test
        # [{'status': 'not ok', 'name': 'test_kmem', 'reason': None, 'exit': '126'}]
        exit_val = result_list[0]["exit"]

        # tests that failed with exit code
        if exit_val:
            return int(exit_val)
        # tests that passed, skipped or timed out
        else:
            return 0
