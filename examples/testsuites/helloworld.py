# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import time
from typing import Any

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import Posix
from lisa.testsuite import DebugHandler
from lisa.tools import Echo, Uname


class customDebugHandler(DebugHandler):
    def __init__(self) -> None:
        super().__init__()
        print("==>>>> debugHandler: _add_before_test_run")
        super()._add_before_test_run("date")
        print("==>>>> debugHandler: _add_while_test_run")
        super()._add_while_test_run("free -m")
        print("==>>>> debugHandler: _add_after_test_run")
        super()._add_after_test_run("date")


@TestSuiteMetadata(
    area="demo",
    category="functional",
    description="""
    this is an example test suite.
    it helps to understand how to write a test case.
    """,
    requirement=simple_requirement(unsupported_os=[]),
)
class HelloWorld(TestSuite):
    @TestCaseMetadata(
        description="""
        this test case use default node to
            1. get system info
            2. echo hello world!
        """,
        priority=0,
        use_new_environment=True,
        debug_handler=customDebugHandler(),
    )
    def hello(self, node: Node, log: Logger) -> None:
        if node.os.is_posix:
            assert isinstance(node.os, Posix)
            info = node.tools[Uname].get_linux_information()
            log.info(
                f"release: '{info.uname_version}', "
                f"version: '{info.kernel_version_raw}', "
                f"hardware: '{info.hardware_platform}', "
                f"os: '{info.operating_system}'"
            )
        else:
            log.info("windows operating system")

        for i in range(20):
            temp = node.execute("uname -a; sleep 5;", shell=True).stdout
            print(f"running testcase workload: {temp}")
            time.sleep(1)
            if i > 5:
                raise Exception("Check the failed flow too")

        # get process output directly.
        echo = node.tools[Echo]
        hello_world = "hello world!"
        result = echo.run(hello_world)
        assert_that(result.stdout).is_equal_to(hello_world)
        assert_that(result.stderr).is_equal_to("")
        assert_that(result.exit_code).is_equal_to(0)

    @TestCaseMetadata(
        description="""
        demonstrate a simple way to run command in one line.
        """,
        priority=1,
        # debug_handler=customDebugHandler(),
    )
    def bye(self, node: Node) -> None:
        node.tools.get(Echo)  # Ensure echo is in cache
        assert_that(str(node.tools.echo("bye!"))).is_equal_to("bye!")

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        log.info("before test case")

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        log.info("after test case")
