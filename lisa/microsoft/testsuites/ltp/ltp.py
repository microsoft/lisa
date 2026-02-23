# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import os
import re
from dataclasses import dataclass
from pathlib import PurePath, PurePosixPath
from typing import Any, Dict, List, Optional, Type

from assertpy import assert_that

from lisa.executable import Tool
from lisa.messages import TestStatus, send_sub_test_result_message
from lisa.node import Node
from lisa.operating_system import CBLMariner, Debian, Fedora, Posix, Redhat, Suse
from lisa.testsuite import TestResult
from lisa.tools import (
    Cat,
    Chmod,
    Echo,
    Free,
    Gcc,
    Git,
    Ls,
    Make,
    Mkdir,
    Pidof,
    RemoteCopy,
    Rm,
    Swap,
    Sysctl,
    Tar,
)
from lisa.util import LisaException, find_patterns_in_lines


@dataclass
class LtpResult:
    version: str = ""
    name: str = ""
    status: TestStatus = TestStatus.QUEUED
    exit_value: int = 0


class Ltp(Tool):
    # Test Start Time: Wed Jun  8 23:43:08 2022
    _RESULT_TIMESTAMP_REGEX = re.compile(r"Test Start Time: (.*)\s+")

    # abs01  PASS  0
    _RESULT_TESTCASE_REGEX = re.compile(r"(.*)\s+(PASS|CONF|FAIL)\s+(\d+)")

    # Machine Architecture: x86_64
    _RESULT_LTP_ARCH_REGEX = re.compile(r"Machine Architecture: (.*)\s+")

    LTP_DIR_NAME = "ltp"
    DEFAULT_LTP_TESTS_GIT_TAG = "20250130"
    LTP_GIT_URL = "https://github.com/linux-test-project/ltp.git"
    LTP_RESULT_FILE = "ltp-results.log"
    LTP_OUTPUT_FILE = "ltp-output.log"
    LTP_SKIP_FILE = "skipfile"
    LTP_RUN_COMMAND = "runltp"
    BUILD_REQUIRED_DISK_SIZE_IN_GB = 2
    COMPILE_TIMEOUT = 1800

    @property
    def command(self) -> str:
        return f"{self._command_path}/{self.LTP_RUN_COMMAND}"

    @property
    def dependencies(self) -> List[Type[Tool]]:
        if self._binary_file:
            return []
        else:
            return [Make, Gcc, Git]

    @property
    def can_install(self) -> bool:
        return True

    def __init__(
        self,
        node: Node,
        source_file: str,
        binary_file: str,
        install_path: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(node, args, kwargs)
        git_tag = kwargs.get("git_tag", "")
        self._git_tag = git_tag if git_tag else self.DEFAULT_LTP_TESTS_GIT_TAG
        self._source_file = source_file
        self._binary_file = binary_file

        if install_path:
            self._command_path = install_path
        else:
            # default binary_file install path is /tmp/ltp
            self._command_path = "/tmp/ltp" if self._binary_file else "/opt/ltp"

    def run_test(
        self,
        test_result: TestResult,
        # empty ltp_tests will run LTP full test
        ltp_tests: List[str],
        skip_tests: List[str],
        log_path: str,
        user_input_skip_file: str = "",
        block_device: Optional[str] = None,
        temp_dir: str = "/tmp/",
        ltp_run_timeout: int = 12000,
    ) -> List[LtpResult]:
        result_file = f"{self._command_path}/{self.LTP_RESULT_FILE}"
        output_file = f"{self._command_path}/{self.LTP_OUTPUT_FILE}"
        skip_file = f"{self._command_path}/{self.LTP_SKIP_FILE}"

        ls = self.node.tools[Ls]
        rm = self.node.tools[Rm]

        # remove skipfile if it exists
        if ls.path_exists(skip_file):
            self._log.debug(f"Removing skipfile: {skip_file}")
            rm.remove_file(skip_file, sudo=True)

        # remove results file if it exists
        if ls.path_exists(result_file, sudo=True):
            self._log.debug(f"Removing {result_file}")
            rm.remove_file(result_file, sudo=True)

        # remove output file if it exists
        if ls.path_exists(output_file, sudo=True):
            self._log.debug(f"Removing {output_file}")
            rm.remove_file(output_file, sudo=True)

        # add parameters for the test logging
        parameters = f"-p -q -l {result_file} -o {output_file} "

        # add the list of tests to run
        # if ltp_tests=[], "-f" not set, ltp will run full test
        if ltp_tests:
            parameters += f"-f {','.join(ltp_tests)} "

        # some tests require a big unmounted block device
        # to run correctly.
        if block_device:
            parameters += f"-z {block_device} "

        # directory where temporary files will be created
        parameters += f"-d {temp_dir} "

        # add the list of skip tests to run
        if user_input_skip_file:
            # copy user provided skip file to remote skip_file location
            if not os.path.exists(user_input_skip_file):
                raise LisaException(
                    f"User provided skip file does not exist: {user_input_skip_file}"
                )
            self._log.debug(f"user_input_skip_file: {user_input_skip_file}")
            self.node.shell.copy(
                PurePath(user_input_skip_file),
                PurePosixPath(skip_file),
            )
            parameters += f"-S {skip_file} "
        elif len(skip_tests) > 0:
            # write skip test to skipfile with newline separator
            skip_file_value = "\n".join(skip_tests)
            self.node.tools[Echo].write_to_file(
                skip_file_value, PurePosixPath(skip_file), sudo=True
            )
            parameters += f"-S {skip_file} "

        # Minimum 4M swap space is needed by some mmp test
        if self.node.tools[Free].get_swap_size() < 4:
            self.node.tools[Swap].create_swap()

        # run ltp tests
        cur_command = f"echo y | {self.command} {parameters}"
        self.node.execute_async(
            cur_command,
            sudo=True,
            shell=True,
        )

        pidof = self.node.tools[Pidof]
        process_name = f"-x {self.LTP_RUN_COMMAND}"
        if self._binary_file:
            process_name = self.LTP_RUN_COMMAND
        pidof.wait_processes(process_name, sudo=True, timeout=ltp_run_timeout)

        # to avoid no permission issue when copying back files
        self.node.tools[Chmod].update_folder(self._command_path, "a+rwX", sudo=True)

        # write output to log path
        self.node.shell.copy_back(
            PurePosixPath(output_file), PurePath(log_path) / self.LTP_OUTPUT_FILE
        )

        # write results to log path
        local_ltp_results_path = PurePath(log_path) / self.LTP_RESULT_FILE
        self.node.shell.copy_back(PurePosixPath(result_file), local_ltp_results_path)

        # parse results from local_ltp_results_path file
        # read the file
        with open(local_ltp_results_path, "r") as f:
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
            info["information"]["version"] = result.version
            info["information"]["exit_value"] = result.exit_value
            send_sub_test_result_message(
                test_result=test_result,
                test_case_name=result.name,
                test_status=result.status,
                other_fields=info,
            )

        # assert that none of the tests failed
        assert_that(
            failed_tests, f"The following tests failed: {failed_tests}"
        ).is_empty()

        return results

    def _install(self) -> bool:
        if self._binary_file:
            self._install_from_binary_file(self._binary_file)
        else:
            self._build_from_source()

        return self._check_exists()

    def _install_from_binary_file(
        self,
        binary_file: str,
    ) -> None:
        remote_tar_path = self.node.get_pure_path(
            self._command_path
        ) / os.path.basename(binary_file)
        ltp_installed_dir = self.node.get_pure_path("/tmp")
        mkdir = self.node.tools[Mkdir]
        mkdir.create_directory(remote_tar_path.parent.as_posix())
        self.node.shell.copy(
            PurePath(binary_file),
            remote_tar_path,
        )
        self.node.tools[Tar].extract(
            str(remote_tar_path),
            str(ltp_installed_dir),
            sudo=True,
        )

        self._log.debug(f"Extracted tar from path {binary_file}!")

    def _extract_source(
        self,
        source_file: str,
        dest_path: str,
    ) -> PurePath:
        remote_source_folder = self.get_tool_path(use_global=True)
        remote_tar_path = remote_source_folder / os.path.basename(source_file)
        copy = self.node.tools[RemoteCopy]
        copy.copy_to_remote(PurePath(self._source_file), remote_source_folder)

        self.node.tools[Tar].extract(
            str(remote_tar_path), dest_path, strip_components=1
        )

        return self.node.get_pure_path(dest_path)

    def _clone_source(
        self,
        git_url: str,
        dest_path: str,
    ) -> PurePath:
        # clone ltp
        git = self.node.tools[Git]
        ltp_path = git.clone(
            git_url,
            cwd=PurePosixPath(dest_path),
            dir_name=dest_path,
        )
        # checkout tag
        git.checkout(ref=f"tags/{self._git_tag}", cwd=ltp_path)

        return ltp_path

    def _install_dependencies(self) -> None:
        assert isinstance(self.node.os, Posix), f"{self.node.os} is not supported"

        # install common dependencies
        self.node.os.install_packages(
            [
                "m4",
                "bison",
                "flex",
                "psmisc",
                "autoconf",
                "automake",
            ]
        )

        # install distro specific dependencies
        if isinstance(self.node.os, Fedora):
            self.node.os.install_packages(
                [
                    "libaio-devel",
                    "libattr",
                    "libcap-devel",
                    "libdb",
                    "pkgconf",
                    "kernel-headers",
                    "glibc-headers",
                ]
            )

            # db4-utils and ntp are not available in Redhat >= 8.0
            # ntp is replaced by chrony in Redhat8 release
            if not (
                isinstance(self.node.os, Redhat)
                and self.node.os.information.version >= "8.0.0"
            ):
                self.node.os.install_packages(["db4-utils", "ntp"])
        elif isinstance(self.node.os, Debian):
            self.node.os.install_packages(
                [
                    "libaio-dev",
                    "libattr1",
                    "libcap-dev",
                    "keyutils",
                    "libdb4.8",
                    "libberkeleydb-perl",
                    "expect",
                    "dh-autoreconf",
                    "gdb",
                    "libnuma-dev",
                    "quota",
                    "genisoimage",
                    "db-util",
                    "unzip",
                    "pkgconf",
                    "libc6-dev",
                ]
            )

            # install "exfat-utils"
            # Note: Package has been renamed to exfatprogs
            try:
                self.node.os.install_packages(["exfat-utils"])
            except Exception as e:
                self._log.debug(
                    f"Failed to install exfat-utils: {e}, "
                    "Trying alternative package: exfatprogs"
                )
                self.node.os.install_packages(["exfatprogs"])
        elif isinstance(self.node.os, Suse):
            self.node.os.install_packages(
                [
                    "ntp",
                    "git-core",
                    "db48-utils",
                    "libaio-devel",
                    "libattr1",
                    "libcap-progs",
                    "libdb-4_8",
                    "perl-BerkeleyDB",
                    "pkg-config",
                    "linux-glibc-devel",
                    "glibc-devel",
                ]
            )
        elif isinstance(self.node.os, CBLMariner):
            self.node.os.install_packages(
                [
                    "kernel-headers",
                    "binutils",
                    "diffutils",
                    "glibc-devel",
                    "zlib-devel",
                ]
            )
        else:
            raise LisaException(f"{self.node.os} is not supported")

    def _set_realtime_cgroup(self) -> None:
        # Some CPU time is assigned to set real-time scheduler and it affects
        # all cgroup test cases. The values for rt_period_us(1000000us or 1s)
        # and rt_runtime_us (950000us or 0.95s). This gives 0.05s to be used
        # by non-RT tasks.
        if self.node.shell.exists(
            PurePosixPath("/sys/fs/cgroup/cpu/user.slice/cpu.rt_runtime_us")
        ):
            runtime_us = self.node.tools[Cat].read(
                "/sys/fs/cgroup/cpu/user.slice/cpu.rt_runtime_us",
                force_run=True,
                sudo=True,
            )
            runtime_us_int = int(runtime_us)
            if runtime_us_int == 0:
                self.node.tools[Echo].write_to_file(
                    "1000000",
                    PurePosixPath("/sys/fs/cgroup/cpu/cpu.rt_period_us"),
                    sudo=True,
                )
                self.node.tools[Echo].write_to_file(
                    "950000",
                    PurePosixPath("/sys/fs/cgroup/cpu/cpu.rt_runtime_us"),
                    sudo=True,
                )
                self.node.tools[Echo].write_to_file(
                    "1000000",
                    PurePosixPath("/sys/fs/cgroup/cpu/user.slice/cpu.rt_period_us"),
                    sudo=True,
                )
                cpu_file = "/sys/fs/cgroup/cpu/user.slice/cpu.rt_runtime_us"
                self.node.tools[Echo].write_to_file(
                    "950000",
                    PurePosixPath(cpu_file),
                    sudo=True,
                )

            # Fix hung_task_timeout_secs and blocked for more than 120 seconds problem
            sysctl = self.node.tools[Sysctl]
            sysctl.write("vm.dirty_ratio", "10")
            sysctl.write("vm.dirty_background_ratio", "5")
            sysctl.run("-p", sudo=True)

    def _build_from_source(self) -> None:
        self._install_dependencies()
        self._set_realtime_cgroup()

        # find partition to build ltp
        build_dir = self.node.find_partition_with_freespace(
            self.BUILD_REQUIRED_DISK_SIZE_IN_GB
        )
        top_src_dir = f"{build_dir}/{self.LTP_DIR_NAME}".replace("//", "/")

        # remove build directory if it exists
        if self.node.tools[Ls].path_exists(top_src_dir, sudo=True):
            self.node.tools[Rm].remove_directory(top_src_dir, sudo=True)

        # setup build directory
        self.node.tools[Mkdir].create_directory(top_src_dir, sudo=True)
        self.node.tools[Chmod].update_folder(top_src_dir, "a+rwX", sudo=True)

        if self._source_file:
            cur_ltp_path = self._extract_source(self._source_file, top_src_dir)
        else:
            cur_ltp_path = self._clone_source(self.LTP_GIT_URL, top_src_dir)

        # better to install ltp in /opt/ltp since this path is used by some
        # tests, e.g, block_dev test
        make = self.node.tools[Make]
        # uploaded release ltp.tar.xz don't need autoreconf
        if not self._source_file:
            self.node.execute("autoreconf -f", cwd=cur_ltp_path)
            make.make("autotools", cwd=cur_ltp_path)
        self.node.execute(
            f"./configure --prefix={self._command_path}", cwd=cur_ltp_path
        )
        make.make("all", cwd=cur_ltp_path, timeout=self.COMPILE_TIMEOUT)

        # Specify SKIP_IDCHECK=1 since we don't want to modify /etc/{group,passwd}
        # on the remote system's sysroot
        make.make_install(cur_ltp_path, "SKIP_IDCHECK=1", sudo=True)

    def _parse_results(
        self,
        result: str,
    ) -> List[LtpResult]:
        # load results from result_file
        parsed_result: List[LtpResult] = []

        matched = find_patterns_in_lines(
            result, [self._RESULT_LTP_ARCH_REGEX, self._RESULT_TESTCASE_REGEX]
        )

        # get testcase data
        for result in matched[1]:
            parsed_result.append(
                LtpResult(
                    version=self._git_tag,
                    name=result[0].strip(),
                    status=self._parse_status_to_test_status(result[1].strip()),
                    exit_value=int(result[2].strip()),
                )
            )

        return parsed_result

    def _parse_status_to_test_status(self, status: str) -> TestStatus:
        if status == "PASS":
            return TestStatus.PASSED
        elif status == "FAIL":
            return TestStatus.FAILED
        elif status == "CONF":
            return TestStatus.SKIPPED
        else:
            raise LisaException(f"Unknown status: {status}")
