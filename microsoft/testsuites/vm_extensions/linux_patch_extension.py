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
from lisa.operating_system import BSD
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    get_compute_client,
    get_node_context,
    wait_operation,
)
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.util import SkippedException, UnsupportedDistroException


def _verify_unsupported_vm_agent(
    node: Node, status_result: Any, error_code: str
) -> None:
    if (
        error_code == "1"
        and "Unsupported older Azure Linux Agent version"
        in status_result["error"]["details"][0]["message"]
    ):
        raise SkippedException(UnsupportedDistroException(node.os))


def _set_up_vm(node: Node, environment: Environment) -> Any:
    assert environment.platform, "platform shouldn't be None."
    platform: AzurePlatform = environment.platform  # type: ignore
    assert isinstance(
        platform, AzurePlatform
    ), "platform should be AzurePlatform instance"
    assert isinstance(
        platform, AzurePlatform
    ), "platform should be AzurePlatform instance"
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

    log.debug(f"verify walinuxagent or waagent running:{is_vm_agent_running}")

    assert_that(is_vm_agent_running).described_as(
        "Expected walinuxagent or waagent service is running"
    ).is_true()


def _assert_status_file_result(status_file: Any, error_code: str) -> None:
    if (
        len(status_file["error"]["details"]) > 0
        and status_file["error"]["details"][0]["code"] == "PACKAGE_LIST_TRUNCATED"
    ):
        assert_that(status_file["status"]).described_as(
            "Expected the status file patches to CompletedWithWarnings"
        ).is_equal_to("CompletedWithWarnings")
    else:
        assert_that(status_file["status"]).described_as(
            "Expected the status file patches to succeed"
        ).is_equal_to("Succeeded")

        assert_that(error_code).described_as(
            "Expected no error in status file patches operation"
        ).is_equal_to("0")


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
    )
    def verify_vm_assess_patches(
        self, node: Node, environment: Environment, log: Logger
    ) -> None:
        compute_client, resource_group_name, vm_name = _set_up_vm(node, environment)
        # verify vm agent service is running, lpe is a dependent of vm agent
        # service
        _verify_vm_agent_running(node, log)

        try:
            operation = compute_client.virtual_machines.begin_assess_patches(
                resource_group_name=resource_group_name, vm_name=vm_name
            )
            # set wait operation timeout 10 min, status file should be generated
            # before timeout
            assess_result = wait_operation(operation, 600)

        except HttpResponseError as identifier:
            if any(
                s in str(identifier) for s in ["The selected VM image is not supported"]
            ):
                raise SkippedException(UnsupportedDistroException(node.os))
            else:
                raise identifier

        assert assess_result, "assess_result shouldn't be None"
        log.debug(f"assess_result:{assess_result}")
        error_code = assess_result["error"]["code"]

        _verify_unsupported_vm_agent(node, assess_result, error_code)
        _assert_status_file_result(assess_result, error_code)

    @TestCaseMetadata(
        description="""
        Verify walinuxagent or waagent service is running on vm. Perform install
        patches to trigger Microsoft.CPlat.Core.LinuxPatchExtension creation in vm.
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

        # verify vm agent service is running, lpe is a dependent of vm agent
        # service
        _verify_vm_agent_running(node, log)

        try:
            operation = compute_client.virtual_machines.begin_install_patches(
                resource_group_name=resource_group_name,
                vm_name=vm_name,
                install_patches_input=install_patches_input,
            )
            # set wait operation max duration 4H timeout, status file should be
            # generated before timeout
            install_result = wait_operation(operation, self.TIMEOUT)

        except HttpResponseError as identifier:
            if any(
                s in str(identifier) for s in ["The selected VM image is not supported"]
            ):
                raise SkippedException(UnsupportedDistroException(node.os))
            else:
                raise identifier

        assert install_result, "install_result shouldn't be None"
        log.debug(f"install_result:{install_result}")
        error_code = install_result["error"]["code"]

        _verify_unsupported_vm_agent(node, install_result, error_code)
        _assert_status_file_result(install_result, error_code)
