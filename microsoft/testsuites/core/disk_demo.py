from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    search_space,
    simple_requirement,
)
from lisa.features import Disk
from lisa.schema import DiskOptionSettings, DiskType
from lisa.tools import Cat, Echo, Mount


@TestSuiteMetadata(
    area="first test suite",
    category="functional",
    description="""
    this is an example test suite.
    it shows a basic sample of writing a test case.
    it also is a good chance to learn about the testsuites.
    """,
)
class FirstTestSuite(TestSuite):
    SAMPLE_TEXT = "Hello World!"
    FILE_PATH = "/sample.txt"
    DISK_PATH = "/disk"

    @TestCaseMetadata(
        description="""
        Demo writing a test and using the disk.
        """,
        priority=4,
        requirement=simple_requirement(
            disk=DiskOptionSettings(
                disk_type=DiskType.StandardHDDLRS,
                data_disk_count=search_space.IntRange(min=1),
            )
        ),
    )
    def check_disk_move_operation_rydailey(
        self,
        node: Node,
        log: Logger,
    ) -> None:
        node.tools[Echo].write_to_file(
            self.SAMPLE_TEXT, node.get_pure_path(self.FILE_PATH), sudo=True
        )
        disk = node.features[Disk]
        disks = disk.get_raw_data_disks()
        mount = node.tools[Mount]
        mount.mount(disks[0], self.DISK_PATH, format=True)
        node.execute(
            f"mv {self.FILE_PATH} {self.DISK_PATH}",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "Failed to move text file to data disk" " failed."
            ),
        )
        # assert the text is the same on disk and in the source variable
        cat = node.tools[Cat]
        results = cat.read(f"{self.DISK_PATH}{self.FILE_PATH}")
        assert_that(
            results, "Text in the file and the variable should match"
        ).is_equal_to(self.SAMPLE_TEXT)
        # assert that the file only exists on the disk
        results = cat.read(self.FILE_PATH)
        assert_that(results, "The file should no longer exist").is_empty
