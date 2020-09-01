from functools import partial

from lisa import schema
from lisa.search_space import IntRange
from lisa.tests.test_search_space import SearchSpaceTestCase
from lisa.testsuite import (
    DEFAULT_REQUIREMENT,
    TestCaseRequirement,
    TestCaseSchema,
    simple_requirement,
)
from lisa.util import constants


class RequirementTestCase(SearchSpaceTestCase):
    def test_supported_simple_requirement(self) -> None:
        n6 = schema.NodeSpace.schema().load(  # type:ignore
            {"type": constants.ENVIRONMENTS_NODES_REQUIREMENT, "coreCount": 6}
        )
        n6 = n6.generate_min_capaiblity(n6)
        n26 = schema.NodeSpace.schema().load(  # type:ignore
            {
                "type": constants.ENVIRONMENTS_NODES_REQUIREMENT,
                "nodeCount": 2,
                "coreCount": 6,
            }
        )
        n26 = n26.generate_min_capaiblity(n26)
        n6g2 = schema.NodeSpace.schema().load(  # type:ignore
            {
                "type": constants.ENVIRONMENTS_NODES_REQUIREMENT,
                "coreCount": 6,
                "gpuCount": 2,
            }
        )
        n6g2 = n6g2.generate_min_capaiblity(n6g2)
        n6g1 = schema.NodeSpace.schema().load(  # type:ignore
            {
                "type": constants.ENVIRONMENTS_NODES_REQUIREMENT,
                "coreCount": 6,
                "gpuCount": 1,
            }
        )
        n6g1 = n6g1.generate_min_capaiblity(n6g1)
        n10 = schema.NodeSpace.schema().load(  # type:ignore
            {"type": constants.ENVIRONMENTS_NODES_REQUIREMENT, "coreCount": 10}
        )
        n10 = n10.generate_min_capaiblity(n10)

        partial_testcase_schema = partial(
            TestCaseSchema, platform_type=None, operating_system=None,
        )
        s16 = partial_testcase_schema(environment=schema.Environment())
        s16.environment.requirements = [n6]
        s16g2 = partial_testcase_schema(environment=schema.Environment())
        s16g2.environment.requirements = [n6g2]
        s16g1 = partial_testcase_schema(environment=schema.Environment())
        s16g1.environment.requirements = [n6g1]
        s110 = partial_testcase_schema(environment=schema.Environment())
        s110.environment.requirements = [n10]
        s2i6 = partial_testcase_schema(environment=schema.Environment())
        s2i6.environment.requirements = [n26]
        s266 = partial_testcase_schema(environment=schema.Environment())
        s266.environment.requirements = [n6, n6]
        s2610 = partial_testcase_schema(environment=schema.Environment())
        s2610.environment.requirements = [n6, n10]
        s2106 = partial_testcase_schema(environment=schema.Environment())
        s2106.environment.requirements = [n10, n6]

        self._verify_matrix(
            expected_meet=[
                [False, True, True, True, True, True, True, True, True],
                [False, True, True, True, True, True, True, True, True],
                [False, True, True, True, False, True, True, True, False],
                [False, False, False, False, False, True, False, False, False],
                [False, True, True, True, False, True, True, True, False],
                [False, False, True, False, False, False, False, False, False],
            ],
            expected_min=[
                [False, s16, s16, s16g2, s110, s2i6, s16, s16, s110],
                [False, s16, s16, s16g2, s110, s2i6, s16, s16, s110],
                [False, s16, s16, s16g2, False, s2i6, s16, s16, False],
                [False, False, False, False, False, s2i6, False, False, False],
                [False, s16, s16, s16g2, False, s2i6, s16, s16, False],
                [False, False, s16g1, False, False, False, False, False, False],
            ],
            requirements=[
                DEFAULT_REQUIREMENT,
                simple_requirement(),
                simple_requirement(node=schema.NodeSpace(core_count=IntRange(4, 8))),
                simple_requirement(
                    min_count=2, node=schema.NodeSpace(core_count=IntRange(4, 8))
                ),
                TestCaseRequirement(
                    environment=schema.Environment(
                        requirements=[schema.NodeSpace(core_count=6, node_count=1)]
                    )
                ),
                simple_requirement(
                    min_count=1,
                    node=schema.NodeSpace(core_count=IntRange(4, 8), gpu_count=1),
                ),
            ],
            capabilities=[
                simple_requirement(),
                TestCaseRequirement(
                    environment=schema.Environment(
                        requirements=[schema.NodeSpace(core_count=6, node_count=1)]
                    )
                ),
                TestCaseRequirement(
                    environment=schema.Environment(
                        requirements=[
                            schema.NodeSpace(
                                node_count=1, core_count=6, gpu_count=IntRange(max=2)
                            )
                        ]
                    )
                ),
                TestCaseRequirement(
                    environment=schema.Environment(
                        requirements=[
                            schema.NodeSpace(node_count=1, core_count=6, gpu_count=2)
                        ]
                    )
                ),
                TestCaseRequirement(
                    environment=schema.Environment(
                        requirements=[schema.NodeSpace(core_count=10, node_count=1)]
                    )
                ),
                TestCaseRequirement(
                    environment=schema.Environment(
                        requirements=[schema.NodeSpace(core_count=6, node_count=2)]
                    )
                ),
                TestCaseRequirement(
                    environment=schema.Environment(
                        requirements=[
                            schema.NodeSpace(core_count=6, node_count=1),
                            schema.NodeSpace(core_count=6, node_count=1),
                        ]
                    )
                ),
                TestCaseRequirement(
                    environment=schema.Environment(
                        requirements=[
                            schema.NodeSpace(core_count=6, node_count=1),
                            schema.NodeSpace(core_count=10, node_count=1),
                        ]
                    )
                ),
                TestCaseRequirement(
                    environment=schema.Environment(
                        requirements=[
                            schema.NodeSpace(core_count=10, node_count=1),
                            schema.NodeSpace(core_count=6, node_count=1),
                        ]
                    )
                ),
            ],
        )
