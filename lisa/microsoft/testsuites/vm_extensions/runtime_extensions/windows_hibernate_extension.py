# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict

from lisa import Environment, Logger, Node, TestCaseMetadata, TestSuiteMetadata
from lisa.operating_system import Windows

from .hibernate_extension_base import (
    HIBERNATE_RESUME_TEST_TIMEOUT_SECONDS,
    HibernateExtensionTestBase,
    hibernate_extension_requirement,
)


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="""
    Validates Microsoft.CPlat.Core.WindowsHibernateExtension candidates supplied
    by AzCertify.
    """,
    tags=[
        "VM_Extension",
        "HibernateExtension",
        "WindowsHibernateExtension",
        "microsoft.cplat.core.windowshibernateextension",
    ],
    requirement=hibernate_extension_requirement(Windows),
)
class WindowsHibernateExtensionTests(HibernateExtensionTestBase):
    PUBLISHER = "Microsoft.CPlat.Core"
    EXTENSION_TYPE = "WindowsHibernateExtension"
    EXTENSION_KEY = "windows_hibernate_extension"
    EXTENSION_RESOURCE_NAME = "AzureHibernateExtension"
    EXPECTED_INSTANCE_VIEW_TYPES = (
        "Microsoft.Azure.Extensions.Edp.WindowsHibernateTestExtension",
        "Microsoft.CPlat.Core.WindowsHibernateExtension",
    )
    EXPECTED_OS = Windows
    PLATFORM_MANAGED = True

    @TestCaseMetadata(
        description="""
        Verifies the platform-managed Windows hibernate extension candidate
        supplied by AzCertify is provisioned successfully, checks the exact
        installed version when a full version is requested, then runs the
        complete Aurora HibernateResume scenario. It captures boot and process
        state and performs five hibernate/resume cycles with memory pressure
        ramped from 10% through 50%. Each cycle verifies hibernated and running
        states, a fresh extension resume substatus, proves the guest resumed
        rather than rebooted, and confirms the memory-load process survived.
        Validation uses Azure control-plane operations and does not require
        inbound SSH.
        """,
        priority=5,
        timeout=HIBERNATE_RESUME_TEST_TIMEOUT_SECONDS,
        maturity="preview",
    )
    def microsoft_cplat_core_windowshibernateextension_boot_validation_test(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        variables: Dict[str, Any],
    ) -> None:
        self._run_hibernate_resume_validation(
            node=node,
            log=log,
            environment=environment,
            variables=variables,
        )
