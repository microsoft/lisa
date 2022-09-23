# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import json
from pathlib import Path
from typing import Any, Dict

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.operating_system import CBLMariner, Ubuntu
from lisa.testsuite import TestResult
from lisa.tools import Lscpu
from lisa.util import LisaException, SkippedException
from microsoft.testsuites.kata_conformance.aks_infra import AKSInfra
from microsoft.testsuites.kata_conformance.kata_conformance_tests_tool import (
    KataConformanceTests,
)


def validate_variable(variables, key, log, nullable=True, default=None):
    log.debug(f"Checking for param : {key} in variables , nullable : {nullable}")
    value = variables.get(key, None)
    if (not nullable and value is None) or (
        not nullable and type(value) == str and value.strip() == ""
    ):
        raise LisaException(key + " : Variable is null/empty")
    else:
        return value if value else default


@TestSuiteMetadata(
    area="kubernetes",
    category="community",
    description="""
    This test suite is for executing the conformance test with kata container
    which uses infra of azure AKS as kubernetes cluster
    """,
)
class KataConformanceTestSuite(TestSuite):
    @TestCaseMetadata(
        description="""
            Runs Kubernetes Kata Cotaniner Conformance test.
        """,
        priority=4,
        timeout=18000,
    )
    def kata_conformance_tests(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        log_path: Path,
        result: TestResult,
        variables: Dict[str, Any],
    ) -> None:
        # ensure virtualization is enabled in hardware before running tests
        virtualization_enabled = node.tools[Lscpu].is_virtualization_enabled()
        if not virtualization_enabled:
            raise SkippedException("Virtualization is not enabled in hardware")
        if not isinstance(node.os, (CBLMariner, Ubuntu)):
            raise SkippedException(
                f"Kata Conformance tests are not implemented in LISA for {node.os.name}"
            )

        log.debug("Variables " + json.dumps(variables))
        subscription_id = validate_variable(
            variables, "subscription_id", log, nullable=False
        )
        client_id = validate_variable(variables, "service_principal_client_id", log)
        client_secret = validate_variable(variables, "service_principal_key", log)
        tenant_id = validate_variable(variables, "service_principal_tenant_id", log)
        kubernetes_version = validate_variable(
            variables, "kubernetes_version", log, default="1.24.0"
        )
        worker_vm_size = validate_variable(
            variables, "worker_vm_size", log, default="Standard_D4s_v5"
        )
        node_count = validate_variable(variables, "node_count", log, default=3)
        azure_region = validate_variable(
            variables, "azure_region", log, default="eastus"
        )

        headers = {
            "AKSHTTPCustomFeatures": validate_variable(
                variables,
                "aks_http_custom_features",
                log,
                default="Microsoft.ContainerService/UseCustomizedOSImage",
            ),
            "OSImageSubscriptionID": validate_variable(
                variables,
                "os_image_subscription_id",
                log,
                default="b8f169b2-5b23-444a-ae4b-19a31b5e3652",
            ),
            "OSImageResourceGroup": validate_variable(
                variables, "os_image_resource_group", log, default="nehaagarwal_home"
            ),
            "OSImageGallery": validate_variable(
                variables, "os_image_gallery", log, default="packerACG"
            ),
            "OSImageName": validate_variable(
                variables, "os_image_name", log, default="output"
            ),
            "OSImageVersion": validate_variable(
                variables, "os_image_version", log, default="1.1661882687.6923"
            ),
            "OSSKU": validate_variable(variables, "ossku", log, default="CBLMariner"),
        }

        aks = AKSInfra(
            log=log,
            subscription_id=subscription_id,
            client_id=client_id,
            client_secret=client_secret,
            tenant_id=tenant_id,
        )
        aks.create_aks_infra(
            kubernetes_version, worker_vm_size, node_count, azure_region, headers
        )
        node.tools[KataConformanceTests].run_tests(result, environment, log_path)
