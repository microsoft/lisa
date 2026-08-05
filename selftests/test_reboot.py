# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from datetime import datetime, timedelta
from unittest import TestCase
from unittest.mock import MagicMock, Mock, call, patch

from lisa.tools import Date, Reboot


class RebootTestCase(TestCase):
    def setUp(self) -> None:
        self.reboot = Reboot.__new__(Reboot)
        self.reboot.node = MagicMock()
        self.reboot._log = MagicMock()
        self.reboot._command = "/sbin/reboot"
        self.date = MagicMock()
        self.reboot.node.tools = {Date: self.date}
        self.command_result = Mock(exit_code=0, stdout="", stderr="")
        self.reboot.node.execute.return_value = self.command_result
        self.boot_time = datetime(2026, 1, 1)

    def test_reconnects_before_remote_operation_after_uptime_wait(self) -> None:
        events = []
        boot_times = iter(
            [self.boot_time, self.boot_time, self.boot_time + timedelta(minutes=2)]
        )
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

        self.reboot.node.close.side_effect = lambda: events.append("close")
        self.reboot.node.execute.side_effect = lambda *args, **kwargs: (
            events.append("execute") or self.command_result
        )
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
                "get_last_boot_time",
                "date_current",
            ],
            events[:6],
        )

    def test_does_not_reboot_when_host_reboots_during_uptime_wait(self) -> None:
        refreshed_boot_time = self.boot_time + timedelta(minutes=2)
        self.date.current.side_effect = [
            self.boot_time + timedelta(seconds=20),
            self.boot_time + timedelta(seconds=61),
        ]

        with patch.object(
            self.reboot,
            "_get_last_boot_time",
            side_effect=[self.boot_time, refreshed_boot_time],
        ), patch.object(
            self.reboot, "_wait_ssh_session_stable"
        ) as wait_ssh_session_stable, patch("lisa.tools.reboot.sleep"):
            self.reboot.reboot()

        self.reboot.node.close.assert_called_once_with()
        self.reboot.node.execute.assert_not_called()
        wait_ssh_session_stable.assert_called_once()

    def test_reboots_once_when_host_stays_up_during_uptime_wait(self) -> None:
        refreshed_boot_time = self.boot_time + timedelta(minutes=2)
        self.date.current.side_effect = [
            self.boot_time + timedelta(seconds=20),
            self.boot_time + timedelta(seconds=61),
        ]

        with patch.object(
            self.reboot,
            "_get_last_boot_time",
            side_effect=[self.boot_time, self.boot_time, refreshed_boot_time],
        ), patch.object(self.reboot, "_wait_ssh_session_stable"), patch(
            "lisa.tools.reboot.sleep"
        ):
            self.reboot.reboot()

        reboot_call = call(
            "systemctl reboot -i",
            shell=True,
            sudo=True,
            timeout=10,
        )
        self.assertEqual(1, self.reboot.node.execute.call_args_list.count(reboot_call))
