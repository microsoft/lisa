# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import math

from assertpy import assert_that

from lisa import Environment, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.features import Nvme
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.testsuite import simple_requirement
from lisa.tools import Lscpu


@TestSuiteMetadata(
    area="nvme",
    category="functional",
    description="""
    This test suite is to validate NVMe disk on Linux VM.
    """,
)
class nvme(TestSuite):
    TIME_OUT = 300

    @TestCaseMetadata(
        description="""
        This test case will
        1. Get nvme devices and nvme namespaces from /dev/ folder,
         compare the count of nvme namespaces and nvme devices.

        2. Compare the count of nvme namespaces return from `nvme list`
          and list nvme namespaces under /dev/.

        3. Compare nvme devices count return from `lspci`
          and list nvme devices under /dev/.

        4. Azure platform only, nvme devices count should equal to
          actual vCPU count / 8.
        """,
        priority=0,
        requirement=simple_requirement(
            supported_features=[Nvme],
        ),
    )
    def nvme_basic_validation(self, environment: Environment, node: Node) -> None:
        # 1. Get nvme devices and nvme namespaces from /dev/ folder,
        #  compare the count of nvme namespaces and nvme devices.
        nvme = node.features[Nvme]
        nvme_device = nvme.get_devices()
        nvme_namespace = nvme.get_namespaces()
        assert_that(nvme_device).described_as(
            "nvme devices count should be equal to namespace count by listing devices "
            "under folder /dev."
        ).is_length(len(nvme_namespace))

        # 2. Compare the count of nvme namespaces return from `nvme list`
        #  and list nvme namespaces under /dev/.
        nvme_namespace_cli = nvme.get_namespaces_from_cli()
        assert_that(nvme_namespace_cli).described_as(
            "nvme namespace count should be consistent between listed devides under "
            "folder /dev and return value from [nvme list]."
        ).is_length(len(nvme_namespace))

        # 3. Compare nvme devices count return from `lspci`
        #  and list nvme devices under /dev/.
        nvme_device_from_lspci = nvme.get_devices_from_lspci()
        assert_that(nvme_device).described_as(
            "nvme devices count should be consistent between return value from [lspci] "
            "and listed devices under folder /dev."
        ).is_length(len(nvme_device_from_lspci))

        # 4. Azure platform only, nvme devices count should equal to
        #  actual vCPU count / 8.
        if isinstance(environment.platform, AzurePlatform):
            lscpu_tool = node.tools[Lscpu]
            core_count = lscpu_tool.get_core_count()
            expected_count = math.ceil(core_count / 8)
            assert_that(nvme_namespace).described_as(
                "nvme devices count should be equal to [vCPU/8]."
            ).is_length(expected_count)
