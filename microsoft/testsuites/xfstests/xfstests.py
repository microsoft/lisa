# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, Dict, List, Optional, Type, cast

from assertpy import assert_that

from lisa.executable import Tool
from lisa.messages import TestStatus, send_sub_test_result_message
from lisa.operating_system import (
    CBLMariner,
    Debian,
    Oracle,
    Posix,
    Redhat,
    Suse,
    Ubuntu,
)
from lisa.testsuite import TestResult
from lisa.tools import Cat, Chmod, Diff, Echo, Git, Make, Pgrep, Rm, Sed
from lisa.util import LisaException, UnsupportedDistroException, find_patterns_in_lines


@dataclass
class XfstestsResult:
    name: str = ""
    status: TestStatus = TestStatus.QUEUED
    message: str = ""


class Xfstests(Tool):
    """
    Xfstests - Filesystem testing tool.
    installed (default) from https://git.kernel.org/pub/scm/fs/xfs/xfstests-dev.git
    Mirrored daily from kernel.org repository.
    For details, refer to https://github.com/kdave/xfstests/blob/master/README
    """

    # This is the default repo and branch for xfstests.
    # Override this via _install method if needed.
    repo = "https://git.kernel.org/pub/scm/fs/xfs/xfstests-dev.git"
    branch = "master"
    # This hash table contains recommended tags for different OS versions
    # based on our findings that are known to build without issues.
    # The format for key is either "<vendor>_<release>" or "<vendor>_<major>
    # NOTE: The vendor field is case sensitive.
    # This information is derived from node.os.information
    # Logic : the method "get_os_id_version" will return a string
    # in the format "<vendor>_<release>"
    # Example: "SLES_15.5"
    # Alternatively, a partial lookup for SLES_15.5 can be done against a key
    # such as "SLES_15" which is used to encompass all SLES 15.x releases.
    # If you have a specific version of OS with known major and minor version,
    # please ensure it's added to the top of the hash table above partial match keys
    # This string is used to lookup the recommended key-value pair from
    # the hash table. If a match is found, the value is used as the
    # recommended tag for the OS version.
    # If the OS Version is not detected, the method "get_os_id_version" will return
    # "unknown" and a corresponding value will be used from the hash table.
    # If the OS Version is not found in the hash table,
    # the default branch will be used from line 45.
    # NOTE: This table should be updated on a regular basis when the distros
    # are updated to support newer versions of xfstests.
    os_recommended_tags: Dict[str, str] = {
        "SLES_15.5": "v2025.04.27",
        "SLES_12.5": "v2024.12.22",
        "Debian GNU/Linux_11": "v2024.12.22",
        "Debian GNU/Linux_12": "v2024.12.22",
        "Ubuntu_18": "v2024.12.22",
        "Ubuntu_20": "v2024.12.22",
        "Ubuntu_22": "v2024.12.22",
        "Ubuntu_24": "v2024.12.22",
        "Red Hat_7": "v2024.02.09",
        "CentOS_7": "v2024.02.09",
        "unknown": "v2024.02.09",  # Default tag for distros that cannot be identified
    }
    # for all other distros not part of the above hash table,
    # the default branch will be used from line 45
    # these are dependencies for xfstests. Update on regular basis.
    common_dep = [
        "acl",
        "attr",
        "automake",
        "bc",
        "cifs-utils",
        "dos2unix",
        "dump",
        "e2fsprogs",
        "e2fsprogs-devel",
        "gawk",
        "gcc",
        "libtool",
        "lvm2",
        "make",
        "parted",
        "quota",
        "quota-devel",
        "sed",
        "xfsdump",
        "xfsprogs",
        "indent",
        "python",
        "fio",
        "dbench",
        "autoconf",
    ]
    debian_dep = [
        "exfatprogs",
        "f2fs-tools",
        "ocfs2-tools",
        "udftools",
        "xfsdump",
        "xfslibs-dev",
        "dbench",
        "libacl1-dev",
        "libaio-dev",
        "libcap-dev",
        "libgdbm-dev",
        "libtool-bin",
        "liburing-dev",
        "libuuid1",
        "psmisc",
        "python3",
        "uuid-dev",
        "uuid-runtime",
        "linux-headers-generic",
        "sqlite3",
        "libgdbm-compat-dev",
    ]
    fedora_dep = [
        "btrfs-progs",
        "byacc",
        "exfatprogs",
        "f2fs-tools",
        "gcc-c++",
        "gdbm-devel",
        "kernel-devel",
        "libacl-devel",
        "libaio-devel",
        "libcap-devel",
        "libtool",
        "liburing-devel",
        "libuuid-devel",
        "ocfs2-tools",
        "psmisc",
        "python3",
        "sqlite",
        "udftools",
        "xfsprogs-devel",
    ]
    suse_dep = [
        "btrfsprogs",
        "duperemove",
        "libacl-devel",
        "libaio-devel",
        "libattr-devel",
        "libbtrfs-devel",
        "libcap",
        "libcap-devel",
        "libtool",
        "liburing-devel",
        "libuuid-devel",
        "sqlite3",
        "xfsprogs-devel",
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
        "binutils",
        "kernel-headers",
        "util-linux-devel",
        "psmisc",
        "perl-CPAN",
    ]
    # Regular expression for parsing xfstests output
    # Example:
    # Passed all 35 tests
    __all_pass_pattern = re.compile(
        r"([\w\W]*?)Passed all (?P<pass_count>\d+) tests", re.MULTILINE
    )
    # Example:
    # Failed 22 of 514 tests
    __fail_pattern = re.compile(
        r"([\w\W]*?)Failed (?P<fail_count>\d+) of (?P<total_count>\d+) tests",
        re.MULTILINE,
    )
    # Example:
    # Failures: generic/079 generic/193 generic/230 generic/256 generic/314 generic/317 generic/318 generic/355 generic/382 generic/523 generic/536 generic/553 generic/554 generic/565 generic/566 generic/587 generic/594 generic/597 generic/598 generic/600 generic/603 generic/646 # noqa: E501
    __fail_cases_pattern = re.compile(
        r"([\w\W]*?)Failures: (?P<fail_cases>.*)",
        re.MULTILINE,
    )
    # Example:
    # Ran: generic/001 generic/002 generic/003 ...
    __all_cases_pattern = re.compile(
        r"([\w\W]*?)Ran: (?P<all_cases>.*)",
        re.MULTILINE,
    )
    # Example:
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

    def run_test(
        self,
        log_path: Path,
        result: "TestResult",
        test_section: str = "",
        test_group: str = "generic/quick",
        data_disk: str = "",
        test_cases: str = "",
        timeout: int = 14400,
    ) -> None:
        """About: This method runs XFSTest on a given node with the specified
        test group and test cases
        Parameters:
        log_path (Path): (Mandatory)The path where the xfstests logs will be saved
        result (TestResult): (Mandatory The LISA test result object to which the
            subtest results will be sent
        test_section (Str): (Optional)The test section name to be used for testing.
            Defaults to empty string. If not specified, xfstests will use environment
            variables and any first entries in local.config to run tests
            note: if specified, test_section must exist in local.config. There is no
            local checks in code
        test_group (str): The test group to be used for testing. Defaults to
            generic/quick. test_group signifies the basic mandatory tests to run.
            Normally this is <Filesystem>/quick but can be any one of the values from
            groups.list in tests/<filesystem> directory.
            If passed as "", it will be ignored and xfstests will run all tests.
        data_disk(st): The data disk device ID used for testing as scratch and mount
            space
        test_cases(str): Intended to be used in conjunction with test_group.
            This is a space separated list of test cases to be run. If passed as "",
            it will be ignored. test_cases signifies additional cases to be run apart
            from the group tests and exclusion list from exclude.txt previously
            generated and put in the tool path. Its usefull for mixing and matching
            test cases from different file systems, example xfs tests and generic tests.
        timeout(int): The time in seconds after which the test run will be timed out.
            Defaults to 4 hours.
        Example:
        xfstest.run_test(
            log_path=Path("/tmp/xfstests"),
            result=test_result,
            test_section="ext4"
            test_group="generic/quick",
            data_disk="/dev/sdd",
            test_cases="generic/001 generic/002",
            timeout=14400,
        )
        """
        # Note : the sequence is important here.
        # Do not rearrange !!!!!
        # Refer to xfstests-dev guide on https://github.com/kdave/xfstests

        # Test if exclude.txt exists
        xfstests_path = self.get_xfstests_path()
        exclude_file_path = xfstests_path.joinpath("exclude.txt")
        if self.node.shell.exists(exclude_file_path):
            exclude_file = True
        else:
            exclude_file = False
        cmd = ""
        if test_group:
            cmd += f" -g {test_group}"
        if test_section:
            cmd += f" -s {test_section}"
        if exclude_file:
            cmd += " -E exclude.txt"
        if test_cases:
            cmd += f" {test_cases}"
        # Finally
        cmd += " > xfstest.log 2>&1"

        # run ./check command
        self.run_async(
            cmd,
            sudo=True,
            shell=True,
            force_run=True,
            cwd=self.get_xfstests_path(),
        )

        pgrep = self.node.tools[Pgrep]
        # this is the actual process name, when xfstests runs.
        # monitor till process completes or timesout
        try:
            pgrep.wait_processes("check", timeout=timeout)
        finally:
            self.check_test_results(
                log_path=log_path,
                test_section=test_section if test_section else "generic",
                result=result,
                data_disk=data_disk,
            )

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._code_path = self.get_tool_path(use_global=True) / "xfstests-dev"

    def _install_dep(self) -> None:
        """
        About: This method will install dependencies based on OS.
        Dependencies are fetched from the common arrays such as
        common_dep, debian_dep, fedora_dep, suse_dep, mariner_dep.
        If the OS is not supported, a LisaException is raised.
        """
        posix_os: Posix = cast(Posix, self.node.os)
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
            if isinstance(self.node.os, Oracle):
                posix_os.install_packages("oracle-softwarecollection-release-el7")
            else:
                arch = self.node.os.get_kernel_information().hardware_platform
                if arch == "x86_64":
                    xfsprogs_version = posix_os.get_package_information("xfsprogs")
                    # 4.5.0-20.el7.x86_64
                    version_string = ".".join(map(str, xfsprogs_version[:3])) + str(
                        xfsprogs_version[4]
                    )
                    # try to install the compatible version of xfsprogs-devel with
                    # xfsprogs package
                    posix_os.install_packages(f"xfsprogs-devel-{version_string}")
                    # check if xfsprogs-devel is installed successfully
                    assert_that(posix_os.package_exists("xfsprogs-devel")).described_as(
                        "xfsprogs-devel is not installed successfully, please check "
                        "whether it is available in the repo, and the available "
                        "versions are compatible with xfsprogs package."
                    ).is_true()

                posix_os.install_packages(packages="centos-release-scl")
            posix_os.install_packages(
                packages="devtoolset-7-gcc*", extra_args=["--skip-broken"]
            )
            self.node.execute("rm -f /bin/gcc", sudo=True, shell=True)
            self.node.execute(
                "ln -s /usr/bin/x86_64-redhat-linux-gcc /bin/gcc",
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

    def _install(
        self,
        branch: str = "",
        repo: str = "",
    ) -> bool:
        """
        About:This method will download and install XFSTest on a given node.
        Supported OS are Redhat, Debian, Suse, Ubuntu and CBLMariner3.
        Dependencies are installed based on the OS type from _install_dep method.
        The test users are added to the node using _add_test_users method.
        This method allows you to specify custom repo and branch for xfstest.
        Else this defaults to:
        https://git.kernel.org/pub/scm/fs/xfs/xfstests-dev.git:master
        Example:
        xfstest._install(
                         branch="master",
                         repo="https://git.kernel.org/pub/scm/fs/xfs/xfstests-dev.git"
        )
        """
        # Set the branch to the recommended tag for the OS if not provided
        if not branch:
            os_id_version = self.get_os_id_version()
            # First try full match
            if os_id_version in self.os_recommended_tags:
                branch = self.os_recommended_tags[os_id_version]
            else:
                # Try partial match - check if any key is a prefix of os_id_version
                # example: "Ubuntu_20.04" match with "Ubuntu_20" from hash table.
                branch = self.branch  # default fallback
                for key in self.os_recommended_tags:
                    if os_id_version.startswith(key):
                        branch = self.os_recommended_tags[key]
                        # match found, break loop and exit conditional block
                        break
        repo = repo or self.repo
        self._install_dep()
        self._add_test_users()
        tool_path = self.get_tool_path(use_global=True)
        git = self.node.tools[Git]
        git.clone(url=repo, cwd=tool_path, ref=branch)
        make = self.node.tools[Make]
        code_path = tool_path.joinpath("xfstests-dev")

        self.node.tools[Rm].remove_file(str(code_path / "src" / "splice2pipe.c"))
        self.node.tools[Sed].substitute(
            regexp="splice2pipe",
            replacement="",
            file=str(code_path / "src" / "Makefile"),
        )

        make.make_install(code_path)
        return True

    def get_xfstests_path(self) -> PurePath:
        return self._code_path

    def set_local_config(
        self,
        file_system: str,
        scratch_dev: str,
        scratch_mnt: str,
        test_dev: str,
        test_folder: str,
        test_section: str = "",
        mount_opts: str = "",
        testfs_mount_opts: str = "",
        additional_parameters: Optional[Dict[str, str]] = None,
        overwrite_config: bool = False,
    ) -> None:
        """
        About: This method will create // append a local.config file in the install dir
        local.config is used by XFStest to set global as well as testgroup options
        Note:You can call this method multiple times to create multiple sections.
        The code does not checks for duplicate section names, so that is the users
        responsibility.
        Also take note of how options are carried between sectoins, that include the
        sections which are not going to be run.
        Recommend going through link:
        https://github.com/kdave/xfstests/blob/master/README.config-sections
        for more details on how to use local.config
        Parameters:
            scratch_dev (str)   : (M)The scratch device to be used for testing
            scratch_mnt (str)   : (M)The scratch mount point to be used for testing
            test_dev (str)      : (M)The test device to be used for testing
            test_folder (str)   : (M)The test folder to be used for testing
            file_system (str)   : (M)The filesystem type to be tested
            test_section (str)  : (O)The test group name to be used for testing.
                Defaults to the file_system
            mount_opts (str)    : (O)The mount options to be used for testing.
                Empty signifies disk target
            testfs_mount_opts (str): (O)The test filesystem mount options to be used for
                testing.Defaults to mount_opts
            additional_parameters (dict): (O)Additional parameters (dict) to be used for
                testing
            overwrite_config (bool): (O)If True, the existing local.config file will be
                overwritten
        Example:
        xfstest.set_local_config(
            scratch_dev="/dev/sdb",
            scratch_mnt="/mnt/scratch",
            test_dev="/dev/sdc",
            test_folder="/mnt/test",
            file_system="xfs",
            test_section="xfs-custom",
            mount_opts="noatime",
            testfs_mount_opts="noatime",
            additional_parameters={"TEST_DEV2": "/dev/sdd"},
            overwrite_config=True
            )
            Note: This method will by default enforce dmesg logging.
            Note2: Its imperitive that disk labels are set correctly for the tests
            to run.
            We highly advise to fetch the labels at runtime and not hardcode them.
            _prepare_data_disk() method in xfstesting.py is a good example of this.
            Note3: The test folder should be created before running the tests.
            All tests will have a corresponding dmesg log file in output folder.
        """
        xfstests_path = self.get_xfstests_path()
        config_path = xfstests_path.joinpath("local.config")
        # If overwrite is specified, remove the existing config file and start afresh
        if overwrite_config and self.node.shell.exists(config_path):
            self.node.shell.remove(config_path)
        # If groupname is not provided, use Filesystem name.
        # Warning !!!: if you create multiple sections,
        # you must specify unique group names for each
        if not test_section:
            test_section = file_system
        echo = self.node.tools[Echo]
        # create the core config section
        content = "\n".join(
            [
                f"[{test_section}]",
                f"FSTYP={file_system}",
                f"SCRATCH_DEV={scratch_dev}",
                f"SCRATCH_MNT={scratch_mnt}",
                f"TEST_DEV={test_dev}",
                f"TEST_DIR={test_folder}",
            ]
        )

        # if Mount options are provided, append to the end of 'content'
        if mount_opts:
            content += f"\nMOUNT_OPTIONS='{mount_opts}'"
        if testfs_mount_opts:
            content += f"\nTEST_FS_MOUNT_OPTS='{testfs_mount_opts}'"
        # if additional parameters are provided, append to the end of 'content'
        if additional_parameters is not None:
            for key, value in additional_parameters.items():
                content += f"\n{key}={value}"
        # Finally enable DMESG
        content += "\nKEEP_DMESG=yes"
        # Append to the file if exists, else create a new file if none
        echo.write_to_file(content, config_path, append=True)

    def set_excluded_tests(self, exclude_tests: str) -> None:
        """
        About:This method will create an exclude.txt file with the provided test cases.
        The exclude.txt file is used by XFStest to exclude specific test cases from
        running.
        The method takes in the following parameters:
        exclude_tests: The test cases to be excluded from testing
        Parameters:
        exclude_tests (str): The test cases to be excluded from testing
        Example Usage:
        xfstest.set_excluded_tests(exclude_tests="generic/001 generic/002")
        """
        if exclude_tests:
            xfstests_path = self.get_xfstests_path()
            exclude_file_path = xfstests_path.joinpath("exclude.txt")
            if self.node.shell.exists(exclude_file_path):
                self.node.shell.remove(exclude_file_path)
            echo = self.node.tools[Echo]
            for exclude_test in exclude_tests.split():
                echo.write_to_file(exclude_test, exclude_file_path, append=True)

    def create_send_subtest_msg(
        self,
        test_result: "TestResult",
        raw_message: str,
        test_section: str,
        data_disk: str,
    ) -> None:
        """
        About:This method is internal to LISA and is not intended for direct calls.
        This method will create and send subtest results to the test result object.
        Parmaeters:
        test_result: The test result object to which the subtest results will be sent
        raw_message: The raw message from the xfstests output
        test_section: The test group name used for testing
        data_disk: The data disk used for testing. ( method is partially implemented )
        """
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
            x for x in all_cases if x not in not_run_cases and x not in fail_cases
        ]
        results: List[XfstestsResult] = []
        for case in fail_cases:
            results.append(
                XfstestsResult(
                    name=case,
                    status=TestStatus.FAILED,
                    message=self.extract_case_content(case, raw_message),
                )
            )
        for case in pass_cases:
            results.append(
                XfstestsResult(
                    name=case,
                    status=TestStatus.PASSED,
                    message=self.extract_case_content(case, raw_message),
                )
            )
        for case in not_run_cases:
            results.append(
                XfstestsResult(
                    name=case,
                    status=TestStatus.SKIPPED,
                    message=self.extract_case_content(case, raw_message),
                )
            )
        for result in results:
            # create test result message
            info: Dict[str, Any] = {}
            info["information"] = {}
            if test_section:
                info["information"]["test_section"] = test_section
            if data_disk:
                info["information"]["data_disk"] = data_disk
            info["information"]["test_details"] = str(
                self.create_xfstest_stack_info(
                    result.name, test_section, str(result.status.name)
                )
            )
            send_sub_test_result_message(
                test_result=test_result,
                test_case_name=result.name,
                test_status=result.status,
                test_message=result.message,
                other_fields=info,
            )

    def check_test_results(
        self,
        log_path: Path,
        test_section: str,
        result: "TestResult",
        data_disk: str = "",
    ) -> None:
        """
        About: This method is intended to be called by run_test method only.
        This method will check the xfstests output and send subtest results
        to the test result object.
        This method depends on create_send_subtest_msg method to send
        subtest results.
        Parameters:
        log_path: The path where the xfstests logs will be saved
        test_section: The test group name used for testing
        result: The test result object to which the subtest results will be sent
        data_disk: The data disk used for testing ( Method partially implemented )
        """
        xfstests_path = self.get_xfstests_path()
        console_log_results_path = xfstests_path / "xfstest.log"
        results_path = xfstests_path / "results/check.log"
        fail_cases_list: List[str] = []
        try:
            if not self.node.shell.exists(console_log_results_path):
                raise LisaException(
                    f"Console log path {console_log_results_path} doesn't exist, "
                    "please check testing runs well or not."
                )
            else:
                log_result = self.node.tools[Cat].run(
                    str(console_log_results_path), force_run=True, sudo=True
                )
                log_result.assert_exit_code()
                ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
                raw_message = ansi_escape.sub("", log_result.stdout)
                self.create_send_subtest_msg(
                    test_result=result,
                    raw_message=raw_message,
                    test_section=test_section,
                    data_disk=data_disk,
                )

            if not self.node.shell.exists(results_path):
                raise LisaException(
                    f"Result path {results_path} doesn't exist, please check testing"
                    " runs well or not."
                )
            else:
                results = self.node.tools[Cat].run(
                    str(results_path), force_run=True, sudo=True
                )
                results.assert_exit_code()
                pass_match = self.__all_pass_pattern.match(results.stdout)
                if pass_match:
                    pass_count = pass_match.group("pass_count")
                    self._log.debug(
                        f"All pass in xfstests, total pass case count is {pass_count}."
                    )
                fail_match = self.__fail_pattern.match(results.stdout)
                if fail_match:
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
                    fail_cases_list = fail_cases.split()
                    raise LisaException(
                        f"Fail {fail_count} cases of total {total_count}, "
                        f"\n\nfail cases: {fail_cases}, "
                        f"\n\ndetails: \n\n{fail_info}, \n\nplease investigate."
                    )
                else:
                    # Mark the fail count as zero, else code will fail since we never
                    # fetch fail_count from regex.This variable is used in Finally block
                    fail_count = 0
                    self._log.debug("No failed cases found in xfstests.")
        finally:
            self.save_xfstests_log(fail_cases_list, log_path, test_section)
            results_folder = xfstests_path / "results/"
            self.node.execute(f"rm -rf {results_folder}", sudo=True)
            self.node.execute(f"rm -f {console_log_results_path}", sudo=True)

    def save_xfstests_log(
        self, fail_cases_list: List[str], log_path: Path, test_section: str
    ) -> None:
        """
        About:This method is intended to be called by check_test_results method only.
        This method will copy the output of XFSTest results to the Log folder of host
        calling LISA. Files copied are xfsresult.log, check.log and all failed cases
        files if they exist.
        """
        xfstests_path = self.get_xfstests_path()
        self.node.tools[Chmod].update_folder(str(xfstests_path), "a+rwx", sudo=True)
        if self.node.shell.exists(xfstests_path / "results/check.log"):
            self.node.shell.copy_back(
                xfstests_path / "results/check.log",
                log_path / "xfstests/check.log",
            )
        if self.node.shell.exists(xfstests_path / "xfstest.log"):
            self.node.shell.copy_back(
                xfstests_path / "xfstest.log",
                log_path / "xfstests/xfstest.log",
            )

        for fail_case in fail_cases_list:
            file_name = f"results/{test_section}/{fail_case}.out.bad"
            result_path = xfstests_path / file_name
            if self.node.shell.exists(result_path):
                self.node.shell.copy_back(result_path, log_path / file_name)
            else:
                self._log.debug(f"{file_name} doesn't exist.")
            file_name = f"results/{test_section}/{fail_case}.full"
            result_path = xfstests_path / file_name
            if self.node.shell.exists(result_path):
                self.node.shell.copy_back(result_path, log_path / file_name)
            else:
                self._log.debug(f"{file_name} doesn't exist.")
            file_name = f"results/{test_section}/{fail_case}.dmesg"
            result_path = xfstests_path / file_name
            if self.node.shell.exists(result_path):
                self.node.shell.copy_back(result_path, log_path / file_name)
            else:
                self._log.debug(f"{file_name} doesn't exist.")

    def extract_case_content(self, case: str, raw_message: str) -> str:
        """
        About:Support method to extract the content of a specific test case
        from the xfstests output. Its intended for LISA use only.
        The method takes in the following parameters:
        case: The test case name for which the content is needed
        raw_message: The raw message from the xfstests output
        The method returns the content of the specific test case
        Example:
        xfstest.extract_case_content(case="generic/001", raw_message=raw_message)
        """
        # Define the pattern to match the specific case and capture all
        # content until the next <string>/<number> line
        pattern = re.compile(
            rf"({case}.*?)(?="
            r"\n[a-zA-Z]+/\d+|\nRan: |\nNot run: |\nFailures: |\nSECTION|\Z)",
            re.DOTALL,
        )
        # Search for the pattern in the raw_message
        result = pattern.search(raw_message)

        # Extract the matched content and remove the {case} from the start
        if result:
            extracted_content = result.group(1)
            cleaned_content = re.sub(rf"^{case}\s*", "", extracted_content)
            # Remove any string in [ ] at the start of the cleaned_content
            cleaned_content = re.sub(r"^\[.*?\]\s*", "", cleaned_content)
            return cleaned_content.strip()
        else:
            return ""

    def extract_file_content(self, file_path: str) -> str:
        """
        About: Support method to use the Cat command to extract file content.
        This method is called by the create_xfstest_stack_info method.
        Its purpose is to read the ASCII content of the file for further
        tasks such as diff in case of failed cases.
        Parameters:
        file_path: The file path for which the content is needed
        The method returns the content of the specific file
        Example:
        xfstest.extract_file_content(file_path="/path/to/file")
        """
        # Use the cat tool to read the file content
        if not Path(file_path).exists():
            self._log.debug(f"{file_path} doesn't exist.")
            return ""
        cat_tool = self.node.tools[Cat]
        file_content = cat_tool.run(file_path, force_run=True)
        return str(file_content.stdout)

    def create_xfstest_stack_info(
        self,
        case: str,
        test_section: str,
        test_status: str,
    ) -> str:
        """
        About:This method is used to look up the xfstests results directory and extract
        dmesg and full/fail diff output for the given test case.

        Parameters:
        case: The test case name for which the stack info is needed
        test_section: The test group name used for testing
        test_status: The test status for the given test case
        Returns:
        The method returns the stack info message for the given test case
        Example:
        xfstest.create_xfstest_stack_info(
            case="generic/001",
            test_section="xfs",
            test_status="FAILED"
        )
        Note: When running LISA in debug mode, expect verbose messages from 'ls' tool.
        This is because the method checks for file existence per case in the results
        dir.
        This is normal behavior and can be ignored. We are working on reducing verbosity
        of 'ls' calls to improve performance.
        """

        # Get XFSTest current path. we are looking at results/{test_type} directory here
        xfstests_path = self.get_xfstests_path()
        test_class = case.split("/")[0]
        test_id = case.split("/")[1]
        result_path = xfstests_path / f"results/{test_section}/{test_class}"
        cat_tool = self.node.tools[Cat]
        result = ""
        # note: ls tool is not used here due to performance issues.
        if not self.node.shell.exists(result_path):
            self._log.debug(f"No files found in path {result_path}")
            # Note: This is a non terminating error.
            # Do not force an exception for this definition in the future !!!
            # Reason : XFStest in certain conditions will not generate any output
            # for specific tests. these output include *.full, *.out and *.out.fail
            # This also holds true for optional output files such as *.dmesg
            # and *.notrun
            # This however does not means that the subtest has failed. We can and
            # still use xfstests.log output to parse subtest count and extract
            # failed test status and messages in regular case.
            # Conditions for failure :
            # 1. XFStests.log is not found
            # 2. XFStests.log is empty
            # 3. XFStests.log EOF does not contains test summary ( implies proc fail )
            # 4. Loss of SSH connection that cannot be re-established
            # Conditions not for test failure :
            # 1. No files found in results directory
            # 2. No files found for specific test case status, i.e notrun or dmesg
            # 3. No files found for specific test case status, i.e full or out.bad
            # 4. Any other file output when xfstests.log states test status with message
            # 5. Any other file output when xfstests.log states test status without
            # 6. XFStests.log footer contains test summary ( implies proc success )
            result = f"No files found in path {result_path}"
        else:
            # Prepare file paths
            # dmesg is always generated.
            dmesg_file = result_path / f"{test_id}.dmesg"
            # ideally this file is also generated on each run. but under specific cases
            # it may not if the test even failed to execute
            full_file = result_path / f"{test_id}.full"
            # this file is generated only when the test fails, but not necessarily
            # always
            fail_file = result_path / f"{test_id}.out.bad"
            # this file is generated only when the test fails, but not necessarily
            # always
            hint_file = result_path / f"{test_id}.hints"
            # this file is generated only when the test is skipped
            notrun_file = result_path / f"{test_id}.notrun"

            # Process based on test status
            if test_status == "PASSED":
                dmesg_output = ""
                if self.node.shell.exists(dmesg_file):
                    dmesg_output = cat_tool.run(
                        str(dmesg_file), force_run=True, sudo=True
                    ).stdout
                    result = f"DMESG: {dmesg_output}"
                else:
                    result = "No diagnostic information available for passed test"
            elif test_status == "FAILED":
                # Collect dmesg info if available
                dmesg_output = ""
                if self.node.shell.exists(dmesg_file):
                    dmesg_output = cat_tool.run(
                        str(dmesg_file), force_run=True, sudo=True
                    ).stdout

                # Collect diff or file content
                diff_output = ""
                full_exists = self.node.shell.exists(full_file)
                fail_exists = self.node.shell.exists(fail_file)
                hint_exists = self.node.shell.exists(hint_file)
                if full_exists and fail_exists:
                    # Both files exist - get diff
                    diff_output = self.node.tools[Diff].comparefiles(
                        src=full_file, dest=fail_file
                    )
                elif fail_exists:
                    # Only failure output exists
                    diff_output = cat_tool.run(
                        str(fail_file), force_run=True, sudo=True
                    ).stdout
                elif full_exists:
                    # Only full log exists
                    diff_output = cat_tool.run(
                        str(full_file), force_run=True, sudo=True
                    ).stdout
                else:
                    diff_output = "No diff or failure output available"

                hint_output = ""
                if hint_exists:
                    hint_output = cat_tool.run(
                        str(hint_file), force_run=True, sudo=True
                    ).stdout

                # Construct return message with available information
                parts = []
                if diff_output:
                    parts.append(f"DIFF: {diff_output}")
                if dmesg_output:
                    parts.append(f"DMESG: {dmesg_output}")
                if hint_output:
                    parts.append(f"HINT: {hint_output}")

                result = (
                    "\n\n".join(parts)
                    if parts
                    else "No diagnostic information available"
                )

            elif test_status == "SKIPPED":
                if self.node.shell.exists(notrun_file):
                    notrun_output = cat_tool.run(
                        str(notrun_file), force_run=True, sudo=True
                    ).stdout
                    result = f"NOTRUN: {notrun_output}"
                else:
                    result = "No notrun information available"
            else:
                # If we get here, no relevant files were found for the given test status
                result = (
                    f"No relevant output files found for test case {case} "
                    f"with status {test_status}"
                )
        return result

    def get_os_id_version(self) -> str:
        """
        Extracts OS information from node.os.information.
        Returns a string in the format "<vendor>_<release>".
        If OS information is not available, returns "unknown".
        """
        try:
            os_info = self.node.os.information
            vendor = getattr(os_info, "vendor", "")
            release = getattr(os_info, "release", "")

            if not vendor or not release:
                return "unknown"

            return f"{vendor}_{release}"
        except Exception:
            return "unknown"
