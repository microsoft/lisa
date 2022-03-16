# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, cast

from lisa.executable import Tool
from lisa.messages import NetworkPPSPerformanceMessage, create_message
from lisa.operating_system import Posix
from lisa.util import constants
from lisa.util.process import ExecutableResult, Process

from .firewall import Firewall

if TYPE_CHECKING:
    from lisa.environment import Environment


class Sar(Tool):
    # 06:37:41        IFACE   rxpck/s   txpck/s    rxkB/s    txkB/s   rxcmp/s   txcmp/s  rxmcst/s   %ifutil # noqa: E501
    # 06:37:42           lo      0.00      0.00      0.00      0.00      0.00      0.00      0.00      0.00 # noqa: E501
    # 06:37:42         eth0   2856.00   2857.00    186.86    187.28      0.00      0.00      0.00      0.00 # noqa: E501
    #
    # 06:37:42        IFACE   rxpck/s   txpck/s    rxkB/s    txkB/s   rxcmp/s   txcmp/s  rxmcst/s   %ifutil # noqa: E501
    # 06:37:43           lo      0.00      0.00      0.00      0.00      0.00      0.00      0.00      0.00 # noqa: E501
    # 06:37:43         eth0   3195.00   3194.00    209.04    209.33      0.00      0.00      0.00      0.00 # noqa: E501
    sar_results_pattern = re.compile(r"(IFACE[\w\W]*?)(?=IFACE|\Z)", re.MULTILINE)

    @property
    def command(self) -> str:
        return "sar"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("sysstat")
        return self._check_exists()

    def get_statistics_async(
        self, key_word: str = "DEV", interval: int = 1, count: int = 120
    ) -> Process:
        # sar [ options ] [ <interval> [ <count> ] ]
        # -n { <keyword> [,...] | ALL }
        #     Network statistics
        #     Keywords are:
        #     DEV     Network interfaces
        #     EDEV    Network interfaces (errors)
        #     NFS     NFS client
        #     NFSD    NFS server
        #     SOCK    Sockets (v4)
        #     IP      IP traffic      (v4)
        #     EIP     IP traffic      (v4) (errors)
        #     ICMP    ICMP traffic    (v4)
        #     EICMP   ICMP traffic    (v4) (errors)
        #     TCP     TCP traffic     (v4)
        #     ETCP    TCP traffic     (v4) (errors)
        #     UDP     UDP traffic     (v4)
        #     SOCK6   Sockets (v6)
        #     IP6     IP traffic      (v6)
        #     EIP6    IP traffic      (v6) (errors)
        #     ICMP6   ICMP traffic    (v6)
        #     EICMP6  ICMP traffic    (v6) (errors)
        #     UDP6    UDP traffic     (v6)
        #     FC      Fibre channel HBAs
        #     SOFT    Software-based network processing
        cmd = f"{self.command} -n {key_word} {interval} {count}"
        process = self.node.execute_async(cmd)
        return process

    def get_statistics(
        self, key_word: str = "DEV", interval: int = 1, count: int = 120
    ) -> ExecutableResult:
        process = self.get_statistics_async(key_word, interval, count)
        return process.wait_result(
            expected_exit_code=0,
            expected_exit_code_failure_message="fail to run sar command",
        )

    def create_pps_performance_messages(
        self,
        result: ExecutableResult,
        test_case_name: str,
        environment: "Environment",
        test_type: str,
    ) -> NetworkPPSPerformanceMessage:
        # IFACE: Name of the network interface for which statistics are reported.
        # rxpck/s: packet receiving rate (unit: packets/second)
        # txpck/s: packet transmitting rate (unit: packets/second)
        # rxkB/s: data receiving rate (unit: Kbytes/second)
        # txkB/s: data transmitting rate (unit: Kbytes/second)
        # rxcmp/s: compressed packets receiving rate (unit: Kbytes/second)
        # txcmp/s: compressed packets transmitting rate (unit: Kbytes/second)
        # rxmcst/s: multicast packets receiving rate (unit: Kbytes/second)
        nic_name = self.node.nics.default_nic
        sar_result_pattern = re.compile(
            rf"([\w\W]*?){nic_name}\s+(?P<rxpck>\d+.\d+)\s+(?P<txpck>\d+.\d+)"
            r"\s+(?P<rxkb>\d+.\d+)\s+(?P<rxcmp>\d+.\d+)\s+(?P<txcmp>\d+.\d+)"
            r"\s+(?P<rxmcst>\d+.\d+)\s+(?P<ifutil>\d+.\d+)",
            re.M,
        )
        raw_list = re.finditer(self.sar_results_pattern, result.stdout)
        rx_pps: List[Decimal] = []
        tx_pps: List[Decimal] = []
        tx_rx_pps: List[Decimal] = []
        for sar_result in raw_list:
            temp = sar_result_pattern.match(sar_result.group())
            assert temp, f"not find matched sar result for nic {nic_name}"
            rx_pps.append(Decimal(temp.group("rxpck")))
            tx_pps.append(Decimal(temp.group("txpck")))
            tx_rx_pps.append(
                Decimal(temp.group("rxpck")) + Decimal(temp.group("txpck"))
            )
        result_fields: Dict[str, Any] = {}
        result_fields["tool"] = constants.NETWORK_PERFORMANCE_TOOL_SAR
        result_fields["test_type"] = test_type
        result_fields["rx_pps_maximum"] = max(rx_pps)
        result_fields["rx_pps_average"] = Decimal(sum(rx_pps) / len(rx_pps))
        result_fields["rx_pps_minimum"] = min(rx_pps)
        result_fields["tx_pps_maximum"] = max(tx_pps)
        result_fields["tx_pps_average"] = Decimal(sum(tx_pps) / len(tx_pps))
        result_fields["tx_pps_minimum"] = min(tx_pps)
        result_fields["rx_tx_pps_maximum"] = max(tx_rx_pps)
        result_fields["rx_tx_pps_average"] = Decimal(sum(tx_rx_pps) / len(tx_rx_pps))
        result_fields["rx_tx_pps_minimum"] = min(tx_rx_pps)
        message = create_message(
            NetworkPPSPerformanceMessage,
            self.node,
            environment,
            test_case_name,
            result_fields,
        )
        return message

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        firewall = self.node.tools[Firewall]
        firewall.stop()
