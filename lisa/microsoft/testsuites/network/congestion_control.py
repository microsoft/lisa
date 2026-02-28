# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
import time
from pathlib import Path
from typing import List, Optional, Tuple

from assertpy import assert_that

from lisa import (
    LisaException,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import BSD, Windows
from lisa.sut_orchestrator import AZURE, HYPERV, READY
from lisa.tools import Cat, KernelConfig, Modprobe, Rm, Ss, Sysctl
from lisa.util import create_timer


@TestSuiteMetadata(
    area="network",
    category="functional",
    description="""
    This test suite validates TCP congestion control behavior.
    Current coverage focuses on BBR3-specific functionality (only for kernels that are built with BBR3 support)
    """,
    requirement=simple_requirement(
        supported_platform_type=[AZURE, READY, HYPERV],
        unsupported_os=[BSD, Windows],
    ),
)
class CongestionControlSuite(TestSuite):
    _BBR3 = "bbr3"
    _BBR3_MODULE = "tcp_bbr3"
    _TCP_AVAILABLE = "net.ipv4.tcp_available_congestion_control"
    _TCP_ACTIVE = "net.ipv4.tcp_congestion_control"
    _BBR3_CONFIG = "CONFIG_TCP_CONG_BBR3"
    _TCP_SCRIPT = "lisa_tcp_test.py"
    _TCP_ALGO_OUTPUT = "lisa_tcp_algo.txt"
    _INVALID_ALGO = "lisa_invalid_cc_algorithm"
    _PORT_RANGE_START = 34567
    _PORT_RANGE_END = 34667

    @TestCaseMetadata(
        description="""
        This test case verifies the BBR3 algorithm appears in available
        TCP congestion control algorithms.

        Steps:
        1. Read available TCP congestion control algorithms.
        2. Verify BBR3 is listed.

        """,
        priority=3,
    )
    def verify_bbr3_available(self, node: Node) -> None:
        loaded_by_test = False
        try:
            available, loaded_by_test = self._ensure_bbr3_available(node)
            assert_that(
                available,
                f"{self._BBR3} should be listed in {self._TCP_AVAILABLE}",
            ).contains(self._BBR3)
        finally:
            self._cleanup_loaded_module(node, loaded_by_test)

    @TestCaseMetadata(
        description="""
        This test case verifies the BBR3 algorithm can be selected and restored.

        Steps:
        1. Verify BBR3 is available.
        2. Save the current TCP congestion control algorithm.
        3. Set TCP congestion control to BBR3.
        4. Verify BBR3 is active.
        5. Restore the original algorithm.

        """,
        priority=2,
    )
    def verify_bbr3_set_and_restore(self, node: Node) -> None:
        loaded_by_test = False
        sysctl = node.tools[Sysctl]
        original_algo = sysctl.get(self._TCP_ACTIVE).strip()

        try:
            _, loaded_by_test = self._ensure_bbr3_available(node)
            sysctl.write(self._TCP_ACTIVE, self._BBR3)
            active_algo = sysctl.get(self._TCP_ACTIVE).strip()
            assert_that(
                active_algo,
                f"{self._TCP_ACTIVE} should be set to {self._BBR3}",
            ).is_equal_to(self._BBR3)
        finally:
            sysctl.write(self._TCP_ACTIVE, original_algo)
            restored_algo = sysctl.get(self._TCP_ACTIVE).strip()
            assert_that(
                restored_algo,
                f"{self._TCP_ACTIVE} should be restored to {original_algo}",
            ).is_equal_to(original_algo)
            self._cleanup_loaded_module(node, loaded_by_test)

    @TestCaseMetadata(
        description="""
        This test case verifies the BBR3 algorithm remains stable on a live TCP flow.

        Steps:
        1. Verify BBR3 is available.
        2. Set TCP congestion control to BBR3.
        3. Create a TCP connection and verify it reaches ESTAB.
        4. Validate the connection remains established.
        5. Restore the original algorithm and cleanup.

        """,
        priority=2,
    )
    def verify_bbr3_applies_to_live_tcp_flow(self, node: Node) -> None:
        loaded_by_test = False
        test_port: Optional[int] = None
        script_path = node.working_path / self._TCP_SCRIPT
        algo_output_path = node.working_path / self._TCP_ALGO_OUTPUT
        connection_process = None
        sysctl = node.tools[Sysctl]
        rm = node.tools[Rm]
        original_algo = sysctl.get(self._TCP_ACTIVE).strip()

        try:
            _, loaded_by_test = self._ensure_bbr3_available(node)
            sysctl.write(self._TCP_ACTIVE, self._BBR3)
            active_algo = sysctl.get(self._TCP_ACTIVE).strip()
            assert_that(
                active_algo,
                f"{self._TCP_ACTIVE} should be set to {self._BBR3}",
            ).is_equal_to(self._BBR3)

            test_port = self._find_available_port(node)
            self._copy_to_node(node, self._TCP_SCRIPT)

            connection_process = node.execute_async(
                f"python3 {script_path} {test_port} {algo_output_path}",
                sudo=False,
                nohup=True,
            )

            if not self._wait_for_connection_state(
                node=node,
                port=test_port,
                expected_state=Ss.ConnState.ESTAB,
                timeout=15,
                poll_interval=0.5,
            ):
                raise LisaException(
                    f"TCP connection on port {test_port} did not reach ESTAB."
                )

            socket_algo = self._read_socket_congestion_algorithm(
                node=node,
                output_path=algo_output_path,
            )
            assert_that(socket_algo).described_as(
                "Expected live TCP socket congestion algorithm to be bbr3."
            ).is_equal_to(self._BBR3)

            time.sleep(2)

            if not self._wait_for_connection_state(
                node=node,
                port=test_port,
                expected_state=Ss.ConnState.ESTAB,
                timeout=5,
                poll_interval=0.5,
            ):
                raise LisaException(
                    f"TCP connection on port {test_port} was not stable in ESTAB."
                )
        finally:
            cleanup_errors: List[str] = []
            if connection_process is not None:
                pkill_result = node.execute(
                    f"pkill -f {script_path}",
                    sudo=True,
                    expected_exit_code=None,
                    expected_exit_code_failure_message=(
                        f"Failed to kill background process for {script_path}"
                    ),
                )
                if pkill_result.exit_code not in (0, 1):
                    cleanup_errors.append(
                        "Cleanup failed: pkill returned error code "
                        f"{pkill_result.exit_code}."
                    )
                connection_process.wait_result(timeout=5, raise_on_timeout=False)
                # Socket teardown can lag process exit; wait before module cleanup.
                if test_port is not None and not self._wait_for_connection_state(
                    node=node,
                    port=test_port,
                    expected_state=Ss.ConnState.NONE,
                    timeout=10,
                    poll_interval=0.3,
                ):
                    node.log.warning(
                        f"Connection on port {test_port} still exists during cleanup."
                    )

            if node.shell.exists(script_path):
                try:
                    rm.remove_file(str(script_path), sudo=True)
                except AssertionError as identifier:
                    cleanup_errors.append(
                        f"Failed to remove temporary script {script_path}: {identifier}"
                    )
            if node.shell.exists(algo_output_path):
                try:
                    rm.remove_file(str(algo_output_path), sudo=True)
                except AssertionError as identifier:
                    cleanup_errors.append(
                        f"Failed to remove algorithm output {algo_output_path}: "
                        f"{identifier}"
                    )

            sysctl.write(self._TCP_ACTIVE, original_algo)
            restored_algo = sysctl.get(self._TCP_ACTIVE).strip()
            assert_that(
                restored_algo,
                f"{self._TCP_ACTIVE} should be restored to {original_algo}",
            ).is_equal_to(original_algo)
            self._cleanup_loaded_module(node, loaded_by_test)
            if cleanup_errors:
                raise LisaException(" ".join(cleanup_errors))

    @TestCaseMetadata(
        description="""
        This test case verifies BBR3 kernel config and runtime state are consistent
        as part of congestion-control validation.

        Steps:
        1. Check if BBR3 is enabled in kernel config.
        2. Verify BBR3 appears in runtime available algorithms.

        """,
        priority=3,
    )
    def verify_bbr3_kernel_config_runtime_consistency(self, node: Node) -> None:
        kernel_config = node.tools[KernelConfig]
        if not kernel_config.is_enabled(self._BBR3_CONFIG):
            raise SkippedException(f"{self._BBR3_CONFIG} is not enabled in kernel.")

        loaded_by_test = False
        try:
            available, loaded_by_test = self._ensure_bbr3_available(node)
            assert_that(
                available,
                f"{self._BBR3} should be listed in {self._TCP_AVAILABLE}",
            ).contains(self._BBR3)
        finally:
            self._cleanup_loaded_module(node, loaded_by_test)

    def _ensure_bbr3_available(self, node: Node) -> Tuple[List[str], bool]:
        """
        Helper function to be called before any bbr3 test case.
        Check if bbr3 is available in the kernel config. If not, then skip the test.

        If available, ensure that if it's a module then it's loaded, and ensure it's
        listed in the available congestion control algorithms. 
        If any of these steps fail, the overall test case is a failure.
        Returns (available_algorithms, loaded_by_test)
        """
        available = self._get_available_algorithms(node)
        if self._BBR3 in available:
            return available, False

        kernel_config = node.tools[KernelConfig]
        if not kernel_config.is_enabled(self._BBR3_CONFIG):
            raise SkippedException(
                f"{self._BBR3} is not available in {self._TCP_AVAILABLE}. "
                f"{self._BBR3_CONFIG} is not enabled in kernel. "
                f"available algorithms: {', '.join(available) or 'none'}"
            )

        if kernel_config.is_built_as_module(self._BBR3_CONFIG):
            try:
                node.tools[Modprobe].load(self._BBR3_MODULE)
            except AssertionError as identifier:
                raise LisaException(
                    f"Failed to load {self._BBR3_MODULE} while "
                    f"{self._BBR3_CONFIG}=m. {identifier}"
                ) from identifier

            available = self._get_available_algorithms(node)
            if self._BBR3 not in available:
                raise LisaException(
                    f"{self._BBR3} is still missing from {self._TCP_AVAILABLE} "
                    f"after loading module {self._BBR3_MODULE}. "
                    f"available algorithms: {', '.join(available) or 'none'}"
                )
            return available, True

        raise LisaException(
            f"{self._BBR3_CONFIG} is enabled but {self._BBR3} is missing from "
            f"{self._TCP_AVAILABLE}. available algorithms: "
            f"{', '.join(available) or 'none'}"
        )

    def _get_available_algorithms(self, node: Node) -> List[str]:
        try:
            raw = node.tools[Sysctl].get(self._TCP_AVAILABLE)
        except AssertionError as identifier:
            raise SkippedException(
                f"{self._TCP_AVAILABLE} is not available on this kernel."
            ) from identifier

        return [algo.strip() for algo in raw.split() if algo.strip()]

    def _cleanup_loaded_module(self, node: Node, loaded_by_test: bool) -> None:
        if not loaded_by_test:
            return

        active_algo = node.tools[Sysctl].get(self._TCP_ACTIVE).strip()
        if active_algo == self._BBR3:
            return

        # Sometimes modprobe can fail to remove the module on the first try due to lingering references.
        modprobe = node.tools[Modprobe]
        last_error: Optional[AssertionError] = None
        for _ in range(5):
            if not modprobe.is_module_loaded(self._BBR3_MODULE, force_run=True):
                return

            try:
                modprobe.remove([self._BBR3_MODULE])
                return
            except AssertionError as identifier:
                last_error = identifier
                time.sleep(1)

        if modprobe.is_module_loaded(self._BBR3_MODULE, force_run=True):
            node.log.warning(
                f"Best-effort cleanup could not remove module {self._BBR3_MODULE}. "
                f"Leaving it loaded to avoid failing the functional test. "
                f"Last error: {last_error}"
            )

    def _find_available_port(self, node: Node) -> int:
        ss = node.tools[Ss]

        for port in range(self._PORT_RANGE_START, self._PORT_RANGE_END):
            if not ss.port_in_use(port=port, sport=True):
                return port

        raise LisaException(
            f"No available ports found in range "
            f"{self._PORT_RANGE_START}-{self._PORT_RANGE_END}"
        )

    def _copy_to_node(self, node: Node, filename: str) -> None:
        file_path = Path(os.path.dirname(__file__)) / "TestScripts" / filename
        if not node.shell.exists(node.working_path / filename):
            node.shell.copy(file_path, node.working_path / filename)

    def _read_socket_congestion_algorithm(
        self,
        node: Node,
        output_path: Path,
        timeout: int = 5,
        poll_interval: float = 0.2,
    ) -> str:
        timer = create_timer()
        cat = node.tools[Cat]
        while timer.elapsed(stop=False) < timeout:
            if node.shell.exists(output_path):
                algo = cat.read(str(output_path), force_run=True).strip()
                if algo:
                    return algo
            time.sleep(poll_interval)

        raise LisaException(
            f"Failed to read TCP congestion algorithm output from {output_path}."
        )

    def _wait_for_connection_state(
        self,
        node: Node,
        port: int,
        expected_state: Ss.ConnState,
        timeout: int = 10,
        poll_interval: float = 0.5,
    ) -> bool:
        timer = create_timer()
        while timer.elapsed(stop=False) < timeout:
            ss = node.tools[Ss]
            if expected_state == Ss.ConnState.NONE:
                connection_exists = ss.connection_exists(
                    port=port, state=Ss.ConnState.ESTAB.value, sport=True
                )
                if not connection_exists:
                    return True
            else:
                connection_exists = ss.connection_exists(
                    port=port, state=expected_state.value, sport=True
                )
                if connection_exists:
                    return True

            time.sleep(poll_interval)

        return False
