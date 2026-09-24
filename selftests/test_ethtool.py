# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, cast
from unittest import TestCase
from unittest.mock import MagicMock

from assertpy import assert_that

from lisa.operating_system import Alpine
from lisa.tools.ethtool import (
    DeviceCoalesceSettings,
    DeviceRssIndirectionTable,
    DeviceStatistics,
    Ethtool,
)
from lisa.util import LisaException, UnsupportedDistroException
from lisa.util.process import ExecutableResult


class EthtoolTestCase(TestCase):
    def test_parse_rss_indirection_table(self) -> None:
        output = """RX flow hash indirection table for eth1 with 4 RX ring(s):
    0:      0     1     2     3
    4:      0     1     2     3
RSS hash key:
6d:5a:56:da
"""

        settings = DeviceRssIndirectionTable("eth1", output)

        assert_that(settings.rx_ring_count).is_equal_to(4)
        assert_that(settings.table).is_equal_to([0, 1, 2, 3, 0, 1, 2, 3])
        assert_that(settings.indirection_size).is_equal_to(8)

    def test_reject_missing_rss_indirection_table_row(self) -> None:
        output = """RX flow hash indirection table for eth1 with 4 RX ring(s):
    0:      0     1     2     3
    8:      0     1     2     3
"""

        with self.assertRaises(LisaException):
            DeviceRssIndirectionTable("eth1", output)

    def test_reject_missing_rss_indirection_table_entries(self) -> None:
        output = """RX flow hash indirection table for eth1 with 4 RX ring(s):
RSS hash key:
6d:5a:56:da
"""

        with self.assertRaises(LisaException):
            DeviceRssIndirectionTable("eth1", output)

    def test_rss_indirection_setter_quotes_and_invalidates_cache(self) -> None:
        ethtool = Ethtool.__new__(Ethtool)
        ethtool._device_settings_map = {}
        cached = DeviceRssIndirectionTable(
            "eth 1",
            """RX flow hash indirection table for eth1 with 1 RX ring(s):
    0:      0
""",
        )
        ethtool._get_or_create_device_setting(
            "eth 1"
        ).device_rss_indirection_table = cached
        result = ExecutableResult("", "", 0, "", "", 0)
        cast(Any, ethtool).run = MagicMock(return_value=result)

        actual = ethtool.set_device_rss_indirection_table("eth 1", "equal 2")

        assert_that(actual).is_same_as(result)
        cast(Any, ethtool).run.assert_called_once_with(
            "-X 'eth 1' equal 2", sudo=True, force_run=True, shell=True
        )
        assert_that(
            ethtool._get_or_create_device_setting("eth 1").device_rss_indirection_table
        ).is_none()

    def test_rss_indirection_setter_rejects_shell_syntax(self) -> None:
        ethtool = Ethtool.__new__(Ethtool)
        ethtool._device_settings_map = {}
        cast(Any, ethtool).run = MagicMock()

        with self.assertRaises(LisaException):
            ethtool.set_device_rss_indirection_table("eth1", "equal 2; reboot")

        cast(Any, ethtool).run.assert_not_called()

    def test_coalesce_setter_invalidates_cache(self) -> None:
        ethtool = Ethtool.__new__(Ethtool)
        ethtool._device_settings_map = {}
        device = ethtool._get_or_create_device_setting("eth1")
        device.device_coalesce_settings = DeviceCoalesceSettings(
            "eth1", "rx-cqe-frames: 1"
        )
        result = ExecutableResult("", "", 0, "", "", 0)
        cast(Any, ethtool).run = MagicMock(return_value=result)

        actual = ethtool.set_device_coalesce_setting("eth1", "rx-cqe-frames", 4)

        assert_that(actual).is_same_as(result)
        assert_that(device.device_coalesce_settings).is_none()

    def test_parse_coalesce_settings(self) -> None:
        output = """Coalesce parameters for eth1:
Adaptive RX: off  TX: off
rx-usecs: n/a
rx-frames: n/a
rx-cqe-frames: 4
tx-usecs: 0
"""

        settings = DeviceCoalesceSettings("eth1", output)

        assert_that(settings.settings).is_equal_to({"rx-cqe-frames": 4, "tx-usecs": 0})
        assert_that(settings.not_applicable).contains_only("rx-usecs", "rx-frames")

    def test_parse_all_not_applicable_coalesce_settings(self) -> None:
        output = """Coalesce parameters for eth1:
Adaptive RX: n/a  TX: n/a
rx-usecs: n/a
rx-frames: n/a
"""

        settings = DeviceCoalesceSettings("eth1", output)

        assert_that(settings.settings).is_empty()
        assert_that(settings.not_applicable).contains_only("rx-usecs", "rx-frames")

    def test_reject_unrecognized_coalesce_output(self) -> None:
        with self.assertRaises(LisaException):
            DeviceCoalesceSettings("eth1", "Coalesce parameters unavailable")

    def test_reject_unsupported_fallback_distro(self) -> None:
        ethtool = Ethtool.__new__(Ethtool)
        ethtool.node = cast(Any, MagicMock(os=MagicMock(spec=Alpine)))

        with self.assertRaises(UnsupportedDistroException):
            ethtool._install_rx_cqe_frames_ethtool()

    def test_statistics_delta_preserves_cached_absolute_values(self) -> None:
        raw_output = """NIC statistics:
     rx_0_packets: 15
     tx_0_packets: 28
"""
        statistics = DeviceStatistics("eth1", raw_output)
        ethtool = Ethtool.__new__(Ethtool)
        cast(Any, ethtool).get_device_statistics = MagicMock(return_value=statistics)
        ethtool._log = MagicMock()

        delta = ethtool.get_device_statistics_delta(
            "eth1", {"rx_0_packets": 10, "tx_0_packets": 20}
        )

        assert_that(delta).is_equal_to({"rx_0_packets": 5, "tx_0_packets": 8})
        assert_that(statistics.counters).described_as(
            "Calculating a delta must not replace cached absolute counters."
        ).is_equal_to({"rx_0_packets": 15, "tx_0_packets": 28})
        assert_that(statistics.raw_output).is_equal_to(raw_output)
