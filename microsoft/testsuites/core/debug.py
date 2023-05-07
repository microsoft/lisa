# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

from assertpy.assertpy import assert_that

from lisa import (
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.sut_orchestrator import AZURE, READY
from lisa.tools import Cat, Echo, KernelConfig, Mount
from lisa.tools.mkfs import FileSystem


@TestSuiteMetadata(
    area="core",
    category="functional",
    description="""
    This test suite covers kernel debug functionalities.
    """,
    requirement=simple_requirement(unsupported_os=[]),
)
class KernelDebug(TestSuite):
    @TestCaseMetadata(
        description="""
        This test case check VM can be enabled kprobe.

        Steps:
        1. Check if CONFIG_KPROBE_EVENTS is enabled in kernel config.
        2. Check if /sys/kernel/debug/tracing/ is mounted, if not, mount it.
        3. Get origin values of /sys/kernel/debug/tracing/kprobe_events and
         /sys/kernel/debug/tracing/events/kprobes/my/enable.
        4. Write "p:my filp_close" to /sys/kernel/debug/tracing/kprobe_events and
         write "1" to /sys/kernel/debug/tracing/events/kprobes/my/enable.
        5. Check if /sys/kernel/debug/tracing/kprobe_events and
         /sys/kernel/debug/tracing/events/kprobes/my/enable are changed.
        6. Write origin values back to /sys/kernel/debug/tracing/kprobe_events and
         /sys/kernel/debug/tracing/events/kprobes/my/enable.

        """,
        priority=1,
        requirement=simple_requirement(supported_platform_type=[AZURE, READY]),
    )
    def verify_enable_kprobe(self, node: Node) -> None:
        if not node.tools[KernelConfig].is_enabled("CONFIG_KPROBE_EVENTS"):
            raise SkippedException("CONFIG_KPROBE_TRACING is not enabled")

        mount = node.tools[Mount]
        if not (
            mount.check_mount_point_exist("/sys/kernel/tracing")
            or mount.check_mount_point_exist("/sys/kernel/debug")
        ):
            mount.mount("nodev", "/sys/kernel/debug", FileSystem.tracefs)

        origin_kprobe_events: str = ""
        origin_kprobe_enable: str = "0"
        try:
            cat = node.tools[Cat]

            origin_kprobe_events = cat.read(
                "/sys/kernel/debug/tracing/kprobe_events", force_run=True, sudo=True
            )
            if origin_kprobe_events:
                origin_kprobe_enable = cat.read(
                    "/sys/kernel/debug/tracing/events/kprobes/my/enable",
                    force_run=True,
                    sudo=True,
                )

            echo = node.tools[Echo]
            echo.write_to_file(
                "p:my filp_close",
                node.get_pure_path("/sys/kernel/debug/tracing/kprobe_events"),
                sudo=True,
            )
            echo.write_to_file(
                "1",
                node.get_pure_path(
                    "/sys/kernel/debug/tracing/events/kprobes/my/enable"
                ),
                sudo=True,
            )

            cat = node.tools[Cat]
            assert_that(
                cat.read(
                    "/sys/kernel/debug/tracing/kprobe_events",
                    sudo=True,
                    force_run=True,
                )
            ).described_as(
                "after echoing 'p:my filp_close' to "
                "/sys/kernel/debug/tracing/kprobe_events, "
                "its value should be changed into 'p:kprobes/my filp_close'"
            ).is_equal_to(
                "p:kprobes/my filp_close"
            )
            assert_that(
                cat.read(
                    "/sys/kernel/debug/tracing/events/kprobes/my/enable",
                    sudo=True,
                    force_run=True,
                )
            ).described_as(
                "after echoing '1' to "
                "/sys/kernel/debug/tracing/events/kprobes/my/enable, "
                "its value should be changed into '1'"
            ).is_equal_to(
                "1"
            )
        finally:
            echo.write_to_file(
                origin_kprobe_enable,
                node.get_pure_path(
                    "/sys/kernel/debug/tracing/events/kprobes/my/enable"
                ),
                sudo=True,
            )
            echo.write_to_file(
                origin_kprobe_events,
                node.get_pure_path("/sys/kernel/debug/tracing/kprobe_events"),
                sudo=True,
            )
