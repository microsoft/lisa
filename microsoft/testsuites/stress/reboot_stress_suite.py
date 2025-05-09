from typing import Any, List

from lisa import (
    Environment,
    Logger,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
    create_timer
)
from lisa.features import SerialConsole, StartStop
from lisa.util import BadEnvironmentStateException, SkippedException
from lisa.util.shell import wait_tcp_port_ready

@TestSuiteMetadata(
    area="reboot",
    category="stress",
    description="""
    This test suite verifies the stability of VMs under reboot stress conditions.
    It includes tests for rebooting VMs multiple times and ensuring they remain
    functional after each reboot.
    """,
)
class RebootStressSuite(TestSuite):
    TIME_OUT = 300  # Timeout for each reboot operation

    @TestCaseMetadata(
        description="""
        This test reboots the VM multiple times from the guest OS and verifies
        that the VM remains functional after each reboot.

        Steps:
        1. Reboot the VM from the guest OS.
        2. Verify the VM is reachable after reboot.
        3. Check for kernel panic after each reboot.
        4. Repeat the reboot process for 10 iterations.
        """,
        priority=2,
        timeout=TIME_OUT * 10,
        requirement=simple_requirement(
            min_core_count=2,
        ),
    )
    def reboot_stress_guest(self, environment: Environment, log: Logger) -> None:
        for node in environment.nodes.list():
            self._reboot_stress_test(node, log, reboot_method="guest")

    @TestCaseMetadata(
        description="""
        This test reboots the VM multiple times using the platform API and verifies
        that the VM remains functional after each reboot.

        Steps:
        1. Reboot the VM using the platform API.
        2. Verify the VM is reachable after reboot.
        3. Check for kernel panic after each reboot.
        4. Repeat the reboot process for 10 iterations.
        """,
        priority=2,
        timeout=TIME_OUT * 10,
        requirement=simple_requirement(
            min_core_count=2,
            supported_features=[StartStop],
        ),
    )
    def reboot_stress_platform(self, environment: Environment, log: Logger) -> None:
        for node in environment.nodes.list():
            self._reboot_stress_test(node, log, reboot_method="platform")

    def _reboot_stress_test(
        self, node: RemoteNode, log: Logger, reboot_method: str
    ) -> None:
        """
        Performs a reboot stress test on the given node.

        :param node: The node to test.
        :param log: Logger for logging messages.
        :param reboot_method: The method to use for rebooting ("guest" or "platform").
        """
        reboot_times = []  # List to store reboot times
        for iteration in range(10):  # Reboot 10 times
            try:
                timer = create_timer()
                log.info(
                    f"Iteration {iteration + 1}: Rebooting node '{node.name}' "
                    f"using {reboot_method} method."
                )

                # Perform reboot based on the method
                if reboot_method == "guest":
                    node.reboot()
                elif reboot_method == "platform":
                    start_stop = node.features[StartStop]
                    start_stop.restart()
                else:
                    raise ValueError(f"Unknown reboot method: {reboot_method}")

                reboot_time = timer.elapsed()
                reboot_times.append((iteration + 1, reboot_time))
                log.info(
                    f"Iteration {iteration + 1}: Node '{node.name}' rebooted in "
                    f"{reboot_time:.2f}s"
                )

                # Verify the node is reachable
                self._verify_node_reachable(node, log)

            except Exception as identifier:
                log.warning(
                    f"Iteration {iteration + 1}: Exception occurred: {identifier}"
                )
                if isinstance(identifier, BadEnvironmentStateException):
                    raise

            finally:
                # Check for kernel panic after each reboot
                serial_console = node.features[SerialConsole]
                serial_console.check_panic(
                    saved_path=None,
                    stage=f"reboot_iteration_{iteration + 1}",
                    force_run=True,
                )

        # Log all reboot times
        log.info("Reboot times for all iterations:")
        for iteration, time in reboot_times:
            log.info(f"Iteration {iteration}: Reboot time = {time:.2f}s")

    def _verify_node_reachable(self, node: RemoteNode, log: Logger) -> None:
        """
        Verifies that the node is reachable after a reboot by checking the TCP port.
        """
        is_ready, tcp_error_code = wait_tcp_port_ready(
            node.connection_info.address,
            node.connection_info.port,
            log=log,
            timeout=self.TIME_OUT,
        )
        if not is_ready:
            raise BadEnvironmentStateException(
                f"Node '{node.name}' is not reachable after reboot. "
                f"TCP error code: {tcp_error_code}"
            )
        log.info(f"Node '{node.name}' is reachable after reboot.")