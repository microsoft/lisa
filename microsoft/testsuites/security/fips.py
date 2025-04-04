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
from lisa.operating_system import CBLMariner
from lisa.sut_orchestrator.azure.common import METADATA_ENDPOINT
from lisa.tools import Curl, Fips
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
        else:
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

        # First, see if the test runner specified the FIPS image type in the variables.
        testing_fips_image = variables.get("testing_fips_image", None)
        if testing_fips_image is not None:
            log.debug(
                f"get_expected_fips_mode: testing_fips_image '{testing_fips_image}' "
                "is set in the variables; using it to determine the expected FIPS mode."
            )
            return to_bool(testing_fips_image)

        # Fall back to checking the image SKU from the azure metadata endpoint.
        log.debug(
            "get_expected_fips_mode: testing_fips_image is not set; falling back to "
            "marketplace image sku."
        )
        response = node.tools[Curl].fetch(
            arg="--max-time 2 --header Metadata:true --silent",
            execute_arg="",
            expected_exit_code=None,
            url=METADATA_ENDPOINT,
        )

        # If we successfully fetched the metadata, check the image SKU.
        if response.exit_code == 0:
            log.debug(
                "get_expected_fips_mode: successfully fetched metadata; checking image SKU."
            )
            response = json.loads(response.stdout)
            return "fips" in response["compute"]["sku"]

        # If we couldn't determine the FIPS mode, return False as a default.
        log.debug(
            "get_expected_fips_mode: could not determine the FIPS mode; returning None."
        )
        return None
