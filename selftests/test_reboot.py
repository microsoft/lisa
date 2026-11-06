# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from datetime import datetime, timedelta
from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch

from func_timeout import FunctionTimedOut

from lisa.tools import Date, Reboot, Uptime, Who


class RebootTestCase(TestCase):
    def setUp(self) -> None:
        self.reboot = Reboot.__new__(Reboot)
        self.node = MagicMock()
        self.reboot.node = self.node
        self.reboot._log = MagicMock()
        self.reboot._command = "/sbin/reboot"
        self.date = MagicMock()
        self.node.tools = {Date: self.date}
        self.command_result = Mock(exit_code=0, stdout="", stderr="")
        self.node.execute.return_value = self.command_result
        self.boot_time = datetime(2026, 1, 1)

    def test_falls_back_to_uptime_when_who_times_out(self) -> None:
        uptime = MagicMock()
        uptime.since_time.return_value = self.boot_time
        self.node.tools = {Who: MagicMock(), Uptime: uptime}

        with patch("lisa.tools.reboot._who_last", side_effect=FunctionTimedOut()):
            last_boot_time = self.reboot._get_last_boot_time()

        self.assertEqual(self.boot_time, last_boot_time)
        uptime.since_time.assert_called_once_with()

    def test_reconnects_before_remote_operation_after_uptime_wait(self) -> None:
        events = []
        boot_times = iter([self.boot_time, self.boot_time + timedelta(minutes=2)])
        current_times = iter(
            [
                self.boot_time + timedelta(seconds=20),
                self.boot_time + timedelta(seconds=61),
            ]
        )

        def get_last_boot_time() -> datetime:
            events.append("get_last_boot_time")
            return next(boot_times)

        def get_current_time() -> datetime:
            events.append("date_current")
            return next(current_times)

        def execute(*args: object, **kwargs: object) -> Mock:
            events.append("execute")
            return self.command_result

        self.node.close.side_effect = lambda: events.append("close")
        self.node.execute.side_effect = execute
        self.date.current.side_effect = get_current_time

        with patch.object(
            self.reboot, "_get_last_boot_time", side_effect=get_last_boot_time
        ), patch.object(self.reboot, "_wait_ssh_session_stable"), patch(
            "lisa.tools.reboot.sleep", side_effect=lambda _: events.append("sleep")
        ):
            self.reboot.reboot()

        self.assertEqual(
            [
                "get_last_boot_time",
                "date_current",
                "sleep",
                "close",
                "date_current",
            ],
            events[:5],
        )
