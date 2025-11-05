# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.operating_system import BSD, Windows
from lisa.tools import Lsmod, Modprobe


@TestSuiteMetadata(
    area="storage",
    category="functional",
    description="""
    This test suite covers dm-cache functionality.
    dm-cache provides block-level caching for Linux device mapper.
    It allows for the creation of hybrid storage solutions by caching
    frequently accessed data from slow storage devices (like HDDs) onto
    faster storage devices (like SSDs).
    """,
)
class DmCache(TestSuite):
    @TestCaseMetadata(
        description="""
        This test verifies dm-cache module functionality.
        
        Steps:
        1. Check if dm-cache module is available in the system
        2. Load the dm-cache module if not already loaded
        3. Verify the module was loaded successfully
        4. Check that required dm-cache components are available
        
        The test will skip if dm-cache module is not available on the system.
        """,
        priority=2,
    )
    def verify_dm_cache_module_loading(self, node: Node, log: Logger) -> None:
        # Skip test on unsupported operating systems
        if isinstance(node.os, (BSD, Windows)):
            raise SkippedException(
                f"dm-cache is not supported on {node.os.__class__.__name__}"
            )

        modprobe = node.tools[Modprobe]
        lsmod = node.tools[Lsmod]

        # Check if dm-cache module exists on the system
        if not modprobe.module_exists("dm_cache"):
            raise SkippedException(
                "dm-cache module is not available on this system"
            )

        log.info("dm-cache module is available on the system")

        # Check if dm-cache is already loaded
        is_loaded_before = lsmod.module_exists("dm_cache")
        if is_loaded_before:
            log.info("dm-cache module is already loaded")
        else:
            log.info("Loading dm-cache module")
            
            # Load the dm-cache module
            load_result = modprobe.load("dm_cache")
            assert_that(load_result).described_as(
                "Failed to load dm-cache module"
            ).is_true()

        # Verify the module is now loaded
        is_loaded_after = lsmod.module_exists("dm_cache")
        assert_that(is_loaded_after).described_as(
            "dm-cache module should be loaded after modprobe"
        ).is_true()

        log.info("dm-cache module loaded successfully")

        # Check for related dm modules that should be available
        # These are typically loaded automatically when dm-cache is loaded
        related_modules = ["dm_mod"]  # Basic device mapper module
        
        for module in related_modules:
            if lsmod.module_exists(module):
                log.info(f"Related module '{module}' is loaded")
            else:
                log.warning(f"Related module '{module}' is not loaded")

        log.info("dm-cache module verification completed successfully")
