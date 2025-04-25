import os
import re
from dataclasses import dataclass
from pathlib import PurePath, PurePosixPath
from typing import Any, Dict, List, Optional

from assertpy import assert_that

from lisa.base_tools.uname import Uname
from lisa.executable import Tool
from lisa.messages import TestStatus, send_sub_test_result_message
from lisa.node import Node
from lisa.operating_system import CBLMariner, Ubuntu
from lisa.testsuite import TestResult
from lisa.tools import Cp, Git, Ls, Make, RemoteCopy, Tar
from lisa.tools.chmod import Chmod
from lisa.tools.mkdir import Mkdir
from lisa.tools.whoami import Whoami
from lisa.util import LisaException, UnsupportedDistroException, find_groups_in_lines

_UBUNTU_OS_PACKAGES = [
    "git",
    "build-essential",
    "bison",
    "flex",
    "libelf-dev",
    "xz-utils",
    "libssl-dev",
    "bc",
    "ccache",
    "libncurses-dev",
]

_MARINER_OS_PACKAGES = [
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
    "glibc-devel",
    "binutils",
    "kernel-headers",
]


@dataclass
class KselftestResult:
    name: str = ""
    status: TestStatus = TestStatus.QUEUED
    exit_value: int = 0


class Kselftest(Tool):
    _KSELF_TEST_SRC_REPO = (
        "git://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git"
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
        return len(self.node.tools[Ls].list(str(self._installed_path))) > 0

    def __init__(
        self,
        node: Node,
        working_path: str,
        file_path: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(node, *args, **kwargs)

        # tar file path specified in yml
        self._working_path = working_path
        self._tar_file_path = file_path
        kselftest_packages = "kselftest-packages"
        if self._working_path:
            package_path = self.node.get_pure_path(
                self._working_path,
            ) / (kselftest_packages)
        else:
            package_path = self.get_tool_path(use_global=True) / kselftest_packages

        self._installed_path = package_path

        if self._tar_file_path:
            self._remote_tar_path = package_path / os.path.basename(self._tar_file_path)

        self._command = self._installed_path / "run_kselftest.sh"

    # install common dependencies
    def _install(self) -> bool:
        is_support = False
        if (
            (
                isinstance(self.node.os, Ubuntu)
                and self.node.os.information.version >= "18.4.0"
            )
            or isinstance(self.node.os, CBLMariner)
            or (self._tar_file_path and self._working_path)
        ):
            is_support = True
        if not is_support:
            raise UnsupportedDistroException(
                self.node.os, "kselftests in LISA does not support this os"
            )

        if self._tar_file_path:
            mkdir = self.node.tools[Mkdir]
            mkdir.create_directory(self._remote_tar_path.parent.as_posix())
            self.node.shell.copy(PurePath(self._tar_file_path), self._remote_tar_path)
            self.node.tools[Tar].extract(
                str(self._remote_tar_path), str(self._installed_path)
            )
            self._log.debug(f"Extracted tar from path {self._remote_tar_path}!")
        else:
            mkdir = self.node.tools[Mkdir]
            mkdir.create_directory(self._installed_path.as_posix())
            if isinstance(self.node.os, Ubuntu):
                arch = self.node.os.get_kernel_information().hardware_platform
                if arch == "aarch64":
                    for package in [
                        "gobjc-arm-linux-gnueabihf",
                        "gobjc-multilib-arm-linux-gnueabihf",
                        "libc6-dev-i386-cross",
                        "libc6-i386-cross",
                    ]:
                        if self.node.os.is_package_in_repo(package):
                            _UBUNTU_OS_PACKAGES.append(package)
                else:
                    _UBUNTU_OS_PACKAGES.append("gcc-multilib libc6-i386 libc6-dev-i386")
                # cache is used to speed up recompilation
                self.node.os.install_packages(_UBUNTU_OS_PACKAGES)
            elif isinstance(self.node.os, CBLMariner):
                # clone kernel, build kernel, then build kselftests
                self.node.os.install_packages(_MARINER_OS_PACKAGES)

            uname = self.node.tools[Uname]
            uname_result = uname.get_linux_information(force_run=False)
            git = self.node.tools[Git]

            branch = "master"
            branch_to_clone = f"{self._KSELF_TEST_SRC_REPO} -b {branch} --depth 1"
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

            self.node.tools[Make].run(
                "headers",
                cwd=kernel_path,
                expected_exit_code=0,
                expected_exit_code_failure_message="failed to build kernel headers.",
            ).assert_exit_code()

            # build and install kselftests
            self.node.execute(
                cmd=f"./kselftest_install.sh {self._installed_path}",
                shell=True,
                cwd=PurePosixPath(kernel_path, "tools/testing/selftests"),
                expected_exit_code=0,
                expected_exit_code_failure_message="fail to build & install kselftest",
            ).assert_exit_code()
            # change permissions of kselftest-packages directory
            # to run test as non root user.
            chmod = self.node.tools[Chmod]
            chmod.update_folder(self._installed_path.as_posix(), "777")

        return self._check_exists()

    def run_all(
        self,
        test_result: TestResult,
        log_path: str,
        timeout: int = 5000,
        run_test_as_root: bool = False,
        run_collections: Optional[List[str]] = None,
        skip_tests: Optional[List[str]] = None,
    ) -> List[KselftestResult]:
        # Executing kselftest as root may cause VM to hang

        # get username
        username = self.node.tools[Whoami].get_username()
        result_directory = f"/home/{username}"
        if self._working_path:
            result_directory = self._working_path
        if os.path.exists(result_directory) is False:
            mkdir = self.node.tools[Mkdir]
            mkdir.create_directory(result_directory)

        result_file_name = "kselftest-results.txt"
        result_file = f"{result_directory}/{result_file_name}"

        if self._tar_file_path:
            work_dir = PurePosixPath(self._installed_path)
        else:
            work_dir = None

        if run_collections or skip_tests:
            # List all available tests
            list_result = self.run(" -l", shell=True)
            list_result.assert_exit_code(
                message="failed to retrieve the list of available kself tests"
            )
            all_tests = list_result.stdout.splitlines()

            # Filter tests based on run_collections if it exists
            # Example: if run_collections = ['uevent']
            # all_tests will already have all tests in the format:
            #   ['core:close_range_test', 'core:unshare_test',
            #    'tty:tty_tstamp_update', 'uevent:uevent_filtering']
            # The filtered_tests will then have the value:
            #   ['uevent:uevent_filtering']
            # This means all the tests that belong to the 'uevent'
            #   collection are selected.
            if run_collections:
                filtered_tests = [
                    test
                    for test in all_tests
                    if any(
                        (match := re.match(r"^[^:/]+", test))
                        and collection == match.group(0)
                        for collection in run_collections
                    )
                ]
            else:
                filtered_tests = all_tests

            # Ensure skip_tests is not None
            skip_tests = skip_tests or []
            # Exclude tests based on skip_tests
            tests_to_run = [test for test in filtered_tests if test not in skip_tests]

            if tests_to_run:
                tests_to_run_str = " ".join(f"-t {test}" for test in tests_to_run)
                self._log.debug(f"Running tests: {tests_to_run}")
                self.run(
                    f" {tests_to_run_str} 2>&1 | tee -a {result_file}",
                    cwd=work_dir,
                    sudo=run_test_as_root,
                    force_run=True,
                    shell=True,
                    timeout=timeout,
                )
        else:
            # run all tests
            self.run(
                f" 2>&1 | tee {result_file}",
                cwd=work_dir,
                sudo=run_test_as_root,
                force_run=True,
                shell=True,
                timeout=timeout,
            )

        # Allow read permissions for "others" to remote copy the file
        # kselftest-results.txt
        chmod = self.node.tools[Chmod]
        chmod.update_folder(result_file, "644")

        # copy kselftest-results.txt from remote to local node for processing results
        remote_copy = self.node.tools[RemoteCopy]
        remote_copy.copy_to_local(
            PurePosixPath(result_file), PurePath(log_path), False, False
        )

        local_kselftest_results_path = PurePath(log_path) / result_file_name

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
            send_sub_test_result_message(
                test_result=test_result,
                test_case_name=result.name,
                test_status=result.status,
                other_fields=info,
            )

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
