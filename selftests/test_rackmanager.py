# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.sut_orchestrator.baremetal.cluster.rackmanager import RackManagerSerialConsole
from lisa.util import LisaException


class RackManagerSerialConsoleTestCase(TestCase):
    def test_login_reports_serial_process_exit_before_input(self) -> None:
        serial_console = RackManagerSerialConsole.__new__(RackManagerSerialConsole)
        serial_console._process = MagicMock()
        serial_console._process.is_running.return_value = False
        serial_console._process.wait_result.return_value.exit_code = 1
        serial_console._process.wait_result.return_value.stdout = "serial unavailable"
        serial_console._process.wait_result.return_value.stderr = "session closed"

        with patch.object(serial_console, "_get_prompt_state", return_value="empty"):
            with self.assertRaisesRegex(
                LisaException, "Rack Manager serial session exited"
            ):
                serial_console._login(timeout=1)

        serial_console._process.input.assert_not_called()

    def test_login_reports_serial_process_exit_during_input(self) -> None:
        serial_console = RackManagerSerialConsole.__new__(RackManagerSerialConsole)
        serial_console._process = MagicMock()
        serial_console._process.is_running.return_value = True
        serial_console._process.input.side_effect = OSError("Socket is closed")
        serial_console._process.wait_result.return_value.exit_code = 1
        serial_console._process.wait_result.return_value.stdout = "serial unavailable"
        serial_console._process.wait_result.return_value.stderr = "session closed"

        with patch.object(serial_console, "_get_prompt_state", return_value="empty"):
            with self.assertRaisesRegex(
                LisaException,
                "Exit code: 1.*serial unavailable.*session closed",
            ):
                serial_console._login(timeout=1)
