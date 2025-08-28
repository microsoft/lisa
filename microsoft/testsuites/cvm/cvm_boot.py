# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import itertools
from pathlib import Path
from typing import Any, Dict, cast

from assertpy.assertpy import assert_that

from lisa import (
    Logger,
    Node,
    RemoteNode,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.environment import EnvironmentStatus
from lisa.features.security_profile import (
    CvmDiskEncryptionEnabled,
    CvmEnabled,
    SecurityProfile,
    SecurityProfileSettings,
)
from lisa.operating_system import CBLMariner
from lisa.sut_orchestrator import AZURE
from lisa.testsuite import simple_requirement
from lisa.tools import BootCtl, Lsblk, Tpm2
from lisa.tools.lsblk import PartitionInfo
from lisa.util import SkippedException, UnsupportedDistroException


@TestSuiteMetadata(
    area="cvm",
    category="functional",
    description="""This test suite covers some common scenarios related to
    CVM boot on Azure.
    """,
)
class CVMBootTestSuite(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        if not isinstance(node.os, CBLMariner):
            raise SkippedException(
                UnsupportedDistroException(
                    node.os, "CVM boot test supports only Azure Linux."
                )
            )

    @TestCaseMetadata(
        description="""This test verifies that TPM enrollment is done correctly on
        a CVM with encrypted root partition
        """,
        priority=2,
        requirement=simple_requirement(
            supported_features=[CvmDiskEncryptionEnabled()],
            supported_platform_type=[AZURE],
        ),
    )
    def verify_encrypted_root_partition(self, node: RemoteNode) -> None:
        security_profile_settings = cast(
            SecurityProfileSettings, node.features[SecurityProfile].get_settings()
        )
        if not security_profile_settings.encrypt_disk:
            raise SkippedException("This test requires disk encryption to be enabled")

        disks = node.tools[Lsblk].get_disks(force_run=True)
        root_device = node.tools[BootCtl].get_root_device()
        partitions = itertools.chain.from_iterable(disk.partitions for disk in disks)
        root_partition = next(
            (p for p in partitions if p.device_name == root_device), None
        )

        assert_that(root_partition, "Cannot locate root partition").is_not_none()
        assert isinstance(root_partition, PartitionInfo)
        assert_that(root_partition.fstype).is_equal_to("crypto_LUKS")

    @TestCaseMetadata(
        description="""This test case verifies that a CVM can still boot if any boot
        component is upgraded.

        Steps:
        1. On first boot, check current PCR values for PCR4 and PCR7
        2. Get current boot components versions (e.g. shim, grub, systemd-boot, uki)
        3. Run a package upgrade to update boot components
        4. Get new boot components versions to see if anything has changed
        5. Reboot the CVM, make sure the CVM can boot up again
        6. PCR4 should change if any of the boot components is upgraded
        7. PCR7 may change (for example, if a signing certificate is changed)
        """,
        priority=1,
        requirement=simple_requirement(
            environment_status=EnvironmentStatus.Connected,
            supported_features=[CvmEnabled()],
            supported_platform_type=[AZURE],
        ),
        use_new_environment=True,
    )
    def verify_boot_success_after_component_upgrade(
        self,
        log: Logger,
        node: RemoteNode,
        log_path: Path,
        variables: Dict[str, Any],
    ) -> None:
        os: CBLMariner = cast(CBLMariner, node.os)
        # First boot - no package upgrade has been performed
        # Check PCR values (PCR4, PCR7)
        pcrs_before_reboot = node.tools[Tpm2].pcrread(pcrs=[4, 7])

        # - Get current boot components versions (shim, systemd-boot, kernel-uki)
        boot_components = ["shim", "systemd-boot", "kernel-uki"]
        boot_components_versions: Dict[str, str] = dict()
        for pkg in boot_components:
            pkg_version = os.get_package_information(pkg, use_cached=False)
            boot_components_versions[pkg] = pkg_version.version_str

        repo_url = variables.get("rpm_repository")
        if repo_url:
            os.add_repository(repo_url)

        # Upgrade boot components
        os.update_packages(boot_components)

        # Get new boot components versions
        boot_components_new_versions: Dict[str, str] = dict()
        for pkg in boot_components:
            pkg_version = os.get_package_information(pkg, use_cached=False)
            boot_components_new_versions[pkg] = pkg_version.version_str

        # Reboot
        node.reboot()

        # VM is up again
        pcrs_after_reboot = node.tools[Tpm2].pcrread(pcrs=[4, 7])
        boot_component_changed = (
            boot_components_versions != boot_components_new_versions
        )

        # - PCR4 should change if any of the boot components is upgraded
        # - PCR7 may change if a signing cert is changed
        if boot_component_changed:
            assert_that(
                pcrs_after_reboot[4],
                "PCR4 value is still the same even though a boot component changed",
            ).is_not_equal_to(pcrs_before_reboot[4])
            if pcrs_after_reboot[7] != pcrs_before_reboot[7]:
                log.info(
                    "PCR7 changed after a boot component changed. This may happen if a "
                    "signing certificate was updated"
                )
        else:
            assert_that(
                pcrs_after_reboot,
                "PCR values changed even though no boot component was updated",
            ).is_equal_to(pcrs_before_reboot)
