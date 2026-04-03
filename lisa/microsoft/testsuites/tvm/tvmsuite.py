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
from lisa.operating_system import (
    AzureCoreRepo,
    CpuArchitecture,
    Debian,
    Posix,
    Redhat,
    Suse,
    Ubuntu,
)
from lisa.sut_orchestrator.azure.tools import VmGeneration
from lisa.testsuite import simple_requirement
from lisa.tools import Lscpu, Mokutil, Tpm2Pcrread
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
            1. Enable repository azurecore and install
               azure-security, then run sbinfo to check Secure
               Boot compatibility (skipped on ARM64).
            2. Install mokutil and verify Secure Boot is enabled
               via mokutil --sb-state.
        """,
        priority=2,
        requirement=simple_requirement(
            supported_features=[SecureBootEnabled()],
        ),
    )
    def verify_secureboot_compatibility(self, node: Node) -> None:
        self._is_supported(node)

        if node.tools[Lscpu].get_architecture() == CpuArchitecture.ARM64:
            node.log.info(
                "Temporarily disabling sbinfo check on ARM64 images"
                " due to tool sbinfo not supporting ARM64."
            )
        else:
            posix_os: Posix = cast(Posix, node.os)
            posix_os.add_azure_core_repo()
            posix_os.install_packages("azure-security", signed=False)
            cmd_result = node.execute("/usr/local/bin/sbinfo", sudo=True, timeout=1000)
            secure_boot_pattern = re.compile(
                r"(.*\"SBEnforcementStage\": "
                r"\"Secure Boot (is|is not) enforced\".*)$",
                re.M,
            )
            matched = find_patterns_in_lines(cmd_result.stdout, [secure_boot_pattern])
            if not (matched and matched[0]):
                raise LisaException("This OS image is not compatible with Secure Boot.")
        try:
            mokutil_tool = node.tools[Mokutil]
        except UnsupportedDistroException as e:
            raise SkippedException(e) from e
        if not mokutil_tool.is_secure_boot_enabled():
            raise LisaException("Secure Boot is not enabled on this VM.")

    @TestCaseMetadata(
        description="""
        This case tests the image is compatible with Measured Boot.

        Steps:
            1. Enable repository azurecore and install
               azure-compatscanner, then run mbinfo to check
               Measured Boot compatibility (skipped on ARM64).
            2. Install tpm2-tools and read TPM PCR0-7 values
               using tpm2_pcrread.
            3. Verify that PCR0-7 are not all zeros, which
               indicates the firmware and bootloader recorded
               measurements during boot (Measured Boot active).
        """,
        priority=2,
        requirement=simple_requirement(
            supported_features=[SecureBootEnabled()],
        ),
    )
    def verify_measuredboot_compatibility(self, node: Node) -> None:
        self._is_supported(node)

        if node.tools[Lscpu].get_architecture() == CpuArchitecture.ARM64:
            node.log.info(
                "Temporarily disabling mbinfo check on ARM64 images"
                " due to tool mbinfo not supporting ARM64."
            )
        else:
            posix_os: Posix = cast(Posix, node.os)
            if isinstance(posix_os, Ubuntu):
                # focal and jammy don't have azure-compatscanner
                # package in azurecore repo, use bionic instead
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

        # Verify Measured Boot via TPM PCR (Platform Configuration
        # Register) values. When Measured Boot is active, the firmware
        # and bootloader record measurements into PCR0-7 during the
        # boot process. If all PCR0-7 values are zeros, it means no
        # measurements were recorded, indicating Measured Boot is not
        # functioning.
        try:
            tpm2_pcrread = node.tools[Tpm2Pcrread]
        except UnsupportedDistroException as e:
            raise SkippedException(e) from e

        pcr_indices = list(range(8))
        node.log.info("Reading TPM PCR0-7 values to verify Measured Boot is active.")
        pcr_values = tpm2_pcrread.read(pcrs=pcr_indices)

        # Ensure all requested PCR indices were successfully read.
        missing_pcrs = [i for i in pcr_indices if i not in pcr_values]
        if missing_pcrs:
            raise LisaException(
                f"Failed to read TPM PCR values for indices {missing_pcrs}: "
                "cannot reliably determine Measured Boot status."
            )
        # A sha256 all-zero hash indicates the PCR has not been
        # extended, meaning no boot measurement was recorded.
        zero_hash = "0x" + "0" * 64
        all_zero = all(pcr_values[i] == zero_hash for i in pcr_indices)
        if all_zero:
            raise LisaException("Measured Boot is not active: PCR0-7 are all zeros.")

        node.log.info(
            "Measured Boot verification passed:"
            " PCR0-7 contain non-zero measurements."
        )
        for i in pcr_indices:
            node.log.debug(f"PCR{i}: {pcr_values.get(i, 'N/A')}")

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
