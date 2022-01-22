# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re

from assertpy import assert_that

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.operating_system import CentOs, Redhat
from lisa.sut_orchestrator.azure.tools import LisDriver
from lisa.testsuite import simple_requirement
from lisa.tools import Cat, Modinfo, Wget
from lisa.util import SkippedException, get_matched_str


@TestSuiteMetadata(
    area="lis",
    category="functional",
    description="""
        This test suite contains tests that are dependent on an LIS driver
    """,
    requirement=simple_requirement(
        supported_os=[
            CentOs,
            Redhat,
        ]
    ),
)
class Lis(TestSuite):
    # '#define HV_DRV_VERSION	"4.3.4"' -> 4.3.4
    version_pattern = re.compile(r'"(.+)"')
    # '#define _HV_DRV_VERSION 0x1B2' -> 0x1B2
    hex_version_pattern = re.compile(r"(0x\w+)")

    @TestCaseMetadata(
        description="""
            Downloads header files based on the LIS version and compares the installed
             LIS version to the expected one which is found in the header files.

            Steps:
            1. Check for RPM
            2. Capture installed LIS version on the node
            3. For each rhel version (5,6,7), it downloads the header file and compares
             the LIS version in the header file with the LIS version installed
        """,
        priority=1,
    )
    def verify_lis_driver_version(self, node: Node, log: Logger) -> None:
        cat = node.tools[Cat]
        modinfo_tool = node.tools[Modinfo]
        wget_tool = node.tools[Wget]
        node.tools[LisDriver]

        # Checking for RPM Package Manager
        rpm_qa = node.execute("rpm -qa").stdout
        if ("kmod-microsoft-hyper-v" not in rpm_qa) or (
            "microsoft-hyper-v" not in rpm_qa
        ):
            raise SkippedException("No LIS RPM's are detected. Skipping test.")

        # Capturing LIS version from the node
        version = modinfo_tool.get_version(mod_name='"hv_vmbus"').strip()

        for i in range(5, 8):
            node.execute("rm -rf hv_compat.h")
            wget_tool.get(
                "https://raw.githubusercontent.com/LIS/lis-next/"
                f"{version}/hv-rhel{i}.x/hv/include/linux/hv_compat.h",
                filename="hv_compat.h",
                file_path="./",
            )

            # Capturing the LIS version from the source code
            source_version = cat.read_with_filter(
                "hv_compat.h", "define HV_DRV_VERSION"
            )
            source_version = get_matched_str(source_version, self.version_pattern)

            # Capturing the LIS version in hex from the source code
            source_version_hex = source_version = cat.read_with_filter(
                "hv_compat.h", "define _HV_DRV_VERSION"
            )
            source_version_hex = get_matched_str(
                source_version_hex, self.hex_version_pattern
            )

            self._check_lis_version(node, version, source_version, log)
            self._check_lis_version_hex(node, version, source_version_hex, log)

    # Returns true if version and source_version are the same
    def _check_lis_version(
        self, node: Node, version: str, source_version: str, log: Logger
    ) -> None:
        log.debug("Detected modinfo version is {version}")
        log.debug("Version found in source code is {source_version}")

        assert_that(version).described_as(
            "Detected version and Source version are different. Expected LIS version:"
            f" {source_version}, Actual LIS version: {version}"
        )

    # Returns true if version and source_version_hex are the same
    def _check_lis_version_hex(
        self, node: Node, version: str, source_version_hex: str, log: Logger
    ) -> None:
        log.debug("Detected modinfo version is {version}")
        log.debug("Version found in source code is {source_version}")

        # The below two lines are converting the inputted LIS version to hex
        version_hex = version.replace(".", "")
        version_hex = str(hex(int(version_hex))).lower()

        # Converting to lower for consistency
        source_version_hex = source_version_hex.lower()

        assert_that(version).described_as(
            "Detected version and Source version are different for hex value. Expected"
            f" LIS version: {source_version_hex}, Actual LIS version: {version_hex}"
        )
