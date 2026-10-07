from typing import Any, cast
from unittest import TestCase
from unittest.mock import Mock, patch

from assertpy import assert_that

from lisa.executable import ExecutableResult
from lisa.microsoft.testsuites.network.sriov import Sriov
from lisa.tools.netshaper import NetShaperInfo
from lisa.util import LisaException


class SriovNetShaperTestCase(TestCase):
    def setUp(self) -> None:
        suite_type = cast(Any, Sriov).__wrapped__
        self.suite = suite_type.__new__(suite_type)
        self.node = Mock()
        self.log = Mock()
        self.net_shaper = Mock()
        self.net_shaper.get_shapers.return_value = []
        self.net_shaper.set_shaper.return_value = Mock(spec=ExecutableResult)
        self.net_shaper.delete_shaper.return_value = Mock(spec=ExecutableResult)

    def _verify_clamp(self) -> None:
        self.suite._verify_vf_netshaper_clamp(
            self.node,
            self.net_shaper,
            "eth1",
            self.log,
            "netdev",
            1,
            "bps",
            (100000000,),
        )

    def test_cleanup_verified_after_readback_failure(self) -> None:
        failure = LisaException("Readback failed; inspect shaper output.")
        with patch.object(
            self.suite, "_verify_netshaper_bandwidth", side_effect=failure
        ):
            with self.assertRaises(LisaException) as context:
                self._verify_clamp()
        assert_that(context.exception).is_same_as(failure)
        self.net_shaper.delete_shaper.assert_called_once_with("eth1", "netdev", 1)
        assert_that(self.net_shaper.get_shapers.call_count).is_equal_to(2)

    def test_remaining_cap_fails_cleanup_after_readback_failure(self) -> None:
        self.net_shaper.get_shapers.side_effect = [
            [],
            [NetShaperInfo(scope="netdev", id=1, raw="remaining cap")],
        ]
        with patch.object(
            self.suite,
            "_verify_netshaper_bandwidth",
            side_effect=LisaException("Readback failed; inspect shaper output."),
        ):
            with self.assertRaisesRegex(AssertionError, "after deletion"):
                self._verify_clamp()
        self.net_shaper.delete_shaper.assert_called_once_with("eth1", "netdev", 1)

    def test_cleanup_verified_after_successful_readback(self) -> None:
        with patch.object(self.suite, "_verify_netshaper_bandwidth"):
            self._verify_clamp()
        self.net_shaper.delete_shaper.assert_called_once_with("eth1", "netdev", 1)
        assert_that(self.net_shaper.get_shapers.call_count).is_equal_to(2)

    def test_node_marked_dirty_before_link_up_failure(self) -> None:
        ip = Mock()
        ip.is_device_up.return_value = False
        ip.up.side_effect = LisaException("Link-up failed; inspect interface state.")
        timeline = Mock()
        timeline.attach_mock(ip.node.mark_dirty, "mark_dirty")
        timeline.attach_mock(ip.up, "up")
        with self.assertRaises(LisaException):
            self.suite._require_device_up(ip, "eth1", self.log)
        assert_that([event[0] for event in timeline.mock_calls]).is_equal_to(
            ["mark_dirty", "up"]
        )

    def test_up_interface_does_not_mark_node_dirty(self) -> None:
        ip = Mock()
        ip.is_device_up.return_value = True
        self.suite._require_device_up(ip, "eth1", self.log)
        ip.up.assert_not_called()
        ip.node.mark_dirty.assert_not_called()
