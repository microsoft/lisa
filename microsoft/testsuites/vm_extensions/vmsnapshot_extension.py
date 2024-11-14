# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import base64
import os
import time
import uuid
from datetime import datetime
from pathlib import PurePosixPath

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
from lisa.operating_system import BSD, Debian, Windows
from lisa.sut_orchestrator import AZURE
from lisa.sut_orchestrator.azure.common import (
    AzureNodeSchema,
    get_compute_client,
    get_node_context,
    wait_operation,
)
from lisa.sut_orchestrator.azure.features import AzureExtension
from lisa.sut_orchestrator.azure.platform_ import AzurePlatform
from lisa.testsuite import TestResult
from lisa.tools.chmod import Chmod
from lisa.tools.chown import Chown
from lisa.tools.find import Find
from lisa.tools.python import Pip, Python
from lisa.tools.whoami import Whoami


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
        self._verify_vmsnapshot_extension(log, node, environment)

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

    @TestCaseMetadata(
        description="""
        Runs a script on the VM
        The script takes the responsibility of distinguishing the various ditros into
        supported or unsupported for selective billing feature.
        The test would be passed in both the cases, just that the information helps in
        clearly classifying the distro, when the test runs on various distros.
        """,
        priority=2,
        requirement=simple_requirement(
            supported_features=[AzureExtension],
            unsupported_os=[BSD, Windows],
        ),
    )
    def verify_exclude_disk_support_restore_point(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        result: TestResult,
    ) -> None:
        # Any extension will do, use CustomScript for convenience.
        # This test would only run when extension is installed already else will
        # triggere a retsore point that helps in installing the extension on the VM
        # Copy the local files into the VM.
        # Move the files to the extension directory
        # Give the execution permissions to the files
        # Run the files
        # Validate the results
        extension_dir = self._find_extension_dir(node)
        if extension_dir == "":
            self._verify_vmsnapshot_extension(log, node, environment)
            trial = 0
            while trial < 3:
                time.sleep(2)
                extension_dir = self._find_extension_dir(node)
                if extension_dir == "":
                    trial = trial + 1
                else:
                    break

        # installing all the required packages
        # install python3
        python = node.tools[Python]
        if isinstance(node.os, Debian):
            package_name = "python3-mock"
            node.os.install_packages(package_name)
        else:
            # install pip
            pip = node.tools[Pip]
            pip.install_packages("mock")

        # copy the file into the vm
        self._copy_to_node(node, "handle.txt")
        assert extension_dir, "Unable to find the extension directory."

        # moving the handle_test.py file to extension directory
        script = (
            "#!/bin/sh\n"
            f"mv {node.working_path}/handle.txt {extension_dir}/main/handle_test.py"
        )
        script_base64 = base64.b64encode(bytes(script, "utf-8")).decode("utf-8")
        settings = {"script": script_base64}
        extension = node.features[AzureExtension]
        extension.create_or_update(
            name="CustomScript",
            publisher="Microsoft.Azure.Extensions",
            type_="CustomScript",
            type_handler_version="2.1",
            auto_upgrade_minor_version=True,
            settings=settings,
        )
        log.info(f"extension_directory: {extension_dir}")
        # give the execution permissions to the file
        file_path = f"{extension_dir}/main/handle_test.py"
        permissions = "777"
        node.tools[Chmod].chmod(path=file_path, permission=permissions, sudo=True)
        username = node.tools[Whoami].get_username()
        node.tools[Chown].change_owner(
            PurePosixPath(extension_dir), user=username, recurse=True
        )
        # execute the file
        script_result = python.run(
            f"{extension_dir}/main/handle_test.py", sudo=True, shell=True
        )
        log.info(f"The script returned {script_result.stdout}")
        if "True" in script_result.stdout:
            # isSizeComputationFailed flag is set to True.
            result.information["selective_billing_support"] = False
            log.info(
                "unsupported distro as it do not have few of the modules "
                "like lsblk, lsscsi not pre-installed"
            )
        else:
            result.information["selective_billing_support"] = True
            log.info("supported distro")

    def _verify_vmsnapshot_extension(
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
        for _ in range(10):
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
            count += 1
        assert_that(count, "Restore point creation failed.").is_less_than(10)

    def _find_extension_dir(self, node: Node) -> str:
        startpath = node.get_pure_path("/var/lib/waagent/")
        namepattern = "Microsoft.Azure.RecoveryServices.VMSnapshotLinux-1.0.*"
        sudo = True
        find_tool = node.tools[Find]
        file_list = find_tool.find_files(
            start_path=startpath, name_pattern=namepattern, sudo=sudo
        )
        extension_directory = ""
        if len(file_list) == 1:
            extension_directory = file_list[0]
        return extension_directory

    def _copy_to_node(self, node: Node, filename: str) -> None:
        f_name = node.working_path / filename
        temp_file = PurePosixPath(filename)
        file_path = node.get_pure_path(
            os.path.join((os.path.dirname(__file__)), "scripts", temp_file)
        )
        node.shell.copy(file_path, f_name)
