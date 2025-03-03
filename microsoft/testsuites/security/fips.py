# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
import re
from abc import ABC, abstractmethod
from typing import Any, Dict

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.features import Disk
from lisa.operating_system import CBLMariner, OperatingSystem
from lisa.sut_orchestrator.azure.common import METADATA_ENDPOINT
from lisa.tools import Blkid, Cat, Curl, Sed
from lisa.util import SkippedException, get_matched_str


def assert_package_exists(os: OperatingSystem, package: str) -> None:
    """
    Assert that a package/tool is installed on the node.
    """
    assert_that(os.package_exists(package)).described_as(
        f"Package {package} is not installed."
    ).is_true()


def assert_package_not_exists(os: OperatingSystem, package: str) -> None:
    """
    Assert that a package/tool is not installed on the node.
    """
    assert_that(os.package_exists(package)).described_as(
        f"Package {package} is installed."
    ).is_false()


class AzlFips(ABC):
    '''
    Base class for AZL FIPS tests. This class provides methods to check if
    FIPS is enabled or disabled, and to enable or disable FIPS.
    The derived classes (AzlV2Fips and AzlV3Fips) implement the specific
    behavior for AZL2 and AZL3.
    '''
    @staticmethod
    def create_instance(log: Logger, node: Node) -> "AzlFips":
        '''
        Factory method to create an instance of AzlFips based
        on the OS release.
        '''
        release_to_class = {
            "2.0": AzlV2Fips,
            "3.0": AzlV3Fips,
        }

        assert_that(node.os.information.release).described_as(
            "Test only works on currently supported Azure Linux releases."
        ).is_in(*release_to_class.keys())

        klass = release_to_class[node.os.information.release]
        log.debug(
            f"Creating '{klass.__name__}' instance for release "
            f"{node.os.information.release}.")
        return klass(log, node)

    def __init__(self, log: Logger, node: Node):
        self.log = log
        self.node = node

    @abstractmethod
    def assert_fips_enabled(self) -> None:
        '''
        When implemented by the derived class, this method should assert that
        FIPS is enabled on the system.
        '''

    @abstractmethod
    def assert_fips_disabled(self) -> None:
        '''
        When implemented by the derived class, this method should assert that
        FIPS is disabled on the system.
        '''

    @abstractmethod
    def enable_fips(self) -> None:
        '''
        When implemented by the derived class, this method should enable FIPS
        on the system.
        '''

    @abstractmethod
    def disable_fips(self) -> None:
        '''
        When implemented by the derived class, this method should disable FIPS
        on the system.
        '''
        pass

    def _assert_kernel_fips_mode(self, expected: str) -> None:
        '''
        Assert that the kernel FIPS mode is set to the expected value.
        '''
        fips_enabled = self.node.tools[Cat].read(
            "/proc/sys/crypto/fips_enabled",
            force_run=True)

        assert_that(
            fips_enabled
        ).described_as(
            "kernel fips mode"
        ).is_equal_to(expected)

    def _azl_get_boot_uuid(self) -> str:
        '''
        Get the UUID of the boot disk partition.
        '''
        boot_disk_part_uuid = ""

        # Get the boot and root devices.
        disk = self.node.features[Disk]
        root_disk_partition = disk.get_partition_with_mount_point("/")
        boot_disk_partition = disk.get_partition_with_mount_point("/boot")

        # If the boot and root devices are different, add the boot block id to
        # the kernel command line.
        if boot_disk_partition.name == root_disk_partition.name:
            self.log.info("Boot and root partitions are the same; returning empty string.")
        else:
            boot_disk_part_uuid = self.node.tools[Blkid].get_partition_info_by_name(boot_disk_partition.name).uuid
            self.log.info(
                "Boot and root partitions are different; "
                f"boot disk UUID is '{boot_disk_part_uuid}'.")

        return boot_disk_part_uuid


class AzlV2Fips(AzlFips):
    '''
    FIPS test class for AZL2. This class implements the methods to check if
    FIPS is enabled or disabled, and to enable or disable FIPS.
    '''
    # In AZL2, the command openssl md5 should fail with error messages like:
    #   Error setting digest
    #   131590634539840:error:060800C8:digital envelope routines:EVP_DigestInit_ex:disabled for FIPS:crypto/evp/digest.c:135: # noqa: E501
    _md5_expected_failure_pattern = re.compile(
        "Error setting digest\r\n.*EVP_DigestInit_ex:disabled for FIPS.*", re.M
    )

    def assert_fips_enabled(self) -> None:
        # We rely on the dracut-fips package for bootloader FIPS support.
        assert_package_exists(self.node.os, "dracut-fips")

        # Check if fips is enabled in the kernel
        self._assert_kernel_fips_mode("1")

        # In AZL2, non-FIPS certified algorithms like MD5 will fail
        # when FIPS is enabled.
        result = self.node.execute("echo 'test' | openssl md5", shell=True)
        result.assert_exit_code(1, "openssl md5 should fail on AZL2 in FIPS mode")
        assert_that(get_matched_str(
            result.stdout,
            self._md5_expected_failure_pattern)
        ).is_not_empty()

    def assert_fips_disabled(self) -> None:
        # dracut-fips provides FIPS support in the bootloader.
        assert_package_not_exists(self.node.os, "dracut-fips")

        # FIPS should be disabled in the kernel.
        self._assert_kernel_fips_mode("0")

        # In AZL2, non-FIPS certified algorithms like MD5 will fail when FIPS is enabled
        # so we make sure that it works when FIPS is disabled.
        result = self.node.execute("echo 'test' | openssl md5", shell=True)
        result.assert_exit_code(0, "openssl md5 should work on AZL2 when FIPS is disabled")

    def enable_fips(self) -> None:
        # dracut-fips provides FIPS support in the bootloader.
        self.node.os.install_packages("dracut-fips")

        # In AZL2, grubby is used to modify kernel parameters.
        self.node.os.install_packages("grubby")

        # In AZL2, we use grubby to modify the kernel command line.
        # We need to add `fips=1` and `boot=UUID=<boot_disk_part_uuid>`
        # to the kernel command line.
        boot_disk_part_uuid = self._azl_get_boot_uuid()
        result = self.node.execute(
            "grub2-editenv - list | grep 'kernelopts'",
            sudo=True,
            shell=True)
        if result.exit_code == 0:
            self.log.info("Found kernelopts in grub2-editenv; editing with grub2-editenv")
            self.node.execute(
                f'sudo grub2-editenv - set "{result.stdout} fips=1 boot=UUID={boot_disk_part_uuid}"',
                sudo=True)
        else:
            self.log.info("Did not find kernelopts in grub2-editenv; adding with grubby")
            self.node.execute(
                f'sudo grubby --update-kernel=ALL --args="fips=1 boot=UUID={boot_disk_part_uuid}"',
                sudo=True)

    def disable_fips(self) -> None:
        # dracut-fips provides FIPS support in the bootloader.
        self.node.os.uninstall_packages("dracut-fips")

        # In AZL2, grubby is used to modify kernel parameters.
        self.node.os.install_packages("grubby")

        # If FIPS is set in the kernel command line, we need to change it.
        self.node.tools[Sed].raw(
            r's/ fips=1//g',
            "/boot/grub2/grub.cfg",
            sudo=True
        )

        # Remove the boot UUID from the kernel command line.
        self.node.tools[Sed].raw(
            r's/ boot=UUID=[^ ]*//g',
            "/boot/grub2/grub.cfg",
            sudo=True
        )

class AzlV3Fips(AzlFips):
    '''
    FIPS test class for AZL3. This class implements the methods to check if
    FIPS is enabled or disabled, and to enable or disable FIPS.
    '''
    def assert_fips_enabled(self) -> None:
        # We rely on the dracut-fips package for bootloader FIPS support.
        assert_package_exists(self.node.os, "dracut-fips")

        # Check if fips is enabled in the kernel
        self._assert_kernel_fips_mode("1")

        # In AZL3, FIPS-compliant openssl is provided by the SymCrypt provider.
        assert_package_exists(self.node.os, "SymCrypt")
        assert_package_exists(self.node.os, "SymCrypt-OpenSSL")

    def assert_fips_disabled(self) -> None:
        # dracut-fips provides FIPS support in the bootloader.
        assert_package_not_exists(self.node.os, "dracut-fips")

        # FIPS should be disabled in the kernel.
        self._assert_kernel_fips_mode("0")

    def enable_fips(self) -> None:
        # dracut-fips provides FIPS support in the bootloader.
        # AZL3 requres the SymCrypt provider for FIPS-compliant openssl.
        self.node.os.install_packages("dracut-fips SymCrypt SymCrypt-OpenSSL")

        # Update the kernel command line to enable FIPS.
        # This sed expression looks for the GRUB_CMDLINE_LINUX line an
        # appends `fips=1` to the end of the line or changes `fips=0` to `fips=1`.
        self.node.tools[Sed].raw(
            r'/^GRUB_CMDLINE_LINUX=/ { /fips=/! s/"$/ fips=1"/; s/fips=0/fips=1/ }',
            "/etc/default/grub",
            sudo=True
        )

        # Add the boot UUID to the kernel command line.
        # This sed expressions looks for the end of the GRUB_CMDLINE_LINUX
        # line and appends `boot=UUID=<boot_disk_part_uuid>` to the end of the
        # line, but only if it doesn't already contain `boot=UUID=`.
        self.node.tools[Sed].raw(
            f'/^GRUB_CMDLINE_LINUX=/ {{ /boot=UUID/! s/"$/ boot=UUID={self._azl_get_boot_uuid()}"/ }}',
            "/etc/default/grub",
            sudo=True
        )

        # Update the grub configuration.
        self.node.execute("grub2-mkconfig -o /boot/grub2/grub.cfg", sudo=True)

    def disable_fips(self) -> None:
        # dracut-fips provides FIPS support in the bootloader.
        self.node.os.uninstall_packages("dracut-fips")

        # This sed expression looks for the GRUB_CMDLINE_LINUX line and
        # removes `fips=1` from it.
        self.node.tools[Sed].raw(
            r'/^GRUB_CMDLINE_LINUX=/ s/ fips=1//',
            "/etc/default/grub",
            sudo=True
        )

        # Update the grub configuration.
        self.node.execute("grub2-mkconfig -o /boot/grub2/grub.cfg", sudo=True)


def ensure_fips_expectations(
        log: Logger,
        node: Node,
        variables: Dict[str, Any],
        should_be_fips: bool):
    """
    Ensures that the expectations about the node's FIPS status are correct
    for the test.
    The argument `should_be_fips` indicates whether the test should be run on a
    FIPS vs. non-FIPS image.
    To determine whether the image is FIPS or not, the function first checks
    the `testing_fips_image` variable in the `variables` dictionary.
    If it can't determine the image type from the variable, it falls back to checking
    the image SKU from the azure metadata endpoint.
    If this does not match the expectation, a SkippedException is raised.

    Args:
        log (Logger): The logger instance for logging messages.
        node (Node): The node object representing the target machine.
        should_be_fips (bool): A flag indicating whether the test should be
                               run on a FIPS vs. non-FIPS image.
        variables (Dict[str, Any]): A dictionary of variables containing the
                                   'testing_fips_image' key.
    Raises:
        SkippedException: If the FIPS image expectation does not match the actual image SKU.
    """
    log.debug(f"ensure_fips_expectations: should_be_fips is '{should_be_fips}'")
    log.debug(f"ensure_fips_expectations: variables is '{variables}'")

    # First, try to deduce the FIPS image type from the variables dictionary.
    fips_image_map = {"yes": True, "no": False}
    testing_fips_image = variables.get("testing_fips_image", None)
    is_fips_image = fips_image_map.get(testing_fips_image, None)

    # If the variable is not set or not in the expected format, fall back to
    # checking the image SKU from the azure metadata endpoint.
    if is_fips_image is None:
        log.debug(
            f"ensure_fips_expectations: testing_fips_image not in '{list(fips_image_map.keys())}'; "
            "falling back to marketplace image sku")
        response = node.tools[Curl].fetch(
            arg="--max-time 2 --header Metadata:true --silent",
            execute_arg="",
            expected_exit_code=None,
            url=METADATA_ENDPOINT
        )

        # If we successfully fetched the metadata, check the image SKU.
        if response.exit_code == 0:
            response = json.loads(response.stdout)
            is_fips_image = "fips" in response["compute"]["sku"]

    # If the image type does not match the expectation, raise a SkippedException.
    # This includes the case where we could not determine the image type.
    if is_fips_image != should_be_fips:
        raise SkippedException(
            f"FIPS image expectation does not match actual image SKU. "
            f"Expected: {should_be_fips}, Actual: {is_fips_image}"
        )


@TestSuiteMetadata(
    area="security",
    category="functional",
    description="""
    Tests the functionality of FIPS enable
    """,
)
class Fips(TestSuite):
    @TestCaseMetadata(
        description="""
            Ensures that an AZL machine is fips enabled.
        """,
        priority=1,
        requirement=simple_requirement(
            supported_os=[CBLMariner],
        ),
    )
    def verify_fips_is_enabled_azl(
        self,
        log: Logger,
        node: Node,
        variables: Dict[str, Any]
    ) -> None:
        # Skip the test if the image is not FIPS enabled.
        ensure_fips_expectations(log, node, variables, should_be_fips=True)

        # Ensure the system is FIPS enabled.
        azl_fips = AzlFips.create_instance(log, node)
        azl_fips.assert_fips_enabled()

        log.info("FIPS is enabled and working correctly.")

    @TestCaseMetadata(
        description="""
            Ensures that an AZL machine is not FIPS enabled.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_os=[CBLMariner],
        ),
    )
    def verify_fips_is_disabled_azl(
        self,
        log: Logger,
        node: Node,
        variables: Dict[str, Any]
    ) -> None:
        # Skip the test if the image is FIPS enabled.
        ensure_fips_expectations(log, node, variables, should_be_fips=False)

        # Ensure the system is not FIPS enabled.
        azl_fips = AzlFips.create_instance(log, node)
        azl_fips.assert_fips_disabled()

        log.info("FIPS is disabled and properly.")

    @TestCaseMetadata(
        description="""
            This test case will
            1. Enable FIPS on the AZL machine
            2. Restart the machine
            3. Verify that FIPS was enabled properly
        """,
        priority=2,
        requirement=simple_requirement(
            supported_os=[CBLMariner],
        ),
    )
    def verify_fips_enable_azl(
        self,
        log: Logger,
        node: Node,
        variables: Dict[str, Any]
    ) -> None:
        # Skip the test if the image is already FIPS enabled.
        ensure_fips_expectations(log, node, variables, should_be_fips=False)

        # Enable FIPS on the system and make sure it is worked.
        azl_fips = AzlFips.create_instance(log, node)
        azl_fips.enable_fips()
        node.reboot()
        azl_fips.assert_fips_enabled()

        log.info("Successfully enabled FIPS.")

    @TestCaseMetadata(
        description="""
            This test case will
            1. Disable FIPS on the AZL machine
            2. Restart the machine
            3. Verify that FIPS is disabled
        """,
        priority=2,
        requirement=simple_requirement(
            supported_os=[CBLMariner],
        ),
    )
    def verify_fips_disable_azl(
        self,
        log: Logger,
        node: Node,
        variables: Dict[str, Any]
    ) -> None:
        # Skip the test if the image is already not FIPS enabled.
        ensure_fips_expectations(log, node, variables, should_be_fips=True)

        # Disable FIPS on the system and make sure it is worked.
        azl_fips = AzlFips.create_instance(log, node)
        azl_fips.disable_fips()
        node.reboot()
        azl_fips.assert_fips_disabled()

        log.debug("Successfully disabled FIPS.")

    @TestCaseMetadata(
        description="""
        This test case will
        1. Check whether FIPS can be enabled on the VM
        2. Enable FIPS
        3. Restart the VM for the changes to take effect
        4. Verify that FIPS was enabled properly
        """,
        priority=3,
        requirement=simple_requirement(
            unsupported_os=[CBLMariner],
        )
    )
    def verify_fips_enable(self, log: Logger, node: Node) -> None:
        result = node.execute("command -v fips-mode-setup", shell=True)
        if result.exit_code != 0:
            raise SkippedException(
                "Command not found: fips-mode-setup. "
                f"Please ensure {node.os.name} supports fips mode."
            )

        node.execute("fips-mode-setup --enable", sudo=True)

        log.info("FIPS mode set to enable. Attempting reboot.")
        node.reboot()

        result = node.execute("fips-mode-setup --check")

        assert_that(result.stdout).described_as(
            "FIPS was not properly enabled."
        ).contains("is enabled")
