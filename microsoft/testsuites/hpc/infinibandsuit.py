# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.features import Infiniband, Sriov
from lisa.sut_orchestrator.azure.tools import Waagent
from lisa.tools import Modprobe
from lisa.util import SkippedException
from lisa.util.parallel import run_in_parallel


@TestSuiteMetadata(
    area="hpc",
    category="functional",
    description="""
    Tests the functionality of infiniband.
    """,
)
class InfinibandSuit(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case will
        1. Determine whether the VM has Infiniband over SR-IOV
        2. Ensure waagent is configures with OS.EnableRDMA=y
        3. Check that appropriate drivers are present
        """,
        priority=2,
        requirement=simple_requirement(
            network_interface=Sriov(), supported_features=[Infiniband]
        ),
    )
    def verify_hpc_over_sriov(self, log: Logger, node: Node) -> None:

        infiniband = node.features[Infiniband]
        assert_that(infiniband.is_over_sriov()).described_as(
            "Based on VM SKU information we expected Infiniband over SR-IOV,"
            " but no matching devices were found."
        ).is_true()

        waagent = node.tools[Waagent]
        assert_that(waagent.is_rdma_enabled()).described_as(
            "Found waagent configuration of OS.EnableRDMA=y "
            "was missing or commented out"
        ).is_true()
        log.debug("Verified waagent config OS.EnableRDMA=y set successfully")

        modprobe = node.tools[Modprobe]
        expected_modules = [
            "mlx5_ib",
            "ib_uverbs",
            "ib_core",
            "mlx5_core",
            "mlx_compat",
            "rdma_cm",
            "iw_cm",
            "ib_cm",
        ]

        for module in expected_modules:
            assert_that(modprobe.is_module_loaded(module)).described_as(
                f"Module {module} is not loaded."
            ).is_true()

    @TestCaseMetadata(
        description="""
        This test case will
        1. Determine whether the VM has Infiniband over Network Direct
        2. Ensure waagent is configures with OS.EnableRDMA=y
        3. Check that appropriate drivers are present
        """,
        priority=2,
        requirement=simple_requirement(supported_features=[Infiniband]),
    )
    def verify_hpc_over_nd(self, log: Logger, node: Node) -> None:

        infiniband = node.features[Infiniband]
        if not infiniband.is_over_nd():
            raise SkippedException("Inifiniband over ND was not detected.")

        waagent = node.tools[Waagent]
        assert_that(waagent.is_rdma_enabled()).described_as(
            "Found waagent configuration of OS.EnableRDMA=y "
            "was missing or commented out"
        ).is_true()
        log.debug("Verified waagent config OS.EnableRDMA=y set successfully")

        modprobe = node.tools[Modprobe]
        expected_modules = ["mlx5_ib", "hv_networkdirect"]

        for module in expected_modules:
            assert_that(modprobe.is_module_loaded(module)).described_as(
                f"Module {module} is not loaded."
            ).is_true()

    @TestCaseMetadata(
        description="""
        This test case will
        1. Identify the infiniband devices and their cooresponding network interfaces
        2. Run several ping-pong tests to check RDMA / Infiniband functionality
        """,
        priority=1,
        requirement=simple_requirement(
            supported_features=[Infiniband],
            min_count=2,
        ),
    )
    def verify_ping_pong(self, environment: Environment, log: Logger) -> None:
        # Constants
        ping_pong_tests = ["ibv_rc_pingpong", "ibv_uc_pingpong", "ibv_ud_pingpong"]

        server_node = environment.nodes[0]
        client_node = environment.nodes[1]

        # Ensure RDMA is setup
        run_in_parallel(
            [
                lambda: client_node.features[Infiniband],
                lambda: server_node.features[Infiniband],
            ]
        )
        infiniband = server_node.features[Infiniband]
        ib_interfaces = infiniband.get_ib_interfaces()

        for interface in ib_interfaces:
            ib_device_name = interface[0]
            ip_addr = interface[2]

            for test in ping_pong_tests:
                server_process = server_node.execute_async(
                    f"{test} -g 0 -d {ib_device_name}"
                )
                client_process = client_node.execute_async(
                    f"{test} -g 0 -d {ib_device_name} {ip_addr}"
                )

                client_result = client_process.wait_result()
                client_result.assert_exit_code(
                    0,
                    f"Client ping-pong test {test} failed with exit code "
                    f"{client_result.exit_code} and output {client_result.stdout}",
                )

                server_result = server_process.wait_result()
                server_result.assert_exit_code(
                    0,
                    f"Server ping-pong test {test} failed with exit code "
                    f"{server_result.exit_code} and output {server_result.stdout}",
                )
