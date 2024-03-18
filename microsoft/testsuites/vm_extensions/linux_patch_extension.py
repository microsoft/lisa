# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


from assertpy.assertpy import assert_that
from lisa.base_tools.service import Service
from lisa.sut_orchestrator.azure.common import (
    get_compute_client,
    get_node_context,
    wait_operation,
)

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)

from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.util import LisaException

def _verify_vm_agent_running(node: Node, log: Logger) -> None:
    service = node.tools[Service]
    is_vm_agent_running = service.is_service_running("walinuxagent.service") or service.is_service_running("waagent.service")
    
    if is_vm_agent_running:
        log.debug("verify walinuxagent or waagent is running")
        assert_that(is_vm_agent_running).described_as(
            "Expected walinuxagent or waagent is running"
        ).is_true()
    else:
        log.debug("verify walinuxagent or waagent is not running")
        raise LisaException("walinuxagent or waagent is not running. Test case failed.")

@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="Test for Linux Patch Extension",
    requirement=simple_requirement(unsupported_os=[]),
)

class LinuxPatchExtensionBVT(TestSuite):
    @TestCaseMetadata(
        description="""
        Verify walinuxagent or waagent is running on virtual machine.
        Perform assess patches to trigger Microsoft.CPlat.Core.LinuxPatchExtension creation in a virtual machine.
        Verify status file response for validity.
        """,
        priority=0,
    )
    def verify_vm_assess_patches(self, node:Node, environment:Environment, log:Logger)->None:
        assert environment.platform
        platform: AzurePlatform = environment.platform  # type: ignore
        assert isinstance(platform, AzurePlatform)
        compute_client = get_compute_client(platform)
        node_context = get_node_context(node)
        resource_group_name = node_context.resource_group_name
        vm_name = node_context.vm_name

        # verify vm agent is running
        _verify_vm_agent_running(node, log)

        operation = compute_client.virtual_machines.begin_assess_patches(resource_group_name=resource_group_name,vm_name=vm_name)

        # pause fetching operation by 1min, so status file can be generated
        assess_result =wait_operation(operation, 60000)
        log.debug(f"assess_result: {assess_result}")

        assert_that(assess_result["status"]).described_as(
            "Expected the assess patches to succeed"
        ).is_equal_to("Succeeded")

        assert_that(assess_result["error"]['code']).described_as(
            "Expected no error in assess patches operation"
        ).is_equal_to("0")

    @TestCaseMetadata(
        description="""
        Verify walinuxagent or waagent is running on virtual machine.
        Perform install patches to trigger Microsoft.CPlat.Core.LinuxPatchExtension creation in a virtual machine.
        Verify status file response for validity.
        """,
        priority=1,
    )
    def verify_vm_install_patches(self, node:Node, environment:Environment, log:Logger)->None:
        assert environment.platform
        platform: AzurePlatform = environment.platform  # type: ignore
        assert isinstance(platform, AzurePlatform)
        compute_client = get_compute_client(platform)
        node_context = get_node_context(node)
        resource_group_name = node_context.resource_group_name
        vm_name = node_context.vm_name

        # verify vm agent is running
        _verify_vm_agent_running(node, log)

        operation = compute_client.virtual_machines.begin_install_patches(resource_group_name=resource_group_name,vm_name=vm_name)

        # pause fetching operation by 1min, so status file can be generated
        result =wait_operation(operation, 60000)
        log.debug(f"result: {result}")

        assert_that(result["status"]).described_as(
            "Expected the install patches to succeed"
        ).is_equal_to("Succeeded")

        assert_that(result["error"]['code']).described_as(
            "Expected no error in install patches operation"
        ).is_equal_to("0")

    
    