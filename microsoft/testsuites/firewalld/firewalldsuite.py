# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from typing import Any, List

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.messages import TestStatus
from lisa.operating_system import CBLMariner
from lisa.testsuite import TestResult
from lisa.tools import Cat, KernelConfig, Ls
from lisa.util import LisaException, SkippedException, UnsupportedDistroException


def _is_ipv6_rpfilter_supported(node: Node) -> bool:
    # If IPv6 reverse path filtering is enabled in firewalld's
    # configuration (IPv6_rpfilter=yes), check if node's kernel
    # is built with the necessary configs, otherwise the firewalld
    # daemon fails to start.
    cat = node.tools[Cat]
    ipv6_rpfilter_str = cat.read_with_filter(
        "/etc/firewalld/firewalld.conf", "^IPv6_rpfilter=", sudo=True
    )

    if "=yes" in ipv6_rpfilter_str:
        kconfig = node.tools[KernelConfig]
        fib_inet = kconfig.is_enabled("CONFIG_FIB_INET")
        fib_ipv6 = kconfig.is_enabled("CONFIG_FIB_IPV6")
        if not fib_inet and not fib_ipv6:
            # kernel does not support the needed configs
            return False

    return True


def _update_test_result(
    node: Node,
    log_file: str,
    log_dir: str,
    result: TestResult,
) -> None:
    # Update TestResult data to add:
    # - summary of the tests (Total/Skipped/Failed)
    # - list of failed & skipped tests
    # - overall status (PASSED/FAILED)
    cat = node.tools[Cat]
    ls = node.tools[Ls]
    if not ls.path_exists(log_file):
        raise LisaException(
            f"Consolidated firewalld test log path: {log_file} doesn't exist, "
            "please check if testing runs well or not."
        )

    total_tests = None
    failed_tests = None
    skipped_tests = None
    num_regex = r"\d+ "

    total_str = cat.read_with_filter(f"{log_file}", "tests were run", sudo=True)
    m = re.search(num_regex, total_str)
    if m:
        total_tests = m[0]

    failed_str = cat.read_with_filter(f"{log_file}", "failed unexpectedly", sudo=True)
    m = re.search(num_regex, failed_str)
    if m:
        failed_tests = m[0]

    skipped_str = cat.read_with_filter(f"{log_file}", "were skipped", sudo=True)
    m = re.search(num_regex, skipped_str)
    if m:
        skipped_tests = m[0]

    # Logs dir contains the list of failed tests.
    current_failures: List[str] = []
    failed_tests_list = ls.list_dir(log_dir, sudo=True)
    for test in failed_tests_list:
        # each entry in this list looks like
        # "/usr/share/firewalld/testsuite/testsuite.dir/123/"
        # using / as delimiter, we extract the test case number
        # in this case 123
        current_failures.append(test.split("/")[-2])

    # Note: There are known failures due to missing support for `FIB`
    # based expressions in kernel.
    # This is a constant list of failing test cases in each run.
    known_failures = [
        "061",
        "107",
        "120",
        "124",
        "192",
        "193",
        "194",
        "195",
        "196",
        "197",
        "200",
        "240",
        "252",
        "306",
        "324",
    ]

    if set(known_failures) != set(current_failures):
        raise LisaException(
            "Found unexpected failures, check logs for details\n"
            f"expected failure list: {known_failures}\n"
            f"actual failure list:   {current_failures}\n"
        )

    # Update the test result data
    result.set_status(
        TestStatus.PASSED,
        f"TOTAL:{total_tests}\nFAILED:{failed_tests}\nSKIPPED:{skipped_tests}\n",
    )


@TestSuiteMetadata(
    area="firewalld",
    category="functional",
    description="""
    This test suite is to validate firewalld daemon on Azure Linux 3.0.
    """,
)
class FirewalldSuite(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        if not isinstance(node.os, CBLMariner) or node.os.information.version < "3.0.0":
            raise SkippedException(
                UnsupportedDistroException(
                    node.os, "Firewalld testsuite is supported only on AzureLinux 3.0."
                )
            )

    @TestCaseMetadata(
        description="""
        This test case runs the firewalld testsuite.
        The test suite is a collection of tests which run against
        a local firewalld installation.
        These tests interacts with both iptables & nftables as backend.
        The set of tests run are
        1. cli: firewall-cmd client tests
        2. dbus: dbus interface tests
        3. python: python binding tests
        4. features: firewalld daemon functional tests
        5. regressions: regression tests
        The testsuite is provided by the firewalld-test rpm.
        """,
        priority=3,
    )
    def verify_firewalld(
        self,
        node: Node,
        log: Logger,
        result: TestResult,
    ) -> None:
        # Install the dependencies for running the test suite
        if isinstance(node.os, CBLMariner):
            node.os.install_packages(
                [
                    "ebtables",
                    "nftables",
                    "python3-dbus",
                    "iproute",
                    "firewalld",
                    "firewalld-test",
                ]
            )

        # Check if ipv6_rpfilter config is supported
        # Note: Right now, this is the only known config which
        # causes failure in starting firewalld daemon.
        if not _is_ipv6_rpfilter_supported(node):
            raise SkippedException(
                "Skipping tests. Needs kernel config CONFIG_FIB_INET &"
                "CONFIG_FIB_IPV6 enabled to use fib based expressions for"
                "ipv6_rpfilter configuration."
            )

        # these paths are specific to testsuite.
        test_suite_dir = "/usr/share/firewalld/testsuite"
        test_suite_binary = "/usr/share/firewalld/testsuite/testsuite"
        test_logs_dir = "/usr/share/firewalld/testsuite/testsuite.dir"
        test_log = "/usr/share/firewalld/testsuite/testsuite.log"

        # these commands are specific to testsuite binary.
        # arg to set log directory
        set_logs_dir_arg = f"-C {test_suite_dir}"

        # arg to clean test artifacts
        clean_arg = "-c"

        # arg to set number of jobs
        jobs_arg = "-j4"

        clean_command = f"{test_suite_binary} {clean_arg} {set_logs_dir_arg}"
        test_command = f"{test_suite_binary} {jobs_arg} {set_logs_dir_arg}"

        ls = node.tools[Ls]
        # Remove any artifacts generated by the testsuite.
        if ls.path_exists(test_logs_dir):
            log.info("Removing any older artifacts created by firewalld tests")
            node.execute(clean_command, sudo=True, shell=False)

        # The tests switches backend between iptables/nftables.
        # For using iptables, we need to switch back to legacy.
        for binary in ["iptables", "ip6tables", "ebtables"]:
            log.info("Switching %s to legacy mode", binary)
            cmd = f"update-alternatives --set {binary} /usr/sbin/{binary}-legacy"
            node.execute(cmd, sudo=True, shell=False)

        # Run the test
        log.info("Running tests")
        node.execute(test_command, sudo=True, shell=True, timeout=3000)

        # Update the test result
        log.info("Updating test results")
        _update_test_result(node, test_log, test_logs_dir, result)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        # Set the iptables/ip6tables/ebtables back to default nft
        node: Node = kwargs["node"]
        for binary in ["iptables", "ip6tables", "ebtables"]:
            cmd = f"update-alternatives --set {binary} /usr/sbin/{binary}-nft"
            node.execute(cmd, sudo=True, shell=False)
