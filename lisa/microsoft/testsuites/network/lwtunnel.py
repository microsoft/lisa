# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
"""
Test suite for validating Linux Lightweight Tunnel (LWTUNNEL) functionality.
"""
from __future__ import annotations

from logging import Logger
from pathlib import PurePath
from typing import Any, cast

from assertpy import assert_that

from lisa import (
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import CBLMariner, Linux
from lisa.sut_orchestrator import AZURE, HYPERV, READY
from lisa.tools import Ip, Ls, Rm, Tee
from lisa.tools.kernel_config import KernelConfig
from lisa.util import UnsupportedDistroException


@TestSuiteMetadata(
    area="network",
    category="functional",
    description="""
    Validates LWTUNNEL (Lightweight Tunnel) functionality including
    route-based encapsulation for BPF, SEG6, and other tunnel types.
    """,
    requirement=simple_requirement(
        supported_platform_type=[AZURE, READY, HYPERV],
        supported_os=[Linux],
    ),
)
class LwtunnelSuite(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        if not isinstance(node.os, CBLMariner) or node.os.information.version < "3.0.0":
            raise SkippedException(
                UnsupportedDistroException(
                    node.os,
                    "LWTUNNEL BPF support is only tested on"
                    " AzureLinux 3.0 and later.",
                )
            )

    # Minimal BPF C program for lwt_xmit that returns BPF_OK.
    # lwt_xmit is one of four LWT BPF hook points (lwt_in, lwt_out, lwt_xmit,
    # lwt_seg6local). lwt_xmit runs at transmit time and is the most capable —
    # it can modify, redirect, or drop packets. The section name tells clang to
    # place the function in an ELF section that `ip route ... sec lwt_xmit`
    # references when attaching the BPF program to a route.
    _BPF_PROG_SRC = """
#include <linux/bpf.h>

__attribute__((section("lwt_xmit"), used))
int lwtunnel_pass(struct __sk_buff *skb) {
    return BPF_OK;
}

char _license[] __attribute__((section("license"), used)) = "GPL";
"""

    @TestCaseMetadata(
        description="""
        Verifies BPF-based lightweight tunnel support by:
        1. Checking kernel configs are enabled
        2. Compiling and loading a minimal BPF program
        3. Attaching it to a route as lwtunnel encap
        4. Verifying the route is created with BPF encap
        """,
        priority=3,
    )
    def verify_lwtunnel_bpf_support(self, node: Node) -> None:
        # Check kernel configuration for required LWTUNNEL support
        kernel_config = node.tools[KernelConfig]

        if not kernel_config.is_enabled("CONFIG_LWTUNNEL"):
            raise SkippedException(
                "Kernel does not have CONFIG_LWTUNNEL enabled - "
                "lightweight tunnel support is required"
            )

        if not kernel_config.is_enabled("CONFIG_LWTUNNEL_BPF"):
            raise SkippedException(
                "Kernel does not have CONFIG_LWTUNNEL_BPF enabled - "
                "BPF encapsulation for lwtunnel is required"
            )

        linux_os = cast(Linux, node.os)
        ip = node.tools[Ip]
        tee = node.tools[Tee]
        ls = node.tools[Ls]
        rm = node.tools[Rm]

        # Check/install clang for BPF compilation
        clang_result = node.execute("command -v clang", shell=True)
        if clang_result.exit_code != 0:
            for pkg in ["clang", "clang-11", "clang-14", "clang-15"]:
                if linux_os.is_package_in_repo(pkg):
                    linux_os.install_packages(pkg)
                    break
            clang_result = node.execute("command -v clang", shell=True)
            if clang_result.exit_code != 0:
                raise SkippedException("clang not available for BPF compile")

        # Ensure kernel headers are available for linux/bpf.h
        if not ls.path_exists("/usr/include/linux/bpf.h", sudo=True):
            for pkg in [
                "kernel-headers",
                "kernel-devel",
                "linux-headers-$(uname -r)",
                "linux-libc-dev",
            ]:
                if linux_os.is_package_in_repo(pkg):
                    linux_os.install_packages(pkg)
                    break
            if not ls.path_exists("/usr/include/linux/bpf.h", sudo=True):
                raise SkippedException(
                    "linux/bpf.h not found - kernel headers required"
                )

        bpf_src = "/tmp/lwt_test.c"
        bpf_obj = "/tmp/lwt_test.o"
        pinned_prog = "/sys/fs/bpf/lwt_test"
        dummy_if = "lwtbpf0"
        test_route = "198.51.100.0/24"

        try:
            # Write BPF source file (Tee uses single quotes,
            # preserving the double quotes in section attributes)
            tee.write_to_file(
                self._BPF_PROG_SRC,
                PurePath(bpf_src),
                sudo=True,
            )

            # Compile BPF program
            compile_result = node.execute(
                f"clang -O2 -target bpf -c {bpf_src} -o {bpf_obj}",
                sudo=True,
            )
            if compile_result.exit_code != 0:
                error_output = compile_result.stderr or compile_result.stdout
                raise SkippedException(f"Failed to compile BPF program: {error_output}")

            node.log.info("BPF program compiled successfully")

            # Create dummy interface
            if ip.nic_exists(dummy_if):
                ip.delete_interface(dummy_if)
            result = ip.run(f"link add {dummy_if} type dummy", sudo=True)
            if result.exit_code != 0:
                raise SkippedException(
                    f"Cannot create dummy interface: {result.stderr}"
                )
            ip.up(dummy_if)
            ip.add_ipv4_address(dummy_if, "192.0.2.1/24", persist=False)

            # Add route with BPF encap using compiled object file
            route_result = ip.run(
                f"route add {test_route} encap bpf xmit obj {bpf_obj} "
                f"sec lwt_xmit dev {dummy_if}",
                sudo=True,
                force_run=True,
            )
            assert_that(route_result.exit_code).described_as(
                "BPF encap route should be added successfully. "
                "Failure indicates kernel lacks LWTUNNEL_BPF "
                f"support: {route_result.stderr}"
            ).is_equal_to(0)

            # Verify route shows BPF encap
            show_result = ip.run(f"route show {test_route}", sudo=True)
            assert_that(show_result.stdout.lower()).described_as(
                "Route should show BPF encap"
            ).contains("encap bpf")

            node.log.info(f"BPF encap route created: {show_result.stdout.strip()}")
            node.log.info("BPF lwtunnel support verified")

        finally:
            # Cleanup
            ip.run(f"route del {test_route}", sudo=True, force_run=True)
            rm.remove_file(pinned_prog, sudo=True)
            rm.remove_file(bpf_src, sudo=True)
            rm.remove_file(bpf_obj, sudo=True)
            if ip.nic_exists(dummy_if):
                ip.delete_interface(dummy_if)
