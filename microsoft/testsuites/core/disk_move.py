# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    search_space,
    simple_requirement,
)
from lisa.features import Disk
from lisa.features.disks import DiskStandardHDDLRS
from lisa.node import Node
from lisa.schema import DiskType
from lisa.tools import Cat, Echo, Mount

from .common import get_resource_disk_mount_point


@TestSuiteMetadata(
    area="disk storage",
    category="functional",
    description="""
    Test suite exercise for ramp-up
    """,
)
class DiskStorage(TestSuite):
    @TestCaseMetadata(
        description=""""
        This is a demo test case for ramp up. The goal is to move a file from
        the home folder to the data disk and assert the contents are in the disk.
        The tteps are:
        1. Setup testcase with data disk requirement.
        2. Write “Hello World!” string to a file.
        3. Move the file from home folder to data disk.
        4. Assert the file content in data disk.
        5. Assert the file in original place does not exist.
        """,
        priority=4,
        requirement=simple_requirement(
            disk=schema.DiskOptionSettings(
                disk_type=schema.DiskType.StandardHDDLRS,
                data_disk_count=search_space.IntRange(min=1),
            )
        ),
    )
    def check_disk_move_operation_frmunozp(self, node: Node, log: Logger) -> None:
        test_file = "~/test.txt"
        test_str = "hello world!"

        echo = node.tools[Echo]
        echo.write_to_file(test_str, node.get_pure_path(test_file))

        cat = node.tools[Cat]
        output = cat.read(test_file)
        assert_that(output).matches(test_str)

        # disk = node.features[Disk]
        data_disks = node.features[Disk].get_raw_data_disks()
        mount_point = "demo"

        # mount = node.tools[Mount]
        node.tools[Mount].mount(data_disks[0], mount_point, format=True)

        if node.shell.exists(node.get_pure_path(mount_point)):
            node.execute(
                f"mv {test_file} {mount_point}",
                shell=True,
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    f"failed to move {test_file} to disk"
                ),
            )

        output = cat.read(f"{mount_point}/test.txt")
        assert_that(output).is_equal_to(test_str)

        assert_that(test_file).does_not_exist()
