# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import MagicMock, call

from lisa.operating_system import BSD
from lisa.tools.sysctl import Sysctl


class SysctlTestCase(TestCase):
    def test_write_saves_original_value(self) -> None:
        sysctl = Sysctl.__new__(Sysctl)
        sysctl._polling_enabled = False
        sysctl._original_values = {}
        sysctl._set = MagicMock()
        sysctl.get = MagicMock(return_value="0")

        # First write queries initial value and caches it
        sysctl.write("net.core.busy_poll", "50")
        self.assertEqual(sysctl._original_values, {"net.core.busy_poll": "0"})
        sysctl.get.assert_called_once_with("net.core.busy_poll", force_run=True)
        sysctl._set.assert_called_once_with("net.core.busy_poll", "50")

        # Second write does not re-query initial value
        sysctl.get.reset_mock()
        sysctl._set.reset_mock()
        sysctl.write("net.core.busy_poll", "100")
        self.assertEqual(sysctl._original_values, {"net.core.busy_poll": "0"})
        sysctl.get.assert_not_called()
        sysctl._set.assert_called_once_with("net.core.busy_poll", "100")

    def test_reset_restores_original_values_and_clears_cache(self) -> None:
        sysctl = Sysctl.__new__(Sysctl)
        sysctl._polling_enabled = False
        sysctl._original_values = {
            "net.core.busy_poll": "0",
            "net.core.busy_read": "10",
        }
        sysctl._set = MagicMock()
        sysctl.get = MagicMock()

        sysctl.reset()

        # Cache must be completely empty after reset
        self.assertEqual(sysctl._original_values, {})
        # get should never be called during reset
        sysctl.get.assert_not_called()
        self.assertEqual(sysctl._set.call_count, 2)
        sysctl._set.assert_has_calls(
            [
                call("net.core.busy_poll", "0"),
                call("net.core.busy_read", "10"),
            ],
            any_order=True,
        )

    def test_reset_idempotent(self) -> None:
        sysctl = Sysctl.__new__(Sysctl)
        sysctl._polling_enabled = False
        sysctl._original_values = {"net.core.busy_poll": "0"}
        sysctl._set = MagicMock()
        sysctl.get = MagicMock()

        sysctl.reset()
        self.assertEqual(sysctl._original_values, {})
        self.assertEqual(sysctl._set.call_count, 1)

        # Subsequent reset call should do nothing
        sysctl.reset()
        self.assertEqual(sysctl._original_values, {})
        self.assertEqual(sysctl._set.call_count, 1)
        sysctl.get.assert_not_called()

    def test_reset_bsd_polling(self) -> None:
        sysctl = Sysctl.__new__(Sysctl)
        sysctl.node = MagicMock()
        sysctl.node.os = BSD.__new__(BSD)
        sysctl._polling_enabled = True
        sysctl._original_values = {}
        sysctl._set = MagicMock()

        sysctl.reset()

        self.assertFalse(sysctl._polling_enabled)
        sysctl.node.execute.assert_called_once_with(
            "for i in `ifconfig -l` ; do ifconfig $i -polling; done",
            sudo=True,
            shell=True,
        )
