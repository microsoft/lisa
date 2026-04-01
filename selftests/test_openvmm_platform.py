# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock

from lisa.microsoft.testsuites.openvmm.openvmm_platform import OpenVmmPlatform
from lisa.tools import Uname


class OpenVmmPlatformTestCase(TestCase):
    def test_verify_openvmm_guest_boot_accepts_string_log_path(self) -> None:
        suite = OpenVmmPlatform.__new__(OpenVmmPlatform)
        kernel_info = SimpleNamespace(kernel_version_raw="5.4.0-test")
        uname = MagicMock()
        uname.get_linux_information.return_value = kernel_info

        node = MagicMock()
        node.tools = {Uname: uname}
        log = MagicMock()

        suite.verify_openvmm_guest_boot(log, node, str(Path(__file__).parent))

        log.info.assert_called_once_with(
            "Connected to OpenVMM guest kernel 5.4.0-test"
        )
