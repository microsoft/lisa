# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from typing import TYPE_CHECKING, Any

from assertpy import assert_that

from lisa.executable import Tool
from lisa.operating_system import CBLMariner
from lisa.tools import Blkid, Cat
from lisa.util import UnsupportedDistroException, get_matched_str, to_bool

from .grub_config import GrubConfig

if TYPE_CHECKING:
    from lisa.node import Node


class Fips(Tool):
    """
    Base class for AZL FIPS tests. This class provides methods to check if
    FIPS is enabled or disabled, and to enable or disable FIPS.
    The derived classes (AzlV2Fips and AzlV3Fips) implement the specific
    behavior for AZL2 and AZL3.
    """

    @classmethod
    def create(cls, node: "Node", *args: Any, **kwargs: Any) -> Tool:
        """
        Factory method to create an instance of the Fips tool.
        """
        if isinstance(node.os, CBLMariner):
            if node.os.information.release == "2.0":
                return AzlV2Fips(node, args, kwargs)
            if node.os.information.release == "3.0":
                return AzlV3Fips(node, args, kwargs)

        raise UnsupportedDistroException(
            os=node.os, message="FIPS tool only supported on CBLMariner 2.0 and 3.0."
        )

    @property
    def command(self) -> str:
        """
        Returns the command to run the FIPS tool.
        In this case, there is no direct command to run so we return an empty string.
        """
        return ""

    @property
    def can_install(self) -> bool:
        """
        Check if the tool can be installed.
        In this case, we return False as the FIPS tool is not installable.
        """
        return False

    def install(self) -> bool:
        """
        Installation method for the FIPS tool.
        This method does nothing as the tool is not installable.
        """
        return False

    def assert_fips_mode(self, expect_fips_mode: bool) -> None:
        """
        When implemented by the derived class, this method should assert that
        FIPS is enabled or disabled on the system.
        """
        # We rely on the dracut-fips package for bootloader FIPS support.
        self.node.os.package_exists("dracut-fips", assert_existance=expect_fips_mode)

        # Kernel needs to be in the correct FIPS mode.
        assert_that(self.is_kernel_fips_mode()).described_as(
            "kernel fips mode"
        ).is_equal_to(expect_fips_mode)

    def set_fips_mode(self, fips_mode: bool) -> None:
        """
        Set the FIPS mode on the system.
        This method should be called to enable or disable FIPS mode.
        """
        if fips_mode:
            self._enable_fips()
        else:
            self._disable_fips()

    def is_kernel_fips_mode(self) -> bool:
        """
        Get the current FIPS mode.
        This method checks if the dracut-fips package is installed and if the
        kernel FIPS mode is enabled.
        """
        fips_enabled = self.node.tools[Cat].read(
            "/proc/sys/crypto/fips_enabled", force_run=True
        )

        return to_bool(fips_enabled)

    def _enable_fips(self) -> None:
        # dracut-fips provides FIPS support in the bootloader.
        self.node.os.install_packages("dracut-fips")

        # Set the fips flag to the kernel command line.
        self.node.tools[GrubConfig].set_kernel_cmdline_arg("fips", "1")

        # If the boot and root devices are different, add the boot uuid to the
        # kernel command line.
        boot_disk_part_uuid = self._get_boot_uuid()
        boot_arg_value = f"UUID={boot_disk_part_uuid}" if boot_disk_part_uuid else ""
        self.node.tools[GrubConfig].set_kernel_cmdline_arg("boot", boot_arg_value)

    def _disable_fips(self) -> None:
        # dracut-fips provides FIPS support in the bootloader.
        self.node.os.uninstall_packages("dracut-fips")

        # Set the fips flag to the kernel command line.
        self.node.tools[GrubConfig].set_kernel_cmdline_arg("fips", "0")

        # Set the boot flag to the kernel command line.
        self.node.tools[GrubConfig].set_kernel_cmdline_arg("boot", "")

    def _get_boot_uuid(self) -> str:
        """
        Get the UUID of the boot disk partition.
        This method checks if the boot and root devices are different.
        If the boot and root devices are different, return (True, boot uuid).
        If they are the same, return (False, empty string).
        """
        boot_and_root_same = False
        boot_disk_part_uuid = ""

        # Get the boot and root devices.
        from lisa.features import Disk

        disk = self.node.features[Disk]
        root_disk_partition = disk.get_partition_with_mount_point("/")
        boot_disk_partition = disk.get_partition_with_mount_point("/boot")

        # If the boot and root devices are different, get the boot uuid it.
        if boot_disk_partition.name == root_disk_partition.name:
            boot_and_root_same = True
            boot_disk_part_uuid = ""
        else:
            boot_and_root_same = False
            boot_disk_part_uuid = (
                self.node.tools[Blkid]
                .get_partition_info_by_name(boot_disk_partition.name, force_run=True)
                .uuid
            )

        self._log.debug(
            f"_get_boot_uuid: boot_and_root_same={boot_and_root_same}, "
            f"boot_disk_part_uuid='{boot_disk_part_uuid}'"
        )
        return boot_disk_part_uuid


class AzlV2Fips(Fips):
    """
    FIPS test class for AZL2. This class implements the methods to check if
    FIPS is enabled or disabled, and to enable or disable FIPS.
    """

    # In AZL2, the command openssl md5 should fail with error messages like:
    #   Error setting digest
    #   131590634539840:error:060800C8:digital envelope routines:EVP_DigestInit_ex:disabled for FIPS:crypto/evp/digest.c:135: # noqa: E501
    _md5_expected_failure_pattern = re.compile(
        "Error setting digest\r\n.*EVP_DigestInit_ex:disabled for FIPS.*", re.M
    )

    def assert_fips_mode(self, expect_fips_mode: bool) -> None:
        super().assert_fips_mode(expect_fips_mode)

        # In AZL2, non-FIPS certified algorithms like MD5 will fail
        # when FIPS is enabled.
        result = self.node.execute(
            "echo 'test' | openssl md5",
            shell=True,
            expected_exit_code=int(expect_fips_mode),
        )
        if expect_fips_mode:
            assert_that(
                get_matched_str(result.stdout, self._md5_expected_failure_pattern)
            ).is_not_empty()


class AzlV3Fips(Fips):
    """
    FIPS test class for AZL3. This class implements the methods to check if
    FIPS is enabled or disabled, and to enable or disable FIPS.
    """

    _SYMCRYPT_PACKAGES = [
        "SymCrypt",
        "SymCrypt-OpenSSL",
    ]

    def assert_fips_mode(self, expect_fips_mode: bool) -> None:
        super().assert_fips_mode(expect_fips_mode)

        # In AZL3, FIPS-compliant openssl is provided by the SymCrypt provider.
        # They're also installed by default, so we don't want to check for them
        # when FIPS is disabled.
        if expect_fips_mode:
            for package in self._SYMCRYPT_PACKAGES:
                self.node.os.package_exists(package, assert_existance=True)

    def _enable_fips(self) -> None:
        super()._enable_fips()

        # AZL3 requres the SymCrypt provider for FIPS-compliant openssl.
        self.node.os.install_packages(self._SYMCRYPT_PACKAGES)
