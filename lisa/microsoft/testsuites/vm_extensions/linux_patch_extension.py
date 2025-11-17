# Copyright (c) Microsoft Corporation. Licensed under the MIT license.

from typing import Any

from assertpy.assertpy import assert_that
from azure.core.exceptions import HttpResponseError

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.base_tools.service import Service
from lisa.operating_system import BSD, SLES, CentOs, Oracle, Redhat, Ubuntu
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    get_compute_client,
    get_node_context,
    wait_operation,
)
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.sut_orchestrator.azure.tools import VmGeneration
from lisa.util import SkippedException, UnsupportedDistroException, parse_version


def _verify_supported_arm64_images(node: Node, log: Logger, full_version: Any) -> None:
    # lpe current supported images for arm64
    supported_versions_arm64 = {
        # major.minor.gen
        CentOs: ["7.9.2"],
        Oracle: ["8.10.2", "9.4.2"],
        Ubuntu: ["20.4.2"],
    }

    # check for other supported image versions
    _validate_supported_distro(node, log, full_version, supported_versions_arm64)


def _verify_lpe_supported_images(node: Node, log: Logger, full_version: Any) -> None:
    # lpe current supported images
    lpe_supported_images_versions = {
        # major.minor.gen
        CentOs: ["7.7.1", "7.7.2", "7.9.2"],
        SLES: ["12.5.1", "12.5.2", "15.2.1", "15.2.2"],
        Ubuntu: [
            "16.4.1",
            "16.4.2",
            "18.4.1",
            "18.4.2",
            "20.4.1",
            "20.4.2",
            "22.4.1",
            "22.4.2",
        ],
    }

    # check for supported Redhat image versions [7.2.1 -> 9.5.2]
    if (
        isinstance(node.os, Redhat)
        and full_version >= parse_version("7.2.1")
        and full_version <= parse_version("9.5.2")
    ):
        log.debug(f"This is a supported image: {full_version}")
        return

    # check for supported Oracle image versions [7.9.1-> 8.5.2]
    # [8.9.1 -> 9.1.2] [9.4.1 -> 9.4.2]
    if isinstance(node.os, Oracle) and (
        (
            full_version >= parse_version("7.9.1")
            and full_version <= parse_version("8.5.2")
        )
        or (
            full_version >= parse_version("8.9.1")
            and full_version <= parse_version("9.1.2")
        )
        or (
            full_version >= parse_version("9.4.1")
            and full_version <= parse_version("9.4.2")
        )
    ):
        log.debug(f"This is a supported image: {full_version}")
        return

    # check for other supported image versions
    _validate_supported_distro(node, log, full_version, lpe_supported_images_versions)


def _validate_supported_distro(
    node: Node, log: Logger, full_version: Any, supported_distro_list: Any
) -> None:
    # check for other supported image versions
    for distro, version_list in supported_distro_list.items():
        if isinstance(node.os, distro) and full_version in version_list:
            log.debug(f"This is a supported image: {full_version}")
            return

    # Raise an exception for unsupported image versions
    log.debug(f"This is an unsupported image: {full_version}")
    _unsupported_image_exception_msg(node)


def _verify_unsupported_vm_agent(
    node: Node, status_result: Any, error_code: str
) -> None:
    unsupported_agent_msg = "Unsupported older Azure Linux Agent version"
    if error_code == "1" and any(
        unsupported_agent_msg in details["message"]
        for details in status_result["error"]["details"]
        if "message" in details
    ):
        _unsupported_image_exception_msg(node)


def _set_up_vm(node: Node, environment: Environment) -> Any:
    platform_msg = "platform should be AzurePlatform instance"
    assert environment.platform, "platform shouldn't be None."
    platform: AzurePlatform = environment.platform  # type: ignore
    assert isinstance(platform, AzurePlatform), platform_msg
    compute_client = get_compute_client(platform)
    node_context = get_node_context(node)
    resource_group_name = node_context.resource_group_name
    vm_name = node_context.vm_name

    return compute_client, resource_group_name, vm_name


def _verify_vm_agent_running(node: Node, log: Logger) -> None:
    service = node.tools[Service]
    is_vm_agent_running = service.is_service_running(
        "walinuxagent"
    ) or service.is_service_running("waagent")

    log.debug(f"verify walinuxagent or waagent running: {is_vm_agent_running}")

    if is_vm_agent_running is False:
        raise SkippedException(
            UnsupportedDistroException(
                node.os,
                (
                    "Required walinuxagent or waagent service is not running "
                    "on this vm"
                ),
            )
        )


def _verify_supported_images_and_vm_agent(node: Node, log: Logger) -> None:
    # Get the full version and OS architecture
    full_version = _get_os_full_version(node)
    arch = node.os.get_kernel_information().hardware_platform  # type: ignore

    if arch == "aarch64":
        _verify_supported_arm64_images(node, log, full_version)
    else:
        _verify_lpe_supported_images(node, log, full_version)

    # Verify if VM agent service is running, lpe is a dependent of VM agent
    _verify_vm_agent_running(node, log)


def _get_os_full_version(node: Node) -> Any:
    return (
        f"{node.os.information.version.major}."
        f"{node.os.information.version.minor}."
        f"{node.tools[VmGeneration].get_generation()}"
    )


def _assert_status_file_result(status_file: Any, error_code: str) -> None:
    file_status_is_error = status_file["status"].lower() == "error"
    expected_succeeded_status_msg = "Expected the status file status to be Succeeded"
    expected_warning_status_msg = (
        "Expected the status file status to be CompletedWithWarnings"
    )
    error_details_not_empty = len(status_file["error"]["details"]) > 0
    truncated_package_code = (
        _verify_details_code(status_file, "PACKAGE_LIST_TRUNCATED")
        if error_details_not_empty
        else False
    )
    ua_esm_required_code = (
        _verify_details_code(status_file, "UA_ESM_REQUIRED")
        if error_details_not_empty
        else False
    )
    package_manager_failure_code = (
        _verify_details_code(status_file, "PACKAGE_MANAGER_FAILURE")
        if error_details_not_empty
        else False
    )

    if truncated_package_code and not file_status_is_error:
        assert_that(status_file["status"]).described_as(
            f"{expected_warning_status_msg} - Actual status: {status_file['status']}"
        ).is_in("Warning", "CompletedWithWarnings", "Succeeded")

        # PACKAGE_LIST_TRUNCATED error code is 2
        if len(status_file["error"]["details"]) <= 1:
            assert_that(error_code).described_as(
                "Expected error code in status file patches operation"
            ).is_equal_to("2")
        else:
            # multiple errors, error code is 1
            assert_that(error_code).described_as(
                "Expected error code in status file patches operation"
            ).is_equal_to("1")

    elif ua_esm_required_code and not file_status_is_error:
        assert_that(status_file["status"]).described_as(
            f"{expected_warning_status_msg} - Actual status: {status_file['status']}"
        ).is_in("Warning", "CompletedWithWarnings", "Succeeded")
        assert_that(error_code).described_as(
            "Expected error code in status file patches operation"
        ).is_equal_to("1")

    elif package_manager_failure_code:
        assert_that(status_file["status"]).described_as(
            f"{expected_succeeded_status_msg} - Actual status: {status_file['status']}"
        ).is_equal_to("Succeeded")
        assert_that(error_code).described_as(
            "Expected error code in status file patches operation"
        ).is_equal_to("1")

    else:
        assert_that(status_file["status"]).described_as(
            f"{expected_succeeded_status_msg} - Actual status: {status_file['status']}"
        ).is_equal_to("Succeeded")
        assert_that(error_code).described_as(
            "Expected error code in status file patches operation"
        ).is_equal_to("0")


def _verify_details_code(status_file: Any, code: str) -> bool:
    return any(
        code.upper() in detail_code["code"].upper()
        for detail_code in status_file["error"]["details"]
        if "code" in detail_code
    )


def _unsupported_image_exception_msg(node: Node) -> None:
    raise SkippedException(
        UnsupportedDistroException(
            node.os, "Linux Patch Extension doesn't support this Distro version."
        )
    )


def _assert_assessment_patch(
    node: Node, log: Logger, compute_client: Any, resource_group_name: Any, vm_name: Any
) -> None:
    try:
        log.debug("Initiate the API call for the assessment patches.")
        operation = compute_client.virtual_machines.begin_assess_patches(
            resource_group_name=resource_group_name, vm_name=vm_name
        )
        # Set wait operation timeout 10 min, status file should be generated
        # before timeout
        assess_result = wait_operation(operation, 600)

    except HttpResponseError as e:
        if any(
            s in str(e)
            for s in [
                "The selected VM image is not supported",
                "CPU Architecture 'arm64' was not found in the extension repository",
            ]
        ):
            _unsupported_image_exception_msg(node)
        else:
            raise e

    assert assess_result, "assess_result shouldn't be None"
    log.debug(f"assess_result:{assess_result}")
    error_code = assess_result["error"]["code"]

    _verify_unsupported_vm_agent(node, assess_result, error_code)
    _assert_status_file_result(assess_result, error_code)


def _assert_installation_patch(
    node: Node,
    log: Logger,
    compute_client: Any,
    resource_group_name: Any,
    vm_name: Any,
    timeout: Any,
    install_patches_input: Any,
) -> None:
    try:
        log.debug("Initiate the API call for the installation patches.")
        operation = compute_client.virtual_machines.begin_install_patches(
            resource_group_name=resource_group_name,
            vm_name=vm_name,
            install_patches_input=install_patches_input,
        )
        # Set wait operation max duration 4H timeout, status file should be
        # generated before timeout
        install_result = wait_operation(operation, timeout)

    except HttpResponseError as e:
        if any(
            s in str(e)
            for s in [
                "The selected VM image is not supported",
                "CPU Architecture 'arm64' was not found in the extension repository",
            ]
        ):
            _unsupported_image_exception_msg(node)
        else:
            raise e

    assert install_result, "install_result shouldn't be None"
    log.debug(f"install_result:{install_result}")
    error_code = install_result["error"]["code"]

    _verify_unsupported_vm_agent(node, install_result, error_code)
    _assert_status_file_result(install_result, error_code)


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="Test for Linux Patch Extension",
    requirement=simple_requirement(
        supported_platform_type=[AZURE], unsupported_os=[BSD]
    ),
)
class LinuxPatchExtensionBVT(TestSuite):
    TIMEOUT = 14400  # 4H Max install operation duration

    @TestCaseMetadata(
        description="""
        Verify walinuxagent or waagent service is running on vm. Perform assess
        patches to trigger Microsoft.CPlat.Core.LinuxPatchExtension creation in
        vm. Verify status file response for validity.
        """,
        priority=1,
        timeout=600,
    )
    def verify_vm_assess_patches(
        self, node: Node, environment: Environment, log: Logger
    ) -> None:
        compute_client, resource_group_name, vm_name = _set_up_vm(node, environment)

        # Check if the OS is supported and the VM agent is running
        _verify_supported_images_and_vm_agent(node, log)

        # Verify the assessment patches
        _assert_assessment_patch(
            node, log, compute_client, resource_group_name, vm_name
        )

    @TestCaseMetadata(
        description="""
        Verify walinuxagent or waagent service is running on vm. Perform
        install patches to trigger Microsoft.CPlat.Core.LinuxPatchExtension
        creation in vm.
        Verify status file response for validity.
        """,
        priority=3,
        timeout=TIMEOUT,
    )
    def verify_vm_install_patches(
        self, node: Node, environment: Environment, log: Logger
    ) -> None:
        compute_client, resource_group_name, vm_name = _set_up_vm(node, environment)
        install_patches_input = {
            "maximumDuration": "PT4H",
            "rebootSetting": "IfRequired",
            "linuxParameters": {
                "classificationsToInclude": ["Security", "Critical"],
                "packageNameMasksToInclude": ["ca-certificates*", "php7-openssl*"],
            },
        }

        # Check if the OS is supported and the VM agent is running
        _verify_supported_images_and_vm_agent(node, log)

        # Verify the assessment patches
        _assert_assessment_patch(
            node, log, compute_client, resource_group_name, vm_name
        )

        # Verify the installation patches
        _assert_installation_patch(
            node,
            log,
            compute_client,
            resource_group_name,
            vm_name,
            self.TIMEOUT,
            install_patches_input,
        )
