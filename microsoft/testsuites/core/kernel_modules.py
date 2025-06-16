# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Dict, List

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
from lisa.sut_orchestrator import AZURE, HYPERV, READY
from lisa.tools import KernelConfig


@TestSuiteMetadata(
    area="core",
    category="functional",
    description="""
    This test suite covers validation of essential non hv kernel modules.
    """,
    requirement=simple_requirement(supported_platform_type=[AZURE, HYPERV, READY]),
)
class KernelModule(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case will
        1. Verify the presence of essential kernel modules.
        """,
        priority=1,
    )
    def verify_essential_kernel_modules(
        self, log: Logger, environment: Environment
    ) -> None:
        node = environment.nodes[0]

        not_enabled_modules = self._get_not_enabled_modules(node)

        assert_that(not_enabled_modules).described_as(
            "Not all kernel modules are enabled."
        ).is_length(0)

    def _get_kernel_modules_configuration(self, node: Node) -> Dict[str, str]:
        """
        Returns a dictionary of kernel modules and their configuration names.
        """
        return {
            "wdt": "CONFIG_WATCHDOG",
            "cifs": "CONFIG_CIFS",
        }

    def _get_not_enabled_modules(self, node: Node) -> List[str]:
        """
        Returns the list of modules that are neither integrated into the kernel
        nor compiled as loadable modules.
        """
        not_built_in_modules = []

        kernel_modules_configuration = self._get_kernel_modules_configuration(node)
        for module in kernel_modules_configuration:
            if not node.tools[KernelConfig].is_enabled(
                kernel_modules_configuration[module]
            ):
                not_built_in_modules.append(module)
        return not_built_in_modules
