# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import os
import re
from pathlib import Path
from typing import Any, Dict

import time

from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata
)
# from lisa.features import SerialConsole
from lisa.testsuite import TestResult
from lisa.tools import Cp, Dmesg, Ls, Reboot

@TestSuiteMetadata(
    area="mshv",
    category="functional",
    description="""
    This test suite is to test VM working well after updating MSHV on VM and rebooting.
    """,
)
class MshvHostInstallSuite(TestSuite):

    _test_hvix_file_path = (
        Path(os.path.dirname(__file__)) / "test_data" / f"hvix64.exe"
    )

    _test_hvix_file_path_dst = (
        Path("/boot/efi/Windows/System32") / f"hvix64.exe"
    )

    _test_kdstub_file_path = (
        Path(os.path.dirname(__file__)) / "test_data" / f"kdstub.dll"
    )

    _test_kdstub_file_path_dst = (
        Path("/boot/efi/Windows/System32") / f"kdstub.dll"
    )

    _test_lxhvloader_file_path = (
        Path(os.path.dirname(__file__)) / "test_data" / f"lxhvloader.dll"
    )

    _test_lxhvloader_file_path_dst = (
        Path("/boot/efi") / f"lxhvloader.dll"
    )

    _init_path_dst = (
        Path("/home/cloud")
    )

    _init_path_dst_hvix = (
        Path("/home/cloud") / f"hvix64.exe"
    )

    _init_path_dst_kdstub = (
        Path("/home/cloud") / f"kdstub.dll"
    )

    _init_path_dst_lxhvloader = (
        Path("/home/cloud") / f"lxhvloader.dll"
    )

    @TestCaseMetadata(
        description="""
        This test case will
        1. Update to new MSHV components over old ones in a pre-configured MSHV image
        2. Reboot VM, check that mshv comes up

        The test expects the MSHV binaries to be installed to be placed under lisa/microsoft/testsuites/mshv/test_data
        before lisa is executed.
        """,
        timeout=60,  # 60 seconds
    )
    def verify_mshv_install_succeeds(
        self,
        log: Logger,
        node: Node,
        log_path: Path,
        result: TestResult,
    ) -> None:
        # Copy Hvix64.exe, kdstub.dll, lxhvloader.dll into test machine
        node.shell.copy(self._test_hvix_file_path, self._init_path_dst_hvix)
        test_sha256_cmd = "sudo sha256sum %s" % self._test_hvix_file_path_dst.as_posix()
        res = node.execute(
            test_sha256_cmd,
            shell=True,
            sudo=True
        )
        time.sleep(5)
        node.tools[Cp].copy(self._init_path_dst_hvix.as_posix(), self._test_hvix_file_path_dst.as_posix(), sudo=True)
        res = node.execute(
            test_sha256_cmd,
            shell=True,
            sudo=True
        )

        # node.shell.copy(self._test_kdstub_file_path, self._init_path_dst_kdstub)
        # node.tools[Cp].copy(self._init_path_dst_kdstub.as_posix(), self._test_hvix_file_path_dst.as_posix(), sudo=True)
        
        node.shell.copy(self._test_lxhvloader_file_path, self._init_path_dst_lxhvloader)
        node.tools[Cp].copy(self._init_path_dst_lxhvloader.as_posix(), self._test_lxhvloader_file_path_dst.as_posix(), sudo=True)


        reboot_tool = node.tools[Reboot]
        reboot_tool.reboot_and_check_panic(log_path)

        # 2. check that mshv comes up
        mshvUp = node.tools[Ls].path_exists("/dev/mshv", sudo=True)
        assert mshvUp
