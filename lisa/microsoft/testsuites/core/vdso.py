# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from lisa import TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.node import Node
from lisa.operating_system import BSD, Windows
from lisa.testsuite import simple_requirement
from lisa.tools import Vdsotest


@TestSuiteMetadata(
    area="core",
    category="functional",
    description="""
    This test suite is used to test vdso using vdsotest benchmark.
    """,
)
class Vdso(TestSuite):
    @TestCaseMetadata(
        description="""
        This test is to check gettime, getres, getcpu and gettimeofday calls are not
        being redirected as system calls, leading to performance bottleneck, Linux
        systems have a mechanism called vdso which helps in above methods to be executed
        in userspace (no syscall).

        The kernel selftest can't be used here for two reasons:
        1. need clone all linux source code
        2. can't repro the regression issue https://bugs.launchpad.net/bugs/1977753

        Steps:
            1. Install vdsotest benchmark.
            2. Run vdsotest benchmark.
        """,
        priority=1,
        requirement=simple_requirement(
            unsupported_os=[BSD, Windows],
        ),
    )
    def verify_vdso(self, node: Node) -> None:
        vdso_test = node.tools[Vdsotest]
        vdso_test.run_benchmark()
