# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
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
from lisa.operating_system import CBLMariner
from lisa.sut_orchestrator.azure.common import METADATA_ENDPOINT
from lisa.tools import Curl, Fips
from lisa.util import SkippedException


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
            Ensures that an AZL machine is fips enabled.
        """,
        priority=1,
        requirement=simple_requirement(
            supported_os=[CBLMariner],
        ),
    )
    def verify_azl_fips_is_enabled(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        # Skip the test if the image is not FIPS enabled.
        self._ensure_fips_expectations(log, node, variables, should_be_fips=True)

        # Ensure the system is FIPS enabled.
        node.tools[Fips].assert_fips_mode(True)

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
    def verify_azl_fips_is_disabled(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        # Skip the test if the image is FIPS enabled.
        self._ensure_fips_expectations(log, node, variables, should_be_fips=False)

        # Ensure the system is not FIPS enabled.
        node.tools[Fips].assert_fips_mode(False)

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
    def verify_azl_fips_enable(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        # Skip the test if the image is already FIPS enabled.
        self._ensure_fips_expectations(log, node, variables, should_be_fips=False)

        # Enable FIPS on the system and make sure it is worked.
        azl_fips = node.tools[Fips]
        azl_fips.enable_fips()
        node.reboot()
        azl_fips.assert_fips_mode(True)

        log.info("Successfully enabled FIPS.")

        # Re-disable FIPS to make sure the test can be run multiple times.
        azl_fips.disable_fips()
        node.reboot()

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
    def verify_azl_fips_disable(
        self, log: Logger, node: Node, variables: Dict[str, Any]
    ) -> None:
        # Skip the test if the image is already not FIPS enabled.
        self._ensure_fips_expectations(log, node, variables, should_be_fips=True)

        # Disable FIPS on the system and make sure it is worked.
        azl_fips = node.tools[Fips]
        azl_fips.disable_fips()
        node.reboot()
        azl_fips.assert_fips_mode(False)

        log.info("Successfully disabled FIPS.")

        # Re-enable FIPS to make sure the test can be run multiple times.
        azl_fips.enable_fips()
        node.reboot()

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
        ),
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

    def _ensure_fips_expectations(
        self, log: Logger, node: Node, variables: Dict[str, Any], should_be_fips: bool
    ):
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
                f"ensure_fips_expectations: testing_fips_image not in '{list(fips_image_map.keys())}'"
                "falling back to marketplace image sku"
            )
            response = node.tools[Curl].fetch(
                arg="--max-time 2 --header Metadata:true --silent",
                execute_arg="",
                expected_exit_code=None,
                url=METADATA_ENDPOINT,
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
