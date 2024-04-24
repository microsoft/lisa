# Copyright (c) Microsoft Corporation. Licensed under the MIT license.

from typing import Any, Dict, List

from assertpy.assertpy import assert_that

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
from lisa.operating_system import BSD, SLES, CBLMariner, Debian, Redhat
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    get_compute_client,
    get_node_context,
    wait_operation,
)
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.util import SkippedException, UnsupportedDistroException


def _is_os_unsupported(self, node: Node) -> None:
    """
    Below specific Linux distro versions that are
    not supported by linux patch extension.
    debian debian-11 11 0.20230124.1270
    redhat rhel-arm64 8_6-arm64 8.6.2022060901
    debian debian-11 11-backports 0.20221219.1234
    microsoftcblmariner cbl-mariner cbl-mariner-2-arm64 2.20230126.01
    suse sles-15-sp5 gen2 2024.02.07
    """
    unsupported_versions_x86_64: Dict[type, List[str]] = {
        Debian: [10, 11],
        SLES: [15],
        CBLMariner: [2],
    }
    unsupported_versions_arm64: Dict[type, List[str]] = {
        Redhat: [8_6],
    }

    arch = node.os.get_kernel_information().hardware_platform  # type: ignore
    if arch == "aarch64":
        unsupported_versions = unsupported_versions_arm64
    else:
        unsupported_versions = unsupported_versions_x86_64

    # Extract Debian version from the complete version string
    debian_version = node.os.information.version.major.split()[1]

    for distro, version_list in unsupported_versions.items():
        if isinstance(node.os, distro) and debian_version in version_list:
            # Both node.os and distro are in the version_list, so raise an exception
            raise SkippedException(
                UnsupportedDistroException(
                    node.os, "This Distro version is unsupported"
                )
            )


def _set_up_vm(node: Node, environment: Environment) -> Any:
    _is_os_unsupported(node)
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

        operation = compute_client.virtual_machines.begin_assess_patches(
            resource_group_name=resource_group_name, vm_name=vm_name
        )
        # set wait operation timeout 10 min, status file should be generated
        # before timeout
        assess_result = wait_operation(operation, 600)

        assert assess_result, "assess_result shouldn't be None"
        log.debug(f"assess_result:{assess_result}")
        assert_that(assess_result["status"]).described_as(
            "Expected the assess patches to succeed"
        ).is_equal_to("Succeeded")

        assert_that(assess_result["error"]["code"]).described_as(
            "Expected no error in assess patches operation"
        ).is_equal_to("0")

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

        operation = compute_client.virtual_machines.begin_install_patches(
            resource_group_name=resource_group_name,
            vm_name=vm_name,
            install_patches_input=install_patches_input,
        )
        # set wait operation max duration 3H30M timeout, status file should be
        # generated before timeout
        install_result = wait_operation(operation, self.TIMEOUT)

        assert install_result, "install_result shouldn't be None"
        log.debug(f"install_result:{install_result}")
        assert_that(install_result["status"]).described_as(
            "Expected the install patches to succeed"
        ).is_equal_to("Succeeded")

        assert_that(install_result["error"]["code"]).described_as(
            "Expected no error in install patches operation"
        ).is_equal_to("0")
