# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

from assertpy import assert_that

from lisa import (
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import BSD, Windows
from lisa.sut_orchestrator import AZURE, HYPERV, READY
from lisa.tools import KernelConfig, Python


@TestSuiteMetadata(
    area="network",
    category="functional",
    description="""
    This test suite validates INET_DIAG functionality, particularly
    the INET_DIAG_DESTROY feature which allows administrative termination
    of TCP connections via netlink socket interface. This is useful for
    forcefully closing stuck connections or cleaning up resources.
    """,
    requirement=simple_requirement(
        supported_platform_type=[AZURE, READY, HYPERV],
        unsupported_os=[BSD, Windows],
    ),
)
class InetDiagSuite(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case verifies that the INET_DIAG_DESTROY kernel feature
        works correctly by creating a TCP connection and then destroying it
        using the ss (socket statistics) command.

        Steps:
        1. Check if CONFIG_INET_DIAG_DESTROY is enabled in kernel config.
        2. Create an established TCP connection using Python sockets.
        3. Verify the connection exists using ss command.
        4. Destroy the connection using 'ss -K' (kill socket).
        5. Verify the connection was destroyed (no longer visible).
        6. Verify attempting to use the socket fails with connection reset.
        7. Clean up any remaining connections.

        """,
        priority=2,
    )
    def verify_inet_diag_destroy(self, node: Node) -> None:
        kernel_config = node.tools[KernelConfig]
        python = node.tools[Python]

        # Check kernel configuration
        if not kernel_config.is_enabled("CONFIG_INET_DIAG"):
            raise SkippedException("CONFIG_INET_DIAG is not enabled in kernel")

        if not kernel_config.is_enabled("CONFIG_INET_DIAG_DESTROY"):
            raise SkippedException("CONFIG_INET_DIAG_DESTROY is not enabled in kernel")

        # Verify ss command exists and supports -K flag
        ss_version = node.execute("ss --version", shell=True)
        assert_that(ss_version.exit_code).described_as(
            "ss command should be available"
        ).is_equal_to(0)

        # Run the test directly using python -c instead of creating a file
        test_script_cmd = f"""{python.command} -c '
import socket, subprocess, time, sys, threading

test_port = 34567
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("127.0.0.1", test_port))
server.listen(1)
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

accepted_conns = []
def accept_conn():
    conn, addr = server.accept()
    accepted_conns.append(conn)
    time.sleep(30)

accept_thread = threading.Thread(target=accept_conn, daemon=True)
accept_thread.start()
time.sleep(0.5)
client.connect(("127.0.0.1", test_port))
time.sleep(1)

result = subprocess.run(
    ["ss", "-tn", "sport", "=", str(test_port)],
    capture_output=True, text=True
)
if "ESTAB" not in result.stdout:
    print("ERROR: Connection not established")
    sys.exit(1)
print("BEFORE: Connection established on port", test_port)

destroy_result = subprocess.run(
    ["sudo", "ss", "-K", "sport", "=", str(test_port)],
    capture_output=True, text=True
)
print("DESTROY: ss -K exit code:", destroy_result.returncode)
time.sleep(1)

check_result = subprocess.run(
    ["ss", "-tn", "sport", "=", str(test_port)],
    capture_output=True, text=True
)
print("AFTER: Checking for connection")
if "ESTAB" in check_result.stdout:
    print("ERROR: Connection still exists after ss -K")
    sys.exit(1)

try:
    client.send(b"test")
    print("ERROR: Socket still works")
    sys.exit(1)
except (BrokenPipeError, ConnectionResetError, OSError) as e:
    print("SUCCESS: Socket properly destroyed -", type(e).__name__)

server.close()
client.close()
print("TEST PASSED")
'"""

        # Run the test script
        result = node.execute(
            test_script_cmd,
            shell=True,
            sudo=True,
            timeout=60,
        )

        # Check the output
        node.log.debug(f"Test script output:\n{result.stdout}")
        if result.stderr:
            node.log.debug(f"Test script stderr:\n{result.stderr}")

        # Verify the test passed
        assert_that(result.exit_code).described_as(
            "inet_diag_destroy test script should complete successfully"
        ).is_equal_to(0)

        assert_that(result.stdout).described_as(
            "Test should report successful socket destruction"
        ).contains("SUCCESS: Socket properly destroyed")

        assert_that(result.stdout).described_as("Test should pass all checks").contains(
            "TEST PASSED"
        )

    @TestCaseMetadata(
        description="""
        This test case verifies that CONFIG_INET_DIAG is enabled in the kernel,
        which is required for socket diagnostic functionality. INET_DIAG provides
        the interface for tools like ss to query socket information.

        Steps:
        1. Check if CONFIG_INET_DIAG is enabled in kernel config.
        2. Verify ss command is available and functional.
        3. Test basic ss functionality by listing sockets.

        """,
        priority=3,
    )
    def verify_inet_diag_enabled(self, node: Node) -> None:
        kernel_config = node.tools[KernelConfig]

        # Check kernel configuration
        if not kernel_config.is_enabled("CONFIG_INET_DIAG"):
            raise SkippedException("CONFIG_INET_DIAG is not enabled in kernel")

        # Verify ss command works
        result = node.execute("ss -s", shell=True)
        assert_that(result.exit_code).described_as(
            "ss -s command should work with INET_DIAG enabled"
        ).is_equal_to(0)

        assert_that(result.stdout).described_as(
            "ss should provide socket statistics"
        ).contains("TCP:")

        node.log.info("CONFIG_INET_DIAG is enabled and functional")
