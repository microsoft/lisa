# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import datetime
import uuid
from typing import Any, Dict, Optional, Type

from microsoft.testsuites.vm_extensions.vm_extension_base import VmExtensionTestBase

from lisa import Logger, Node, TestCaseMetadata, TestSuiteMetadata, simple_requirement
from lisa.operating_system import (
    SLES,
    Debian,
    Linux,
    OperatingSystem,
    Oracle,
    Redhat,
    Ubuntu,
    Windows,
)
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.testsuite import TestCaseRequirement
from lisa.util import SkippedException

_SITE_RECOVERY_PUBLISHER = "Microsoft.Azure.RecoveryServices.SiteRecovery"
_SITE_RECOVERY2_PUBLISHER = "Microsoft.Azure.RecoveryServices.SiteRecovery2"


def _extension_requirement(
    os_type: Type[OperatingSystem],
) -> TestCaseRequirement:
    return simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        supported_os=[os_type],
    )


def _settings(command: str) -> Dict[str, str]:
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {
        "publicObject": "",
        "module": "a2a",
        "timeStamp": timestamp.replace("+00:00", "Z"),
        "commandToExecute": command,
        "taskId": str(uuid.uuid4()),
    }


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="""
    This test suite validates production Azure Site Recovery VM extensions.

    The common Linux extension runs GetOsDetails. Windows and distro-specific
    extensions run the public-only Install command, which installs the embedded
    Mobility Service package without configuring replication.
    """,
    tags=["VM_Extension"],
    requirement=simple_requirement(
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        supported_os=[Linux, Windows],
    ),
)
class SiteRecoveryTests(VmExtensionTestBase):  # type: ignore[misc]
    def _validate_extension(
        self,
        node: Node,
        log: Logger,
        variables: Dict[str, Any],
        publisher: str,
        extension_type: str,
        extension_key: str,
        command: str,
        expected_os: Optional[Type[OperatingSystem]] = None,
        expected_major_version: Optional[int] = None,
    ) -> None:
        if expected_os is not None:
            actual_major_version = node.os.information.version.major
            if (
                type(node.os) is not expected_os
                or actual_major_version != expected_major_version
            ):
                raise SkippedException(
                    f"{publisher}.{extension_type} requires "
                    f"{expected_os.__name__} {expected_major_version}, but the "
                    f"node is {type(node.os).__name__} {actual_major_version}."
                )

        case_variables = dict(variables)
        case_variables["extension_publisher"] = publisher
        case_variables["extension_type"] = extension_type
        if not str(case_variables.get("extension_version", "")).strip():
            scoped_version = str(
                case_variables.get(f"{extension_key}_version", "")
            ).strip()
            if scoped_version:
                case_variables["extension_version"] = scoped_version

        self._boot_validation(
            node=node,
            log=log,
            variables=case_variables,
            settings=_settings(command),
            mark_dirty_before_install=command == "Install",
        )

    @TestCaseMetadata(
        description="""
        Validates the production Site Recovery common Linux extension by
        running GetOsDetails with the explicitly requested candidate version.
        """,
        priority=5,
        tags=["microsoft.azure.recoveryservices.siterecovery.linux"],
        maturity="preview",
        requirement=_extension_requirement(Linux),
    )
    def microsoft_azure_recoveryservices_siterecovery_linux_boot_validation_test(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._validate_extension(
            node,
            log,
            variables,
            _SITE_RECOVERY_PUBLISHER,
            "Linux",
            "site_recovery_linux",
            "GetOsDetails",
        )

    @TestCaseMetadata(
        description="""
        Validates the production Site Recovery Windows extension by installing
        its embedded Mobility Service package without configuring replication.
        """,
        priority=5,
        tags=["microsoft.azure.recoveryservices.siterecovery.windows"],
        maturity="preview",
        requirement=_extension_requirement(Windows),
    )
    def microsoft_azure_recoveryservices_siterecovery_windows_boot_validation_test(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._validate_extension(
            node,
            log,
            variables,
            _SITE_RECOVERY_PUBLISHER,
            "Windows",
            "site_recovery_windows",
            "Install",
        )

    @TestCaseMetadata(
        description="Validates the production Site Recovery RHEL 7 package.",
        priority=5,
        tags=["microsoft.azure.recoveryservices.siterecovery.linuxrhel7"],
        maturity="preview",
        requirement=_extension_requirement(Redhat),
    )
    def microsoft_azure_recoveryservices_siterecovery_linuxrhel7_boot_validation_test(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._validate_extension(
            node,
            log,
            variables,
            _SITE_RECOVERY_PUBLISHER,
            "LinuxRHEL7",
            "site_recovery_linux_rhel7",
            "Install",
            Redhat,
            7,
        )

    @TestCaseMetadata(
        description="Validates the production Site Recovery Debian 11 package.",
        priority=5,
        tags=["microsoft.azure.recoveryservices.siterecovery2.linuxdebian11"],
        maturity="preview",
        requirement=_extension_requirement(Debian),
    )
    def microsoft_azure_recoveryservices_siterecovery2_linuxdebian11_boot_validation_test(  # noqa: E501
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._validate_extension(
            node,
            log,
            variables,
            _SITE_RECOVERY2_PUBLISHER,
            "LinuxDEBIAN11",
            "site_recovery2_linux_debian11",
            "Install",
            Debian,
            11,
        )

    @TestCaseMetadata(
        description="Validates the production Site Recovery Debian 12 package.",
        priority=5,
        tags=["microsoft.azure.recoveryservices.siterecovery2.linuxdebian12"],
        maturity="preview",
        requirement=_extension_requirement(Debian),
    )
    def microsoft_azure_recoveryservices_siterecovery2_linuxdebian12_boot_validation_test(  # noqa: E501
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._validate_extension(
            node,
            log,
            variables,
            _SITE_RECOVERY2_PUBLISHER,
            "LinuxDEBIAN12",
            "site_recovery2_linux_debian12",
            "Install",
            Debian,
            12,
        )

    @TestCaseMetadata(
        description="Validates the production Site Recovery Debian 13 package.",
        priority=5,
        tags=["microsoft.azure.recoveryservices.siterecovery2.linuxdebian13"],
        maturity="preview",
        requirement=_extension_requirement(Debian),
    )
    def microsoft_azure_recoveryservices_siterecovery2_linuxdebian13_boot_validation_test(  # noqa: E501
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._validate_extension(
            node,
            log,
            variables,
            _SITE_RECOVERY2_PUBLISHER,
            "LinuxDEBIAN13",
            "site_recovery2_linux_debian13",
            "Install",
            Debian,
            13,
        )

    @TestCaseMetadata(
        description="Validates the production Site Recovery Oracle Linux 8 package.",
        priority=5,
        tags=["microsoft.azure.recoveryservices.siterecovery2.linuxol8"],
        maturity="preview",
        requirement=_extension_requirement(Oracle),
    )
    def microsoft_azure_recoveryservices_siterecovery2_linuxol8_boot_validation_test(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._validate_extension(
            node,
            log,
            variables,
            _SITE_RECOVERY2_PUBLISHER,
            "LinuxOL8",
            "site_recovery2_linux_ol8",
            "Install",
            Oracle,
            8,
        )

    @TestCaseMetadata(
        description="Validates the production Site Recovery Oracle Linux 9 package.",
        priority=5,
        tags=["microsoft.azure.recoveryservices.siterecovery2.linuxol9"],
        maturity="preview",
        requirement=_extension_requirement(Oracle),
    )
    def microsoft_azure_recoveryservices_siterecovery2_linuxol9_boot_validation_test(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._validate_extension(
            node,
            log,
            variables,
            _SITE_RECOVERY2_PUBLISHER,
            "LinuxOL9",
            "site_recovery2_linux_ol9",
            "Install",
            Oracle,
            9,
        )

    @TestCaseMetadata(
        description="Validates the production Site Recovery RHEL 8 package.",
        priority=5,
        tags=["microsoft.azure.recoveryservices.siterecovery2.linuxrhel8"],
        maturity="preview",
        requirement=_extension_requirement(Redhat),
    )
    def microsoft_azure_recoveryservices_siterecovery2_linuxrhel8_boot_validation_test(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._validate_extension(
            node,
            log,
            variables,
            _SITE_RECOVERY2_PUBLISHER,
            "LinuxRHEL8",
            "site_recovery2_linux_rhel8",
            "Install",
            Redhat,
            8,
        )

    @TestCaseMetadata(
        description="Validates the production Site Recovery RHEL 9 package.",
        priority=5,
        tags=["microsoft.azure.recoveryservices.siterecovery2.linuxrhel9"],
        maturity="preview",
        requirement=_extension_requirement(Redhat),
    )
    def microsoft_azure_recoveryservices_siterecovery2_linuxrhel9_boot_validation_test(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._validate_extension(
            node,
            log,
            variables,
            _SITE_RECOVERY2_PUBLISHER,
            "LinuxRHEL9",
            "site_recovery2_linux_rhel9",
            "Install",
            Redhat,
            9,
        )

    @TestCaseMetadata(
        description="Validates the production Site Recovery SLES 12 package.",
        priority=5,
        tags=["microsoft.azure.recoveryservices.siterecovery2.linuxsles12"],
        maturity="preview",
        requirement=_extension_requirement(SLES),
    )
    def microsoft_azure_recoveryservices_siterecovery2_linuxsles12_boot_validation_test(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._validate_extension(
            node,
            log,
            variables,
            _SITE_RECOVERY2_PUBLISHER,
            "LinuxSLES12",
            "site_recovery2_linux_sles12",
            "Install",
            SLES,
            12,
        )

    @TestCaseMetadata(
        description="Validates the production Site Recovery SLES 15 package.",
        priority=5,
        tags=["microsoft.azure.recoveryservices.siterecovery2.linuxsles15"],
        maturity="preview",
        requirement=_extension_requirement(SLES),
    )
    def microsoft_azure_recoveryservices_siterecovery2_linuxsles15_boot_validation_test(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._validate_extension(
            node,
            log,
            variables,
            _SITE_RECOVERY2_PUBLISHER,
            "LinuxSLES15",
            "site_recovery2_linux_sles15",
            "Install",
            SLES,
            15,
        )

    @TestCaseMetadata(
        description="Validates the production Site Recovery SLES 16 package.",
        priority=5,
        tags=["microsoft.azure.recoveryservices.siterecovery2.linuxsles16"],
        maturity="preview",
        requirement=_extension_requirement(SLES),
    )
    def microsoft_azure_recoveryservices_siterecovery2_linuxsles16_boot_validation_test(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._validate_extension(
            node,
            log,
            variables,
            _SITE_RECOVERY2_PUBLISHER,
            "LinuxSLES16",
            "site_recovery2_linux_sles16",
            "Install",
            SLES,
            16,
        )

    @TestCaseMetadata(
        description="Validates the production Site Recovery Ubuntu 18.04 package.",
        priority=5,
        tags=["microsoft.azure.recoveryservices.siterecovery2.linuxubuntu1804"],
        maturity="preview",
        requirement=_extension_requirement(Ubuntu),
    )
    def microsoft_azure_recoveryservices_siterecovery2_linuxubuntu1804_boot_validation_test(  # noqa: E501
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._validate_extension(
            node,
            log,
            variables,
            _SITE_RECOVERY2_PUBLISHER,
            "LinuxUBUNTU1804",
            "site_recovery2_linux_ubuntu1804",
            "Install",
            Ubuntu,
            18,
        )

    @TestCaseMetadata(
        description="Validates the production Site Recovery Ubuntu 20.04 package.",
        priority=5,
        tags=["microsoft.azure.recoveryservices.siterecovery2.linuxubuntu2004"],
        maturity="preview",
        requirement=_extension_requirement(Ubuntu),
    )
    def microsoft_azure_recoveryservices_siterecovery2_linuxubuntu2004_boot_validation_test(  # noqa: E501
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._validate_extension(
            node,
            log,
            variables,
            _SITE_RECOVERY2_PUBLISHER,
            "LinuxUBUNTU2004",
            "site_recovery2_linux_ubuntu2004",
            "Install",
            Ubuntu,
            20,
        )

    @TestCaseMetadata(
        description="Validates the production Site Recovery Ubuntu 22.04 package.",
        priority=5,
        tags=["microsoft.azure.recoveryservices.siterecovery2.linuxubuntu2204"],
        maturity="preview",
        requirement=_extension_requirement(Ubuntu),
    )
    def microsoft_azure_recoveryservices_siterecovery2_linuxubuntu2204_boot_validation_test(  # noqa: E501
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._validate_extension(
            node,
            log,
            variables,
            _SITE_RECOVERY2_PUBLISHER,
            "LinuxUBUNTU2204",
            "site_recovery2_linux_ubuntu2204",
            "Install",
            Ubuntu,
            22,
        )

    @TestCaseMetadata(
        description="Validates the production Site Recovery Ubuntu 24.04 package.",
        priority=5,
        tags=["microsoft.azure.recoveryservices.siterecovery2.linuxubuntu2404"],
        maturity="preview",
        requirement=_extension_requirement(Ubuntu),
    )
    def microsoft_azure_recoveryservices_siterecovery2_linuxubuntu2404_boot_validation_test(  # noqa: E501
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._validate_extension(
            node,
            log,
            variables,
            _SITE_RECOVERY2_PUBLISHER,
            "LinuxUBUNTU2404",
            "site_recovery2_linux_ubuntu2404",
            "Install",
            Ubuntu,
            24,
        )

    @TestCaseMetadata(
        description="Validates the production Site Recovery Ubuntu 26.04 package.",
        priority=5,
        tags=["microsoft.azure.recoveryservices.siterecovery2.linuxubuntu2604"],
        maturity="preview",
        requirement=_extension_requirement(Ubuntu),
    )
    def microsoft_azure_recoveryservices_siterecovery2_linuxubuntu2604_boot_validation_test(  # noqa: E501
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        self._validate_extension(
            node,
            log,
            variables,
            _SITE_RECOVERY2_PUBLISHER,
            "LinuxUBUNTU2604",
            "site_recovery2_linux_ubuntu2604",
            "Install",
            Ubuntu,
            26,
        )
