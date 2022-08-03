# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, Dict, List, Type, cast

from lisa import notifier
from lisa.executable import Tool
from lisa.messages import SubTestMessage, TestStatus, create_test_result_message
from lisa.operating_system import CBLMariner, Debian, Posix, Redhat, Suse, Ubuntu
from lisa.testsuite import TestResult
from lisa.tools import Cat, Echo
from lisa.tools.git import Git
from lisa.tools.make import Make
from lisa.util import LisaException, UnsupportedDistroException, find_patterns_in_lines


@dataclass
class XfstestsResult:
    name: str = ""
    status: TestStatus = TestStatus.QUEUED


class Xfstests(Tool):
    repo = "https://git.kernel.org/pub/scm/fs/xfs/xfstests-dev.git"
    common_dep = [
        "acl",
        "attr",
        "automake",
        "bc",
        "cifs-utils",
        "dos2unix",
        "dump",
        "e2fsprogs",
        "gawk",
        "gcc",
        "libtool",
        "lvm2",
        "make",
        "parted",
        "quota",
        "sed",
        "xfsdump",
        "xfsprogs",
        "indent",
        "python",
        "fio",
    ]
    debian_dep = [
        "libacl1-dev",
        "libaio-dev",
        "libattr1-dev",
        "libgdbm-dev",
        "libtool-bin",
        "libuuid1",
        "libuuidm-ocaml-dev",
        "sqlite3",
        "uuid-dev",
        "uuid-runtime",
        "xfslibs-dev",
        "zlib1g-dev",
        "btrfs-tools",
        "btrfs-progs",
    ]
    fedora_dep = [
        "libtool",
        "libuuid-devel",
        "libacl-devel",
        "xfsprogs-devel",
        "epel-release",
        "libaio-devel",
        "libattr-devel",
        "sqlite",
        "xfsprogs-qa-devel",
        "zlib-devel",
        "btrfs-progs-devel",
        "llvm-ocaml-devel",
        "uuid-devel",
    ]
    suse_dep = [
        "btrfsprogs",
        "libacl-devel",
        "libaio-devel",
        "libattr-devel",
        "sqlite",
        "xfsprogs-devel",
        "lib-devel",
    ]
    mariner_dep = [
        "python-iniparse",
        "libacl-devel",
        "libaio-devel",
        "libattr-devel",
        "sqlite",
        "xfsprogs-devel",
        "zlib-devel",
        "trfs-progs-devel",
        "diffutils",
        "btrfs-progs",
        "btrfs-progs-devel",
        "gcc",
        "autoconf",
        "binutils",
        "kernel-headers",
        "util-linux-devel",
        "psmisc",
    ]
    # Passed all 35 tests
    __all_pass_pattern = re.compile(
        r"([\w\W]*?)Passed all (?P<pass_count>\d+) tests", re.MULTILINE
    )
    # Failed 22 of 514 tests
    __fail_pattern = re.compile(
        r"([\w\W]*?)Failed (?P<fail_count>\d+) of (?P<total_count>\d+) tests",
        re.MULTILINE,
    )
    # Failures: generic/079 generic/193 generic/230 generic/256 generic/314 generic/317 generic/318 generic/355 generic/382 generic/523 generic/536 generic/553 generic/554 generic/565 generic/566 generic/587 generic/594 generic/597 generic/598 generic/600 generic/603 generic/646 # noqa: E501
    __fail_cases_pattern = re.compile(
        r"([\w\W]*?)Failures: (?P<fail_cases>.*)",
        re.MULTILINE,
    )
    # Ran: generic/001 generic/002 generic/003 ...
    __all_cases_pattern = re.compile(
        r"([\w\W]*?)Ran: (?P<all_cases>.*)",
        re.MULTILINE,
    )
    # Not run: generic/110 generic/111 generic/115 ...
    __not_run_cases_pattern = re.compile(
        r"([\w\W]*?)Not run: (?P<not_run_cases>.*)",
        re.MULTILINE,
    )

    @property
    def command(self) -> str:
        # The command is not used
        # _check_exists is overwritten to check tool existence
        return str(self.get_tool_path(use_global=True) / "xfstests-dev" / "check")

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Git, Make]

    def run_test(self, test_type: str, timeout: int = 14400) -> str:
        cmd_result = self.run(
            f"-g {test_type}/quick -E exclude.txt",
            sudo=True,
            shell=True,
            force_run=True,
            cwd=self.get_xfstests_path(),
            timeout=timeout,
        )
        return cmd_result.stdout

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._code_path = self.get_tool_path(use_global=True) / "xfstests-dev"

    def _install_dep(self) -> None:
        posix_os: Posix = cast(Posix, self.node.os)
        tool_path = self.get_tool_path(use_global=True)
        git = self.node.tools[Git]
        git.clone(self.repo, tool_path)
        # install dependency packages
        package_list = []
        package_list.extend(self.common_dep)
        if isinstance(self.node.os, Redhat):
            package_list.extend(self.fedora_dep)
        elif isinstance(self.node.os, Debian):
            if (
                isinstance(self.node.os, Ubuntu)
                and self.node.os.information.version < "18.4.0"
            ):
                raise UnsupportedDistroException(self.node.os)
            package_list.extend(self.debian_dep)
        elif isinstance(self.node.os, Suse):
            package_list.extend(self.suse_dep)
        elif isinstance(self.node.os, CBLMariner):
            package_list.extend(self.mariner_dep)
        else:
            raise LisaException(
                f"Current distro {self.node.os.name} doesn't support xfstests."
            )

        # if install the packages in one command, the remain available packages can't
        # be installed if one of packages is not available in that distro,
        # so here install it one by one
        for package in list(package_list):
            # to make code simple, put all packages needed by one distro in one list.
            # the package name may be different for the different sku of the
            #  same distro. so, install it when the package exists in the repo.
            if posix_os.is_package_in_repo(package):
                posix_os.install_packages(package)
        # fix compile issue on RHEL/CentOS 7.x
        if (
            isinstance(self.node.os, Redhat)
            and self.node.os.information.version < "8.0.0"
        ):
            posix_os.install_packages(packages="centos-release-scl")
            posix_os.install_packages(
                "http://mirror.centos.org/centos/7/os/x86_64/Packages/"
                "xfsprogs-devel-4.5.0-22.el7.x86_64.rpm"
            )
            posix_os.install_packages(
                packages="devtoolset-7-gcc*", extra_args=["--skip-broken"]
            )
            self.node.execute("rm -f /bin/gcc", sudo=True, shell=True)
            self.node.execute(
                "ln -s /opt/rh/devtoolset-7/root/usr/bin/gcc /bin/gcc",
                sudo=True,
                shell=True,
            )
        # fix compile issue on SLES12SP5
        if (
            isinstance(self.node.os, Suse)
            and self.node.os.information.version < "15.0.0"
        ):
            posix_os.install_packages(packages="gcc5")
            self.node.execute("rm -rf /usr/bin/gcc", sudo=True, shell=True)
            self.node.execute(
                "ln -s /usr/bin/gcc-5 /usr/bin/gcc",
                sudo=True,
                shell=True,
            )

    def _add_test_users(self) -> None:
        # prerequisite for xfstesting
        # these users are used in the test code
        # refer https://github.com/kdave/xfstests
        self.node.execute("useradd -m fsgqa", sudo=True)
        self.node.execute("groupadd fsgqa", sudo=True)
        self.node.execute("useradd 123456-fsgqa", sudo=True)
        self.node.execute("useradd fsgqa2", sudo=True)

    def _install(self) -> bool:
        self._install_dep()
        self._add_test_users()
        tool_path = self.get_tool_path(use_global=True)
        make = self.node.tools[Make]
        code_path = tool_path.joinpath("xfstests-dev")
        make.make_install(code_path)
        return True

    def get_xfstests_path(self) -> PurePath:
        return self._code_path

    def set_local_config(
        self,
        scratch_dev: str,
        scratch_mnt: str,
        test_dev: str,
        test_folder: str,
        test_type: str,
        mount_opts: str = "",
    ) -> None:
        xfstests_path = self.get_xfstests_path()
        config_path = xfstests_path.joinpath("local.config")
        if self.node.shell.exists(config_path):
            self.node.shell.remove(config_path)
        if "generic" == test_type:
            test_type = "xfs"
        echo = self.node.tools[Echo]
        if mount_opts:
            content = "\n".join(
                [
                    "[cifs]",
                    "FSTYP=cifs",
                    f"TEST_FS_MOUNT_OPTS=''{mount_opts}''",
                    f"MOUNT_OPTIONS=''{mount_opts}''",
                ]
            )
        else:
            content = "\n".join(
                [
                    f"[{test_type}]",
                    f"FSTYP={test_type}",
                ]
            )
        echo.write_to_file(content, config_path, append=True)

        content = "\n".join(
            [
                f"SCRATCH_DEV={scratch_dev}",
                f"SCRATCH_MNT={scratch_mnt}",
                f"TEST_DEV={test_dev}",
                f"TEST_DIR={test_folder}",
            ]
        )
        echo.write_to_file(content, config_path, append=True)

    def set_excluded_tests(self, exclude_tests: str) -> None:
        if exclude_tests:
            xfstests_path = self.get_xfstests_path()
            exclude_file_path = xfstests_path.joinpath("exclude.txt")
            if self.node.shell.exists(exclude_file_path):
                self.node.shell.remove(exclude_file_path)
            echo = self.node.tools[Echo]
            echo.write_to_file(exclude_tests, exclude_file_path)

    def create_send_subtest_msg(
        self,
        test_result: TestResult,
        raw_message: str,
        test_type: str,
        data_disk: str,
    ) -> None:
        environment = test_result.environment
        assert environment, "fail to get environment from testresult"
        all_cases_match = self.__all_cases_pattern.match(raw_message)
        assert all_cases_match, "fail to find run cases from xfstests output"
        all_cases = (all_cases_match.group("all_cases")).split()
        not_run_cases: List[str] = []
        fail_cases: List[str] = []
        not_run_match = self.__not_run_cases_pattern.match(raw_message)
        if not_run_match:
            not_run_cases = (not_run_match.group("not_run_cases")).split()
        fail_match = self.__fail_cases_pattern.match(raw_message)
        if fail_match:
            fail_cases = (fail_match.group("fail_cases")).split()
        pass_cases = [
            x for x in all_cases if x not in not_run_cases and x not in not_run_cases
        ]
        results: List[XfstestsResult] = []
        for case in fail_cases:
            results.append(XfstestsResult(case, TestStatus.FAILED))
        for case in pass_cases:
            results.append(XfstestsResult(case, TestStatus.PASSED))
        for case in not_run_cases:
            results.append(XfstestsResult(case, TestStatus.SKIPPED))
        for result in results:
            # create test result message
            info: Dict[str, Any] = {}
            info["information"] = {}
            info["information"]["test_type"] = test_type
            info["information"]["data_disk"] = data_disk
            subtest_message = create_test_result_message(
                SubTestMessage,
                test_result.id_,
                environment,
                result.name,
                result.status,
                other_fields=info,
            )

            # notify subtest result
            notifier.notify(subtest_message)

    def check_test_results(
        self,
        raw_message: str,
        log_path: Path,
        test_type: str,
        result: TestResult,
        data_disk: str = "",
    ) -> None:
        self.create_send_subtest_msg(result, raw_message, test_type, data_disk)
        xfstests_path = self.get_xfstests_path()
        results_path = xfstests_path / "results/check.log"
        if not self.node.shell.exists(results_path):
            raise LisaException(
                f"Result path {results_path} doesn't exist, please check testing runs"
                " well or not."
            )
        results = self.node.tools[Cat].run(str(results_path), force_run=True, sudo=True)
        results.assert_exit_code()
        pass_match = self.__all_pass_pattern.match(results.stdout)
        if pass_match:
            pass_count = pass_match.group("pass_count")
            self._log.debug(
                f"All pass in xfstests, total pass case count is {pass_count}."
            )
            return
        fail_match = self.__fail_pattern.match(results.stdout)
        assert fail_match
        fail_count = fail_match.group("fail_count")
        total_count = fail_match.group("total_count")
        fail_cases_match = self.__fail_cases_pattern.match(results.stdout)
        assert fail_cases_match
        fail_info = ""
        fail_cases = fail_cases_match.group("fail_cases")
        for fail_case in fail_cases.split():
            fail_info += find_patterns_in_lines(
                raw_message, [re.compile(f".*{fail_case}.*$", re.MULTILINE)]
            )[0][0]
        self.save_xfstests_log(fail_cases.split(), log_path, test_type)
        results_folder = xfstests_path / "results/"
        self.node.execute(f"rm -rf {results_folder}", sudo=True)
        raise LisaException(
            f"Fail {fail_count} cases of total {total_count}, fail cases"
            f" {fail_cases}, details {fail_info}, please investigate."
        )

    def save_xfstests_log(
        self, fail_cases: List[str], log_path: Path, test_type: str
    ) -> None:
        if "generic" == test_type:
            test_type = "xfs"
        xfstests_path = self.get_xfstests_path()
        self.node.shell.copy_back(
            xfstests_path / "results/check.log",
            log_path / "xfstests/check.log",
        )
        for fail_case in fail_cases:
            file_name = f"results/{test_type}/{fail_case}.out.bad"
            result_path = xfstests_path / file_name
            if self.node.shell.exists(result_path):
                self.node.shell.copy_back(result_path, log_path / file_name)
            else:
                self._log.debug(f"{file_name} doesn't exist.")
            file_name = f"results/{test_type}/{fail_case}.full"
            result_path = xfstests_path / file_name
            if self.node.shell.exists(result_path):
                self.node.shell.copy_back(result_path, log_path / file_name)
            else:
                self._log.debug(f"{file_name} doesn't exist.")
