# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, cast
from unittest import TestCase
from unittest.mock import MagicMock

from assertpy import assert_that

from lisa.operating_system import Alpine
from lisa.tools.ethtool import DeviceCoalesceSettings, DeviceStatistics, Ethtool
from lisa.util import LisaException, UnsupportedDistroException


class EthtoolTestCase(TestCase):
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
