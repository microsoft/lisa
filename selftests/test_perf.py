# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch

from lisa.operating_system import Ubuntu
from lisa.tools import Perf, Uname


class PerfTestCase(TestCase):
    def setUp(self) -> None:
        self.perf = Perf.__new__(Perf)

    def test_check_exists_rejects_nonzero_exit_code(self) -> None:
        result = Mock(
            exit_code=2,
            stdout="WARNING: perf not found for kernel 6.14.0-1017-azure",
        )

        with patch.object(
            self.perf, "command_exists", return_value=(True, False)
        ), patch.object(self.perf, "run", return_value=result) as run:
            self.assertFalse(self.perf._check_exists())
            run.assert_called_once_with(force_run=True)

    def test_check_exists_accepts_successful_perf(self) -> None:
        result = Mock(exit_code=0, stdout="perf version 6.14")

        with patch.object(
            self.perf, "command_exists", return_value=(True, False)
        ), patch.object(self.perf, "run", return_value=result) as run:
            self.assertTrue(self.perf._check_exists())
            run.assert_called_once_with(force_run=True)

    def test_install_uses_azure_kernel_packages_on_ubuntu(self) -> None:
        ubuntu = MagicMock(spec=Ubuntu)
        uname = MagicMock()
        uname.get_linux_information.return_value.kernel_version_raw = (
            "6.14.0-1017-azure"
        )
        self.perf.node = MagicMock(os=ubuntu, tools={Uname: uname})

        with patch.object(self.perf, "_check_exists", side_effect=[False, True]):
            self.assertTrue(self.perf._install())
        ubuntu.install_packages.assert_called_once_with(
            [
                "linux-tools-6.14.0-1017-azure",
                "linux-cloud-tools-6.14.0-1017-azure",
                "linux-tools-azure",
                "linux-cloud-tools-azure",
            ]
        )
