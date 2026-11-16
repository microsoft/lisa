from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import Ubuntu
from lisa.tools import Getconf, Smaps, Uname
from lisa.util import LisaException


@TestSuiteMetadata(
    area="core",
    category="functional",
    description="Validates running kernel configuration and behavior.",
)
class Kernel(TestSuite):
    @TestCaseMetadata(
        description="""
        Verify the running kernel's base page size on Ubuntu 24.04 or newer.
        Kernel releases containing '64k' (case-insensitive) must use 65536-byte
        pages. All other releases must use 4096-byte pages. Read the actual
        size with getconf PAGE_SIZE and cross-check KernelPageSize and
        MMUPageSize for the first mapping in /proc/self/smaps.
        Hugepage sizes are not considered.
        Older Ubuntu releases are skipped. No guest state is changed.
        """,
        priority=1,
        maturity="preview",
        requirement=simple_requirement(supported_os=[Ubuntu]),
    )
    def verify_kernel_page_size(self, node: Node, log: Logger) -> None:
        if node.os.information.version < "24.4.0":
            raise SkippedException(
                "Kernel page-size validation requires Ubuntu 24.04 or newer; "
                f"detected {node.os.information.version}."
            )

        kernel = node.tools[Uname].get_linux_information(force_run=True)
        kernel_release = kernel.kernel_version_raw.strip()
        if not kernel.has_result or not kernel_release:
            raise LisaException(
                "Could not determine the running kernel release. "
                "Check 'uname -r' on the guest before validating page size."
            )
        expected_page_size = 64 * 1024 if "64k" in kernel_release.lower() else 4 * 1024
        page_size = node.tools[Getconf].get_page_size()

        log.info(
            f"Kernel page-size validation: release={kernel_release}, "
            f"expected={expected_page_size} bytes, actual={page_size} bytes"
        )
        assert_that(page_size).described_as(
            f"Kernel {kernel_release} must use {expected_page_size}-byte base pages "
            "according to its 64k release marker. Check the booted kernel flavor "
            "and its page-size configuration."
        ).is_equal_to(expected_page_size)

        # KernelPageSize checks the mapping's backing-page size; MMUPageSize
        # cross-checks its reported hardware translation granularity. Use only
        # the first ordinary mapping, not later mappings that may use hugepages.
        for field, mapping_page_size in node.tools[Smaps].get_page_sizes().items():
            log.info(
                f"Kernel page-size validation: release={kernel_release}, "
                f"smaps {field}={mapping_page_size} bytes, "
                f"expected={expected_page_size} bytes"
            )
            assert_that(mapping_page_size).described_as(
                f"Kernel {kernel_release}: first smaps mapping's {field} must "
                f"match the expected {expected_page_size}-byte base page size. "
                "Check the booted kernel flavor and /proc/self/smaps."
            ).is_equal_to(expected_page_size)
