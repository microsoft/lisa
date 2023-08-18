# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from typing import cast

from lisa import (
    LisaException,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    UnsupportedDistroException,
)
from lisa.features import SecureBootEnabled
from lisa.operating_system import AzureCoreRepo, Debian, Posix, Redhat, Suse, Ubuntu
from lisa.sut_orchestrator.azure.tools import VmGeneration
from lisa.testsuite import simple_requirement
from lisa.util import find_patterns_in_lines


@TestSuiteMetadata(
    area="tvm",
    category="functional",
    description="""
    This test suite is to validate secureboot in Linux VM.
    """,
)
class TvmTest(TestSuite):
    @TestCaseMetadata(
        description="""
        This case tests the image is compatible with Secure Boot.

        Steps:
            1. Enable repository azurecore from https://packages.microsoft.com/repos.
            2. Install package azure-security.
            3. Check image Secure Boot compatibility from output of sbinfo.
        """,
        priority=2,
        requirement=simple_requirement(
            supported_features=[SecureBootEnabled()],
        ),
    )
    def verify_secureboot_compatibility(self, node: Node) -> None:
        self._is_supported(node)
        posix_os: Posix = cast(Posix, node.os)
        posix_os.add_azure_core_repo()
        posix_os.install_packages("azure-security", signed=False)
        cmd_result = node.execute("/usr/local/bin/sbinfo", sudo=True, timeout=1000)
        secure_boot_pattern = re.compile(
            r"(.*\"SBEnforcementStage\": \"Secure Boot (is|is not) enforced\".*)$", re.M
        )
        matched = find_patterns_in_lines(cmd_result.stdout, [secure_boot_pattern])
        if not (matched and matched[0]):
            raise LisaException("This OS image is not compatible with Secure Boot.")

    @TestCaseMetadata(
        description="""
        This case tests the image is compatible with Measured Boot.

        Steps:
            1. Enable repository azurecore from https://packages.microsoft.com/repos.
            2. Install package azure-compatscanner.
            3. Check image Measured Boot compatibility from output of mbinfo.
        """,
        priority=2,
        requirement=simple_requirement(
            supported_features=[SecureBootEnabled()],
        ),
    )
    def verify_measuredboot_compatibility(self, node: Node) -> None:
        self._is_supported(node)
        posix_os: Posix = cast(Posix, node.os)
        if isinstance(posix_os, Ubuntu):
            # focal and jammy don't have azure-compatscanner package in azurecore repo
            # use bionic for temp solution
            posix_os.add_azure_core_repo(code_name="bionic")
        elif isinstance(posix_os, Debian):
            # azurecore-debian doesn't have azure-compatscanner package
            # use azurecore instead
            posix_os.add_azure_core_repo(repo_name=AzureCoreRepo.AzureCore)
        else:
            posix_os.add_azure_core_repo()
        posix_os.install_packages("azure-compatscanner", signed=False)
        node.execute(
            "/usr/bin/mbinfo",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "This OS image is not compatible with Measured Boot."
            ),
        )

    def _is_supported(self, node: Node) -> None:
        vm_generation = node.tools[VmGeneration].get_generation()
        if "1" == vm_generation:
            raise SkippedException("TVM cases only support generation 2 VM.")
        if (
            (isinstance(node.os, Debian) and node.os.information.version < "11.0.0")
            or (isinstance(node.os, Ubuntu) and node.os.information.version < "18.4.0")
            or (isinstance(node.os, Redhat) and node.os.information.version < "8.3.0")
            or (isinstance(node.os, Suse) and node.os.information.version < "15.2.0")
        ):
            raise SkippedException(
                UnsupportedDistroException(node.os, "TVM doesn't support this version.")
            )
