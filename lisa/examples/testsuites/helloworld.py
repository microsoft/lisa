# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

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
from lisa.tools import Echo, Uname


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
    )
    def bye(self, node: Node) -> None:
        node.tools.get(Echo)  # Ensure echo is in cache
        assert_that(str(node.tools.echo("bye!"))).is_equal_to("bye!")

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        log.info("before test case")

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        log.info("after test case")
