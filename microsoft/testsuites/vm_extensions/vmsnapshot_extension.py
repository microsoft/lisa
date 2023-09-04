# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import time
import uuid
from datetime import datetime

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
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    AzureNodeSchema,
    get_compute_client,
    get_node_context,
    wait_operation,
)
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform


@TestSuiteMetadata(
    area="vm_extension",
    category="functional",
    description="Test for VMSnapshot extension",
    requirement=simple_requirement(unsupported_os=[]),
)
class VmSnapsotLinuxBVTExtension(TestSuite):
    @TestCaseMetadata(
        description="""
        Create a restore point collection for the virtual machine.
        Create application consistent restore point on the restore point
        collection.
        Validate response of the restore point for validity.
        Attempt it a few items to rule out cases when VM is under changes.
        """,
        priority=1,
        requirement=simple_requirement(supported_features=[AzureExtension]),
    )
    def verify_vmsnapshot_extension(
        self, log: Logger, node: Node, environment: Environment
    ) -> None:
        unique_name = str(uuid.uuid4())
        node_context = get_node_context(node)
        resource_group_name = node_context.resource_group_name
        vm_name = node_context.vm_name
        node_capability = node.capability.get_extended_runbook(AzureNodeSchema, AZURE)
        location = node_capability.location
        restore_point_collection = "rpc_" + unique_name
        assert environment.platform
        platform: AzurePlatform = environment.platform  # type: ignore
        assert isinstance(platform, AzurePlatform)
        sub_id = platform.subscription_id
        # creating restore point collection
        client = get_compute_client(platform)
        response = client.restore_point_collections.create_or_update(
            resource_group_name=resource_group_name,
            restore_point_collection_name=restore_point_collection,
            parameters={
                "location": location,
                "properties": {
                    "source": {
                        "id": f"/subscriptions/{sub_id}/resourceGroups/"
                        f"{resource_group_name}/providers/Microsoft.Compute/"
                        f"virtualMachines/{vm_name}"
                    }
                },
            },
        )
        log.info("restore point collection created")
        rpc_status = response.provisioning_state
        assert_that(rpc_status, "RPC creation failed").is_equal_to("Succeeded")
        count = 0
        for count in range(10):
            try:
                # create a restore point for the VM
                restore_point = "rp_" + datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
                response = client.restore_points.begin_create(
                    resource_group_name=resource_group_name,
                    restore_point_collection_name=restore_point_collection,
                    restore_point_name=restore_point,
                    parameters={},
                )
                wait_operation(response, time_out=600)
                # check the status of rp and validate the result.
                self.get_restore_point(
                    log,
                    environment,
                    resource_group_name,
                    restore_point_collection,
                    restore_point,
                )
                break
            except Exception as e:
                # Changes were made to the Virtual Machine, while the operation
                # 'Create Restore Point' was in progress.
                # Code: Conflict message is sometimes seen while rp creation
                if "Changes were made to the Virtual Machine" in str(e):
                    # so we will be retrying it after some time
                    pass
                else:
                    raise e
            time.sleep(1)
            count = count + 1
        assert_that(count, "Restore point creation failed.").is_less_than(10)

    def get_restore_point(
        self,
        log: Logger,
        environment: Environment,
        resource_group_name: str,
        restore_point_collection: str,
        restore_point: str,
    ) -> None:
        assert environment.platform
        platform: AzurePlatform = environment.platform  # type: ignore
        assert isinstance(platform, AzurePlatform)
        client = get_compute_client(platform)
        attempts = 0
        max_attempts = 450
        while attempts < max_attempts:
            response = client.restore_points.get(
                resource_group_name=resource_group_name,
                restore_point_collection_name=restore_point_collection,
                restore_point_name=restore_point,
                expand=None,
            )
            if response.provisioning_state == "Succeeded":
                log.info(f"restore point {restore_point} created")
                consistency_mode = response.consistency_mode
                log.info(f"consistency mode is {consistency_mode}")
                if (
                    "FileSystemConsistent" in consistency_mode
                    or "ApplicationConsistent" in consistency_mode
                ):
                    return
                else:
                    raise ValueError(
                        "Restore point consistency mode is not "
                        "FileSystemConsistent or ApplicationConsistent"
                    )
            else:
                log.info(f"rp status is {response.provisioning_state}")
                attempts += 1
                time.sleep(2)
        raise ValueError(
            "Restore point provisioning status not Succeeded "
            "after multiple attempts."
        )
