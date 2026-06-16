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

import base64
import json
import re
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
from lisa.util import LisaException, LisaTimeoutException, check_till_timeout

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

# TRex stateless RPC (ZMQ) port the interactive server listens on.
_TREX_RPC_PORT = 4501
# Maximum time (seconds) to wait for the TRex server to finish DPDK init and
# start listening on the RPC port before giving up.
_TREX_SERVER_READY_TIMEOUT = 90


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
                [
                    "python3",
                    "python3-pip",
                    "pciutils",
                    "python3-yaml",
                    # Modern six (>= 1.16) is required to work around the
                    # vendored six in TRex's bundled scapy 2.4.3, which relies
                    # on the meta-path finder API removed in Python 3.12+.
                    "python3-six",
                ]
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

        # ----------------------------------------------------------------
        # 6. Work around the bundled scapy 2.4.3 / Python 3.12+ incompatibility
        #    - replace the vendored six (six.moves meta-path finder removed)
        #    - provide an ``imp`` shim (the ``imp`` module removed in 3.12)
        # ----------------------------------------------------------------
        self._replace_bundled_six()
        self._install_imp_shim()

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

        # Start as a background daemon; ignore stdout/stderr to the shell.
        # The t-rex-64 launcher invokes its helper scripts (e.g. ``trex-cfg``)
        # using relative paths, so it must run with the TRex install directory
        # as the working directory or it fails with
        # "./trex-cfg: No such file or directory".
        trex_dir = f"{_TREX_INSTALL_DIR}/{_TREX_VERSION}"
        self._log.debug(f"Starting TRex server: {cmd}")
        self.node.execute_async(
            f"cd {trex_dir} && nohup {cmd} > /tmp/trex_server.log 2>&1 &",
            shell=True,
            sudo=True,
        )

        # DPDK initialisation (port binding, hugepage mapping) can take a
        # variable amount of time, so poll until the RPC port is listening
        # instead of using a fixed sleep that races with slow startups.
        self._wait_for_server_ready()

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
        # Wait (bounded) for the process to exit so DPDK releases NIC
        # resources before we free the hugepages it had mapped.
        check_till_timeout(
            lambda: "running"
            not in self.node.execute(
                "pgrep -f t-rex-64 >/dev/null && echo running || echo stopped",
                shell=True,
                sudo=True,
            ).stdout,
            timeout_message=(
                "TRex server process did not exit after pkill; DPDK NIC "
                "resources may still be held. Check for a stuck t-rex-64 "
                "process on the node."
            ),
            timeout=30,
            interval=1,
        )
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

        A small Python driver script is written to the node's working
        directory and executed using TRex's ``trex_stl_lib`` Python API.
        The script connects to the locally running TRex server via the
        default port (4501), transmits traffic for the requested duration,
        captures per-port statistics, and prints a JSON summary to stdout
        which is then parsed into a :class:`TrexResult`.

        Parameters
        ----------
        server_ip:
            Destination IP address for generated packets (the receiver).
        duration:
            How long (seconds) to inject traffic.
        packet_size:
            Frame size in bytes (excluding Ethernet FCS).
        rate_gbps:
            Target TX rate in Gbps.
        protocol:
            ``"UDP"`` (default) or ``"TCP"``.
        port:
            Destination UDP/TCP port.  ``0`` uses a sensible default (12345).

        Returns
        -------
        TrexResult
            Structured TX/RX statistics parsed from the TRex JSON output.
        """
        trex_dir = f"{_TREX_INSTALL_DIR}/{_TREX_VERSION}"
        dst_port = port if port else 12345

        # -----------------------------------------------------------------
        # Build a small inline Python driver that:
        #   1. Imports TRex's STLClient from the bundled library path
        #   2. Connects to the locally running TRex server (localhost:4501)
        #   3. Creates a simple stateless stream (STLStream + STLPktBuilder)
        #   4. Runs traffic for ``duration`` seconds at ``rate_gbps`` Gbps
        #   5. Collects statistics and prints JSON to stdout
        # -----------------------------------------------------------------
        driver_script = f"""\
import sys
import json
import time

# Add TRex Python API paths
trex_dir = "{trex_dir}"
sys.path.insert(
    0,
    trex_dir + "/automation/trex_control_plane/interactive",
)

from trex.stl.api import (
    STLClient,
    STLPktBuilder,
    STLStream,
    STLTXCont,
)
from scapy.layers.l2 import Ether
from scapy.layers.inet import IP, UDP, TCP

# --- Build packet ---
eth = Ether()
ip  = IP(dst="{server_ip}")
if "{protocol}".upper() == "TCP":
    transport = TCP(dport={dst_port})
else:
    transport = UDP(dport={dst_port})

pkt_payload = b"X" * max(
    0, {packet_size} - len(eth / ip / transport)
)
pkt = eth / ip / transport / pkt_payload

# STLTXCont accepts rate in bps_L1; no conversion needed.
rate_bps = int({rate_gbps} * 1e9)

stream = STLStream(
    packet=STLPktBuilder(pkt=pkt),
    mode=STLTXCont(bps_L1=rate_bps),
)

c = STLClient()
try:
    c.connect()
    c.reset()

    tx_port, rx_port = 0, 1
    c.add_streams(stream, ports=[tx_port])
    c.clear_stats()
    c.start(ports=[tx_port], duration={duration})
    c.wait_on_traffic(ports=[tx_port], timeout={duration + 60})

    stats = c.get_stats()
    tx_s  = stats[tx_port]
    rx_s  = stats[rx_port]

    # bytes/sec -> Gbps: multiply bits (x8) then divide by 1e9
    tx_bps = tx_s.get("tx_bps", 0)
    rx_bps = rx_s.get("rx_bps", 0)

    summary = {{
        "tx_gbps":  tx_bps * 8 / 1e9,
        "rx_gbps":  rx_bps * 8 / 1e9,
        "tx_pps":   tx_s.get("tx_pps",   0),
        "rx_pps":   rx_s.get("rx_pps",   0),
        "tx_pkts":  tx_s.get("opackets", 0),
        "rx_pkts":  rx_s.get("ipackets", 0),
    }}
    tx_pkts = summary["tx_pkts"]
    rx_pkts = summary["rx_pkts"]
    if tx_pkts > 0:
        summary["drop_pct"] = (tx_pkts - rx_pkts) / tx_pkts * 100
    else:
        summary["drop_pct"] = 0.0

    print(json.dumps(summary))

finally:
    c.disconnect()
"""

        # Write the driver script using base64 to avoid shell quoting issues.
        # The script content is dynamically generated with the target IP, port,
        # packet size, rate, protocol, and duration baked in as literals.
        script_path = str(self.node.working_path / "trex_run.py")
        encoded = base64.b64encode(driver_script.encode()).decode()
        self.node.execute(
            f"python3 -c \""
            f"import base64; "
            f"open('{script_path}', 'w').write("
            f"base64.b64decode('{encoded}').decode())"
            f"\"",
            shell=True,
            sudo=True,
        )

        self._log.debug(f"Executing TRex stateless driver: {script_path}")
        run_result = self.node.execute(
            f"python3 {script_path}",
            shell=True,
            sudo=True,
            timeout=duration + 180,
            cwd=trex_dir,
        )

        # A non-zero exit code means the TRex Python driver crashed (e.g. the
        # bundled scapy failed to import, DPDK ports could not be bound, or the
        # server connection failed). Without this check a crashed run would be
        # silently parsed into an all-zero TrexResult and reported as a PASS.
        if run_result.exit_code != 0:
            raise LisaException(
                f"TRex stateless driver failed with exit code "
                f"{run_result.exit_code}. The traffic run did not complete, so "
                f"no throughput was measured. Inspect the driver output below "
                f"and /tmp/trex_server.log on the node to investigate.\n"
                f"{run_result.stdout}"
            )

        result = self._parse_result(
            run_result.stdout, protocol, packet_size, duration
        )

        # On success the driver prints a JSON statistics summary. If none was
        # found, the run produced no usable measurement and must not be treated
        # as a passing result.
        if not result.raw_json:
            raise LisaException(
                "TRex stateless driver exited successfully but did not emit a "
                "JSON statistics summary, so no throughput was measured. Verify "
                "TRex generated traffic and that both ports are bound to DPDK. "
                f"Driver output:\n{run_result.stdout}"
            )

        return result

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

    def _replace_bundled_six(self) -> None:
        """
        Replace TRex's vendored scapy ``six.py`` with the system ``six``.

        TRex v3.04 bundles scapy 2.4.3, whose vendored ``six`` registers
        ``six.moves`` through the legacy ``find_module``/``load_module``
        meta-path API that was removed in Python 3.12.  On Python 3.12+ this
        breaks with ``ModuleNotFoundError: No module named
        'scapy.modules.six.moves'`` as soon as the Python traffic driver
        imports the TRex stateless API.

        The system ``six`` (installed as a tool dependency) implements the
        modern ``find_spec`` API, so overwriting the bundled copy makes the
        bundled scapy import cleanly without any per-run shimming.
        """
        bundled_six = (
            f"{_TREX_INSTALL_DIR}/{_TREX_VERSION}/external_libs/"
            "scapy-2.4.3/scapy/modules/six.py"
        )

        # Locate the system six module installed via the OS package.
        result = self.node.execute(
            "python3 -c 'import six; print(six.__file__)'",
            shell=True,
        )
        system_six = result.stdout.strip()
        if result.exit_code != 0 or not system_six:
            self._log.debug(
                "System six not found; leaving bundled scapy six in place. "
                "TRex traffic driver may fail on Python 3.12+."
            )
            return

        self.node.execute(
            f"cp -f {system_six} {bundled_six}",
            shell=True,
            sudo=True,
        )
        self._log.debug(
            f"Replaced bundled scapy six with system six from {system_six}"
        )

    def _install_imp_shim(self) -> None:
        """
        Drop an ``imp`` compatibility shim into TRex's interactive path.

        TRex v3.04's ``trex_stl_streams.py`` (and a few other bundled modules)
        still ``import imp``, a standard-library module that was removed in
        Python 3.12.  On Ubuntu 24.04 / Python 3.12+ this fails with
        ``ModuleNotFoundError: No module named 'imp'`` while importing the TRex
        stateless API.

        The TRex traffic driver prepends
        ``automation/trex_control_plane/interactive`` to ``sys.path``, so
        placing an ``imp.py`` there makes every ``import imp`` in the bundled
        code resolve to this shim.  Only ``imp.reload`` is actually exercised
        by the stateless path, but the shim re-implements the small, commonly
        used subset of the legacy API on top of ``importlib`` for safety.
        """
        shim_dir = (
            f"{_TREX_INSTALL_DIR}/{_TREX_VERSION}/automation/"
            "trex_control_plane/interactive"
        )
        shim_path = f"{shim_dir}/imp.py"
        shim_source = (
            '"""Minimal ``imp`` shim for Python 3.12+ (imp module removed)."""\n'
            "import importlib\n"
            "import importlib.machinery\n"
            "import importlib.util\n"
            "import sys\n"
            "import types\n"
            "\n"
            "PY_SOURCE = 1\n"
            "PY_COMPILED = 2\n"
            "C_EXTENSION = 3\n"
            "PKG_DIRECTORY = 5\n"
            "\n"
            "\n"
            "def reload(module):\n"
            "    return importlib.reload(module)\n"
            "\n"
            "\n"
            "def new_module(name):\n"
            "    return types.ModuleType(name)\n"
            "\n"
            "\n"
            "def acquire_lock():\n"
            "    pass\n"
            "\n"
            "\n"
            "def release_lock():\n"
            "    pass\n"
            "\n"
            "\n"
            "def load_source(name, pathname, file=None):\n"
            "    loader = importlib.machinery.SourceFileLoader(name, pathname)\n"
            "    spec = importlib.util.spec_from_file_location(\n"
            "        name, pathname, loader=loader\n"
            "    )\n"
            "    module = importlib.util.module_from_spec(spec)\n"
            "    sys.modules[name] = module\n"
            "    loader.exec_module(module)\n"
            "    return module\n"
            "\n"
            "\n"
            "def find_module(name, path=None):\n"
            "    if path is None:\n"
            "        spec = importlib.util.find_spec(name)\n"
            "    else:\n"
            "        spec = importlib.machinery.PathFinder.find_spec(name, path)\n"
            "    if spec is None:\n"
            "        raise ImportError(f'No module named {name!r}')\n"
            "    return None, spec.origin, ('', '', PY_SOURCE)\n"
            "\n"
            "\n"
            "def load_module(name, file, pathname, description):\n"
            "    return load_source(name, pathname, file)\n"
        )

        encoded = base64.b64encode(shim_source.encode()).decode()
        self.node.execute(
            f'python3 -c "'
            f"import base64; "
            f"open('{shim_path}', 'w').write("
            f"base64.b64decode('{encoded}').decode())"
            f'"',
            shell=True,
            sudo=True,
        )
        self._log.debug(f"Installed imp compatibility shim at {shim_path}")

    def _wait_for_server_ready(
        self, timeout: int = _TREX_SERVER_READY_TIMEOUT
    ) -> None:
        """
        Block until the TRex server is listening on its RPC port.

        DPDK initialisation (port binding, hugepage mapping) takes a variable
        amount of time, so instead of a fixed sleep we poll until the
        ``t-rex-64`` process has bound the stateless RPC port.  If the server
        never becomes ready, the tail of ``/tmp/trex_server.log`` is included
        in the raised exception to make DPDK/hugepage failures diagnosable.
        """

        def _is_listening() -> bool:
            result = self.node.execute(
                f"ss -ltn '( sport = :{_TREX_RPC_PORT} )' | "
                f"grep -q ':{_TREX_RPC_PORT}' && echo ready || echo waiting",
                shell=True,
                sudo=True,
            )
            return "ready" in result.stdout

        try:
            check_till_timeout(
                _is_listening,
                timeout_message=(
                    f"TRex server did not start listening on RPC port "
                    f"{_TREX_RPC_PORT} within {timeout}s"
                ),
                timeout=timeout,
                interval=2,
            )
        except LisaTimeoutException:
            server_log = self.node.execute(
                "tail -n 40 /tmp/trex_server.log 2>/dev/null || true",
                shell=True,
                sudo=True,
            ).stdout
            raise LisaException(
                f"TRex server failed to start listening on RPC port "
                f"{_TREX_RPC_PORT} within {timeout}s. DPDK port binding or "
                f"hugepage allocation likely failed. Inspect the server log "
                f"below and /tmp/trex_server.log on the node.\n{server_log}"
            )
        self._log.debug(
            f"TRex server is ready and listening on RPC port {_TREX_RPC_PORT}"
        )

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
