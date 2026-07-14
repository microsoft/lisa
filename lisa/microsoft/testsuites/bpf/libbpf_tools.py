# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

from typing import Any, cast

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import CBLMariner, Linux
from lisa.sut_orchestrator import AZURE, HYPERV, READY
from lisa.util import LisaException


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
        supported_os=[CBLMariner],
    ),
)
class LibbpfToolsSuite(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        if node.os.information.version.major != 3:
            raise SkippedException(
                f"libbpf-tools tests only supported on CBLMariner 3, "
                f"found version {node.os.information.version}"
            )

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
        # Cast for mypy - supported_os filter ensures node.os is linux
        linux_os = cast(Linux, node.os)

        # Check if package is already installed
        package_exists = linux_os.package_exists("libbpf-tools")

        if not package_exists:
            # Check if package is available in repositories
            if not linux_os.is_package_in_repo("libbpf-tools"):
                raise SkippedException("libbpf-tools package not found in repositories")

            # Package is available, install it
            linux_os.install_packages("libbpf-tools")

            # Verify package is now installed
            package_installed = linux_os.package_exists("libbpf-tools")
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
                node.log.debug(
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

    def _ensure_profile_tool(self, node: Node) -> str:
        """Make sure bpf-profile is installed and return the binary name."""
        self.verify_libbpf_tools_package_available(node)
        tool_found, tool_name = self._find_tool(node, "profile")
        if not tool_found:
            raise SkippedException("bpf-profile tool not found")
        return cast(str, tool_name)

    def _start_cpu_workload(self, node: Node) -> str:
        """Spin up a CPU-burning workload and return its PID."""
        pid_result = node.execute(
            "yes >/dev/null 2>&1 & echo $!",
            sudo=True,
            shell=True,
        )
        pid_lines = [
            line.strip() for line in pid_result.stdout.splitlines() if line.strip()
        ]
        pid = pid_lines[-1] if pid_lines else ""
        if not pid.isdigit():
            raise LisaException(
                "Failed to start CPU workload: did not get a valid PID. "
                f"stdout: {pid_result.stdout.strip() or '<empty>'}. "
                f"stderr: {pid_result.stderr.strip() or '<empty>'}"
            )
        return pid

    def _kill_workload(self, node: Node, pid: str) -> None:
        """Clean up a background workload."""
        pid = pid.strip()
        if not pid.isdigit():
            return
        node.execute(
            f"kill -- {pid} 2>/dev/null || true",
            sudo=True,
            shell=True,
        )

    @TestCaseMetadata(
        description="""
        Verify bpf-profile captures stack traces from a running process.
        Starts a CPU workload, profiles it for 3s, checks output has stacks.
        """,
        priority=2,
        requirement=simple_requirement(),
    )
    def verify_bpf_profile_captures_stacks(self, node: Node, log: Logger) -> None:
        tool = self._ensure_profile_tool(node)
        pid = self._start_cpu_workload(node)

        try:
            profile_seconds = 3  # Short duration while still capturing stacks.
            result = node.execute(
                f"{tool} -p {pid} {profile_seconds}",
                sudo=True,
                timeout=30,  # Allow extra time on slow/contended VMs.
            )
            combined = result.stdout + result.stderr
            lines = combined.strip().splitlines()
            # Expect at least the header + some stack lines
            has_stacks = len(lines) > 2
            assert_that(has_stacks).described_as(
                f"bpf-profile should produce stack traces. "
                f"Got {len(lines)} line(s): {combined[:500]}"
            ).is_true()
            log.info(
                f"bpf-profile captured stack traces successfully "
                f"({len(lines)} lines)"
            )
        finally:
            self._kill_workload(node, pid)

    @TestCaseMetadata(
        description="""
        Verify -K (kernel only) and -U (user only) stack filtering.
        Uses a CPU workload to generate stacks and validates
        presence/absence of kernel frames.
        """,
        priority=3,
        requirement=simple_requirement(),
    )
    def verify_bpf_profile_stack_filtering(self, node: Node, log: Logger) -> None:
        tool = self._ensure_profile_tool(node)
        kernel_symbols = ["vfs_write", "ksys_write", "entry_SYSCALL"]
        pid = self._start_cpu_workload(node)

        try:
            profile_seconds = 3  # Enough to capture stack variety.
            profile_timeout = 30  # Allow extra time on slow/contended VMs.

            k_result = node.execute(
                f"{tool} -p {pid} -K {profile_seconds}",
                sudo=True,
                timeout=profile_timeout,
            )
            k_out = k_result.stdout + k_result.stderr
            has_kernel = any(sym in k_out for sym in kernel_symbols)
            assert_that(has_kernel).described_as(
                "-K should show kernel functions like vfs_write"
            ).is_true()
            log.info("-K filtering works")

            u_result = node.execute(
                f"{tool} -p {pid} -U {profile_seconds}",
                sudo=True,
                timeout=profile_timeout,
            )
            u_out = u_result.stdout + u_result.stderr
            has_no_kernel = not any(sym in u_out for sym in kernel_symbols)
            assert_that(has_no_kernel).described_as(
                "-U should exclude kernel frames"
            ).is_true()
            log.info("-U filtering works")
        finally:
            self._kill_workload(node, pid)

    @TestCaseMetadata(
        description="""
        Verify bpf-profile cleans up BPF resources after repeated runs.
        Profiles a workload 5 times and checks BPF program count is stable.
        """,
        priority=3,
        requirement=simple_requirement(),
    )
    def verify_bpf_profile_no_resource_leak(self, node: Node, log: Logger) -> None:
        tool = self._ensure_profile_tool(node)

        # Install bpftool if not available; skip if it can't be installed
        bpftool_check = node.execute("which bpftool", sudo=True)
        if bpftool_check.exit_code != 0:
            linux_os = cast(Linux, node.os)
            try:
                linux_os.install_packages("bpftool")
            except LisaException as e:
                raise SkippedException(
                    f"bpftool not available - cannot verify BPF resource leak: {e}"
                )

        before = node.execute(
            "set -o pipefail; bpftool prog show | wc -l",
            sudo=True,
            shell=True,
        )
        before.assert_exit_code(
            0, message="bpftool prog show failed", include_output=True
        )
        before_count = int(before.stdout.strip())
        pid = self._start_cpu_workload(node)

        try:
            run_count = 5  # Enough iterations to detect leaks.
            profile_seconds = 1  # Short per-iteration to keep total time low.
            for _ in range(run_count):
                node.execute(
                    f"{tool} -p {pid} {profile_seconds}",
                    sudo=True,
                    timeout=15,  # Each 1s profile should complete quickly.
                )

            after = node.execute(
                "set -o pipefail; bpftool prog show | wc -l",
                sudo=True,
                shell=True,
            )
            after.assert_exit_code(
                0, message="bpftool prog show failed", include_output=True
            )
            after_count = int(after.stdout.strip())
            delta = after_count - before_count
            # Allow delta of 1 for transient system BPF programs (e.g. systemd).
            assert_that(delta).described_as(
                f"BPF programs should not leak. "
                f"Before: {before_count}, after: {after_count}"
            ).is_less_than_or_equal_to(1)
            log.info(f"No BPF resource leak (delta={delta})")
        finally:
            self._kill_workload(node, pid)

    @TestCaseMetadata(
        description="""
        Verify bpf-profile handles bad input and target exit gracefully.
        Tests non-existent PID and target dying mid-profile.
        """,
        priority=3,
        requirement=simple_requirement(),
    )
    def verify_bpf_profile_handles_edge_cases(self, node: Node, log: Logger) -> None:
        tool = self._ensure_profile_tool(node)

        # Use a PID that is almost certainly not in use.
        invalid_pid = 99999999
        profile_seconds = 2  # Short duration, tool should fail quickly.
        result = node.execute(
            f"{tool} -p {invalid_pid} {profile_seconds}",
            sudo=True,
            timeout=15,  # Allow time for error path.
        )
        assert_that(result.exit_code).described_as(
            f"Should not segfault on bad PID (exit={result.exit_code})"
        ).is_not_in(139, -11)
        log.info("Non-existent PID handled gracefully")

        # Target dies mid-profile
        pid_result = node.execute(
            "sleep 3 >/dev/null 2>&1 & echo $!",
            sudo=True,
            shell=True,
        )
        pid_lines = [
            line.strip() for line in pid_result.stdout.splitlines() if line.strip()
        ]
        pid = pid_lines[-1] if pid_lines else ""
        if not pid.isdigit():
            raise LisaException(
                "Failed to start sleep workload: did not get a valid PID. "
                f"stdout: {pid_result.stdout.strip() or '<empty>'}. "
                f"stderr: {pid_result.stderr.strip() or '<empty>'}"
            )

        # Profile for 10s but target exits after ~3s, tool should handle gracefully.
        result = node.execute(f"{tool} -p {pid} 10", sudo=True, timeout=30)
        assert_that(result.exit_code).described_as(
            "Should not crash when target exits mid-profile"
        ).is_not_in(139, -11)
        log.info("Target exit mid-profile handled gracefully")
