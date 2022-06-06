# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, cast

from lisa import (
    Environment,
    Logger,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.features import HibernationEnabled, Sriov
from lisa.testsuite import simple_requirement
from microsoft.testsuites.power.common import (
    cleanup_env,
    is_distro_supported,
    verify_hibernation,
)


@TestSuiteMetadata(
    area="power",
    category="stress",
    description="""
        This test suite is to test hibernation in guest vm under stress.
    """,
)
class PowerStress(TestSuite):
    _loop = 10

    @TestCaseMetadata(
        description="""
            This case is to verify vm hibernation in a loop.
        """,
        priority=3,
        requirement=simple_requirement(
            network_interface=Sriov(),
            supported_features=[HibernationEnabled()],
        ),
    )
    def verify_stress_hibernation(self, environment: Environment, log: Logger) -> None:
        node = cast(RemoteNode, environment.nodes[0])
        is_distro_supported(node)
        for _ in range(0, self._loop):
            verify_hibernation(node, log)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        cleanup_env(environment)
