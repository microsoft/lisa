# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
"""
Xfstests Tool Module
====================

This module provides the Xfstests tool wrapper and parallel execution infrastructure
for LISA (Linux Integration Services Automation) framework.

Key Components:
---------------
1. Xfstests (Tool class): Wraps the xfstests filesystem testing suite
2. XfstestsParallelRunner (dataclass): Manages parallel test execution across workers
3. XfstestsResult / XfstestsRunResult (dataclasses): Result containers

Parallel Execution Architecture (January 2026 Enhancement):
-----------------------------------------------------------
The parallel execution feature was added to significantly reduce test runtime for
Azure File Share (CIFS) testing. The key design decisions:

**Problem Statement:**
- Single-threaded xfstests execution of 91 tests took ~45+ minutes
- Azure File Share tests are I/O bound, not CPU bound
- Network latency dominates test time; parallelization is effective

**Solution:**
- Multiple isolated xfstests directory copies (workers)
- Each worker has its own Azure File Share pair (test + scratch)
- Workers execute in parallel using LISA's run_in_parallel()
- Results are aggregated after all workers complete

**Why Worker Directory Copies?**
xfstests uses several files in its working directory that cause race conditions:
- results/check.log: Test results log (all workers would overwrite)
- check.time: Timing information
- results/{section}/: Test output files per section
- exclude.txt: Exclusion list (must be worker-specific for logging)

Creating full directory copies at /tmp/xfs_worker_{N} ensures isolation.

**SSH Contention Fix (Critical):**
During parallel execution, SSH calls can block when multiple threads compete
for connections. The original code had:
    if self.node.shell.exists(exclude_file_path):  # SSH call - BLOCKS!
        ...

This caused Worker 1 to hang indefinitely while Workers 2 & 3 completed their
8-11 minute test runs. The fix: always include `-E exclude.txt` in the check
command. xfstests handles missing/empty exclude files gracefully, eliminating
the SSH call entirely.

Performance Results:
- Before parallelization: ~45+ minutes (sequential)
- After (3 workers): ~24 minutes (limited by slowest worker)
- Expected with 4 workers: ~18-20 minutes (with better load balancing)

Load Balancing Note:
--------------------
Current implementation uses round-robin test distribution by count, not by
estimated runtime. This can cause imbalance when tests have varying durations
(e.g., 0s to 285s). Future enhancement: implement runtime-aware distribution.

Usage Example:
--------------
    runner = XfstestsParallelRunner(
        xfstests=xfstests,
        log=log,
        worker_count=3,
    )
    runner.create_workers()
    try:
        batches = runner.split_tests(all_tests)
        results = runner.run_parallel(
            test_batches=batches,
            log_path=log_path,
            result=result,
            test_section="cifs",
            timeout=3600,
        )
        runner.aggregate_results(results)  # Raises if any failures
    finally:
        runner.cleanup_workers()
"""
import re
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path, PurePath, PurePosixPath
from typing import Any, Callable, Dict, List, Optional, Type, cast

from assertpy import assert_that

from lisa import Logger
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
from lisa.tools import Cat, Chmod, Diff, Echo, Git, Make, Rm, Sed
from lisa.util import (
    LisaException,
    UnsupportedDistroException,
    find_patterns_in_lines,
    generate_random_chars,
)
from lisa.util.parallel import run_in_parallel

# =============================================================================
# Constants for Parallel Execution
# =============================================================================

# Default base directory for worker xfstests copies
DEFAULT_WORKER_BASE_DIR = "/tmp"

# Worker directory naming pattern: {base_dir}/xfs_worker_{id}
WORKER_DIR_PREFIX = "xfs_worker_"

# Timeout buffer (seconds) subtracted from total before dividing among workers
PARALLEL_TIMEOUT_BUFFER = 60

# Extra timeout (seconds) added to each worker's share
PARALLEL_TIMEOUT_PADDING = 30


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class XfstestsResult:
    """Individual test case result from xfstests output parsing."""

    name: str = ""
    status: TestStatus = TestStatus.QUEUED
    message: str = ""


@dataclass
class XfstestsRunResult:
    """
    Result object returned by run_test() to support parallel execution.
    Instead of raising immediately on failure, this allows callers to
    aggregate results from multiple parallel runs before deciding how to fail.
    """

    success: bool = True
    fail_count: int = 0
    total_count: int = 0
    fail_cases: List[str] = field(default_factory=list)
    fail_info: str = ""
    run_id: str = ""
    test_section: str = ""

    def get_failure_message(self) -> str:
        """Generate a formatted failure message for this run."""
        if self.success:
            return ""
        return (
            f"[{self.run_id}] Fail {self.fail_count} of {self.total_count} cases, "
            f"\n\nfail cases: {self.fail_cases}, "
            f"\n\ndetails: \n\n{self.fail_info}"
        )


# =============================================================================
# Parallel Execution Runner
# =============================================================================


@dataclass
class XfstestsParallelRunner:
    """
    Manages parallel execution of xfstests across multiple workers.

    This class encapsulates all parallel execution logic for running xfstests
    across multiple isolated worker directories. It is primarily designed for
    Azure File Share (CIFS) testing where parallelization significantly reduces
    test runtime.

    Architecture Overview:
    ----------------------
    Each worker gets:
    - Its own xfstests directory copy at {base_dir}/xfs_worker_{id}
    - Separate configuration (local.config, exclude.txt)
    - Independent test/scratch mount points (configured externally)

    This isolation prevents race conditions on shared files like:
    - results/check.log (test output)
    - check.time (timing data)
    - results/{section}/ (per-test outputs)

    Workflow:
    ---------
    1. create_workers() - Copy xfstests to worker directories
    2. (External) Configure each worker's local.config and mounts
    3. split_tests() - Distribute tests across workers
    4. run_parallel() - Execute all workers simultaneously
    5. aggregate_results() - Combine results, optionally raise on failure
    6. cleanup_workers() - Remove worker directories

    Example:
        runner = XfstestsParallelRunner(xfstests=xfstests, log=log, worker_count=3)
        runner.create_workers()
        try:
            batches = runner.split_tests(test_list)
            results = runner.run_parallel(batches, log_path, result, "cifs", 3600)
            runner.aggregate_results(results)
        finally:
            runner.cleanup_workers()
    """

    xfstests: "Xfstests"
    log: Logger
    worker_count: int = 1
    base_dir: str = DEFAULT_WORKER_BASE_DIR

    # State tracking - populated by create_workers()
    worker_paths: List[PurePath] = field(default_factory=list)

    def worker_ids(self) -> range:
        """
        Return range of worker IDs (1-based).

        Use this helper to iterate over workers consistently:
            for worker_id in runner.worker_ids():
                # worker_id is 1, 2, 3, ... worker_count
        """
        return range(1, self.worker_count + 1)

    def split_tests(self, test_list: List[str]) -> List[List[str]]:
        """
        Split tests into batches using simple round-robin distribution.

        Note: This distributes by count, not by estimated runtime. Tests with
        varying durations (0s to 285s) may cause worker imbalance. Future
        enhancement: implement runtime-aware distribution.

        Args:
            test_list: List of test case names (e.g., ["generic/001", "generic/007"])

        Returns:
            List of test lists, one per worker (indexed 0 to worker_count-1)
        """
        batches: List[List[str]] = [[] for _ in range(self.worker_count)]

        for i, test in enumerate(test_list):
            batches[i % self.worker_count].append(test)

        self.log.debug(
            f"Split {len(test_list)} tests into {self.worker_count} batches: "
            f"{[len(b) for b in batches]} tests each"
        )
        return batches

    def create_workers(self) -> List[PurePath]:
        """
        Create isolated xfstests directory copies for all workers.

        Each worker directory is a full copy of the xfstests installation,
        allowing independent configuration and execution without conflicts.

        Returns:
            List of paths to worker xfstests directories (indexed 0 to worker_count-1)
        """
        self.log.info(
            f"Creating {self.worker_count} worker xfstests directory copies..."
        )
        self.worker_paths = []

        for worker_id in self.worker_ids():
            self.log.debug(f"Worker {worker_id}: Creating xfstests directory copy")
            worker_path = self.xfstests.create_worker_copy(
                worker_id=worker_id,
                base_dir=self.base_dir,
            )
            self.worker_paths.append(worker_path)
            self.log.debug(
                f"Worker {worker_id}: xfstests copy created at {worker_path}"
            )

        self.log.info(f"Created {len(self.worker_paths)} worker directories")
        return self.worker_paths

    def cleanup_workers(self) -> None:
        """
        Remove all worker xfstests directory copies.

        Safe to call even if workers were not created - cleanup failures
        are logged at DEBUG level and do not raise exceptions.
        """
        self.log.debug("Cleaning up worker xfstests directories...")
        for worker_id in self.worker_ids():
            try:
                self.xfstests.cleanup_worker_copy(
                    worker_id=worker_id,
                    base_dir=self.base_dir,
                )
            except Exception as e:
                self.log.debug(
                    f"Worker {worker_id} cleanup failed (may not exist): {e}"
                )
        self.worker_paths = []

    def run_parallel(
        self,
        test_batches: List[List[str]],
        log_path: Path,
        result: TestResult,
        test_section: str,
        timeout: int,
        test_group: str = "",
        run_id_prefix: str = "worker",
    ) -> List["XfstestsRunResult"]:
        """
        Execute xfstests in parallel across all workers.

        Args:
            test_batches: List of test lists, one per worker (from split_tests())
            log_path: Path where xfstests logs will be saved
            result: LISA TestResult object for subtest reporting
            test_section: Test section name (e.g., "cifs", "ext4")
            timeout: Total timeout in seconds (will be divided among workers)
            test_group: Test group (e.g., "generic/quick"), empty for explicit tests
            run_id_prefix: Prefix for worker run IDs (default: "worker")

        Returns:
            List of XfstestsRunResult objects, one per worker
        """
        if not self.worker_paths:
            raise LisaException(
                "No worker paths available. Call create_workers() first."
            )

        if len(test_batches) != self.worker_count:
            raise LisaException(
                f"Batch count ({len(test_batches)}) != "
                f"worker count ({self.worker_count})"
            )

        # Calculate per-worker timeout:
        # (total - buffer) / workers + padding per worker
        # Example: (14400 - 60) / 4 + 30 = 3615 seconds per worker
        worker_timeout = (
            (timeout - PARALLEL_TIMEOUT_BUFFER) // self.worker_count
            + PARALLEL_TIMEOUT_PADDING
        )

        def run_worker(
            worker_id: int,
            tests: List[str],
            worker_path: PurePath,
        ) -> "XfstestsRunResult":
            """Execute xfstests for a single worker."""
            run_id = f"{run_id_prefix}_{worker_id}"
            self.log.info(
                f"Worker {worker_id}: Starting {len(tests)} tests from {worker_path}"
            )
            test_cases_str = " ".join(tests)
            worker_result = self.xfstests.run_test(
                test_section=test_section,
                test_group=test_group,
                log_path=log_path,
                result=result,
                test_cases=test_cases_str,
                timeout=worker_timeout,
                run_id=run_id,
                raise_on_failure=False,
                xfstests_path=worker_path,
            )
            # Log completion with result summary at INFO level for console visibility
            status = "PASSED" if worker_result.success else "FAILED"
            self.log.info(
                f"Worker {worker_id}: {status} - "
                f"{worker_result.total_count} tests, "
                f"{worker_result.fail_count} failed"
            )
            return worker_result

        # Create task list for parallel execution
        tasks: List[Callable[[], "XfstestsRunResult"]] = []
        for worker_id, batch in enumerate(test_batches, start=1):
            if batch:
                worker_path = self.worker_paths[worker_id - 1]
                tasks.append(partial(run_worker, worker_id, batch, worker_path))
                self.log.debug(
                    f"Worker {worker_id}: Queued {len(batch)} tests: "
                    f"{batch[:3]}{'...' if len(batch) > 3 else ''}"
                )

        # Execute all workers in parallel
        self.log.info(f"Starting {len(tasks)} parallel xfstests workers...")
        worker_results = run_in_parallel(tasks, log=self.log)
        self.log.info("All parallel workers completed")

        return worker_results

    def aggregate_results(
        self,
        worker_results: List["XfstestsRunResult"],
        raise_on_failure: bool = True,
    ) -> tuple[int, int, bool]:
        """
        Aggregate and log results from all workers.

        Args:
            worker_results: List of results from run_parallel()
            raise_on_failure: If True, raises LisaException when any tests fail

        Returns:
            Tuple of (total_passed, total_failed, any_failures)

        Raises:
            LisaException: If raise_on_failure=True and any worker failed
        """
        total_passed = 0
        total_failed = 0
        any_failures = False

        for worker_result in worker_results:
            if worker_result.success:
                self.log.info(
                    f"Worker {worker_result.run_id}: PASSED "
                    f"({worker_result.total_count} tests)"
                )
                total_passed += worker_result.total_count
            else:
                self.log.error(
                    f"Worker {worker_result.run_id}: FAILED "
                    f"({worker_result.fail_count}/{worker_result.total_count} "
                    f"tests failed)"
                )
                total_passed += worker_result.total_count - worker_result.fail_count
                total_failed += worker_result.fail_count
                any_failures = True

        self.log.info(
            f"Parallel xfstests summary: {total_passed} passed, "
            f"{total_failed} failed across {len(worker_results)} workers"
        )

        # Raise if any worker failed and raise_on_failure is True
        if any_failures and raise_on_failure:
            failed_results = [r for r in worker_results if not r.success]
            total_tests = sum(r.total_count for r in worker_results)
            all_fail_cases: List[str] = []
            for r in failed_results:
                all_fail_cases.extend(r.fail_cases)
            combined_fail_info = "\n\n".join(
                r.get_failure_message() for r in failed_results
            )
            raise LisaException(
                f"Parallel xfstests failed: {total_failed} of {total_tests} "
                f"tests failed across {len(failed_results)} workers.\n\n"
                f"Failed test cases: {all_fail_cases}\n\n"
                f"Details:\n{combined_fail_info}"
            )

        return total_passed, total_failed, any_failures


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
    # that require specific xfstests versions due to build or compatibility issues.
    # NOTE: Most distros should work with master branch after the autoreconf fix.
    # Only add entries here for distros that have confirmed issues with master.
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
    # the default branch will be used from line 45 (master).
    # NOTE: This table is retained for fallback purposes. Add distros here only
    # if they fail to build with master branch even after running autoreconf.
    os_recommended_tags: Dict[str, str] = {
        # Older RHEL/CentOS 7.x may have toolchain issues with master
        "Red Hat_7": "v2024.02.09",
        "CentOS_7": "v2024.02.09",
        # SLES versions with kernel header incompatibilities (rw_hint.c issue)
        "SLES_15.5": "v2025.04.27",
        "SLES_12.5": "v2024.12.22",
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
        "pkg-config",  # Required for autoreconf to expand PKG_CHECK_MODULES macros
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
        "libgcrypt20-dev",
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
        "pkgconfig",  # pkg-config for RHEL/Fedora (alternative: pkgconf-pkg-config)
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
        run_id: str = "",
        raise_on_failure: bool = True,
        xfstests_path: Optional[PurePath] = None,
    ) -> XfstestsRunResult:
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
        run_id(str): (Optional)Unique identifier for this test run. Used to create
            unique log filenames to support multiple concurrent xfstests instances.
            If not provided, defaults to test_section or generates a random ID.
        raise_on_failure(bool): (Optional)If True (default), raises LisaException when
            tests fail. If False, returns XfstestsRunResult without raising, allowing
            callers to aggregate results from multiple parallel runs before failing.
        xfstests_path(PurePath): (Optional)Custom xfstests directory path. Used for
            parallel worker execution where each worker needs its own directory copy
            to avoid shared state conflicts. If not provided, uses the default
            installation path from get_xfstests_path().
        Returns:
            XfstestsRunResult: Object containing success status, failure counts, and
            failure details. When raise_on_failure=True and tests fail, raises
            LisaException instead of returning.
        Example:
        # Traditional usage (raises on failure):
        xfstest.run_test(
            log_path=Path("/tmp/xfstests"),
            result=test_result,
            test_section="ext4"
            test_group="generic/quick",
            data_disk="/dev/sdd",
            test_cases="generic/001 generic/002",
            timeout=14400,
            run_id="ext4_run1",
        )

        # Parallel execution usage (collect results, fail later):
        result1 = xfstest.run_test(..., raise_on_failure=False)
        result2 = xfstest.run_test(..., raise_on_failure=False)
        if not result1.success or not result2.success:
            combined = result1.get_failure_message() + result2.get_failure_message()
            raise LisaException(combined)

        # Parallel execution with worker copies:
        worker_path = xfstest.create_worker_copy(worker_id=1)
        result = xfstest.run_test(..., xfstests_path=worker_path)
        """
        # Note : the sequence is important here.
        # Do not rearrange !!!!!
        # Refer to xfstests-dev guide on https://github.com/kdave/xfstests

        # Use custom path if provided, otherwise use default installation path
        working_path = xfstests_path if xfstests_path else self.get_xfstests_path()

        # Generate unique run_id if not provided to support multiple concurrent runs.
        # This creates unique log filenames preventing conflicts when multiple
        # xfstests instances run on the same machine.
        if not run_id:
            run_id = test_section if test_section else generate_random_chars()

        # Use unique log filenames based on run_id to prevent conflicts
        # when multiple xfstests instances run concurrently
        console_log_name = f"xfstest_{run_id}.log"
        check_log_name = f"check_{run_id}.log"

        # Build command line arguments for xfstests check script.
        # Always include -E exclude.txt - xfstests handles missing/empty gracefully.
        # This avoids SSH exists() check which blocks in parallel execution.
        cmd = ""
        if test_group:
            cmd += f" -g {test_group}"
        if test_section:
            cmd += f" -s {test_section}"
        cmd += " -E exclude.txt"
        if test_cases:
            cmd += f" {test_cases}"
        # Redirect output to unique log file based on run_id
        cmd += f" > {console_log_name} 2>&1"

        # Build the check command with proper path for worker directories.
        # We use node.execute() directly instead of self.run() because self.run()
        # always prepends self.command (the original installation path), which
        # would run from the wrong directory when using worker copies.
        # The check script must run from its own directory to find its configs.
        check_cmd = f"{working_path}/check{cmd}"

        run_result = XfstestsRunResult(run_id=run_id, test_section=test_section)
        try:
            # Log the command being executed for debugging parallel execution
            self._log.debug(
                f"[{run_id}] Executing xfstests: {check_cmd[:100]}..."
                if len(check_cmd) > 100
                else f"[{run_id}] Executing xfstests: {check_cmd}"
            )
            self.node.execute(
                check_cmd,
                sudo=True,
                shell=True,
                cwd=working_path,
                timeout=timeout,
            )
            self._log.debug(f"[{run_id}] xfstests execution completed")
        except Exception as e:
            self._log.error(f"[{run_id}] xfstests execution failed: {e}")
            raise
        finally:
            self._log.debug(f"[{run_id}] Checking test results...")
            run_result = self.check_test_results(
                log_path=log_path,
                test_section=test_section if test_section else "generic",
                result=result,
                data_disk=data_disk,
                console_log_name=console_log_name,
                check_log_name=check_log_name,
                run_id=run_id,
                xfstests_path=working_path,
            )

        # Raise exception if tests failed and raise_on_failure is True
        # This maintains backward compatibility with existing callers
        if not run_result.success and raise_on_failure:
            raise LisaException(
                f"Fail {run_result.fail_count} cases of total "
                f"{run_result.total_count}, "
                f"\n\nfail cases: {run_result.fail_cases}, "
                f"\n\ndetails: \n\n{run_result.fail_info}, \n\nplease investigate."
            )

        return run_result

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

        # Filter packages to only those available in the repo, then batch install.
        # This is significantly faster than installing one-by-one as it reduces
        # SSH command overhead from ~100 commands to ~52 for 50 packages.
        available_packages = [
            pkg for pkg in package_list if posix_os.is_package_in_repo(pkg)
        ]
        if available_packages:
            posix_os.install_packages(available_packages)
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

        # Remove source files that have kernel header compatibility issues.
        # splice2pipe.c and rw_hint.c use kernel macros that may not exist
        # in older kernel headers (e.g., RWH_WRITE_LIFE_NOT_SET on SLES 15 SP5).
        files_to_remove = ["splice2pipe", "rw_hint"]
        for file_name in files_to_remove:
            self.node.tools[Rm].remove_file(str(code_path / "src" / f"{file_name}.c"))
            self.node.tools[Sed].substitute(
                regexp=file_name,
                replacement="",
                file=str(code_path / "src" / "Makefile"),
            )

        # Regenerate configure script to fix PKG_CHECK_MODULES macro expansion issue.
        # The pre-generated configure script in xfstests-dev git repo may have
        # unexpanded PKG_CHECK_MODULES macros if it was generated without pkg-config.
        # Running autoreconf ensures the macros are properly expanded.
        self.node.execute(
            "autoreconf -fi",
            cwd=code_path,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "autoreconf failed. Ensure autoconf, automake, libtool, "
                "and pkg-config are installed."
            ),
        )

        # Copy xfstests' custom install-sh script to the root directory.
        # The xfstests project uses its own install-sh (different from autotools)
        # located in include/install-sh. This script is referenced by Makefiles
        # in subdirectories and must be in the root for 'make install' to work.
        # See xfstests Makefile 'configure' target:
        # https://github.com/kdave/xfstests/blob/main/Makefile#L72
        self.node.execute(
            "cp include/install-sh .",
            cwd=code_path,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Failed to copy include/install-sh to root directory."
            ),
        )

        # Copy config.sub and config.guess from automake to the xfstests root.
        # Some distros (like SLES) don't have autoreconf copy these files
        # automatically. The configure script needs these files to determine
        # the build system type. We find and copy them from automake's share dir.
        # Note: Using shell=True for glob expansion to handle different automake
        # version directories (e.g., automake-1.15.1, automake-1.16.5).
        self.node.execute(
            "cp /usr/share/automake-*/config.sub "
            "/usr/share/automake-*/config.guess .",
            cwd=code_path,
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Failed to copy config.sub/config.guess from automake. "
                "Ensure automake is installed."
            ),
        )

        make.make_install(code_path)
        return True

    def get_xfstests_path(self) -> PurePath:
        return self._code_path

    def create_worker_copy(
        self,
        worker_id: int,
        base_dir: str = "/tmp",
    ) -> PurePath:
        """
        Create an isolated copy of the xfstests directory for a worker.

        When running multiple xfstests instances in parallel, each instance needs
        its own directory copy to avoid shared state conflicts. The xfstests tool
        uses several files in its working directory that cause race conditions:
        - results/check.log: Test results log
        - check.time: Timing information
        - results/{section}/: Test output files

        This method creates a full copy of the xfstests installation at
        {base_dir}/xfs_worker_{worker_id} for isolated parallel execution.

        Args:
            worker_id: Unique identifier for this worker (1-based)
            base_dir: Base directory for worker copies (default: /tmp)

        Returns:
            PurePath: Path to the worker's xfstests directory copy
        """
        # Use PurePosixPath since the remote machine is Linux
        # PurePath would use backslashes on Windows host, breaking Linux paths
        worker_path = PurePosixPath(f"{base_dir}/xfs_worker_{worker_id}")
        source_path = self.get_xfstests_path()

        self._log.debug(f"Creating worker {worker_id} xfstests copy at {worker_path}")

        # Remove existing directory if present
        self.node.execute(f"rm -rf {worker_path}", sudo=True)

        # Create directory and copy xfstests
        # Using cp -a to preserve permissions and symlinks
        self.node.execute(f"mkdir -p {base_dir}", sudo=True)
        result = self.node.execute(
            f"cp -a {source_path} {worker_path}",
            sudo=True,
            timeout=300,  # Copy can take time for large directories
        )
        if result.exit_code != 0:
            raise LisaException(
                f"Failed to create worker {worker_id} copy: {result.stderr}"
            )

        # Ensure proper permissions for the worker directory
        self.node.execute(f"chmod -R a+rwx {worker_path}", sudo=True)

        self._log.debug(f"Worker {worker_id} xfstests copy created at {worker_path}")
        return worker_path

    def cleanup_worker_copy(
        self,
        worker_id: int,
        base_dir: str = "/tmp",
    ) -> None:
        """
        Remove a worker's xfstests directory copy.

        Args:
            worker_id: Unique identifier for the worker
            base_dir: Base directory containing worker copies (default: /tmp)
        """
        worker_path = f"{base_dir}/xfs_worker_{worker_id}"
        self._log.debug(f"Cleaning up worker {worker_id} directory: {worker_path}")
        self.node.execute(f"rm -rf {worker_path}", sudo=True)

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
        xfstests_path: Optional[PurePath] = None,
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
            xfstests_path (PurePath): (O)Custom xfstests directory path for worker
                execution. If not provided, uses the default path from
                get_xfstests_path().
        """
        # Use custom path if provided, otherwise use default installation path
        working_path = xfstests_path if xfstests_path else self.get_xfstests_path()
        config_path = working_path / "local.config"
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

    def set_excluded_tests(
        self,
        exclude_tests: str,
        xfstests_path: Optional[PurePath] = None,
    ) -> None:
        """
        About:This method will create an exclude.txt file with the provided test cases.
        The exclude.txt file is used by XFStest to exclude specific test cases from
        running.
        The method takes in the following parameters:
        exclude_tests: The test cases to be excluded from testing
        Parameters:
        exclude_tests (str): The test cases to be excluded from testing
        xfstests_path (PurePath): (O)Custom xfstests directory path for worker
            execution. If not provided, uses the default path from get_xfstests_path().
        Example Usage:
        xfstest.set_excluded_tests(exclude_tests="generic/001 generic/002")
        """
        if exclude_tests:
            # Use custom path if provided, otherwise use default installation path
            working_path = xfstests_path if xfstests_path else self.get_xfstests_path()
            exclude_file_path = working_path / "exclude.txt"
            if self.node.shell.exists(exclude_file_path):
                self.node.shell.remove(exclude_file_path)

            # Write all exclusions in a single command for efficiency.
            # Previous implementation used one echo per test case, causing
            # 50+ SSH roundtrips for typical exclusion lists.
            # Now we join all tests with newlines and write once.
            exclude_list = exclude_tests.split()
            content = "\n".join(exclude_list)
            echo = self.node.tools[Echo]
            echo.write_to_file(content, exclude_file_path, append=False)

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
        console_log_name: str = "xfstest.log",
        check_log_name: str = "check.log",
        run_id: str = "",
        xfstests_path: Optional[PurePath] = None,
    ) -> XfstestsRunResult:
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
        console_log_name: The name of the console log file (default: xfstest.log)
            Used to support multiple concurrent xfstests instances with unique
            log files.
        check_log_name: The name of the check log file (default: check.log)
            Used to support multiple concurrent xfstests instances with unique
            check log files.
        run_id: Unique identifier for this test run (used in result object)
        xfstests_path: Optional custom xfstests directory path for worker execution.
            If not provided, uses the default path from get_xfstests_path().
        Returns:
            XfstestsRunResult: Object containing success status and failure details.
        """
        # Use custom path if provided, otherwise use default installation path
        working_path = xfstests_path if xfstests_path else self.get_xfstests_path()
        console_log_results_path = working_path / console_log_name
        results_path = working_path / "results/check.log"
        fail_cases_list: List[str] = []
        run_result = XfstestsRunResult(
            run_id=run_id or test_section,
            test_section=test_section,
        )
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
                    run_result.success = True
                    run_result.total_count = int(pass_count)
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
                    # Populate the result object instead of raising
                    run_result.success = False
                    run_result.fail_count = int(fail_count)
                    run_result.total_count = int(total_count)
                    run_result.fail_cases = fail_cases_list
                    run_result.fail_info = fail_info
                else:
                    # Mark the fail count as zero, else code will fail since we never
                    # fetch fail_count from regex.This variable is used in Finally block
                    fail_count = 0
                    run_result.success = True
                    self._log.debug("No failed cases found in xfstests.")
        finally:
            self.save_xfstests_log(
                fail_cases_list,
                log_path,
                test_section,
                console_log_name,
                check_log_name,
                xfstests_path=working_path,
            )
            results_folder = working_path / "results/"
            self.node.execute(f"rm -rf {results_folder}", sudo=True)
            self.node.execute(f"rm -f {console_log_results_path}", sudo=True)
        return run_result

    def save_xfstests_log(
        self,
        fail_cases_list: List[str],
        log_path: Path,
        test_section: str,
        console_log_name: str = "xfstest.log",
        check_log_name: str = "check.log",
        xfstests_path: Optional[PurePath] = None,
    ) -> None:
        """
        About:This method is intended to be called by check_test_results method only.
        This method will copy the output of XFSTest results to the Log folder of host
        calling LISA. Files copied are xfsresult.log, check.log and all failed cases
        files if they exist.
        Parameters:
        fail_cases_list: List of failed test case names
        log_path: The path where the xfstests logs will be saved on the host
        test_section: The test section name used for testing
        console_log_name: The name of the console log file (default: xfstest.log)
            Used to support multiple concurrent xfstests instances with unique
            log files.
        check_log_name: The name of the check log file (default: check.log)
            Used to support multiple concurrent xfstests instances with unique
            check log files.
        xfstests_path: Optional custom xfstests directory path for worker execution.
            If not provided, uses the default path from get_xfstests_path().
        """
        # Use custom path if provided, otherwise use default installation path
        working_path = xfstests_path if xfstests_path else self.get_xfstests_path()
        self.node.tools[Chmod].update_folder(str(working_path), "a+rwx", sudo=True)
        if self.node.shell.exists(working_path / "results/check.log"):
            self.node.shell.copy_back(
                working_path / "results/check.log",
                log_path / f"xfstests/{check_log_name}",
            )
        console_log_path = working_path / console_log_name
        if self.node.shell.exists(console_log_path):
            self.node.shell.copy_back(
                console_log_path,
                log_path / f"xfstests/{console_log_name}",
            )

        for fail_case in fail_cases_list:
            file_name = f"results/{test_section}/{fail_case}.out.bad"
            result_path = working_path / file_name
            if self.node.shell.exists(result_path):
                self.node.shell.copy_back(result_path, log_path / file_name)
            else:
                self._log.debug(f"{file_name} doesn't exist.")
            file_name = f"results/{test_section}/{fail_case}.full"
            result_path = working_path / file_name
            if self.node.shell.exists(result_path):
                self.node.shell.copy_back(result_path, log_path / file_name)
            else:
                self._log.debug(f"{file_name} doesn't exist.")
            file_name = f"results/{test_section}/{fail_case}.dmesg"
            result_path = working_path / file_name
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
