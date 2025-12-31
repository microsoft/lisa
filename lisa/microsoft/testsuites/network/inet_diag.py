# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
import time
from pathlib import Path

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
from lisa.util import LisaException, create_timer


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
    _LOCALHOST = "127.0.0.1"
    _PORT_RANGE_START = 34567
    _PORT_RANGE_END = 34667

    def _find_available_port(self, node: Node) -> int:
        """
        Find an available port on the node to avoid conflicts.

        Args:
            node: The node to check for available ports

        Returns:
            An available port number

        Raises:
            LisaException: If no available port is found in the range
        """
        ss = node.tools[Ss]

        for port in range(self._PORT_RANGE_START, self._PORT_RANGE_END):
            # Check if port is already in use
            if not ss.connection_exists(port=port, sport=True):
                node.log.debug(f"Found available port: {port}")
                return port

        raise LisaException(
            f"No available ports found in range "
            f"{self._PORT_RANGE_START}-{self._PORT_RANGE_END}"
        )

    def _copy_to_node(self, node: Node, filename: str) -> None:
        """
        Copy a file from the TestScripts directory to the node's working path.

        Args:
            node: The node to copy the file to
            filename: The name of the file in the TestScripts directory
        """
        file_path = Path(os.path.dirname(__file__)) / "TestScripts" / filename
        if not node.shell.exists(node.working_path / filename):
            node.shell.copy(file_path, node.working_path / filename)

    def _wait_for_connection_state(
        self,
        node: Node,
        port: int,
        expected_state: str,
        timeout: int = 10,
        poll_interval: float = 0.5,
    ) -> bool:
        """
        Wait for a TCP connection to reach the expected state.

        Args:
            node: The node to check
            port: The port number to check
            expected_state: Expected connection state (e.g., "ESTAB", "NONE")
            timeout: Maximum time to wait in seconds
            poll_interval: Time between checks in seconds

        Returns:
            True if the expected state was reached, False otherwise
        """
        timer = create_timer()
        check_count = 0

        while timer.elapsed(stop=False) < timeout:
            check_count += 1
            ss = node.tools[Ss]
            
            if expected_state == "NONE":
                # Checking that connection does NOT exist
                connection_exists = ss.connection_exists(
                    port=port, state="ESTAB", sport=True
                )
                if not connection_exists:
                    node.log.debug(
                        f"Connection on port {port} no longer exists "
                        f"after {timer.elapsed_text(stop=False)} "
                        f"({check_count} checks)"
                    )
                    return True
            else:
                # Checking that connection exists in expected state
                connection_exists = ss.connection_exists(
                    port=port, state=expected_state, sport=True
                )
                if connection_exists:
                    node.log.debug(
                        f"Connection on port {port} reached state {expected_state} "
                        f"after {timer.elapsed_text(stop=False)} "
                        f"({check_count} checks)"
                    )
                    return True

            if check_count % 5 == 0:
                node.log.debug(
                    f"Waiting for connection on port {port} to reach state "
                    f"{expected_state}. Elapsed: {timer.elapsed_text(stop=False)}, "
                    f"checks: {check_count}"
                )

            time.sleep(poll_interval)

        node.log.warning(
            f"Timeout waiting for connection on port {port} to reach state "
            f"{expected_state}. Elapsed: {timer.elapsed_text()}, "
            f"total checks: {check_count}"
        )
        return False

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

        # Find an available port to avoid conflicts
        test_port = self._find_available_port(node)
        node.log.info(f"Using port {test_port} for TCP connection test")

        # Copy the TCP connection test script to the node
        script_filename = "lisa_tcp_test.py"
        self._copy_to_node(node, script_filename)
        script_path = node.working_path / script_filename

        connection_process = None
        try:
            # Start the connection in background with nohup to keep it alive
            node.log.debug(
                f"Starting TCP connection test script on port {test_port}"
            )
            connection_process = node.execute_async(
                f"python3 {script_path} {test_port}",
                sudo=False,
                nohup=True,
            )

            # Wait for connection to be established using robust polling
            node.log.debug("Waiting for TCP connection to be established")
            connection_ready = self._wait_for_connection_state(
                node=node,
                port=test_port,
                expected_state="ESTAB",
                timeout=15,
                poll_interval=0.5,
            )

            if not connection_ready:
                raise LisaException(
                    f"TCP connection not established on port {test_port} "
                    f"within timeout period"
                )

            node.log.info(
                f"TCP connection established successfully on port {test_port}"
            )

            # Verify connection exists using assertion
            self._verify_connection_exists(node, test_port, should_exist=True)

            # Destroy the connection using ss -K
            node.log.info(
                f"Destroying connection on port {test_port} using ss -K"
            )
            ss.kill_connection(port=test_port, sport=True, sudo=True)

            # Wait for the connection to be destroyed using robust polling
            node.log.debug("Waiting for connection to be destroyed")
            connection_destroyed = self._wait_for_connection_state(
                node=node,
                port=test_port,
                expected_state="NONE",
                timeout=10,
                poll_interval=0.3,
            )

            if not connection_destroyed:
                raise LisaException(
                    f"Connection on port {test_port} was not destroyed "
                    f"within timeout period"
                )

            # Verify connection no longer exists using assertion
            self._verify_connection_exists(node, test_port, should_exist=False)

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
