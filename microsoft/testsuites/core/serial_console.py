import time

from assertpy.assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.features import SerialConsole


@TestSuiteMetadata(
    area="serial_console",
    category="functional",
    description="""
    This tests functionality of connecting to serial console.
    """,
)
class SerialConsoleSuite(TestSuite):
    @TestCaseMetadata(
        description="""
        The test runs `echo back` command on serial console and verifies
        that the command has been successfully put to the
        serial console.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_features=[SerialConsole],
        ),
    )
    def verify_serial_console(self, log: Logger, node: Node) -> None:
        command = "echo back"
        serial_console = node.features[SerialConsole]

        # retry to read serial console output, because it may not be ready
        for _ in range(180):
            _ = serial_console.read()
            serial_console.write(command)
            output = serial_console.read()

            # check if the output contains the command
            if command in output:
                break

            # sleep for 1 second
            time.sleep(1)

        assert_that(
            output, "output from serial console should contain command"
        ).contains(command)
