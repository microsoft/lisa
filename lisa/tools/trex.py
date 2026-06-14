# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
#
# TRex - Cisco open-source, high-performance, DPDK-based traffic generator.
# https://trex-tgn.cisco.com
#
# This tool class installs TRex on the node, configures DPDK and hugepages,
# and provides methods to start/stop the TRex server and run stateless
# traffic profiles.  Results are returned as structured objects so that
# callers can emit LISA performance messages.
#
# Typical 2-node setup
# --------------------
#   sender node  : runs TRex in stateless server mode (-i)
#   receiver node: acts as the traffic sink (just needs network connectivity)
#
# The TRex server is started on the *sender* node, the Python STL client API
# (or the CLI wrapper used here) is then invoked to inject traffic and collect
# statistics.

import json
import re
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, List, Type, cast

from lisa import notifier
from lisa.executable import Tool
from lisa.messages import (
    MetricRelativity,
    NetworkTCPPerformanceMessage,
    NetworkUDPPerformanceMessage,
    TransportProtocol,
    create_perf_message,
    send_unified_perf_message,
)
from lisa.operating_system import Posix
from lisa.tools.hugepages import HugePageSize, Hugepages
from lisa.util import LisaException

from lisa.base_tools import Wget
from lisa.tools.mkdir import Mkdir
from lisa.tools.tar import Tar

# ---------------------------------------------------------------------------
# TRex version and download URL
# ---------------------------------------------------------------------------
# Always pull a stable released tarball from the official mirror.
_TREX_VERSION = "v3.04"
_TREX_TAR = f"{_TREX_VERSION}.tar.gz"
_TREX_BASE_URL = "https://trex-tgn.cisco.com/trex/release"
_TREX_DOWNLOAD_URL = f"{_TREX_BASE_URL}/{_TREX_TAR}"
_TREX_INSTALL_DIR = "/opt/trex"

# Minimum 2 GB of 2 MB hugepages for DPDK
_HUGEPAGES_MIN_GB = 2


@dataclass
class TrexResult:
    """Structured result from a TRex stateless traffic run."""

    # Measured at the TX side
    tx_pps: Decimal = Decimal(0)
    tx_gbps: Decimal = Decimal(0)
    tx_packets: Decimal = Decimal(0)

    # Measured at the RX side
    rx_pps: Decimal = Decimal(0)
    rx_gbps: Decimal = Decimal(0)
    rx_packets: Decimal = Decimal(0)

    # Loss / quality
    loss_packets: Decimal = Decimal(0)
    loss_percent: Decimal = Decimal(0)

    # Duration of the measurement window (seconds)
    duration_sec: float = 0.0

    # Protocol and packet size used
    protocol: str = "UDP"
    packet_size_bytes: int = 64

    # Raw JSON from TRex (if available)
    raw_json: str = ""


class Trex(Tool):
    """
    LISA tool wrapper for the TRex DPDK traffic generator.

    Installation
    ------------
    TRex is downloaded as a pre-built tarball from the official Cisco mirror
    and extracted to ``/opt/trex``.  No compilation is required.

    Hugepages
    ---------
    TRex (and the underlying DPDK) require 2 MB hugepages.  The ``install``
    method allocates them via the LISA :class:`Hugepages` helper so that the
    system is ready to use straight after tool installation.

    Usage
    -----
    ::

        trex = node.tools[Trex]
        trex.start_server()
        result = trex.run_stateless_traffic(
            server_ip="10.0.0.2",
            duration=30,
            packet_size=1024,
            rate_gbps=1.0,
            protocol="UDP",
        )
        trex.stop_server()
    """

    # ------------------------------------------------------------------
    # Patterns for parsing the simple JSON summary that the built-in
    # TRex ``stl_run`` utility emits via ``--json`` flag.
    # ------------------------------------------------------------------
    _json_pattern = re.compile(r"\{.*\}", re.DOTALL)

    # Fallback text patterns used when JSON is unavailable
    _tx_pps_pattern = re.compile(
        r"TX:\s*(?P<pps>[0-9.]+)\s*Mpps", re.IGNORECASE
    )
    _rx_pps_pattern = re.compile(
        r"RX:\s*(?P<pps>[0-9.]+)\s*Mpps", re.IGNORECASE
    )
    _tx_gbps_pattern = re.compile(
        r"TX bps:\s*(?P<gbps>[0-9.]+)\s*Gbps", re.IGNORECASE
    )
    _rx_gbps_pattern = re.compile(
        r"RX bps:\s*(?P<gbps>[0-9.]+)\s*Gbps", re.IGNORECASE
    )

    # ------------------------------------------------------------------
    # Tool interface
    # ------------------------------------------------------------------

    @property
    def command(self) -> str:
        # The main TRex executable lives inside the versioned subdirectory.
        return f"{_TREX_INSTALL_DIR}/{_TREX_VERSION}/t-rex-64"

    @property
    def can_install(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[Type[Tool]]:
        return [Wget, Tar, Mkdir]

    # ------------------------------------------------------------------
    # Installation
    # ------------------------------------------------------------------

    def install(self) -> bool:
        """
        Download the TRex tarball from the official Cisco mirror, extract it
        to ``/opt/trex``, and pre-allocate hugepages required by DPDK.
        """
        posix_os: Posix = cast(Posix, self.node.os)

        # ----------------------------------------------------------------
        # 1. Install OS-level dependencies
        #    - python3 / pyyaml  : needed by TRex Python API
        #    - pciutils          : lspci used by TRex DPDK init
        # ----------------------------------------------------------------
        try:
            posix_os.install_packages(
                ["python3", "python3-pip", "pciutils", "python3-yaml"]
            )
        except Exception as e:
            self._log.debug(f"Some TRex dependencies could not be installed: {e}")

        # ----------------------------------------------------------------
        # 2. Create the install directory
        # ----------------------------------------------------------------
        self.node.tools[Mkdir].create_directory(_TREX_INSTALL_DIR, sudo=True)

        # ----------------------------------------------------------------
        # 3. Download the TRex tarball
        # ----------------------------------------------------------------
        downloaded_tar = self.node.tools[Wget].get(
            url=_TREX_DOWNLOAD_URL,
            file_path=str(self.node.working_path),
            filename=_TREX_TAR,
            force_run=True,
            timeout=600,
        )

        # ----------------------------------------------------------------
        # 4. Extract into the install directory
        #    The tarball contains a versioned sub-directory, e.g. ``v3.04/``
        # ----------------------------------------------------------------
        self.node.tools[Tar].extract(
            file=downloaded_tar,
            dest_dir=_TREX_INSTALL_DIR,
            sudo=True,
        )

        # ----------------------------------------------------------------
        # 5. Allocate hugepages (2 MB pages, at least 2 GB total)
        #    DPDK requires hugepages; allocate them once here so they are
        #    ready when the TRex server starts.
        # ----------------------------------------------------------------
        self._setup_hugepages()

        return self._check_exists()

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------

    def start_server(
        self,
        config_file: str = "",
        cores: int = 2,
        extra_args: str = "",
    ) -> None:
        """
        Start the TRex server daemon in stateless mode.

        Parameters
        ----------
        config_file:
            Path to a ``/etc/trex_cfg.yaml`` style config file.  When empty,
            TRex auto-detects DPDK ports.
        cores:
            Number of CPU cores to dedicate to traffic generation.
        extra_args:
            Any additional CLI arguments to pass to t-rex-64.
        """
        trex_bin = self.command
        # -i  : interactive (stateless) server mode
        # -c  : number of cores
        # --no-scapy-server : skip the scapy gRPC server (saves resources)
        cmd = f"{trex_bin} -i -c {cores} --no-scapy-server"
        if config_file:
            cmd += f" --cfg {config_file}"
        if extra_args:
            cmd += f" {extra_args}"

        # Start as a background daemon; ignore stdout/stderr to the shell
        self._log.debug(f"Starting TRex server: {cmd}")
        self.node.execute_async(
            f"nohup {cmd} > /tmp/trex_server.log 2>&1 &",
            shell=True,
            sudo=True,
        )

        # Give the server a few seconds to initialise DPDK before clients
        # try to connect.
        time.sleep(5)

    def stop_server(self) -> None:
        """
        Stop the TRex server and clean up resources.

        This kills any running ``t-rex-64`` process and releases hugepages
        that were allocated during installation.
        """
        self._log.debug("Stopping TRex server")
        self.node.execute(
            "pkill -f t-rex-64 || true",
            shell=True,
            sudo=True,
        )
        # Brief pause to let DPDK release NIC resources
        time.sleep(2)
        self._release_hugepages()

    # ------------------------------------------------------------------
    # Traffic generation
    # ------------------------------------------------------------------

    def run_stateless_traffic(
        self,
        server_ip: str,
        duration: int = 30,
        packet_size: int = 64,
        rate_gbps: float = 1.0,
        protocol: str = "UDP",
        port: int = 0,
    ) -> TrexResult:
        """
        Run a stateless traffic profile and return parsed results.

        TRex is run via its built-in ``stl/udp_1pkt_simple.py`` profile for
        UDP or ``stl/tcp_1pkt_simple.py`` for TCP.  The ``--json`` output
        flag is used to capture structured statistics.

        Parameters
        ----------
        server_ip:
            IP of the remote traffic sink node.
        duration:
            How long (seconds) to inject traffic.
        packet_size:
            Frame size in bytes (excluding Ethernet FCS).
        rate_gbps:
            Target TX rate in Gbps.
        protocol:
            ``"UDP"`` (default) or ``"TCP"``.
        port:
            Destination UDP/TCP port.  ``0`` uses the profile default.

        Returns
        -------
        TrexResult
            Structured TX/RX statistics parsed from the TRex JSON output.
        """
        trex_dir = f"{_TREX_INSTALL_DIR}/{_TREX_VERSION}"

        # Choose the appropriate built-in profile
        if protocol.upper() == "TCP":
            profile = "stl/tcp_1pkt_simple.py"
        else:
            profile = "stl/udp_1pkt_simple.py"

        # Build the stl_run command
        # -f  : profile path
        # -d  : duration in seconds
        # -t  : profile parameters (packet size)
        # -m  : multiplier (Gbps)
        # --json : emit JSON summary to stdout
        cmd = (
            f"python3 {trex_dir}/automation/trex_control_plane/interactive/"
            f"trex/examples/stl/stl_run_traffic.py "
            f"--server {server_ip} "
            f"--duration {duration} "
            f"--packet_size {packet_size} "
            f"--rate {rate_gbps}g "
            f"--protocol {protocol.upper()} "
            f"--json"
        )
        if port:
            cmd += f" --port {port}"

        self._log.debug(f"Running TRex traffic: {cmd}")
        result = self.node.execute(
            cmd,
            shell=True,
            sudo=True,
            timeout=duration + 120,
            cwd=trex_dir,
        )

        return self._parse_result(result.stdout, protocol, packet_size, duration)

    # ------------------------------------------------------------------
    # Performance message helpers
    # ------------------------------------------------------------------

    def create_tcp_performance_message(
        self,
        trex_result: TrexResult,
        test_case_name: str,
        test_result: Any,
        node: Any,
    ) -> NetworkTCPPerformanceMessage:
        """Build a LISA :class:`NetworkTCPPerformanceMessage` from a TrexResult."""
        message = create_perf_message(
            NetworkTCPPerformanceMessage,
            node=node,
            test_result=test_result,
            test_case_name=test_case_name,
            other_fields={
                "tool": "trex",
                "protocol_type": TransportProtocol.Tcp,
                "tx_throughput_in_gbps": trex_result.tx_gbps,
                "rx_throughput_in_gbps": trex_result.rx_gbps,
                "connections_num": 1,
            },
        )
        notifier.notify(message)
        return message

    def create_udp_performance_message(
        self,
        trex_result: TrexResult,
        test_case_name: str,
        test_result: Any,
        node: Any,
        packet_size_kbytes: float = 0.0,
    ) -> NetworkUDPPerformanceMessage:
        """Build a LISA :class:`NetworkUDPPerformanceMessage` from a TrexResult."""
        message = create_perf_message(
            NetworkUDPPerformanceMessage,
            node=node,
            test_result=test_result,
            test_case_name=test_case_name,
            other_fields={
                "tool": "trex",
                "protocol_type": TransportProtocol.Udp,
                "tx_throughput_in_gbps": trex_result.tx_gbps,
                "rx_throughput_in_gbps": trex_result.rx_gbps,
                "connections_num": 1,
                "packet_size_kbytes": Decimal(
                    str(packet_size_kbytes or trex_result.packet_size_bytes / 1024)
                ),
                "data_loss": trex_result.loss_percent,
            },
        )
        notifier.notify(message)
        return message

    def send_trex_unified_perf_messages(
        self,
        node: Any,
        test_result: Any,
        test_case_name: str,
        trex_result: TrexResult,
    ) -> None:
        """
        Emit a set of :class:`UnifiedPerfMessage` objects covering the key
        metrics produced by TRex: TX/RX throughput (Gbps), TX/RX PPS, and
        packet loss.
        """
        protocol = trex_result.protocol.upper()
        protocol_type = (
            TransportProtocol.Tcp if protocol == "TCP" else TransportProtocol.Udp
        )

        metrics = [
            ("tx_throughput_gbps", float(trex_result.tx_gbps), "Gbps",
             "TRex TX throughput", MetricRelativity.HigherIsBetter),
            ("rx_throughput_gbps", float(trex_result.rx_gbps), "Gbps",
             "TRex RX throughput", MetricRelativity.HigherIsBetter),
            ("tx_pps", float(trex_result.tx_pps), "pps",
             "TRex TX packets per second", MetricRelativity.HigherIsBetter),
            ("rx_pps", float(trex_result.rx_pps), "pps",
             "TRex RX packets per second", MetricRelativity.HigherIsBetter),
            ("packet_loss_percent", float(trex_result.loss_percent), "%",
             "TRex packet loss", MetricRelativity.LowerIsBetter),
        ]

        for metric_name, value, unit, description, relativity in metrics:
            send_unified_perf_message(
                node=node,
                test_result=test_result,
                test_case_name=test_case_name,
                metric_name=metric_name,
                metric_value=value,
                metric_unit=unit,
                metric_description=description,
                metric_relativity=relativity,
                tool="trex",
                protocol_type=str(protocol_type),
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _setup_hugepages(self) -> None:
        """Allocate 2 MB hugepages required by DPDK / TRex."""
        try:
            hugepages = self.node.tools[Hugepages]
            hugepages.init_hugepages(
                hugepage_size=HugePageSize.HUGE_2MB,
                minimum_gb=_HUGEPAGES_MIN_GB,
            )
            self._log.debug(
                f"Allocated at least {_HUGEPAGES_MIN_GB} GB of 2 MB hugepages"
            )
        except Exception as e:
            # Log as warning – some environments pre-configure hugepages
            self._log.warning(f"Could not allocate hugepages via LISA helper: {e}")

    def _release_hugepages(self) -> None:
        """Release hugepages by writing 0 to nr_hugepages."""
        try:
            self.node.execute(
                "echo 0 | tee /sys/devices/system/node/node*/hugepages/"
                "hugepages-2048kB/nr_hugepages",
                shell=True,
                sudo=True,
            )
        except Exception as e:
            self._log.warning(f"Could not release hugepages: {e}")

    def _parse_result(
        self,
        output: str,
        protocol: str,
        packet_size: int,
        duration: int,
    ) -> TrexResult:
        """
        Parse TRex output into a :class:`TrexResult`.

        Tries JSON first (``--json`` flag), then falls back to regex-based
        text parsing for legacy / alternate output formats.
        """
        result = TrexResult(
            protocol=protocol.upper(),
            packet_size_bytes=packet_size,
            duration_sec=float(duration),
        )

        # ---- Try JSON parsing ----
        json_match = self._json_pattern.search(output)
        if json_match:
            try:
                data = json.loads(json_match.group())
                result = self._parse_json(data, result)
                result.raw_json = json_match.group()
                return result
            except (json.JSONDecodeError, KeyError) as e:
                self._log.debug(f"JSON parse failed, trying regex: {e}")

        # ---- Fallback: regex-based parsing ----
        tx_pps_match = self._tx_pps_pattern.search(output)
        if tx_pps_match:
            result.tx_pps = Decimal(tx_pps_match.group("pps")) * Decimal("1e6")

        rx_pps_match = self._rx_pps_pattern.search(output)
        if rx_pps_match:
            result.rx_pps = Decimal(rx_pps_match.group("pps")) * Decimal("1e6")

        tx_gbps_match = self._tx_gbps_pattern.search(output)
        if tx_gbps_match:
            result.tx_gbps = Decimal(tx_gbps_match.group("gbps"))

        rx_gbps_match = self._rx_gbps_pattern.search(output)
        if rx_gbps_match:
            result.rx_gbps = Decimal(rx_gbps_match.group("gbps"))

        # Derive loss
        if result.tx_packets > 0:
            result.loss_packets = result.tx_packets - result.rx_packets
            result.loss_percent = (
                result.loss_packets / result.tx_packets * Decimal("100")
            )

        return result

    def _parse_json(self, data: dict, result: TrexResult) -> TrexResult:
        """
        Populate *result* from a parsed TRex JSON statistics dictionary.

        TRex JSON schema (simplified)::

            {
              "tx_bps":  <bytes/sec>,
              "rx_bps":  <bytes/sec>,
              "tx_pps":  <packets/sec>,
              "rx_pps":  <packets/sec>,
              "tx_pkts": <total tx packets>,
              "rx_pkts": <total rx packets>,
              "drop_pct": <0-100>
            }
        """
        # Convert bytes/sec → Gbps (1 Gbps = 1e9 bits/sec = 1.25e8 bytes/sec)
        _BYTES_TO_GBPS = Decimal("8e-9")

        if "tx_bps" in data:
            result.tx_gbps = Decimal(str(data["tx_bps"])) * _BYTES_TO_GBPS
        elif "tx_gbps" in data:
            result.tx_gbps = Decimal(str(data["tx_gbps"]))

        if "rx_bps" in data:
            result.rx_gbps = Decimal(str(data["rx_bps"])) * _BYTES_TO_GBPS
        elif "rx_gbps" in data:
            result.rx_gbps = Decimal(str(data["rx_gbps"]))

        if "tx_pps" in data:
            result.tx_pps = Decimal(str(data["tx_pps"]))
        if "rx_pps" in data:
            result.rx_pps = Decimal(str(data["rx_pps"]))

        if "tx_pkts" in data:
            result.tx_packets = Decimal(str(data["tx_pkts"]))
        if "rx_pkts" in data:
            result.rx_packets = Decimal(str(data["rx_pkts"]))

        if "drop_pct" in data:
            result.loss_percent = Decimal(str(data["drop_pct"]))
        elif result.tx_packets > 0:
            result.loss_packets = result.tx_packets - result.rx_packets
            result.loss_percent = (
                result.loss_packets / result.tx_packets * Decimal("100")
            )

        return result
