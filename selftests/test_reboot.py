# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from datetime import datetime, timedelta
from typing import Optional
from unittest import TestCase
from unittest.mock import MagicMock, Mock, call, patch

from lisa.tools import Date, Reboot
from lisa.util import LisaException
from lisa.util.process import ExecutableResult


def _result(
    exit_code: Optional[int] = 0, stdout: str = "", stderr: str = ""
) -> ExecutableResult:
    return ExecutableResult(stdout, stderr, exit_code, "reboot", "test", 0)


class RebootTestCase(TestCase):
    def setUp(self) -> None:
        self.reboot = Reboot.__new__(Reboot)
        self.node = MagicMock()
        self.reboot.node = self.node
        self.reboot._log = MagicMock()
        self.reboot._command = "/sbin/reboot"
        self.date = MagicMock()
        self.node.tools = {Date: self.date}
        self.command_result = _result()
        self.node.execute.return_value = self.command_result
        self.boot_time = datetime(2026, 1, 1)
        self.date.current.return_value = self.boot_time + timedelta(minutes=2)
        self.elapsed = 0.0
        self.boot_times = Mock(
            side_effect=[self.boot_time, self.boot_time + timedelta(minutes=2)]
        )
        self.wait_stable = Mock()
        self.run_mock = Mock(return_value=_result())
        self.sleep_mock = Mock(side_effect=self._advance_time)
        for patcher in (
            patch.object(self.reboot, "_get_last_boot_time", self.boot_times),
            patch.object(self.reboot, "_wait_ssh_session_stable", self.wait_stable),
            patch.object(self.reboot, "run", self.run_mock),
            patch("lisa.tools.reboot.create_timer", side_effect=self._create_timer),
            patch("lisa.tools.reboot.sleep", self.sleep_mock),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _advance_time(self, seconds: float) -> None:
        self.elapsed += seconds

    def _create_timer(self) -> Mock:
        started = self.elapsed
        timer = Mock()
        timer.elapsed.side_effect = lambda *_: self.elapsed - started
        return timer

    def test_retries_inhibitor_refusal_until_normal_reboot_succeeds(self) -> None:
        self.node.execute.side_effect = [
            _result(stdout="/bin/systemctl"),
            _result(
                1, stderr="Call to Reboot failed: Interactive authentication required"
            ),
            _result(stdout="/sbin/reboot"),
            _result(),
        ]
        self.run_mock.return_value = _result(
            1, stderr='Operation inhibited by "RPM": Transaction running'
        )

        self.reboot.reboot()

        self.sleep_mock.assert_called_once_with(5)
        self.run_mock.assert_called_once_with(force_run=True, sudo=True, timeout=10)
        self.assertEqual(
            2,
            sum(
                item.args[0] == "systemctl reboot -i"
                for item in self.node.execute.call_args_list
            ),
        )
        self.wait_stable.assert_called_once_with(295)

    def test_persistent_inhibitor_respects_budget_and_reports_both_refusals(
        self,
    ) -> None:
        self.node.execute.side_effect = [
            _result(stdout="/bin/systemctl"),
            _result(1, stderr="Interactive authentication required"),
            _result(stdout="/sbin/reboot"),
            _result(1, stderr="Interactive authentication required"),
            _result(stdout="/sbin/reboot"),
        ]
        self.run_mock.return_value = _result(
            1,
            stdout='Operation inhibited by "RPM"',
            stderr="Transaction running",
        )

        with self.assertRaisesRegex(
            LisaException, "Timed out waiting for reboot inhibitors"
        ) as error:
            self.reboot.reboot(time_out=6)

        self.assertIn("Interactive authentication required", str(error.exception))
        self.assertIn('Operation inhibited by "RPM"', str(error.exception))
        self.assertIn("Transaction running", str(error.exception))
        self.assertIn("exit code 1", str(error.exception))
        self.sleep_mock.assert_has_calls([call(5), call(1)])
        self.assertEqual(6, self.elapsed)
        self.assertEqual(1, self.boot_times.call_count)
        self.wait_stable.assert_not_called()

    def test_non_inhibitor_failure_is_not_swallowed_or_retried(self) -> None:
        self.node.execute.side_effect = [
            _result(stdout="/bin/systemctl"),
            _result(1, stdout="systemctl denied", stderr="authentication failed"),
            _result(stdout="/sbin/reboot"),
        ]
        self.run_mock.return_value = _result(
            1, stdout="reboot denied", stderr="permission denied"
        )

        with self.assertRaisesRegex(LisaException, "Reboot request failed") as error:
            self.reboot.reboot()

        for diagnostic in (
            "systemctl denied",
            "authentication failed",
            "reboot denied",
            "permission denied",
        ):
            self.assertIn(diagnostic, str(error.exception))
        self.sleep_mock.assert_not_called()
        self.assertEqual(1, self.boot_times.call_count)

    def test_retries_fallback_without_systemctl(self) -> None:
        self.node.execute.side_effect = [
            _result(1),
            _result(stdout="/sbin/reboot"),
            _result(stdout="/sbin/reboot"),
        ]
        self.run_mock.side_effect = [
            _result(1, stdout="Please retry operation after closing inhibitors"),
            _result(),
        ]

        self.reboot.reboot()

        self.assertEqual(2, self.run_mock.call_count)
        self.sleep_mock.assert_called_once_with(5)
        self.wait_stable.assert_called_once_with(295)

    def test_ssh_disconnect_during_request_still_checks_boot_time(self) -> None:
        self.node.execute.side_effect = [
            _result(stdout="/bin/systemctl"),
            ConnectionResetError("SSH closed during reboot"),
        ]

        self.reboot.reboot()

        self.assertEqual(2, self.boot_times.call_count)
        self.wait_stable.assert_called_once()
        self.sleep_mock.assert_not_called()
        self.run_mock.assert_not_called()

    def test_missing_status_or_command_timeout_still_checks_boot_time(self) -> None:
        timed_out = _result(1)
        timed_out.is_timeout = True
        for result in (_result(None), _result(-1), timed_out):
            with self.subTest(result=result):
                self.boot_times.reset_mock()
                self.boot_times.side_effect = [
                    self.boot_time,
                    self.boot_time + timedelta(minutes=2),
                ]
                self.node.execute.side_effect = [
                    _result(stdout="/bin/systemctl"),
                    result,
                ]

                self.reboot.reboot()

                self.assertEqual(2, self.boot_times.call_count)
                self.run_mock.assert_not_called()

    def test_inhibitor_wait_uses_budget_remaining_after_uptime_wait(self) -> None:
        self.date.current.side_effect = [
            self.boot_time + timedelta(seconds=20),
            self.boot_time + timedelta(seconds=61),
        ]
        self.node.execute.side_effect = [
            _result(stdout="/bin/systemctl"),
            _result(1, stderr="Interactive authentication required"),
            _result(stdout="/sbin/reboot"),
        ]
        self.run_mock.return_value = _result(1, stderr="Operation inhibited by RPM")

        with self.assertRaisesRegex(LisaException, "waiting for reboot inhibitors"):
            self.reboot.reboot(time_out=43)

        self.assertEqual([call(41), call(2)], self.sleep_mock.call_args_list)
        self.assertEqual(43, self.elapsed)
        self.assertEqual(1, self.run_mock.call_count)
        self.assertEqual(1, self.boot_times.call_count)

    def test_accepted_request_with_unchanged_boot_time_retains_timeout(self) -> None:
        self.boot_times.side_effect = [self.boot_time, self.boot_time]

        with self.assertRaisesRegex(LisaException, "node may not perform reboot"):
            self.reboot.reboot(time_out=0)

        self.assertEqual(2, self.boot_times.call_count)
        self.sleep_mock.assert_not_called()

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

        def execute(*args: object, **kwargs: object) -> ExecutableResult:
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
