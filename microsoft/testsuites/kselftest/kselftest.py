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
from lisa.operating_system import CBLMariner, Ubuntu
from lisa.testsuite import TestResult
from lisa.tools.git import Git
from lisa.tools.remote_copy import RemoteCopy
from lisa.tools.tar import Tar
from lisa.util import LisaException, find_patterns_in_lines


@dataclass
class KselftestResult:
    name: str = ""
    status: TestStatus = TestStatus.QUEUED
    exit_value: int = 0


class Kselftest(Tool):
    repo = "git://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git"
    mariner_repo = "https://github.com/microsoft/CBL-Mariner-Linux-Kernel"
    # kselftest result log has "ok" and "not ok" prefixes, use regex to filter them
    # example: not ok 1 selftests: breakpoints: step_after_suspend_test # exit=126
    _RESULT_KSELFTEST_OK_REGEX = re.compile(r"ok (.*)\s+")

    @property
    def command(self) -> str:
        return str(self._command)

    @property
    def can_install(self) -> bool:
        return True

    def __init__(self, node: Node, kselftest_file_path: str, *args: Any, **kwargs: Any) -> None:
        super().__init__(node, *args, **kwargs)
        # command to run kselftests
        self._command = (
            self.get_tool_path(use_global=True)
            / "kselftest-packages/run_kselftest.sh"
        )

        # tar file path specified in yml
        self._tar_file_path = kselftest_file_path

        if not self._tar_file_path:
            # clone kernel, build kernel, then build kselftests
            uname = self.node.tools[Uname]
            uname_result = uname.get_linux_information(force_run=False)
            version=uname_result.kernel_version
            git = self.node.tools[Git]

            if (version.patch == 0):
                # clone major.minor kernel from upstream
                branch = "linux-"
                branch += str(version.major) + "." + str(version.minor) + ".y"
                branch_to_clone = self.repo + " -b " + branch + " --depth 1"
                kernel_path = git.clone(branch_to_clone, self.get_tool_path(use_global=True), fail_on_exists=False)
                self.node.execute(cmd="make defconfig", cwd=kernel_path)
            else:
                if isinstance(self.node.os, CBLMariner):
                    branch = "rolling-lts/mariner-2/"
                    branch += str(version.major) + "." + str(version.minor) + "." + str(version.patch) + ".1"
                    branch_to_clone = self.mariner_repo + " -b " + branch + " --depth 1"
                    kernel_path = git.clone(branch_to_clone, self.get_tool_path(use_global=True), fail_on_exists=False)
                    self.node.execute(cmd="wget 'https://raw.githubusercontent.com/microsoft/CBL-Mariner/2.0/SPECS/kernel/config' -O .config", cwd=kernel_path)
                else:
                    # clone major.minor.patch upstream stable kernel for distros other than Mariner
                    branch += str(version.major) + "." + str(version.minor) + ".y"
                    branch_to_clone = self.repo + " -b " + branch + " --depth 1"
                    kernel_path = git.clone(branch_to_clone, self.get_tool_path(use_global=True), fail_on_exists=False)
                    self.node.execute(cmd="make defconfig", cwd=kernel_path)
            self.node.execute(cmd="make -j2", cwd=kernel_path)
            self.node.execute(cmd="make KBUILD_OUTPUT=build FORCE_TARGETS=1 -C tools/testing/selftests gen_tar", cwd=kernel_path, sudo=True)
            self._tar_file_path = str(kernel_path) + "/build/kselftest/kselftest_install/kselftest-packages/kselftest.tar.gz"

    def _install(self) -> bool:
        # install common dependencies
        if isinstance(self.node.os, Ubuntu):
            self.node.os.install_packages(
                [
                    "bison",
                    "flex",
                    "libssl-dev",
                    "libcap-dev"
                ]
            )
        elif isinstance(self.node.os, CBLMariner):
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
                    "clang"
                ]
            )

        # tool_path corresponds to path /home/lisatest/lisa_working/tool/kselftest
        tool_path = self.get_tool_path(use_global=True)
        # file_name corresponds to
        # /home/lisatest/lisa_working/tool/kselftest/kselftests.tar.xz
        file_name = tool_path / os.path.basename(self._tar_file_path)
        # copies tar file from local machine to remote machine
        self.node.shell.copy(self._tar_file_path, file_name)

        self.node.tools[Tar].extract(file_name, tool_path)
        self._log.debug(f"INSTALL from {self._tar_file_path}!")

        return self._check_exists()

    def run_all(
        self, test_result: TestResult, environment: Environment, log_path: str
    ) -> bool:
        self.run(" > kselftest-results.txt", force_run=True, sudo=True, shell=True)
        # Allow read permissions for "others" to remote copy the file kselftest-results.txt
        self.node.execute(f"chmod 644 /home/lisatest/kselftest-results.txt", sudo=True)
        # copy kselftest-results.txt from remote to local node for processing results
        remote_copy = self.node.tools[RemoteCopy]
        remote_copy.copy_to_local(
            PurePosixPath("/home/lisatest/kselftest-results.txt"),
            PurePath(log_path)
        )

        local_kselftest_results_path = PurePath(log_path) / "kselftest-results.txt"

        # parse results from local_kselftest_results_path file
        # read the file
        with open(local_kselftest_results_path, "r") as f:
            result_output = f.read()
            results = self._parse_results(result_output)

        # assert that all tests passed
        failed_tests = []
        for result in results:
            if result.status == TestStatus.FAILED:
                failed_tests.append(result.name)

            # create test result message
            info: Dict[str, Any] = {}
            info["information"] = {}
            info["information"]["name"] = result.name
            info["information"]["exit_value"] = result.exit_value
            subtest_message = create_test_result_message(
                SubTestMessage,
                test_result,
                environment,
                result.name,
                result.status,
            )

            # notify subtest result
            notifier.notify(subtest_message)

        # assert that none of the tests failed
        assert_that(
            failed_tests, f"The following tests failed: {failed_tests}"
        ).is_empty()

        return results

    def _parse_results(
        self,
        result: str,
    ) -> List[KselftestResult]:
        # load results from result_file
        parsed_result: List[KselftestResult] = []

        matched = find_patterns_in_lines(result, [self._RESULT_KSELFTEST_OK_REGEX])

        # get testcase data
        for result in matched[0]:
            # example result_list:
            # ['2', 'selftests:', 'breakpoints:',
            # 'breakpoint_test_arm64', '#', 'exit=1']
            result_list = result.split()
            # example parsed_result: name='breakpoint_test_arm64',
            # status=<TestStatus.FAILED: 4>, exit_value='1'
            parsed_result.append(
                KselftestResult(
                    name=result_list[3],
                    status=self._parse_status_to_test_status(result_list),
                    exit_value=self._parse_exit_val_to_test_status(result_list),
                )
            )

        return parsed_result

    def _parse_status_to_test_status(self, result_list: List) -> TestStatus:
        # example skip test log: "6 selftests: cgroup: test_stress.sh # SKIP"
        # example failed test log: "52 selftests: net: veth.sh # exit=1"
        # example passed test log: "2 selftests: breakpoints: breakpoint_test"

        # in case of skipped or failed test,
        # the last string in the log decides test status
        status = result_list[-1]

        # in case of passed test, length of result_list is always 4
        if len(result_list) == 4:
            return TestStatus.PASSED
        elif status[0:4] == "SKIP":
            return TestStatus.SKIPPED
        elif status[0:4] == "exit":
            return TestStatus.FAILED
        else:
            raise LisaException(f"Unknown status: {status}")

    def _parse_exit_val_to_test_status(self, result_list: List) -> int:
        # example skip test log: "6 selftests: cgroup: test_stress.sh # SKIP"
        # example failed test log: "52 selftests: net: veth.sh # exit=1"
        # example passed test log: "2 selftests: breakpoints: breakpoint_test"

        # last string of the log is either SKIP or "exit=x" or name of test
        status = result_list[-1]

        # in case of failed test, the last character of log is the exit value
        # example failed test log: "52 selftests: net: veth.sh # exit=1"
        if len(result_list) != 4 and status[0:4] == "exit":
            return status[-1]
