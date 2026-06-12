# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
from typing import Any, Dict, Union

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import CBLMariner, Debian, Ubuntu
from lisa.sut_orchestrator.azure.common import METADATA_ENDPOINT
from lisa.tools import Cat, Curl, Fips
from lisa.tools.grub_config import GrubConfig
from lisa.util import SkippedException, to_bool


@TestSuiteMetadata(
    area="security",
    category="functional",
    description="""
    Tests the functionality of FIPS enable
    """,
)
class FipsTests(TestSuite):
    @TestCaseMetadata(
        description="""
        Ensures that an AZL machine is in the correct FIPS mode.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_os=[CBLMariner],
        ),
    )
    def verify_azl_fips_status(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        # Get the expected FIPS mode based on the variables and the node's metadata.
        expected_fips_mode = self._get_expected_fips_mode(log, node, variables)
        if expected_fips_mode is None:
            raise SkippedException(
                "Could not determine the expected FIPS mode from variables or metadata."
            )

        # Ensure the system is not FIPS enabled.
        log.info(f"Expected FIPS mode is '{expected_fips_mode}', checking.")
        node.tools[Fips].assert_fips_mode(expected_fips_mode)

        log.info("FIPS mode is configured and properly.")

    @TestCaseMetadata(
        description="""
        This test case will
        1. Check whether FIPS is currently enabled on the VM.
        2. Switch FIPS mode (enabled-to-disabled or disabled-to-enabled).
        3. Restart the VM for the changes to take effect.
        4. Verify that FIPS was switched properly.
        5. Revert the FIPS mode to its original state.
        6. Restart the VM for the changes to take effect.
        7. Verify that FIPS was reverted properly.

        Note that for some platforms, we will only enable fips if it is disabled,
        and then only if we have the proper tool to do so.
        """,
        priority=2,
        requirement=simple_requirement(
            supported_os=[CBLMariner, Ubuntu],
        ),
    )
    def verify_fips_enablement(self, log: Logger, node: Node) -> None:
        if isinstance(node.os, CBLMariner):
            fips = node.tools[Fips]
            starting_fips_mode = fips.is_kernel_fips_mode()

            # Swap the FIPS mode.
            log.info(f"Starting FIPS mode is '{starting_fips_mode}', switching.")
            fips.set_fips_mode(not starting_fips_mode)
            node.reboot()
            fips.assert_fips_mode(not starting_fips_mode)

            # Revert the FIPS mode to its original state.
            log.info(f"Reverting FIPS mode to '{starting_fips_mode}'.")
            fips.set_fips_mode(starting_fips_mode)
            node.reboot()
            fips.assert_fips_mode(starting_fips_mode)
        elif isinstance(node.os, Debian):
            self._verify_fips_enablement_debian(log, node)
        else:
            raise SkippedException(
                f"FIPS enablement test is not supported on {node.os.name}. "
                "Only Azure Linux (CBL-Mariner) and Debian/Ubuntu are supported."
            )

    def _verify_fips_enablement_debian(self, log: Logger, node: Node) -> None:
        """
        Verify FIPS enablement on Debian/Ubuntu.
        On FIPS images where FIPS is already enabled, verify it is active.
        On images with a FIPS kernel but FIPS not enabled, enable it via
        GRUB boot parameters, reboot, and verify. On non-FIPS images, skip.
        """
        fips_enabled_str = node.tools[Cat].read(
            "/proc/sys/crypto/fips_enabled", force_run=True
        )
        starting_fips_mode = to_bool(fips_enabled_str)

        kernel_version = node.execute("uname -r", shell=True).stdout.strip()
        is_fips_kernel = "fips" in kernel_version.lower()

        if not starting_fips_mode and not is_fips_kernel:
            raise SkippedException(
                f"FIPS is not enabled and kernel '{kernel_version}' "
                "does not appear to be a FIPS kernel. "
                "Skipping FIPS test on non-FIPS Debian/Ubuntu image."
            )

        if not starting_fips_mode and is_fips_kernel:
            # FIPS kernel present but not enabled — enable via GRUB.
            log.info(
                f"FIPS kernel '{kernel_version}' detected but FIPS mode "
                "is not enabled. Enabling fips=1 via GRUB boot parameters."
            )
            node.tools[GrubConfig].set_kernel_cmdline_arg("fips", "1")
            node.reboot()

            fips_after_enable = node.tools[Cat].read(
                "/proc/sys/crypto/fips_enabled", force_run=True
            )
            assert_that(to_bool(fips_after_enable)).described_as(
                f"Failed to enable FIPS on kernel '{kernel_version}'. "
                "Added fips=1 to GRUB_CMDLINE_LINUX but "
                "/proc/sys/crypto/fips_enabled is still 0."
            ).is_true()
            log.info(f"FIPS mode successfully enabled on kernel '{kernel_version}'.")
        else:
            log.info(f"FIPS mode is already enabled on kernel '{kernel_version}'.")

        log.info("FIPS enablement verification complete.")

    def _get_expected_fips_mode(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> Union[None, bool]:
        """
        Get the expected FIPS mode based on the variables and the node's metadata.

        Args:
            log (Logger): The logger instance for logging messages.
            node (Node): The node object representing the target machine.
            variables (Dict[str, Any]): A dictionary of variables containing the
            'testing_fips_image' key.

        Returns:
            bool: The expected FIPS mode (True for enabled,
            False for disabled or None if we can't determine.).
        """
        log.debug(f"get_expected_fips_mode: variables is '{variables}'")

        # First, check FIPS image type in variables
        testing_fips_image = variables.get("testing_fips_image", None)
        if testing_fips_image is not None:
            log.debug(
                f"get_expected_fips_mode: testing_fips_image '{testing_fips_image}' "
                "is set in the variables; using it to determine the expected FIPS mode."
            )
            return to_bool(testing_fips_image)

        # Fall back to checking image SKU from azure metadata endpoint
        log.debug(
            "get_expected_fips_mode: testing_fips_image is not set; "
            "falling back to marketplace image sku."
        )
        response = node.tools[Curl].fetch(
            arg="--max-time 2 --header Metadata:true --silent",
            execute_arg="",
            expected_exit_code=None,
            url=METADATA_ENDPOINT,
        )

        # If metadata fetch successful, check image SKU
        if response.exit_code == 0:
            log.debug(
                "get_expected_fips_mode: successfully fetched metadata; "
                "checking image SKU."
            )
            json_response = json.loads(response.stdout)

            # Safely get compute and sku with default empty values
            compute = json_response.get("compute", {})
            sku = compute.get("sku", "")

            # Ensure SKU is a string type before processing
            if not isinstance(sku, str):
                log.debug(
                    f"get_expected_fips_mode: Expected string for SKU, "
                    f"got {type(sku)}"
                )
                return None

            # Skip empty or whitespace-only SKUs
            if not sku.strip():
                log.debug(
                    "get_expected_fips_mode: SKU is empty or contains only whitespace"
                )
                return None

            # Check if SKU contains 'fips' (case-insensitive)
            return "fips" in sku.lower()

        # If we couldn't determine the FIPS mode, return None as a default.
        log.debug(
            "get_expected_fips_mode: could not determine the FIPS mode; "
            "returning None."
        )
        return None
