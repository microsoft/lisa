# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

from assertpy import assert_that

from lisa import (
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import BSD, Windows
from lisa.sut_orchestrator import AZURE, HYPERV, READY
from lisa.tools import Ip, KernelConfig, Lsmod, Modprobe


@TestSuiteMetadata(
    area="network",
    category="functional",
    description="""
    This test suite validates XFRM (IPsec) interface functionality.
    XFRM interfaces are used for IPsec VPN tunnels and are essential
    for secure network communications.
    """,
    requirement=simple_requirement(
        supported_platform_type=[AZURE, READY, HYPERV],
        unsupported_os=[BSD, Windows],
    ),
)
class XfrmSuite(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case verifies that the xfrm_interface kernel module
        can be loaded and provides the expected functionality.

        Steps:
        1. Check if CONFIG_XFRM_INTERFACE is enabled in kernel config.
        2. Load the xfrm_interface module if not already loaded.
        3. Verify the module is loaded successfully.
        4. Create a test xfrm interface (xfrm0).
        5. Verify the interface was created.
        6. Clean up the test interface.

        """,
        priority=2,
    )
    def verify_xfrm_interface(self, node: Node) -> None:
        kernel_config = node.tools[KernelConfig]

        # Check kernel configuration
        if not kernel_config.is_enabled("CONFIG_XFRM_INTERFACE"):
            raise SkippedException("CONFIG_XFRM_INTERFACE is not enabled in kernel")

        # Check if xfrm_interface is built-in or needs to be loaded as module
        is_builtin = kernel_config.is_built_in("CONFIG_XFRM_INTERFACE")

        modprobe = node.tools[Modprobe]
        lsmod = node.tools[Lsmod]

        # Capture original module state (only relevant if not built-in)
        original_state_loaded = None
        if not is_builtin:
            original_state_loaded = lsmod.module_exists(
                "xfrm_interface", force_run=True
            )

            # Load the module if not already loaded
            if not original_state_loaded:
                modprobe.load("xfrm_interface")

            # Verify module is loaded
            module_loaded = lsmod.module_exists("xfrm_interface", force_run=True)
            assert_that(module_loaded).described_as(
                "xfrm_interface module should be loaded"
            ).is_true()

        # Create a test xfrm interface
        # xfrm interfaces require an interface ID (if_id) parameter
        interface_name = "xfrm0"
        if_id = "100"

        # Ensure `ip link ... type xfrm` is supported on this kernel/platform.
        # Relying on `ip link help` output is unreliable across iproute2 versions
        # (it may not list link types and may return non-zero even when printing
        # usage). A direct probe is more dependable and yields actionable errors.
        #
        # Skip vs true failure guidance:
        # - SKIP: userspace doesn't recognize the xfrm link type (old iproute2),
        #   userspace syntax doesn't support required parameters, missing
        #   privileges, or the kernel/platform refuses to create the device
        #   (environment limitation).
        # - FAIL: we successfully created the test xfrm interface (exit_code==0)
        #   but verification/cleanup fails (e.g. interface not present after a
        #   successful create). That indicates a functional regression.
        # Probe with the actual parameters we'll use in the test.
        # Some older iproute2 builds can recognize "type xfrm" but *cannot*
        # parse the required "dev ... if_id ..." arguments; in that case, skip.
        default_nic = node.nics.default_nic

        ip = node.tools[Ip]
        supported, reason = ip.supports_xfrm(dev=default_nic, if_id=if_id)
        if not supported:
            raise SkippedException(reason)

        try:
            # Create xfrm interface
            # ip link add <name> type xfrm dev <physical_dev> if_id <id>
            # We need to find an existing physical interface first
            cmd = (
                f"link add {interface_name} type xfrm "
                f"dev {default_nic} if_id {if_id}"
            )
            result = ip.run(cmd, sudo=True, force_run=True)

            # Check if interface creation succeeded
            if result.exit_code == 0:
                # Verify interface exists
                if not ip.nic_exists(interface_name):
                    raise AssertionError(
                        f"Interface {interface_name} creation succeeded but "
                        "interface not found."
                    )
                # Also verify it appears in link show output
                show_result = ip.run(
                    f"link show {interface_name}", sudo=True, force_run=True
                )
                assert_that(show_result.stdout).described_as(
                    f"output should contain {interface_name}"
                ).contains(interface_name)
            else:
                # Interface creation failed - this indicates XFRM support issue
                raise AssertionError(
                    f"Failed to create xfrm interface. "
                    f"Exit code: {result.exit_code}, "
                    f"stderr: {result.stderr}"
                )

        finally:
            # Clean up - delete the test interface if it was created
            ip.run(f"link del {interface_name}", sudo=True, force_run=True)

            # Restore original module state if we modified it
            if not is_builtin and original_state_loaded is not None:
                current_state_loaded = lsmod.module_exists(
                    "xfrm_interface", force_run=True
                )
                if not original_state_loaded and current_state_loaded:
                    # Was not loaded originally, need to unload
                    modprobe.remove(["xfrm_interface"])

    @TestCaseMetadata(
        description="""
        This test case verifies that the xfrm_interface kernel module
        can be loaded and unloaded without issues.

        Steps:
        1. Check if CONFIG_XFRM_INTERFACE is enabled and not built-in.
        2. Unload the xfrm_interface module if loaded.
        3. Load the xfrm_interface module.
        4. Verify the module is loaded.
        5. Unload the module.
        6. Verify the module is unloaded.

        """,
        priority=3,
    )
    def verify_xfrm_interface_load_unload(self, node: Node) -> None:
        kernel_config = node.tools[KernelConfig]

        # Check kernel configuration
        if not kernel_config.is_enabled("CONFIG_XFRM_INTERFACE"):
            raise SkippedException("CONFIG_XFRM_INTERFACE is not enabled in kernel")

        # Skip if built-in (can't unload built-in modules)
        if kernel_config.is_built_in("CONFIG_XFRM_INTERFACE"):
            raise SkippedException(
                "CONFIG_XFRM_INTERFACE is built-in, cannot test module load/unload"
            )

        modprobe = node.tools[Modprobe]
        lsmod = node.tools[Lsmod]

        # Capture original state
        original_state_loaded = lsmod.module_exists("xfrm_interface", force_run=True)

        try:
            # Ensure module is unloaded first
            if lsmod.module_exists("xfrm_interface", force_run=True):
                modprobe.remove(["xfrm_interface"])

            # Verify module is unloaded
            module_exists = lsmod.module_exists("xfrm_interface", force_run=True)
            assert_that(module_exists).described_as(
                "xfrm_interface module should be unloaded before test"
            ).is_false()

            # Load the module
            modprobe.load("xfrm_interface")

            # Verify module is loaded
            module_exists = lsmod.module_exists("xfrm_interface", force_run=True)
            assert_that(module_exists).described_as(
                "xfrm_interface module should be loaded after modprobe"
            ).is_true()

            # Unload the module
            modprobe.remove(["xfrm_interface"])

            # Verify module is unloaded
            module_exists = lsmod.module_exists("xfrm_interface", force_run=True)
            assert_that(module_exists).described_as(
                "xfrm_interface module should be unloaded after removal"
            ).is_false()

        finally:
            # Restore original state
            current_state_loaded = lsmod.module_exists("xfrm_interface", force_run=True)
            if original_state_loaded and not current_state_loaded:
                # Was loaded originally, need to reload
                modprobe.load("xfrm_interface")
            elif not original_state_loaded and current_state_loaded:
                # Was not loaded originally, need to unload
                modprobe.remove(["xfrm_interface"])
