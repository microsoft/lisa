# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import Path
from typing import Any

from microsoft.testsuites.libvirt.libvirt_tck_tool import LibvirtTck

from lisa import Logger, Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.operating_system import CBLMariner, Ubuntu
from lisa.testsuite import TestResult, simple_requirement
from lisa.tools import Cat, Dmesg, Journalctl, Lscpu
from lisa.util import SkippedException


@TestSuiteMetadata(
    area="libvirt",
    category="community",
    description="""
    Runs the libvirt TCK (Technology Compatibility Kit) tests. It is a suite
    of functional/integration tests designed to test a libvirt driver's complicance
    with API semantics, distro configuration etc.

    More info: https://gitlab.com/libvirt/libvirt-tck/-/blob/master/README.rst
    """,
    requirement=simple_requirement(supported_os=[Ubuntu, CBLMariner]),
)
class LibvirtTckSuite(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        # Defense-in-depth: catches custom VHD/SIG images whose OS detection
        # may misclassify the node and bypass the supported_os gate.
        if not isinstance(node.os, (Ubuntu, CBLMariner)):
            raise SkippedException(
                f"Libvirt TCK suite is not implemented in LISA for {node.os.name}"
            )
        # ensure virtualization is enabled in hardware before running tests
        virtualization_enabled = node.tools[Lscpu].is_virtualization_enabled()
        if not virtualization_enabled:
            raise SkippedException("Virtualization is not enabled in hardware")

        # The libvirt TCK community suite is not FIPS-aware. On FIPS-enabled
        # kernels the suite is unreliable (tests either time out or report
        # spurious failures), so skip it rather than fail on FIPS images.
        fips_result = node.tools[Cat].run(
            "/proc/sys/crypto/fips_enabled",
            force_run=True,
            no_error_log=True,
        )
        if fips_result.exit_code == 0 and (fips_result.stdout or "").strip() == "1":
            raise SkippedException(
                "The libvirt TCK suite is not supported on FIPS-enabled kernels."
            )

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        dmesg = node.tools[Dmesg]
        dmesg.get_output(force_run=True)

        journalctl = node.tools[Journalctl]
        libvirt_log = journalctl.logs_for_unit(
            unit_name="libvirtd",
            sudo=True,
        )
        log.debug(f"Journalctl libvirt Logs: {libvirt_log}")

    @TestCaseMetadata(
        description="""
        Runs the Libvirt TCK (Technology Compatibility Kit) tests with the default
        configuration i.e. the tests will exercise the qemu driver in libvirt.
        """,
        priority=3,
    )
    def verify_libvirt_tck(
        self,
        node: Node,
        log_path: Path,
        result: TestResult,
    ) -> None:
        libvirt_tck: LibvirtTck = node.tools[LibvirtTck]
        libvirt_tck.run_tests(result, log_path)
