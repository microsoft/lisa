# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re

from lisa import (
    LisaException,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.features import SecureBootEnabled
from lisa.operating_system import CBLMariner
from lisa.sut_orchestrator import AZURE
from lisa.testsuite import simple_requirement
from lisa.tools import Dmesg, Mokutil
from lisa.util import SkippedException


@TestSuiteMetadata(
    area="lvbs",
    category="functional",
    description="""
    This suite validates that an LVBS production image boots correctly on Azure
    with Secure Boot enabled, the VSM module active, and OP-TEE devices present.
    Applicable only to LVBS Azure Linux images.
    """,
    owner="prapal",
)
class LvbsProdBoot(TestSuite):
    @TestCaseMetadata(
        description="""
        Verify LVBS prod image boots with Secure Boot, VSM, and OP-TEE.

        This test is applicable only to LVBS Azure Linux images that include
        built-in VSM support. It is not expected to pass
        on general-purpose Linux distributions.

        Steps:
        1. Confirm Secure Boot is enabled via mokutil.
        2. Check dmesg for VSM VTL1 boot thread messages indicating
           the VSM module is built-in and active.
           Example matched string: "vsm: cpu1 entering vtl1 boot thread"
        3. Verify OP-TEE device nodes /dev/tee0 and /dev/teepriv0 exist.
        """,
        priority=1,
        timeout=300,  # dmesg and modprobe should not take > 5 mins
        requirement=simple_requirement(
            supported_features=[SecureBootEnabled()],
            supported_platform_type=[AZURE],
            supported_os=[CBLMariner],
        ),
    )
    def verify_lvbs_prod_boot(self, node: Node, log: Logger) -> None:
        kernel_release = node.execute("uname -r", shell=True).stdout.strip()
        if "lvbs" not in kernel_release:
            raise SkippedException(
                f"Non-LVBS kernel '{kernel_release}'. "
                "This test targets LVBS Azure Linux images only."
            )

        mokutil = node.tools[Mokutil]
        dmesg = node.tools[Dmesg]
        # --- Act & Assert: Secure Boot ---
        log.info("Checking Secure Boot status...")
        if not mokutil.is_secure_boot_enabled():
            raise LisaException(
                "Secure Boot is not enabled. "
                "Verify the VM is created with Secure Boot enabled"
                " and rerun the test"
            )
        log.info("Secure Boot is enabled.")

        # --- Act & Assert: VSM module (built-in) ---
        # VSM is built into the kernel and won't appear in lsmod.
        # Instead, verify dmesg contains VTL1 boot thread messages.
        # Example: "vsm: cpu1 entering vtl1 boot thread"
        log.info("Checking dmesg for VSM VTL1 boot thread messages...")
        dmesg_output = dmesg.get_output(force_run=True)
        vsm_pattern = re.compile(r"vsm:\s+cpu\d+\s+entering vtl1 boot thread")
        vsm_matches = vsm_pattern.findall(dmesg_output)
        if not vsm_matches:
            raise LisaException(
                "No VSM VTL1 boot thread messages found in dmesg. "
                "Expected messages like 'vsm: cpu1 entering vtl1 boot thread'. "
                "The VSM module may not be active in this image."
            )
        log.info(
            f"VSM module is active: found {len(vsm_matches)} VTL1 boot thread "
            f"entries in dmesg (e.g. '{vsm_matches[0]}')."
        )

        # --- Act & Assert: OP-TEE device nodes ---
        log.info("Checking for OP-TEE device nodes...")
        missing_devices = []
        for dev in ["/dev/tee0", "/dev/teepriv0"]:
            result = node.execute(f"test -e {dev}", shell=True)
            if result.exit_code != 0:
                missing_devices.append(dev)
        if missing_devices:
            raise LisaException(
                f"OP-TEE device nodes missing: {', '.join(missing_devices)}. "
                "Expected /dev/tee0 and /dev/teepriv0 to be present."
            )
        log.info("OP-TEE device nodes /dev/tee0 and /dev/teepriv0 are present.")
