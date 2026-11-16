# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from lisa import TestCaseMetadata, TestSuiteMetadata, simple_requirement
from lisa.environment import EnvironmentStatus
from lisa.operating_system import BSD, Windows
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.features import AzureExtension

from .vm_applications_base import VmApplicationsBase


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="CRP-driven VM applications on one SSH-free Linux VM.",
    tags=["VM_Extension", "VmApplications", "VmApplicationsLinux"],
    maturity="preview",
    reuse_deployed_environment=True,
    requirement=simple_requirement(
        environment_status=EnvironmentStatus.Deployed,
        remote_connection_required=False,
        supported_features=[AzureExtension],
        supported_platform_type=[AZURE],
        unsupported_os=[BSD, Windows],
    ),
)
class VmApplicationsLinuxTests(VmApplicationsBase):
    OS_TYPE = "Linux"
    EXTENSION_TYPE = "VMApplicationManagerLinux"

    @TestCaseMetadata(
        description="Install/configuration, root, manual apps and CRP rejection."
    )
    def verify_installation_and_configuration(self) -> None:
        self._verify_installation_and_configuration()

    @TestCaseMetadata(
        description="Install, idempotency, native update, downgrade and replacement."
    )
    def verify_application_lifecycle(self) -> None:
        self._verify_application_lifecycle()

    @TestCaseMetadata(description="Ordered mixed removal, update and installation.")
    def verify_ordered_operations(self) -> None:
        self._verify_ordered_operations()

    @TestCaseMetadata(
        description="Ordered failure, peer continuation, skipped cleanup and recovery."
    )
    def verify_ordered_failure_and_recovery(self) -> None:
        self._verify_ordered_failure_and_recovery()

    @TestCaseMetadata(description="Install/update deployment-failure flag matrix.")
    def verify_failure_policy(self) -> None:
        self._verify_failure_policy()

    @TestCaseMetadata(description="Failed old-version removal blocks replacement.")
    def verify_replace_failure(self) -> None:
        self._verify_replace_failure()

    @TestCaseMetadata(
        description="Modified-cache/normal removal, preserved peers and reinstallation."
    )
    def verify_removal_and_reuse(self) -> None:
        self._verify_removal_and_reuse()

    # TODO: Re-enable after PIR correctly forwards custom-action metadata to CRP.
    # @TestCaseMetadata(description="Custom actions and literal/default parameters.")
    def verify_custom_action(self) -> None:
        self._verify_custom_action()

    @TestCaseMetadata(description="Remove failure is reported without blocking others.")
    def verify_remove_failure(self) -> None:
        self._verify_remove_failure()

    # TODO: Re-enable after PIR correctly forwards custom-action metadata to CRP.
    # @TestCaseMetadata(description="Custom-action identifiers control replay.")
    def verify_custom_action_replay(self) -> None:
        self._verify_custom_action_replay()

    # TODO: Re-enable after PIR correctly forwards custom-action metadata to CRP.
    # @TestCaseMetadata(description="Custom-action failure reporting and recovery.")
    def verify_custom_action_failure(self) -> None:
        self._verify_custom_action_failure()

    @TestCaseMetadata(description="Child CRUD, instance view and tag-only updates.")
    def verify_child_resource_operations(self) -> None:
        self._verify_child_resource_operations()

    # TODO: Re-enable after PIR correctly forwards custom-action metadata to CRP.
    # @TestCaseMetadata(description="CRP validates action names and parameters.")
    def verify_custom_action_validation(self) -> None:
        self._verify_custom_action_validation()

    @TestCaseMetadata(description="Registry survives a CRP restart without reinstall.")
    def verify_restart_persistence(self) -> None:
        self._verify_restart_persistence()

    @TestCaseMetadata(description="Rebooting installation is not rerun with None.")
    def verify_reboot_without_rerun(self) -> None:
        self._verify_reboot(False)

    @TestCaseMetadata(description="Rebooting installation completes once after Rerun.")
    def verify_reboot_with_rerun(self) -> None:
        self._verify_reboot(True)
