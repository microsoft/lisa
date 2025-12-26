# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import time

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
from lisa.tools import KernelConfig, Ss


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
    _TEST_PORT = 34567
    _LOCALHOST = "127.0.0.1"

    def _create_tcp_server_client(self) -> str:
        """
        Create a TCP server-client connection and return a Python script
        that keeps the connection alive.

        Returns:
            Python code as a string to execute
        """
        script = f"""
import socket
import sys
import time

# Create server socket
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(('{self._LOCALHOST}', {self._TEST_PORT}))
server.listen(1)

# Create client socket
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# Accept connection in background
import threading
accepted_conn = []

def accept_connection():
    conn, addr = server.accept()
    accepted_conn.append(conn)
    # Keep connection alive
    while True:
        time.sleep(1)

accept_thread = threading.Thread(target=accept_connection, daemon=True)
accept_thread.start()
time.sleep(0.5)

# Connect client
client.connect(('{self._LOCALHOST}', {self._TEST_PORT}))
time.sleep(1)

print("CONNECTION_READY")
sys.stdout.flush()

# Keep script running to maintain connection
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    client.close()
    server.close()
"""
        return script

    def _verify_connection_exists(
        self, node: Node, port: int, should_exist: bool = True
    ) -> None:
        """
        Verify whether a TCP connection exists on the specified port.

        Args:
            node: The node to check
            port: The port number to check
            should_exist: True if connection should exist, False otherwise
        """
        ss = node.tools[Ss]
        connection_exists = ss.connection_exists(port=port, state="ESTAB", sport=True)

        if should_exist:
            assert_that(connection_exists).described_as(
                f"Connection should exist on port {port}"
            ).is_true()
        else:
            assert_that(connection_exists).described_as(
                f"Connection should NOT exist on port {port}"
            ).is_false()

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
        6. Clean up any remaining connections.

        """,
        priority=2,
    )
    def verify_inet_diag_destroy(self, node: Node) -> None:
        kernel_config = node.tools[KernelConfig]
        ss = node.tools[Ss]

        # Check kernel configuration
        if not kernel_config.is_enabled("CONFIG_INET_DIAG"):
            raise SkippedException("CONFIG_INET_DIAG is not enabled in kernel")

        if not kernel_config.is_enabled("CONFIG_INET_DIAG_DESTROY"):
            raise SkippedException("CONFIG_INET_DIAG_DESTROY is not enabled in kernel")

        # Verify ss command exists and supports -K flag
        if not ss.has_kill_support():
            raise SkippedException("ss command does not support -K (kill) option")

        # Create the connection script
        script = self._create_tcp_server_client()
        script_path = "/tmp/lisa_tcp_test.py"

        # Create temporary Python script using Python's file writing
        # This is more reliable than heredoc through SSH
        write_cmd = (
            f"python3 -c \"with open('{script_path}', 'w') as f: "
            f'f.write({repr(script)})"'
        )
        node.execute(write_cmd, sudo=False)

        connection_process = None
        try:
            # Start the connection in background with nohup to keep it alive
            connection_process = node.execute_async(
                f"python3 {script_path}",
                sudo=False,
                nohup=True,
            )

            # Wait for connection to be established (check on remote node)
            max_wait = 10
            wait_interval = 0.5
            connection_ready = False

            for _ in range(int(max_wait / wait_interval)):
                time.sleep(wait_interval)

                # Check if connection is established on the remote node
                ss_check = node.execute(
                    f"ss -tn sport = {self._TEST_PORT} | grep ESTAB",
                    shell=True,
                )
                if ss_check.exit_code == 0:
                    connection_ready = True
                    break

            if not connection_ready:
                raise LookupError(
                    f"TCP connection not established on port {self._TEST_PORT} "
                    f"within {max_wait} seconds"
                )

            node.log.debug(
                f"TCP connection established successfully on port {self._TEST_PORT}"
            )

            # Verify connection exists
            node.log.debug(
                f"Checking for established connection on port {self._TEST_PORT}"
            )
            self._verify_connection_exists(node, self._TEST_PORT, should_exist=True)

            # Destroy the connection using ss -K
            node.log.info(
                f"Destroying connection on port {self._TEST_PORT} using ss -K"
            )
            ss.kill_connection(port=self._TEST_PORT, sport=True, sudo=True)

            # Wait a moment for the destruction to take effect
            time.sleep(2)

            # Verify connection no longer exists
            node.log.debug("Verifying connection was destroyed")
            self._verify_connection_exists(node, self._TEST_PORT, should_exist=False)

            node.log.info(
                "Successfully verified INET_DIAG_DESTROY functionality - "
                "connection was destroyed"
            )

        finally:
            # Clean up: kill the background process
            if connection_process:
                node.execute(
                    f"pkill -f {script_path}",
                    sudo=True,
                )
            # Remove temporary script
            node.execute(f"rm -f {script_path}", sudo=True)

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
        ss = node.tools[Ss]

        # Check kernel configuration
        if not kernel_config.is_enabled("CONFIG_INET_DIAG"):
            raise SkippedException("CONFIG_INET_DIAG is not enabled in kernel")

        # Verify ss command works
        stats = ss.get_statistics()
        assert_that(stats).described_as("ss should provide socket statistics").contains(
            "TCP:"
        )

        node.log.info("CONFIG_INET_DIAG is enabled and functional")
