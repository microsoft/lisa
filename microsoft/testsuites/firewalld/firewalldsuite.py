# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from typing import Any, List

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.messages import TestStatus
from lisa.operating_system import CBLMariner
from lisa.testsuite import TestResult
from lisa.tools import Cat, KernelConfig, Ls
from lisa.util import LisaException, SkippedException, UnsupportedDistroException


def _supports_ipv6_rpfilter_config(node: Node) -> bool:
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
    ls = node.tools[Ls]
    if not ls.path_exists(log_file):
        raise LisaException(
            f"Consolidated firewalld test log path: {log_file} doesn't exist, "
            "please check if testing runs well or not."
        )

    cmd_total = f"cat {log_file} | grep \"tests were run\" | cut -d' ' -f 2"
    total_tests = node.execute(cmd_total, sudo=True, shell=True)

    cmd_fail = f"cat {log_file} | grep \"failed unexpectedly\" | cut -d' ' -f 1"
    tests_failed = node.execute(cmd_fail, sudo=True, shell=True)

    cmd_skip = f"cat {log_file} | grep \"were skipped\" | cut -d' ' -f 1"
    tests_skipped = node.execute(cmd_skip, sudo=True, shell=True)

    # Logs dir contains the list of failed tests.
    fail_testcase_num: List[str] = []
    failed_tests_list = ls.list_dir(log_dir, sudo=True)
    for test in failed_tests_list:
        fail_testcase_num.append(test.split("/")[-2])

    # Note: There are known failures due to missing support for `FIB`
    # based expressions in kernel.
    # This is a temporary known (and constant) list of failures
    known_fail_testcase_num = [
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

    status = TestStatus.PASSED
    if known_fail_testcase_num != fail_testcase_num:
        status = TestStatus.FAILED

    # Update the test result data
    result.set_status(
        status,
        f"TOTAL:{total_tests}\nFAILED:{tests_failed}\nSKIPPED:{tests_skipped}\n",
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
        This test runs the firewalld testsuite.
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
        if not _supports_ipv6_rpfilter_config(node):
            raise SkippedException("Skipping test, unsupported kernel config")

        # these paths are specific to testsuite.
        test_suite_dir = "/usr/share/firewalld/testsuite"
        test_suite_binary = "/usr/share/firewalld/testsuite/testsuite"
        test_logs_dir = "/usr/share/firewalld/testsuite/testsuite.dir"
        test_log = "/usr/share/firewalld/testsuite/testsuite.log"

        # these commands are specific to testsuite binary.
        clean_command = f"{test_suite_binary} -c -C {test_suite_dir}"
        test_command = f"{test_suite_binary} -j4 -C {test_suite_dir}"

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
