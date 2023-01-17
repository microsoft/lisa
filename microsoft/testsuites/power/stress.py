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
from lisa.node import Node
from lisa.operating_system import BSD, Windows
from lisa.testsuite import simple_requirement
from lisa.util import SkippedException
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

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        if isinstance(node.os, BSD) or isinstance(node.os, Windows):
            raise SkippedException(f"{node.os} is not supported.")

    @TestCaseMetadata(
        description="""
            This case is to verify vm hibernation in a loop.
        """,
        priority=3,
        timeout=720000,
        requirement=simple_requirement(
            network_interface=Sriov(),
            supported_features=[HibernationEnabled()],
        ),
    )
    def stress_hibernation(self, environment: Environment, log: Logger) -> None:
        node = cast(RemoteNode, environment.nodes[0])
        is_distro_supported(node)
        for index in range(1, self._loop):
            verify_hibernation(environment, log, index)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        cleanup_env(environment)
