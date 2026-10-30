# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from datetime import datetime, timedelta
from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch

from lisa.tools import Date, Reboot
from lisa.util import LisaException


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

        def execute(*_args: object, **_kwargs: object) -> Mock:
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

    def test_systemctl_reboot_exit_codes(self) -> None:
        self.date.current.return_value = self.boot_time + timedelta(minutes=2)
        for exit_code in (0, -1, 1):
            with self.subTest(exit_code=exit_code):
                self.node.execute.side_effect = [
                    Mock(exit_code=0, stdout="/usr/bin/systemctl", stderr=""),
                    Mock(exit_code=exit_code, stdout="", stderr=""),
                ]
                with patch.object(
                    self.reboot,
                    "_get_last_boot_time",
                    side_effect=[
                        self.boot_time,
                        self.boot_time + timedelta(minutes=3),
                    ],
                ) as boot_time, patch.object(
                    self.reboot, "_wait_ssh_session_stable"
                ) as stable, patch.object(
                    self.reboot, "_run_reboot_command"
                ) as fallback:
                    self.reboot.reboot()

                if exit_code in (0, -1):
                    fallback.assert_not_called()
                else:
                    fallback.assert_called_once_with()
                self.assertEqual(2, boot_time.call_count)
                stable.assert_called_once()
                self.node.execute.assert_any_call(
                    "command -v systemctl",
                    shell=True,
                    sudo=True,
                    timeout=10,
                    no_info_log=True,
                )

    def test_ssh_disconnect_does_not_skip_reboot_verification(self) -> None:
        self.date.current.return_value = self.boot_time + timedelta(minutes=2)
        for reachable in (True, False):
            with self.subTest(reachable=reachable):
                self.node.execute.side_effect = [
                    Mock(exit_code=0, stdout="/usr/bin/systemctl", stderr=""),
                    Mock(exit_code=-1, stdout="", stderr=""),
                ]
                boot_result = (
                    self.boot_time if reachable else OSError("SSH unavailable")
                )
                message = "may not perform reboot" if reachable else "may stuck"
                timer = Mock()
                timer.elapsed.return_value = 300
                with patch(
                    "lisa.tools.reboot.create_timer", return_value=timer
                ), patch.object(
                    self.reboot,
                    "_get_last_boot_time",
                    side_effect=[self.boot_time, boot_result],
                ), patch.object(
                    self.reboot, "_wait_ssh_session_stable"
                ) as stable, patch.object(
                    self.reboot, "_run_reboot_command"
                ) as fallback:
                    with self.assertRaisesRegex(LisaException, message):
                        self.reboot.reboot()

                fallback.assert_not_called()
                stable.assert_not_called()

    def test_missing_systemctl_uses_reboot_command(self) -> None:
        self.date.current.return_value = self.boot_time + timedelta(minutes=2)
        self.node.execute.return_value = Mock(exit_code=1)
        with patch.object(
            self.reboot,
            "_get_last_boot_time",
            side_effect=[self.boot_time, self.boot_time + timedelta(minutes=3)],
        ), patch.object(self.reboot, "_wait_ssh_session_stable"), patch.object(
            self.reboot, "_run_reboot_command"
        ) as fallback:
            self.reboot.reboot()

        fallback.assert_called_once_with()

    def test_reboot_command_lookup_is_bounded(self) -> None:
        for exit_code in (0, 1):
            with self.subTest(exit_code=exit_code):
                self.reboot._command = "/sbin/reboot"
                self.node.execute.reset_mock()
                self.node.execute.return_value = Mock(
                    exit_code=exit_code, stdout="/usr/sbin/reboot\n"
                )
                with patch.object(self.reboot, "run") as run:
                    self.reboot._run_reboot_command()

                self.node.execute.assert_called_once_with(
                    "command -v reboot",
                    shell=True,
                    sudo=True,
                    timeout=10,
                    no_info_log=True,
                )
                expected = "/usr/sbin/reboot" if exit_code == 0 else "/sbin/reboot"
                self.assertEqual(expected, self.reboot.command)
                run.assert_called_once_with(force_run=True, sudo=True, timeout=10)

    def test_slow_reboot_can_use_extended_timeout(self) -> None:
        self.date.current.return_value = self.boot_time + timedelta(minutes=2)
        for time_out in (300, 600):
            with self.subTest(time_out=time_out):
                timer = Mock()
                timer.elapsed.side_effect = [0, 400, 400]
                with patch(
                    "lisa.tools.reboot.create_timer", return_value=timer
                ), patch.object(
                    self.reboot,
                    "_get_last_boot_time",
                    side_effect=[
                        self.boot_time,
                        self.boot_time,
                        self.boot_time + timedelta(minutes=3),
                    ],
                ), patch.object(
                    self.reboot, "_wait_ssh_session_stable"
                ) as stable:
                    if time_out == 300:
                        with self.assertRaisesRegex(LisaException, "may not perform"):
                            self.reboot.reboot()
                        stable.assert_not_called()
                    else:
                        self.reboot.reboot(time_out=time_out)
                        stable.assert_called_once_with(200)
