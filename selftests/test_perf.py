# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import MagicMock, Mock

from lisa.tools import Perf


class PerfTestCase(TestCase):
    def setUp(self) -> None:
        self.perf = Perf.__new__(Perf)
        self.perf.command_exists = MagicMock(return_value=(True, False))
        self.perf.run = MagicMock()

    def test_check_exists_rejects_nonzero_exit_code(self) -> None:
        self.perf.run.return_value = Mock(
            exit_code=2,
            stdout="WARNING: perf not found for kernel 6.14.0-1017-azure",
        )

        self.assertFalse(self.perf._check_exists())
        self.perf.run.assert_called_once_with(force_run=True)

    def test_check_exists_accepts_successful_perf(self) -> None:
        self.perf.run.return_value = Mock(exit_code=0, stdout="perf version 6.14")

        self.assertTrue(self.perf._check_exists())
        self.perf.run.assert_called_once_with(force_run=True)
