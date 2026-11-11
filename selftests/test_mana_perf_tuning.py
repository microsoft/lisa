# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Dict, List, Optional, Tuple
from unittest import TestCase
from unittest.mock import MagicMock, Mock, call, patch

from lisa.microsoft.testsuites.performance import common
from lisa.microsoft.testsuites.performance.common import (
    ManaVfPerfTuning,
    fall_back_to_mana_driver_defaults,
    restore_mana_vf_tuning,
    tune_mana_vf_for_perf,
)
from lisa.schema import NetworkDataPath
from lisa.tools import Dmesg, Ethtool, Ip, Kill, Lagscope, Lscpu, Ntttcp, Sysctl
from lisa.tools.ethtool import DeviceChannel, DeviceCoalesceSettings, DeviceStatistics
from lisa.util import LisaException, UnsupportedOperationException
from lisa.util.process import ExecutableResult

VF = "enP30832s1"


def _channels_output(current: int, maximum: int) -> str:
    return (
        f"Channel parameters for {VF}:\n"
        "Pre-set maximums:\n"
        "RX:\t\tn/a\nTX:\t\tn/a\nOther:\t\tn/a\n"
        f"Combined:\t{maximum}\n"
        "Current hardware settings:\n"
        "RX:\t\tn/a\nTX:\t\tn/a\nOther:\t\tn/a\n"
        f"Combined:\t{current}\n"
    )


def _coalesce_output(rx: str, tx: str) -> str:
    return (
        f"Coalesce parameters for {VF}:\n"
        f"Adaptive RX: {rx}  TX: {tx}\n"
        "stats-block-usecs:\tn/a\n"
        "sample-interval:\tn/a\n"
        "\n"
        "rx-usecs:\tn/a\n"
        "rx-frames:\tn/a\n"
        "\n"
        "tx-usecs:\tn/a\n"
        "tx-frames:\tn/a\n"
        "\n"
        "CQE mode RX: n/a  TX: n/a\n"
    )


class FakeManaEthtool:
    """A MANA VF with the 6.8.0-1070-azure defaults: 16 of 32 queues, DIM on."""

    def __init__(
        self,
        driver: str = "mana",
        current: int = 16,
        maximum: int = 32,
        adaptive_rx: Optional[str] = "on",
        adaptive_tx: Optional[str] = "on",
        throttle_stats: bool = True,
    ) -> None:
        self.driver = driver
        self.current = current
        self.maximum = maximum
        # None means the driver doesn't implement ethtool -c.
        self.adaptive: Dict[str, Optional[str]] = {"rx": adaptive_rx, "tx": adaptive_tx}
        # Drivers with "net: mana: Add support to process throttled EQEs".
        self.throttle_stats = throttle_stats
        self.calls: List[Any] = []

    def get_device_driver(self, interface: str) -> str:
        return f" {self.driver}"

    def get_device_statistics(
        self, interface: str, force_run: bool = False
    ) -> DeviceStatistics:
        lines = ["NIC statistics:", "     tx_0_packets: 10", "     rx_0_packets: 10"]
        if self.throttle_stats:
            lines += [f"     eq_{q}_throttle_events: 0" for q in range(self.current)]
        return DeviceStatistics(interface, "\n".join(lines))

    def get_device_channels_info(
        self, interface: str, force_run: bool = False
    ) -> DeviceChannel:
        return DeviceChannel(interface, _channels_output(self.current, self.maximum))

    def set_device_channels_info(self, interface: str, channel_count: int) -> None:
        self.calls.append(("channels", channel_count))
        self.current = channel_count

    def change_device_channels_info(
        self, interface: str, channel_count: int
    ) -> DeviceChannel:
        self.set_device_channels_info(interface, channel_count)
        return self.get_device_channels_info(interface, force_run=True)

    def get_device_coalesce_settings(
        self, interface: str, force_run: bool = False
    ) -> DeviceCoalesceSettings:
        if self.adaptive["rx"] is None:
            raise UnsupportedOperationException("ethtool -c not supported")
        return DeviceCoalesceSettings(
            interface,
            _coalesce_output(str(self.adaptive["rx"]), str(self.adaptive["tx"])),
        )

    def set_device_adaptive_coalesce(
        self,
        interface: str,
        adaptive_rx: Optional[bool] = None,
        adaptive_tx: Optional[bool] = None,
    ) -> DeviceCoalesceSettings:
        self.calls.append(("adaptive", adaptive_rx, adaptive_tx))
        for direction, value in (("rx", adaptive_rx), ("tx", adaptive_tx)):
            if value is not None:
                self.adaptive[direction] = "on" if value else "off"
        return self.get_device_coalesce_settings(interface, force_run=True)


TX_STALL = (
    "[ 1120.035535] mana 7870:00:00.0 ens1: NETDEV WATCHDOG: CPU: 32: transmit "
    "queue 28 timed out 15602 ms"
)
HWC_TIMEOUT = "[ 1313.570858] mana 7870:00:00.0: HWC: Request timed out: 60000 ms"


def _make_node(
    ethtool: FakeManaEthtool, thread_count: int = 192, dmesg: Optional[Mock] = None
) -> MagicMock:
    lscpu = Mock()
    lscpu.get_thread_count.return_value = thread_count
    ip = Mock()
    ip.is_device_up.return_value = True
    if dmesg is None:
        dmesg = Mock()
        dmesg.get_output.return_value = "[    1.0] Linux version 7.0.0-1017-azure"
    tools = {Lscpu: lscpu, Ethtool: ethtool, Ip: ip, Dmesg: dmesg}
    node = MagicMock()
    node.name = "node-0"
    node.is_connected = True
    node.tools.__getitem__.side_effect = lambda tool: tools[tool]
    return node


class DeviceCoalesceSettingsTestCase(TestCase):
    def test_parses_adaptive_state(self) -> None:
        for rx, tx, expected in (
            ("on", "on", (True, True)),
            ("off", "on", (False, True)),
            ("on", "n/a", (True, None)),
        ):
            with self.subTest(rx=rx, tx=tx):
                settings = DeviceCoalesceSettings(VF, _coalesce_output(rx, tx))
                self.assertEqual((settings.adaptive_rx, settings.adaptive_tx), expected)
                # CQE mode and Adaptive lines stay out of the integer settings.
                self.assertNotIn("CQE", " ".join(settings.not_applicable))
                self.assertIn("rx-usecs", settings.not_applicable)

    def test_adaptive_state_is_none_without_adaptive_line(self) -> None:
        settings = DeviceCoalesceSettings(VF, "rx-usecs: 8\ntx-usecs: 8\n")
        self.assertEqual(settings.settings, {"rx-usecs": 8, "tx-usecs": 8})
        self.assertIsNone(settings.adaptive_rx)
        self.assertIsNone(settings.adaptive_tx)

    def test_adaptive_only_output_is_accepted(self) -> None:
        settings = DeviceCoalesceSettings(VF, "Adaptive RX: off  TX: off\n")
        self.assertEqual((settings.adaptive_rx, settings.adaptive_tx), (False, False))

    def test_unrecognized_output_raises(self) -> None:
        with self.assertRaises(LisaException):
            DeviceCoalesceSettings(VF, "garbage")


class EthtoolAdaptiveCoalesceTestCase(TestCase):
    def _make_ethtool(self, exit_code: int = 0, stderr: str = "") -> Ethtool:
        ethtool = Ethtool.__new__(Ethtool)
        ethtool._device_settings_map = {}
        result = ExecutableResult("", stderr, exit_code, "ethtool -C", "1", 0.1)
        ethtool.run = Mock(return_value=result)  # type: ignore[method-assign]
        return ethtool

    def test_sends_only_requested_directions(self) -> None:
        for rx, tx, expected in (
            (False, False, f"-C {VF} adaptive-rx off adaptive-tx off"),
            (False, None, f"-C {VF} adaptive-rx off"),
            (None, True, f"-C {VF} adaptive-tx on"),
        ):
            with self.subTest(rx=rx, tx=tx):
                ethtool = self._make_ethtool()
                with patch.object(
                    ethtool, "get_device_coalesce_settings"
                ) as get_settings:
                    returned = ethtool.set_device_adaptive_coalesce(VF, rx, tx)
                ethtool.run.assert_called_once_with(  # type: ignore[attr-defined]
                    expected, sudo=True, force_run=True, shell=True
                )
                get_settings.assert_called_once_with(VF, force_run=True)
                self.assertIs(returned, get_settings.return_value)

    def test_requires_a_direction(self) -> None:
        ethtool = self._make_ethtool()
        with self.assertRaises(LisaException):
            ethtool.set_device_adaptive_coalesce(VF)
        ethtool.run.assert_not_called()  # type: ignore[attr-defined]

    def test_unsupported_driver_raises_unsupported(self) -> None:
        ethtool = self._make_ethtool(
            exit_code=1, stderr="netlink error: Operation not supported"
        )
        with self.assertRaises(UnsupportedOperationException):
            ethtool.set_device_adaptive_coalesce(VF, adaptive_rx=False)


class ManaVfPerfTuningTestCase(TestCase):
    def test_large_mana_vm_uses_max_queues_and_dim_off(self) -> None:
        ethtool = FakeManaEthtool()
        node = _make_node(ethtool)
        applied: List[ManaVfPerfTuning] = []

        tune_mana_vf_for_perf(node, VF, applied)

        # The pre-1070 defaults: all hardware queues, no interrupt moderation.
        self.assertEqual(ethtool.current, 32)
        self.assertEqual(ethtool.adaptive, {"rx": "off", "tx": "off"})
        self.assertEqual(ethtool.calls, [("channels", 32), ("adaptive", False, False)])
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0].original_channels, 16)
        self.assertTrue(applied[0].original_adaptive_rx)
        self.assertTrue(applied[0].original_adaptive_tx)

        restore_mana_vf_tuning(applied[0])

        self.assertEqual(ethtool.current, 16)
        self.assertEqual(ethtool.adaptive, {"rx": "on", "tx": "on"})
        node.mark_dirty.assert_not_called()

    def test_hardware_max_above_32_is_used(self) -> None:
        ethtool = FakeManaEthtool(maximum=64)
        tune_mana_vf_for_perf(_make_node(ethtool, thread_count=372), VF, [])
        self.assertEqual(ethtool.current, 64)

    def test_skips_vm_at_or_below_threshold(self) -> None:
        for thread_count in (16, 64):
            with self.subTest(thread_count=thread_count):
                ethtool = FakeManaEthtool()
                applied: List[ManaVfPerfTuning] = []
                tune_mana_vf_for_perf(
                    _make_node(ethtool, thread_count=thread_count), VF, applied
                )
                self.assertEqual(ethtool.calls, [])
                self.assertEqual(applied, [])

    def test_skips_non_mana_vf(self) -> None:
        ethtool = FakeManaEthtool(driver="mlx5_core")
        applied: List[ManaVfPerfTuning] = []
        tune_mana_vf_for_perf(_make_node(ethtool), VF, applied)
        self.assertEqual(ethtool.calls, [])
        self.assertEqual(applied, [])

    def test_kernel_without_dim_only_changes_queues(self) -> None:
        ethtool = FakeManaEthtool(adaptive_rx=None, adaptive_tx=None)
        node = _make_node(ethtool)
        applied: List[ManaVfPerfTuning] = []

        tune_mana_vf_for_perf(node, VF, applied)

        self.assertEqual(ethtool.calls, [("channels", 32)])
        self.assertIsNone(applied[0].original_adaptive_rx)
        self.assertIsNone(applied[0].original_adaptive_tx)

        restore_mana_vf_tuning(applied[0])
        self.assertEqual(ethtool.calls[-1], ("channels", 16))

    def test_already_tuned_vf_is_left_unchanged(self) -> None:
        # The 6.8.0-1064-azure defaults need no change and nothing to restore.
        ethtool = FakeManaEthtool(current=32, adaptive_rx="off", adaptive_tx="off")
        applied: List[ManaVfPerfTuning] = []

        tune_mana_vf_for_perf(_make_node(ethtool), VF, applied)
        restore_mana_vf_tuning(applied[0])

        self.assertEqual(ethtool.calls, [])

    def test_only_rx_adaptive_is_turned_off_when_tx_is_not_supported(self) -> None:
        ethtool = FakeManaEthtool(adaptive_tx="n/a")
        applied: List[ManaVfPerfTuning] = []

        tune_mana_vf_for_perf(_make_node(ethtool), VF, applied)
        self.assertIn(("adaptive", False, None), ethtool.calls)

        restore_mana_vf_tuning(applied[0])
        self.assertEqual(ethtool.calls[-1], ("adaptive", True, None))

    def test_failed_tuning_is_still_restored(self) -> None:
        ethtool = FakeManaEthtool()
        node = _make_node(ethtool)
        applied: List[ManaVfPerfTuning] = []

        # The driver accepts the request but keeps 16 queues.
        with patch.object(ethtool, "set_device_channels_info"):
            with self.assertRaises(AssertionError):
                tune_mana_vf_for_perf(node, VF, applied)

        self.assertEqual(applied[0].original_channels, 16)

    def test_restore_failure_marks_node_dirty(self) -> None:
        ethtool = FakeManaEthtool()
        node = _make_node(ethtool)
        applied: List[ManaVfPerfTuning] = []
        tune_mana_vf_for_perf(node, VF, applied)

        with patch.object(
            ethtool, "change_device_channels_info", side_effect=LisaException("x")
        ):
            restore_mana_vf_tuning(applied[0])

        node.mark_dirty.assert_called_once()

    def test_restore_skips_disconnected_node(self) -> None:
        ethtool = FakeManaEthtool()
        node = _make_node(ethtool)
        applied: List[ManaVfPerfTuning] = []
        tune_mana_vf_for_perf(node, VF, applied)
        calls_after_tuning = list(ethtool.calls)
        node.is_connected = False

        restore_mana_vf_tuning(applied[0])

        self.assertEqual(ethtool.calls, calls_after_tuning)
        node.mark_dirty.assert_called_once()

    def test_dim_kept_on_when_driver_drops_throttled_eqes(self) -> None:
        # 7.0.0-1017-azure: no eq_N_throttle_events, DIM off stalls TX queues.
        ethtool = FakeManaEthtool(throttle_stats=False)
        node = _make_node(ethtool, thread_count=372)
        applied: List[ManaVfPerfTuning] = []

        tune_mana_vf_for_perf(node, VF, applied)

        self.assertEqual(ethtool.current, 32)
        self.assertEqual(ethtool.adaptive, {"rx": "on", "tx": "on"})
        self.assertEqual(ethtool.calls, [("channels", 32)])
        self.assertIsNone(applied[0].original_adaptive_rx)
        self.assertIsNone(applied[0].original_adaptive_tx)

        restore_mana_vf_tuning(applied[0])
        self.assertEqual(ethtool.calls[-1], ("channels", 16))
        self.assertEqual(ethtool.adaptive, {"rx": "on", "tx": "on"})

    def test_fault_baseline_counts_existing_mana_faults(self) -> None:
        dmesg = Mock()
        dmesg.get_output.return_value = "\n".join(
            [TX_STALL, HWC_TIMEOUT, "[ 9.0] mana 7870:00:00.0: protocol version"]
        )
        applied: List[ManaVfPerfTuning] = []
        tune_mana_vf_for_perf(_make_node(FakeManaEthtool(), dmesg=dmesg), VF, applied)
        self.assertEqual(applied[0].fault_baseline, 2)


class ManaDriverDefaultsFallbackTestCase(TestCase):
    def _tune(self, dmesg: Mock) -> Tuple[FakeManaEthtool, MagicMock, List[Any]]:
        ethtool = FakeManaEthtool()
        node = _make_node(ethtool, dmesg=dmesg)
        applied: List[ManaVfPerfTuning] = []
        tune_mana_vf_for_perf(node, VF, applied)
        return ethtool, node, applied

    def test_no_new_fault_keeps_tuning(self) -> None:
        dmesg = Mock()
        dmesg.get_output.return_value = TX_STALL
        ethtool, _, applied = self._tune(dmesg)

        self.assertFalse(fall_back_to_mana_driver_defaults(applied))

        self.assertEqual(len(applied), 1)
        self.assertEqual(ethtool.current, 32)
        self.assertEqual(ethtool.adaptive, {"rx": "off", "tx": "off"})

    def test_new_fault_restores_driver_defaults(self) -> None:
        for fault in (TX_STALL, HWC_TIMEOUT):
            with self.subTest(fault=fault):
                dmesg = Mock()
                dmesg.get_output.return_value = ""
                ethtool, node, applied = self._tune(dmesg)
                dmesg.get_output.return_value = fault

                self.assertTrue(fall_back_to_mana_driver_defaults(applied))

                self.assertEqual(applied, [])
                self.assertEqual(ethtool.current, 16)
                self.assertEqual(ethtool.adaptive, {"rx": "on", "tx": "on"})
                node.log.warning.assert_called_once()
                node.mark_dirty.assert_not_called()

    def test_unchanged_vf_is_not_considered(self) -> None:
        dmesg = Mock()
        dmesg.get_output.return_value = ""
        ethtool = FakeManaEthtool(current=32, adaptive_rx="off", adaptive_tx="off")
        applied: List[ManaVfPerfTuning] = []
        tune_mana_vf_for_perf(_make_node(ethtool, dmesg=dmesg), VF, applied)
        dmesg.get_output.return_value = TX_STALL

        self.assertFalse(fall_back_to_mana_driver_defaults(applied))
        self.assertEqual(ethtool.calls, [])

    def test_unreadable_dmesg_keeps_tuning(self) -> None:
        dmesg = Mock()
        dmesg.get_output.return_value = ""
        ethtool, _, applied = self._tune(dmesg)
        dmesg.get_output.side_effect = LisaException("ssh is down")

        self.assertFalse(fall_back_to_mana_driver_defaults(applied))
        self.assertEqual(len(applied), 1)


class PerfNtttcpManaTuningTestCase(TestCase):
    class _StopAfterTuning(Exception):
        pass

    def _make_perf_node(self, name: str, vf: str, events: List[str]) -> MagicMock:
        node = MagicMock()
        node.name = name
        node.os = MagicMock()
        node.capability.network_interface.data_path = NetworkDataPath.Sriov
        node.nics.get_primary_nic.return_value.pci_device_name = vf
        tools: Dict[Any, Any] = {}

        def record_setup(*args: Any, **kwargs: Any) -> None:
            events.append(f"setup {name}")

        def record_set_busy_poll(value: str = "50") -> None:
            self.busy_poll_events.append(f"set {name} {value}")

        def record_restore_busy_poll() -> None:
            self.busy_poll_events.append(f"restore {name}")

        def get_tool(tool: Any) -> Any:
            if tool not in tools:
                tools[tool] = MagicMock()
                if tool is Ntttcp:
                    tools[tool].setup_system.side_effect = record_setup
                if tool is Lagscope:
                    tools[tool].set_busy_poll.side_effect = record_set_busy_poll
                    tools[tool].restore_busy_poll.side_effect = record_restore_busy_poll
                if tool is Lscpu:
                    # The first command after the tuning, stop the run there.
                    tools[tool].get_thread_count.side_effect = self._StopAfterTuning()
            return tools[tool]

        node.tools.__getitem__.side_effect = get_tool
        return node

    def _run(self, **perf_ntttcp_kwargs: Any) -> List[str]:
        events: List[str] = []
        self.busy_poll_events: List[str] = []
        client = self._make_perf_node("client", "enP1s1", events)
        server = self._make_perf_node("server", "enP2s2", events)

        def fake_tune(
            node: Any, interface: str, applied: List[ManaVfPerfTuning]
        ) -> None:
            events.append(f"tune {node.name} {interface}")
            applied.append(ManaVfPerfTuning(node=node, interface=interface))

        def fake_restore(tuning: ManaVfPerfTuning) -> None:
            events.append(f"restore {tuning.node.name} {tuning.interface}")

        with (
            patch.object(common, "tune_mana_vf_for_perf", side_effect=fake_tune),
            patch.object(common, "restore_mana_vf_tuning", side_effect=fake_restore),
        ):
            with self.assertRaises(self._StopAfterTuning):
                common.perf_ntttcp(
                    MagicMock(),
                    server=server,
                    client=client,
                    connections=[1],
                    test_case_name="perf_tcp_ntttcp_sriov",
                    **perf_ntttcp_kwargs,
                )
        return events

    def test_tunes_both_vfs_after_setup_and_restores_on_failure(self) -> None:
        self.assertEqual(
            self._run(tune_mana_vf=True),
            [
                "setup client",
                "setup server",
                "tune client enP1s1",
                "tune server enP2s2",
                "restore client enP1s1",
                "restore server enP2s2",
            ],
        )

    def test_no_tuning_by_default(self) -> None:
        self.assertEqual(
            self._run(tune_mana_vf=False), ["setup client", "setup server"]
        )

    def test_busy_poll_value_is_set_and_restored_on_both_nodes(self) -> None:
        for udp_mode in (False, True):
            for kwargs, value in (({}, "50"), ({"busy_poll_value": "0"}, "0")):
                with self.subTest(udp_mode=udp_mode, value=value):
                    self._run(udp_mode=udp_mode, **kwargs)
                    self.assertEqual(
                        self.busy_poll_events,
                        [
                            f"set client {value}",
                            f"set server {value}",
                            "restore client",
                            "restore server",
                        ],
                    )


class PerfNtttcpRetryFallbackTestCase(TestCase):
    def _make_node(self, name: str, vf: str) -> MagicMock:
        node = MagicMock()
        node.name = name
        node.os = MagicMock()
        node.capability.network_interface.data_path = NetworkDataPath.Sriov
        node.nics.get_primary_nic.return_value.pci_device_name = vf
        tools: Dict[Any, Any] = {}

        def get_tool(tool: Any) -> Any:
            if tool not in tools:
                tools[tool] = MagicMock()
                if tool is Lscpu:
                    tools[tool].get_thread_count.return_value = 8
            return tools[tool]

        node.tools.__getitem__.side_effect = get_tool
        return node

    def _run(self, tune_mana_vf: bool) -> Tuple[List[str], List[Any], MagicMock]:
        events: List[str] = []
        client = self._make_node("client", "enP1s1")
        server = self._make_node("server", "enP2s2")
        # The first attempt hangs like a MANA TX stall, the retry passes.
        client_ntttcp = client.tools[Ntttcp]
        client_ntttcp.run_as_client.side_effect = [LisaException("hang"), MagicMock()]

        def fake_tune(
            node: Any, interface: str, applied: List[ManaVfPerfTuning]
        ) -> None:
            events.append(f"tune {node.name}")
            applied.append(ManaVfPerfTuning(node=node, interface=interface))

        def fake_fallback(tunings: List[ManaVfPerfTuning]) -> bool:
            events.append(f"fallback {len(tunings)}")
            tunings.clear()
            return True

        def fake_restore(tuning: ManaVfPerfTuning) -> None:
            events.append(f"restore {tuning.node.name}")

        with (
            patch.object(common, "tune_mana_vf_for_perf", side_effect=fake_tune),
            patch.object(
                common, "fall_back_to_mana_driver_defaults", side_effect=fake_fallback
            ),
            patch.object(common, "restore_mana_vf_tuning", side_effect=fake_restore),
            patch.object(common, "notifier"),
            patch.object(common.time, "sleep"),
        ):
            messages = common.perf_ntttcp(
                MagicMock(),
                server=server,
                client=client,
                connections=[1],
                test_case_name="perf_tcp_ntttcp_sriov",
                tune_mana_vf=tune_mana_vf,
            )
        # The failed attempt cleaned up ntttcp and lagscope before retrying.
        self.assertGreaterEqual(client.tools[Kill].by_name.call_count, 2)
        return events, messages, client_ntttcp

    def test_failed_attempt_falls_back_before_retrying(self) -> None:
        events, messages, client_ntttcp = self._run(tune_mana_vf=True)

        # Fallback cleared the tunings, so the finally block restores nothing.
        self.assertEqual(events, ["tune client", "tune server", "fallback 2"])
        self.assertEqual(client_ntttcp.run_as_client.call_count, 2)
        self.assertEqual(len(messages), 1)

    def test_no_fallback_without_tuning(self) -> None:
        events, messages, client_ntttcp = self._run(tune_mana_vf=False)

        self.assertEqual(events, [])
        self.assertEqual(client_ntttcp.run_as_client.call_count, 2)
        self.assertEqual(len(messages), 1)


class LagscopeBusyPollTestCase(TestCase):
    def _make_lagscope(self) -> Tuple[Lagscope, Mock]:
        sysctl = Mock()
        tools = {Sysctl: sysctl}
        lagscope = Lagscope.__new__(Lagscope)
        lagscope.node = MagicMock()
        lagscope.node.tools.__getitem__.side_effect = lambda tool: tools[tool]
        return lagscope, sysctl

    def test_default_value_is_unchanged(self) -> None:
        lagscope, sysctl = self._make_lagscope()
        lagscope.set_busy_poll()
        sysctl.write.assert_has_calls(
            [call("net.core.busy_poll", "50"), call("net.core.busy_read", "50")]
        )

    def test_busy_poll_and_busy_read_can_be_disabled(self) -> None:
        lagscope, sysctl = self._make_lagscope()
        lagscope.set_busy_poll("0")
        sysctl.write.assert_has_calls(
            [call("net.core.busy_poll", "0"), call("net.core.busy_read", "0")]
        )
        self.assertEqual(sysctl.write.call_count, 2)
