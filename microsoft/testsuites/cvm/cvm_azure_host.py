# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from pathlib import Path
from typing import Any, Dict

from assertpy.assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.operating_system import CBLMariner
from lisa.sut_orchestrator.azure import features
from lisa.testsuite import TestResult, simple_requirement
from lisa.tools import Cat, Dmesg
from lisa.util import LisaException, SkippedException, get_matched_str


@TestSuiteMetadata(
    area="cvm",
    category="functional",
    description="""
    This test suite is for azure host vm pre-checks
    for nested-cvm cases.
    """,
)
class CVMAzureHostTestSuite(TestSuite):
    __sev_enabled_pattern = re.compile(r"mshv: SEV-SNP is supported")
    __sev_partition_pattern = re.compile(
        r"mshv: Maximum supported SEV-SNP partitions are: (\d+)"
    )

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        if not isinstance(node.os, (CBLMariner)):
            raise SkippedException(
                f"CVMAzureHostTestSuite is not implemented for {node.os.name}"
            )
        elif not is_mariner_dom0(node):
            raise SkippedException(
                "CVMAzureHostTestSuite is supported only on Dom0-Mariner"
            )

    @TestCaseMetadata(
        description="""
            Runs Dmesg tool to get kernel logs
            and verify if azure vm is snp enabled.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_features=[features.CVMNestedVirtualization],
        ),
    )
    def verify_azure_vm_snp_enablement(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        log_path: Path,
        result: TestResult,
        variables: Dict[str, Any],
    ) -> None:
        dmesg: str = node.tools[Dmesg].get_output(force_run=True)

        is_sev_enabled: str = get_matched_str(
            pattern=self.__sev_enabled_pattern,
            content=dmesg,
            first_match=True,
        )
        if not is_sev_enabled:
            raise LisaException("SEV_SNP is not enabled")
        else:
            is_sev_partition_present: str = get_matched_str(
                pattern=self.__sev_partition_pattern,
                content=dmesg,
                first_match=True,
            )
            if not is_sev_partition_present:
                raise LisaException("Can not get maximum SEV-SNP partition")
            else:
                partitions = int(is_sev_partition_present)
                err_msg: str = "Maximum SEV_SNP Partition should be greater than zero"
                assert_that(partitions).described_as(err_msg).is_greater_than(0)
                log.debug(f"Maximum supported SEV-SNP partitions are: {partitions}")


def is_mariner_dom0(node: Node) -> bool:
    cat = node.tools[Cat]
    hosts = cat.read("/etc/hosts")
    pattern = r"dom0-\d+-\d+-\d+-\w+-\d+"
    matches = re.findall(pattern, hosts)
    if matches:
        return True
    return False
