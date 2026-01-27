# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, cast

from microsoft.testsuites.power.common import (
    cleanup_env,
    hibernation_before_case,
    is_distro_supported,
    verify_hibernation,
)

from lisa import (
    Environment,
    Logger,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.features import HibernationEnabled, Sriov
from lisa.features.availability import AvailabilityTypeNoRedundancy
from lisa.node import Node
from lisa.testsuite import simple_requirement


@TestSuiteMetadata(
    area="power",
    category="stress",
    description="""
        This test suite is to test hibernation in guest vm under stress.
    """,
)
class PowerStress(TestSuite):
    _loop = 10

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        hibernation_before_case(node, log)

    @TestCaseMetadata(
        description="""
            This case is to verify vm hibernation in a loop.
        """,
        priority=3,
        timeout=720000,
        requirement=simple_requirement(
            min_os_disk_size=500,
            network_interface=Sriov(),
            supported_features=[HibernationEnabled(), AvailabilityTypeNoRedundancy()],
        ),
    )
    def stress_hibernation(self, environment: Environment, log: Logger) -> None:
        node = cast(RemoteNode, environment.nodes[0])
        is_distro_supported(node)
        for _ in range(0, self._loop):
            verify_hibernation(node, log)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        cleanup_env(environment)
