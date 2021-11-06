# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from assertpy import assert_that

from lisa import (
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


@TestSuiteMetadata(
    area="core",
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
            "ib_core",
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
