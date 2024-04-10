# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import os
import re
from pathlib import Path
from typing import Any, Dict

from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
# from lisa.features import SerialConsole
from lisa.testsuite import TestResult
from lisa.tools import Dmesg, Ls, Service, Reboot
from lisa.util import SkippedException, TcpConnectionException, constants
from lisa.util.shell import wait_tcp_port_ready


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

    @TestCaseMetadata(
        description="""
        This test case will
        1. Update to new MSHV components over old ones in a pre-configured MSHV image
        2. Reboot VM, check that mshv comes up

        The test expects the MSHV binaries to be installed to be placed under lisa/microsoft/testsuites/mshv/test_data
        before lisa is executed.
        """,
        priority=0,
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
        hvix_path = self._init_path_dst / f"hvix64.exe"
        node.shell.copy(self._test_hvix_file_path, hvix_path)
        res = node.shell.spawn(
            command=['sudo', 'cp', hvix_path.as_posix(), self._test_hvix_file_path_dst.as_posix()],
            allow_error=False,
        ).wait_for_result()
        log.info(f"sudo cp result {res.return_code}")

        assert res.return_code == 0

        # kdstub_path = self._init_path_dst / f"kdstub.dll"
        # node.shell.copy(self._test_kdstub_file_path, kdstub_path)
        # res = node.shell.spawn(
        #     command=['sudo', 'cp', kdstub_path.as_posix(), self._test_hvix_file_path_dst.as_posix()],
        #     allow_error=False,
        # ).wait_for_result()
        # assert res.return_code == 0
        
        lxhvloader_path = self._init_path_dst / f"lxhvloader.dll"
        node.shell.copy(self._test_lxhvloader_file_path, lxhvloader_path)
        res = node.shell.spawn(
            command=['sudo', 'cp', lxhvloader_path.as_posix(), self._test_lxhvloader_file_path_dst.as_posix()],
            allow_error=False,
        ).wait_for_result()
        assert res.return_code == 0

        reboot_tool = node.tools[Reboot]
        reboot_tool.reboot_and_check_panic(log_path)

        is_ready, tcp_error_code = wait_tcp_port_ready(
            node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS],
            node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_PORT],
            log=log,
        )

        if is_ready:
            # 2. check that mshv comes up
            mshvUp = node.tools[Ls].path_exists("/dev/mshv", sudo=True)
            assert mshvUp
        else:
            raise TcpConnectionException(
                node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS],
                node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_PORT],
                tcp_error_code,
                "no panic found in serial log",
            )
        return
