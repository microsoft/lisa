# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
import random
import string
import time
from datetime import datetime, timezone
from typing import Any

from assertpy import assert_that
from azure.mgmt.keyvault import KeyVaultManagementClient  # type: ignore
from azure.mgmt.keyvault.models import AccessPolicyEntry, Permissions
from azure.mgmt.keyvault.models import Sku as KeyVaultSku  # type: ignore
from azure.mgmt.keyvault.models import VaultCreateOrUpdateParameters, VaultProperties

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import (
    BSD,
    SLES,
    CBLMariner,
    CentOs,
    Oracle,
    Posix,
    Redhat,
    Suse,
    Ubuntu,
)
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    AzureNodeSchema,
    create_keyvault,
    get_node_context,
    get_tenant_id
)
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.testsuite import TestResult
from lisa.util import SkippedException, generate_random_chars


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="Tests for the Azure Disk Encryption (ADE) extension",
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        supported_os=[Ubuntu, CBLMariner, CentOs, Oracle, Redhat, SLES, Suse]
    ),
)
class AzureDiskEncryption(TestSuite):
    @TestCaseMetadata(
        description="""
        Runs the ADE extension and verifies it executed on the
        remote machine.
        """,
        priority=1,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_azure_disk_encryption(
        self, log: Logger, node: Node, result: TestResult
    ) -> None:
      
        log.debug("Environment setup")
        environment = result.environment
        assert environment, "fail to get environment from testresult"
        platform = environment.platform
        assert isinstance(platform, AzurePlatform)

        # VM attributes
        node_context = get_node_context(node)
        resource_group_name = node_context.resource_group_name
        node_capability = node.capability.get_extended_runbook(AzureNodeSchema, AZURE)
        location = node_capability.location

        # get user tenant id for KV creation
        tenant_id = get_tenant_id(platform.credential)
        if tenant_id is None:
            raise ValueError("Environment variable 'AZURE_TENANT_ID' is not set.")
        
         # User's attributes
        # tenant_id = os.environ["AZURE_TENANT_ID"]
        # if tenant_id is None:
        #     raise ValueError("Environment variable 'tenant_id' is not set.")
        # object_id = os.environ["AZURE_CLIENT_ID"]
        # if object_id is None:
        #     raise ValueError("Environment variable 'object_id' is not set.")

        log.debug(f"tenant_id {tenant_id}")

        # vault_properties = VaultProperties(
        #     tenant_id=tenant_id,
        #     sku=KeyVaultSku(name="standard"),
        #     enabled_for_disk_encryption=True,
        #     access_policies=[
        #         AccessPolicyEntry(
        #             tenant_id=tenant_id,
        #             permissions=Permissions(
        #                 keys=["all"], secrets=["all"], certificates=["all"]
        #             ),
        #         ),
        #     ],
        # )

        # # Create Key Vault
        # vault_name = f"kve-{time.strftime('%y%m%d%H%M%S')}-{random.randint(1, 1000):03}"
        # keyvault_result = create_keyvault(
        #     platform=platform,
        #     resource_group_name=node_context.resource_group_name,
        #     location=node_context.location,
        #     vault_name=vault_name,
        # )

        # log.debug(f"Key vault creation result: {keyvault_result}")