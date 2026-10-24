# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from datetime import datetime, timedelta, timezone
from typing import Any, Optional, cast
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.microsoft.testsuites.core.timesync import TimeSync
from lisa.node import Node
from lisa.tools.chrony import Chrony
from lisa.tools.date import Date
from lisa.util import LisaException


class TimeDriftTestCase(TestCase):
    def setUp(self) -> None:
        suite_class = cast(Any, TimeSync).__wrapped__
        self.suite = object.__new__(suite_class)
        self.node = MagicMock(spec=Node)
        self.node.tools = MagicMock()
        self.log = MagicMock()
        self.chrony = MagicMock(spec=Chrony)
        self.date = MagicMock(spec=Date)
        self.node.tools.__getitem__.side_effect = {
            Chrony: self.chrony,
            Date: self.date,
        }.__getitem__
        self.initial_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.current_time = self.initial_time
        self.reads = 0
        self.recover = False
        self.fail_read_number: Optional[int] = None
        self.date.current.side_effect = self._read_time
        self.date.set.side_effect = self._set_time
        self.restored_time = self.initial_time + timedelta(seconds=61)

        sleep_patch = patch(
            "lisa.microsoft.testsuites.core.timesync.time.sleep",
            return_value=None,
        )
        sleep_patch.start()
        self.addCleanup(sleep_patch.stop)
        timer = MagicMock()
        timer.elapsed.return_value = 60
        timer_patch = patch(
            "lisa.microsoft.testsuites.core.timesync.create_timer",
            return_value=timer,
        )
        timer_patch.start()
        self.addCleanup(timer_patch.stop)

    def _read_time(self) -> datetime:
        self.reads += 1
        if self.reads == self.fail_read_number:
            raise LisaException("clock read failed")
        self.current_time += timedelta(seconds=1)
        if self.recover and self.current_time < self.initial_time:
            self.current_time = self.initial_time + timedelta(seconds=self.reads)
        return self.current_time

    def _set_time(self, value: datetime) -> None:
        self.current_time = value

    def test_uncorrected_drift_fails_and_restores_clock(self) -> None:
        with self.assertRaisesRegex(AssertionError, "Time drift is not corrected"):
            self.suite.verify_timedrift_corrected(node=self.node, log=self.log)

        self.assertEqual(self.current_time, self.restored_time)

    def test_corrected_drift_passes_and_restores_clock(self) -> None:
        self.recover = True

        self.suite.verify_timedrift_corrected(node=self.node, log=self.log)

        self.assertEqual(self.current_time, self.restored_time)

    def test_each_time_jump_requests_measurements_before_waiting(self) -> None:
        def set_time_with_delayed_poll(value: datetime) -> None:
            self._set_time(value)
            if value < self.initial_time:
                self.recover = False

        def receive_measurements() -> None:
            self.recover = True

        self.date.set.side_effect = set_time_with_delayed_poll
        self.chrony.burst = MagicMock(side_effect=receive_measurements)

        self.suite.verify_timedrift_corrected(node=self.node, log=self.log)

        self.assertEqual(self.chrony.burst.call_count, 3)
        self.assertEqual(self.current_time, self.restored_time)

    def test_measurement_failure_propagates_after_clock_restoration(self) -> None:
        self.recover = True
        self.chrony.burst = MagicMock(side_effect=LisaException("burst failed"))

        with self.assertRaisesRegex(LisaException, "burst failed"):
            self.suite.verify_timedrift_corrected(node=self.node, log=self.log)

        self.assertEqual(self.current_time, self.restored_time)

    def test_poll_error_propagates_after_clock_restoration(self) -> None:
        self.fail_read_number = 3

        with self.assertRaisesRegex(LisaException, "clock read failed"):
            self.suite.verify_timedrift_corrected(node=self.node, log=self.log)

        self.assertEqual(self.current_time, self.restored_time)

    def test_unsynchronized_chrony_fails_without_changing_clock(self) -> None:
        self.chrony.check_tracking.side_effect = LisaException("not synchronized")

        with self.assertRaisesRegex(LisaException, "not synchronized"):
            self.suite.verify_timedrift_corrected(node=self.node, log=self.log)

        self.date.set.assert_not_called()
