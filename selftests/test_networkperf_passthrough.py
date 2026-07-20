# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import TestCase
from unittest.mock import MagicMock, call, patch

from microsoft.testsuites.performance.common import (
    _set_iperf_udp_max_sessions,
    get_nic_datapath,
)
from microsoft.testsuites.performance.networkperf_passthrough import (
    NetworkPerformance,
    _filter_throughput_profile,
    _get_median_throughput_by_profile,
    _select_best_throughput_profile,
)

from lisa.features import StartStop
from lisa.messages import NetworkTCPPerformanceMessage, TransportProtocol
from lisa.tools import Dhclient
from lisa.util import LisaException, SkippedException


class NetworkPerformancePassthroughTestCase(TestCase):
    _suite_type = cast(Any, NetworkPerformance).__wrapped__

    def test_missing_nic_datapath_returns_empty(self) -> None:
        node = MagicMock()
        node.capability.network_interface = None

        self.assertEqual("", get_nic_datapath(node))

    def test_udp_session_tuning_skips_local_node(self) -> None:
        node = MagicMock()
        node.is_remote = False
        node.tools.__getitem__.side_effect = AssertionError(
            "local endpoint should not access the SSH tool"
        )

        _set_iperf_udp_max_sessions([node])

        node.tools.__getitem__.assert_not_called()

    def test_median_throughput_keeps_profiles_matched(self) -> None:
        runs = [
            [
                self._create_tcp_message(1, 65536, throughput),
                self._create_tcp_message(4, 65536, throughput * 2),
            ]
            for throughput in [Decimal("9"), Decimal("11"), Decimal("10")]
        ]

        medians = _get_median_throughput_by_profile(runs)

        single_connection = next(
            value for profile, value in medians.items() if profile[2] == 1
        )
        four_connections = next(
            value for profile, value in medians.items() if profile[2] == 4
        )
        self.assertEqual(Decimal("10"), single_connection[0])
        self.assertEqual(Decimal("20"), four_connections[0])

    def test_median_throughput_distinguishes_buffer_sizes(self) -> None:
        runs = [
            [
                self._create_tcp_message(1, 32768, Decimal("8")),
                self._create_tcp_message(1, 65536, Decimal("10")),
            ]
            for _ in range(3)
        ]

        medians = _get_median_throughput_by_profile(runs)

        self.assertEqual(2, len(medians))

    def test_median_throughput_rejects_incomplete_sweep(self) -> None:
        runs = [
            [self._create_tcp_message(1, 65536, Decimal("10"))],
            [self._create_tcp_message(1, 65536, Decimal("11"))],
            [],
        ]

        with self.assertRaisesRegex(
            LisaException, r"reported \[2\] samples across \[3\] runs"
        ):
            _get_median_throughput_by_profile(runs)

    def test_tuning_sweep_selects_and_filters_best_profile(self) -> None:
        messages = [
            self._create_tcp_message(1, 65536, Decimal("10")),
            self._create_tcp_message(4, 65536, Decimal("18")),
        ]

        profile = _select_best_throughput_profile(messages)
        matching = _filter_throughput_profile(messages, profile)

        self.assertEqual(4, profile[2])
        self.assertEqual([messages[1]], matching)

    def test_tuning_sweep_rejects_zero_throughput(self) -> None:
        messages = [self._create_tcp_message(1, 65536, Decimal("0"))]

        with self.assertRaisesRegex(
            LisaException, "did not report any delivered Gbps samples"
        ):
            _select_best_throughput_profile(messages)

    def test_passthrough_peer_requires_peer_ip(self) -> None:
        suite = self._suite_type.__new__(self._suite_type)

        with self.assertRaisesRegex(SkippedException, "passthrough_peer_ip"):
            suite._get_passthrough_peer(
                {
                    "passthrough_peer_username": "lisa",
                    "passthrough_peer_private_key_file": "id_rsa",
                }
            )

    def test_passthrough_peer_uses_peer_ip_for_benchmark_traffic(self) -> None:
        suite = self._suite_type.__new__(self._suite_type)
        suite._baremetal_hosts = []
        peer = MagicMock()
        peer.os = MagicMock()

        with patch(
            "microsoft.testsuites.performance.networkperf_passthrough.RemoteNode",
            return_value=peer,
        ):
            result = suite._get_passthrough_peer(
                {
                    "passthrough_peer_ip": "192.0.2.10",
                    "passthrough_peer_username": "lisa",
                    "passthrough_peer_private_key_file": "id_rsa",
                }
            )

        self.assertIs(peer, result)
        self.assertEqual("192.0.2.10", peer.internal_address)
        peer.set_connection_info.assert_called_once_with(
            address="192.0.2.10",
            public_address="192.0.2.10",
            public_port=22,
            username="lisa",
            password="",
            private_key_file="id_rsa",
        )

    def test_physical_pci_nic_accepts_pf_without_sriov_controls(self) -> None:
        suite = self._suite_type.__new__(self._suite_type)
        node = MagicMock()
        node.name = "peer"
        node.execute.return_value.stdout = """\
device_path=/sys/devices/pci0000:00/0000:00:01.0/0000:01:00.0
subsystem=pci
bdf=0000:01:00.0
pci_class=0x020000
driver=i40e
is_vf=false
sriov_totalvfs=unavailable
sriov_numvfs=unavailable
"""

        suite._validate_physical_pci_nic(node, "enp1s0f0", "remote peer")

        self.assertEqual(2, node.log.info.call_count)
        self.assertIn("BDF [0000:01:00.0]", node.log.info.call_args_list[0].args[0])
        self.assertIn(
            "sriov_totalvfs [unavailable]", node.log.info.call_args_list[1].args[0]
        )

    def test_physical_pci_nic_accepts_pf_with_zero_total_vfs(self) -> None:
        suite = self._suite_type.__new__(self._suite_type)
        node = MagicMock()
        node.name = "peer"
        node.execute.return_value.stdout = """\
device_path=/sys/devices/pci0000:00/0000:00:01.0/0000:01:00.0
subsystem=pci
bdf=0000:01:00.0
pci_class=0x020000
driver=i40e
is_vf=false
sriov_totalvfs=0
sriov_numvfs=0
"""

        suite._validate_physical_pci_nic(node, "enp1s0f0", "remote peer")

        self.assertIn(
            "sriov_totalvfs [0], sriov_numvfs [0]",
            node.log.info.call_args_list[1].args[0],
        )

    def test_physical_pci_nic_rejects_virtual_nic(self) -> None:
        suite = self._suite_type.__new__(self._suite_type)
        node = MagicMock()
        node.name = "peer"
        node.execute.return_value.stdout = """\
device_path=/sys/devices/virtual/net/eth0
subsystem=virtual
bdf=eth0
pci_class=
driver=hv_netvsc
is_vf=false
sriov_totalvfs=unavailable
sriov_numvfs=unavailable
"""

        with self.assertRaisesRegex(
            SkippedException, "not a physical PCI network function"
        ):
            suite._validate_physical_pci_nic(node, "eth0", "remote peer")

    def test_physical_pci_nic_rejects_virtual_function(self) -> None:
        suite = self._suite_type.__new__(self._suite_type)
        node = MagicMock()
        node.name = "peer"
        node.execute.return_value.stdout = """\
device_path=/sys/devices/pci0000:00/0000:00:01.0/0000:01:00.1
subsystem=pci
bdf=0000:01:00.1
pci_class=0x020000
driver=iavf
is_vf=true
sriov_totalvfs=unavailable
sriov_numvfs=unavailable
"""

        with self.assertRaisesRegex(SkippedException, "SR-IOV virtual function"):
            suite._validate_physical_pci_nic(node, "enp1s0f1", "remote peer")

    def test_dhclient_cleanup_does_not_self_match(self) -> None:
        suite = self._suite_type.__new__(self._suite_type)
        node = MagicMock()

        suite._stop_dhcp_on_iface(node, "eth1", "dhclient")

        commands = [item.args[0] for item in node.execute.call_args_list]
        self.assertEqual(3, len(commands))
        self.assertIn("dhclient -r", commands[0])
        self.assertNotIn("pkill", commands[0])
        self.assertIn("dhclient-eth1.pid", commands[1])
        self.assertNotIn("pkill", commands[1])
        self.assertEqual(
            "pkill -f '[d]hclient.*[[:space:]]eth1([[:space:]]|$)' "
            "2>/dev/null || true",
            commands[2],
        )

    def test_dhcpcd_cleanup_releases_only_target_interface(self) -> None:
        suite = self._suite_type.__new__(self._suite_type)
        node = MagicMock()

        suite._stop_dhcp_on_iface(node, "eth1", "dhcpcd")

        node.execute.assert_called_once_with(
            "dhcpcd -k eth1 2>/dev/null || true",
            sudo=True,
            shell=True,
        )

    def test_dhcp_supports_dhcpcd(self) -> None:
        suite = self._suite_type.__new__(self._suite_type)
        suite._install_dhclient_scripts = MagicMock()
        suite._stop_dhcp_on_iface = MagicMock()
        node = MagicMock()
        node.tools = {Dhclient: SimpleNamespace(command="dhcpcd")}
        dhcp_result = MagicMock(exit_code=0, stdout="configured")

        def execute(command: str, *_: Any, **__: Any) -> Any:
            result = MagicMock(exit_code=0, stdout="")
            if "dhcpcd -4 -1 -d eth1" in command:
                return dhcp_result
            return result

        node.execute.side_effect = execute

        result = suite._run_dhcp_on_iface(node, "eth1")

        self.assertIs(dhcp_result, result)
        suite._install_dhclient_scripts.assert_not_called()
        suite._stop_dhcp_on_iface.assert_called_once_with(node, "eth1", "dhcpcd")
        self.assertTrue(
            any(
                "timeout -k 2s 30s dhcpcd -4 -1 -d eth1" in item.args[0]
                for item in node.execute.call_args_list
            )
        )

    def test_dhcp_preserves_dhclient_config_hook(self) -> None:
        suite = self._suite_type.__new__(self._suite_type)
        suite._install_dhclient_scripts = MagicMock()
        suite._stop_dhcp_on_iface = MagicMock()
        node = MagicMock()
        node.tools = {Dhclient: SimpleNamespace(command="dhclient")}
        dhcp_result = MagicMock(exit_code=0, stdout="configured")

        def execute(command: str, *_: Any, **__: Any) -> Any:
            result = MagicMock(exit_code=0, stdout="")
            if "dhclient -v -1 -4 -sf" in command:
                return dhcp_result
            return result

        node.execute.side_effect = execute

        result = suite._run_dhcp_on_iface(node, "eth1")

        self.assertIs(dhcp_result, result)
        suite._install_dhclient_scripts.assert_called_once_with(
            node, "/usr/local/bin/lisa-dhclient-config"
        )
        suite._stop_dhcp_on_iface.assert_called_once_with(node, "eth1", "dhclient")
        self.assertTrue(
            any(
                "aa-exec -p unconfined -- dhclient -v -1 -4 -sf" in item.args[0]
                for item in node.execute.call_args_list
            )
        )

    def test_baseline_failure_restarts_guest_and_restores_host_address(self) -> None:
        suite = self._suite_type.__new__(self._suite_type)
        start_stop = MagicMock()
        guest = MagicMock()
        guest.features = {StartStop: start_stop}
        peer = MagicMock()
        host = MagicMock()
        host.internal_address = "management-address"

        suite._get_passthrough_peer = MagicMock(return_value=peer)
        suite._get_linux_passthrough_host = MagicMock(return_value=host)
        suite._get_host_nic_name = MagicMock(return_value="peer-data-nic")
        suite._validate_physical_pci_nic = MagicMock()

        def configure_host_nic(*_: Any) -> Any:
            host.internal_address = "host-data-address"
            return host, "host-data-nic"

        suite._configure_passthrough_nic_for_host = MagicMock(
            side_effect=configure_host_nic
        )
        suite._collect_host_baseline_runs = MagicMock(
            side_effect=LisaException("baseline collection failed")
        )
        suite._release_passthrough_host_dhcp = MagicMock()
        suite._wait_for_guest_start = MagicMock()

        with self.assertRaisesRegex(LisaException, "baseline collection failed"):
            suite._run_measured_passthrough_benchmark(
                node=guest,
                test_result=MagicMock(),
                log_path=Path("."),
                variables={},
                benchmark=MagicMock(),
            )

        start_stop.stop.assert_called_once_with()
        suite._validate_physical_pci_nic.assert_has_calls(
            [
                call(peer, "peer-data-nic", "remote peer"),
                call(host, "host-data-nic", "immediate virtualization host"),
            ]
        )
        suite._release_passthrough_host_dhcp.assert_called_once_with(
            host, "host-data-nic"
        )
        start_stop.start.assert_called_once_with()
        suite._wait_for_guest_start.assert_called_once_with(guest)
        self.assertEqual("management-address", host.internal_address)

    def test_baseline_failure_removes_temporary_local_host_address(self) -> None:
        suite = self._suite_type.__new__(self._suite_type)
        start_stop = MagicMock()
        guest = MagicMock()
        guest.features = {StartStop: start_stop}
        host = SimpleNamespace()

        suite._get_passthrough_peer = MagicMock(return_value=MagicMock())
        suite._get_linux_passthrough_host = MagicMock(return_value=host)
        suite._get_host_nic_name = MagicMock(return_value="peer-data-nic")
        suite._validate_physical_pci_nic = MagicMock()

        def configure_host_nic(*_: Any) -> Any:
            host.internal_address = "host-data-address"
            return host, "host-data-nic"

        suite._configure_passthrough_nic_for_host = MagicMock(
            side_effect=configure_host_nic
        )
        suite._collect_host_baseline_runs = MagicMock(
            side_effect=LisaException("baseline collection failed")
        )
        suite._release_passthrough_host_dhcp = MagicMock()
        suite._wait_for_guest_start = MagicMock()

        with self.assertRaisesRegex(LisaException, "baseline collection failed"):
            suite._run_measured_passthrough_benchmark(
                node=guest,
                test_result=MagicMock(),
                log_path=Path("."),
                variables={},
                benchmark=MagicMock(),
            )

        suite._release_passthrough_host_dhcp.assert_called_once_with(
            host, "host-data-nic"
        )
        start_stop.start.assert_called_once_with()
        suite._wait_for_guest_start.assert_called_once_with(guest)
        self.assertFalse(hasattr(host, "internal_address"))

    def test_passthrough_baseline_accepts_exactly_95_percent(self) -> None:
        summary = self._assert_baseline(
            baseline_gbps=Decimal("10"), guest_gbps=Decimal("9.5")
        )

        self.assertIn("95.00%", summary)

    def test_passthrough_baseline_rejects_below_95_percent(self) -> None:
        with self.assertRaisesRegex(AssertionError, "must be at least 95%"):
            self._assert_baseline(
                baseline_gbps=Decimal("10"), guest_gbps=Decimal("9.49")
            )

    def _assert_baseline(self, baseline_gbps: Decimal, guest_gbps: Decimal) -> str:
        suite = self._suite_type.__new__(self._suite_type)
        baseline_runs = [
            [self._create_tcp_message(1, 65536, baseline_gbps)] for _ in range(3)
        ]
        guest_runs = [
            [self._create_tcp_message(1, 65536, guest_gbps)] for _ in range(3)
        ]
        guest = MagicMock(name="guest")
        guest.name = "guest"
        host = MagicMock(name="host")
        host.name = "host"
        peer = MagicMock(name="peer")
        peer.name = "peer"

        with patch(
            "microsoft.testsuites.performance.networkperf_passthrough."
            "send_unified_perf_message"
        ):
            summary: str = suite._assert_passthrough_baseline(
                test_result=MagicMock(),
                baseline_runs=baseline_runs,
                guest_runs=guest_runs,
                direction="guest-to-peer",
                guest=guest,
                guest_nic_name="guest-data-nic",
                host=host,
                host_nic_name="host-data-nic",
                peer=peer,
                peer_nic_name="peer-data-nic",
            )
            return summary

    @staticmethod
    def _create_tcp_message(
        connections: int,
        buffer_size: int,
        throughput_gbps: Decimal,
    ) -> NetworkTCPPerformanceMessage:
        return NetworkTCPPerformanceMessage(
            tool="iperf3",
            protocol_type=TransportProtocol.Tcp,
            connections_num=connections,
            buffer_size_bytes=Decimal(buffer_size),
            rx_throughput_in_gbps=throughput_gbps,
        )
