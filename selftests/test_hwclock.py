# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.tools.hwclock import Hwclock
from lisa.util.process import ExecutableResult


class HwclockTestCase(TestCase):
    def test_set_rtc_clock_to_system_time_forces_execution(self) -> None:
        hwclock = Hwclock.__new__(Hwclock)
        command_result = MagicMock(spec=ExecutableResult)

        with patch.object(hwclock, "run", return_value=command_result) as run:
            hwclock.set_rtc_clock_to_system_time()

        run.assert_called_once_with(
            "--systohc",
            force_run=True,
            shell=True,
            sudo=True,
        )
        command_result.assert_exit_code.assert_called_once_with()
