# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from logging import Logger
from typing import Any, Dict

from lisa import (
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    search_space,
    simple_requirement,
)
from lisa.operating_system import BSD, Windows
from lisa.testsuite import TestResult
from lisa.tools import Lsblk, Swap
from microsoft.testsuites.superbench.superbench import Superbench

@TestSuiteMetadata(
    area="Superbench",
    category="functional",
    description="This test suite is used to run Superbench tests.",
)
class SuperbenchSuite(TestSuite):
    TIME_OUT_SEC = { "feature" : 30 * 60,
                     "release" : 60 * 60,
                     "performamce" : 300 * 60 }
    _TIME_OUT = 1800
    _SUPERBENCH_CONFIG = ""

    @TestCaseMetadata(
        description="""
        This test case will run superbench tests choosing relevant config for SKU
        and test type. Test type can be release, performance and feature. Default
        is release testing.

        The VM to run the test on is pre-provisioned. Superbench repo is cloned
        on the target node, derived sb configuration copied in and the test
        launched on the node. Result csv file is copied back from the test node,
        parsed and passed on to a suitable notification mechanism.
        """,
        priority=1,
        requirement=simple_requirement(
            unsupported_os=[BSD, Windows],
        ),
    )
    def verify_superbench(
        self,
        node: Node,
        log_path: str,
        variables: Dict[str, Any],
        result: TestResult,
    ) -> None:

        # parse variables
        gpu = variables["gpu"].upper()
        validation = variables["validation_type"]
        sb_repo = variables["repo_url"]
        sb_config = f"superbench_{validation}_{gpu}.yaml"
        sb_branch = variables["sb_branch"]
        sb_image_tag = variables["sb_image_tag"]

        print(f"gpu: {gpu}\n validation: {validation}\n sb_repo: {sb_repo}\n sb_config: {sb_config}\n sb_branch: {sb_branch}\n sb_image_tag: {sb_image_tag}\n")
        
        # run superbench tests
        superbench: Superbench = node.tools.get(
            Superbench,
            sb_repo=sb_repo, sb_branch=sb_branch,
            sb_config=sb_config, sb_image_tag=sb_image_tag, variables=variables
        )
        superbench.run_test(
            result,
            log_path,
            sb_run_timeout=self.TIME_OUT_SEC[validation]
        )
