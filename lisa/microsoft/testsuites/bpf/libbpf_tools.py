# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

from typing import cast

from assertpy import assert_that

from lisa import (
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import Posix
from lisa.sut_orchestrator import AZURE, HYPERV, READY


@TestSuiteMetadata(
    area="bpf",
    category="functional",
    description="""
    This test suite validates libbpf-tools package functionality.
    libbpf-tools provides eBPF-based observability tools for performance
    analysis and troubleshooting.
    """,
    requirement=simple_requirement(
        supported_platform_type=[AZURE, READY, HYPERV],
        supported_os=[Posix],
    ),
)
class LibbpfToolsSuite(TestSuite):
    def _find_tool(self, node: Node, base_tool_name: str) -> tuple[bool, str | None]:
        """
        Find a libbpf tool by checking for both prefixed and unprefixed variants.

        Different distributions use different naming conventions:
        - Fedora/RHEL: bpf-{toolname} (e.g., bpf-execsnoop)
        - Ubuntu/Debian: {toolname} (e.g., execsnoop)

        Args:
            node: The node to search on
            base_tool_name: Base name of the tool (without prefix)

        Returns:
            Tuple of (found: bool, tool_name: str | None)
        """
        for prefix in ["bpf-", ""]:
            candidate = f"{prefix}{base_tool_name}"
            which_result = node.execute(f"which {candidate}", sudo=True)
            if which_result.exit_code == 0:
                return (True, candidate)
        return (False, None)

    @TestCaseMetadata(
        description="""
        This test case verifies that the libbpf-tools package is available
        and can be installed on the system.

        Steps:
        1. Check if libbpf-tools package exists in repositories.
        2. Install the package if not already installed.
        3. Verify installation was successful.

        """,
        priority=2,
    )
    def verify_libbpf_tools_package_available(self, node: Node) -> None:
        # Cast for mypy - supported_os filter ensures node.os is Posix
        posix_os = cast(Posix, node.os)

        # Check if package is already installed
        package_exists = posix_os.package_exists("libbpf-tools")

        if not package_exists:
            # Check if package is available in repositories
            if not posix_os.is_package_in_repo("libbpf-tools"):
                raise SkippedException("libbpf-tools package not found in repositories")

            # Package is available, install it
            posix_os.install_packages("libbpf-tools")

        # Verify package is now installed
        package_installed = posix_os.package_exists("libbpf-tools")
        assert_that(package_installed).described_as(
            "libbpf-tools package should be installed"
        ).is_true()

    @TestCaseMetadata(
        description="""
        This test case verifies that key libbpf-tools binaries can be
        executed successfully.

        Steps:
        1. Ensure libbpf-tools package is installed.
        2. Test execsnoop tool (traces exec() syscalls).
        3. Test opensnoop tool (traces open() syscalls).
        4. Test biolatency tool (block I/O latency histogram).
        5. Verify each tool can run and produce help output.

        """,
        priority=2,
    )
    def verify_libbpf_tools_binaries_executable(self, node: Node) -> None:
        # Ensure package is installed by calling the availability test
        self.verify_libbpf_tools_package_available(node)

        # List of common libbpf-tools to test
        # We'll test them with --help or similar to verify they execute
        # Note: Fedora and CBL-Mariner use "bpf-" prefix, Ubuntu/Debian don't
        tools_to_test = [
            "execsnoop",  # Trace exec() syscalls
            "opensnoop",  # Trace open() syscalls
            "biolatency",  # Block I/O latency
            "runqlat",  # Scheduler run queue latency
            "tcpconnect",  # Trace TCP connections
        ]

        successful_tools = []
        failed_tools = []
        skipped_tools = []

        for base_tool_name in tools_to_test:
            # Try both with and without bpf- prefix
            tool_found, tool_name = self._find_tool(node, base_tool_name)

            if not tool_found:
                node.log.debug(
                    f"{base_tool_name} not found in PATH "
                    "(tried with and without bpf- prefix), skipping"
                )
                skipped_tools.append(base_tool_name)
                continue

            # Try running with help flag
            cmd = f"{tool_name} -h"
            result = node.execute(cmd, sudo=True)

            # Most BPF tools return 0 for --help or -h
            # Some might return 1, but they should still produce output
            has_output = len(result.stdout) > 0 or len(result.stderr) > 0
            if result.exit_code == 0 or has_output:
                successful_tools.append(tool_name)
                node.log.info(f"✓ {tool_name} executed successfully")
            else:
                failed_tools.append(tool_name)
                node.log.warning(
                    f"✗ {tool_name} failed to execute. "
                    f"Exit code: {result.exit_code}, "
                    f"stdout: {result.stdout}, stderr: {result.stderr}"
                )

        # Log summary
        node.log.info(
            f"libbpf-tools test summary: "
            f"{len(successful_tools)} successful, "
            f"{len(failed_tools)} failed, "
            f"{len(skipped_tools)} skipped"
        )

        # We should have at least some tools working
        assert_that(len(successful_tools)).described_as(
            f"At least one libbpf tool should execute successfully. "
            f"Successful: {successful_tools}, "
            f"Failed: {failed_tools}, "
            f"Skipped: {skipped_tools}"
        ).is_greater_than(0)

        # Ideally no tools should fail (skipping is OK if not installed)
        assert_that(len(failed_tools)).described_as(
            f"No libbpf tools should fail to execute. Failed tools: {failed_tools}"
        ).is_equal_to(0)

    @TestCaseMetadata(
        description="""
        This test case verifies that execsnoop can actually trace exec()
        syscalls by running a simple command and capturing the trace.

        Steps:
        1. Ensure libbpf-tools package is installed.
        2. Start execsnoop in background.
        3. Execute a test command (e.g., /bin/ls).
        4. Stop execsnoop.
        5. Verify the test command was traced in the output.

        """,
        priority=3,
    )
    def verify_execsnoop_traces_execution(self, node: Node) -> None:
        # Ensure package is installed by calling the availability test
        self.verify_libbpf_tools_package_available(node)

        # Check if execsnoop exists (try both bpf-execsnoop and execsnoop)
        tool_found, tool_name = self._find_tool(node, "execsnoop")
        if not tool_found:
            raise SkippedException("execsnoop tool not found")

        # Run execsnoop for a short duration and capture output
        # We'll run a simple command that should show up in the trace
        test_command = "/bin/echo 'test_libbpf_trace'"

        # Start execsnoop in background, run for 5 seconds
        execsnoop_cmd = f"timeout 5 {tool_name} > /tmp/execsnoop_output.txt 2>&1 &"
        node.execute(execsnoop_cmd, sudo=True, shell=True)

        # Wait a moment for execsnoop to initialize
        node.execute("sleep 1")

        # Execute our test command
        node.execute(test_command)

        # Wait for execsnoop to finish
        node.execute("sleep 5")

        # Read the output
        result = node.execute("cat /tmp/execsnoop_output.txt", sudo=True)

        # Clean up
        node.execute("rm -f /tmp/execsnoop_output.txt", sudo=True)

        # Verify our test command appears in the trace
        # execsnoop output typically shows command names
        assert_that(result.stdout).described_as(
            "execsnoop output should contain trace of executed commands"
        ).is_not_empty()

        # We should see 'echo' in the output since we ran /bin/echo
        assert_that(result.stdout.lower()).described_as(
            f"execsnoop should trace the echo command. Output: {result.stdout}"
        ).contains("echo")
