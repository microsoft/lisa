# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
from contextlib import ExitStack, contextmanager
from pathlib import Path
from time import monotonic
from types import TracebackType
from typing import Any, Dict, Iterator, List, Optional, Tuple, Type

from assertpy import assert_that

from lisa import Logger, RemoteNode, constants
from lisa.nic import NicInfo
from lisa.tools import Cat, Dmesg, Ip, Iperf3, Kill, Lsof
from lisa.util import LisaException, LisaTimeoutException, check_till_timeout
from lisa.util.process import ExecutableResult, Process


class ServicingTraffic:
    """Shared traffic observations and diagnostics for network servicing tests."""

    # Two minutes provide baseline samples for this shorter continuity variant.
    _SERVICING_BASELINE_SECONDS = 120
    # Observe each confirmed synthetic/restored path for at least 30 seconds.
    _SERVICING_PHASE_SECONDS = 30
    # Reserve one minute beyond all transition and observation windows.
    _SERVICING_COMPLETION_MARGIN_SECONDS = 60
    # Allow final iperf control exchange and output collection after traffic ends.
    _SERVICING_EXIT_TIMEOUT = 30
    _SERVICING_INTERVAL_SECONDS = 1
    # Ignore a short final partial interval when checking progress.
    _SERVICING_MIN_INTERVAL_SECONDS = 0.5
    # Recovery is diagnostic: five full intervals within 10% of baseline.
    _SERVICING_RECOVERY_RATIO = 0.9
    _SERVICING_RECOVERY_INTERVALS = 5

    @staticmethod
    @contextmanager
    def _servicing_cleanup(log: Logger) -> Iterator[ExitStack]:
        primary_error: Optional[BaseException] = None
        primary_traceback: Optional[TracebackType] = None

        def remember_failure(
            _error_type: Optional[Type[BaseException]],
            error: Optional[BaseException],
            traceback: Optional[TracebackType],
        ) -> bool:
            nonlocal primary_error, primary_traceback
            primary_error, primary_traceback = error, traceback
            return False

        def preserve_failure(
            _error_type: Optional[Type[BaseException]],
            error: Optional[BaseException],
            traceback: Optional[TracebackType],
        ) -> bool:
            if error is not None and error is not primary_error:
                log.error(
                    "Network servicing cleanup failed; inspect the chained "
                    "exceptions and collected traffic/NIC diagnostics",
                    exc_info=(type(error), error, traceback),
                )
                if primary_error is not None:
                    raise primary_error.with_traceback(primary_traceback) from error
            return False

        with ExitStack() as cleanup:
            cleanup.push(preserve_failure)
            # Capture the body failure before running any registered cleanup.
            with ExitStack() as failure_capture:
                failure_capture.push(remember_failure)
                yield cleanup

    @staticmethod
    def _servicing_check_running(processes: Dict[str, Process]) -> None:
        for name, process in processes.items():
            if not process.is_running():
                result = process.wait_result(timeout=10)
                raise LisaException(
                    f"{name} exited before servicing observation completed: "
                    f"exit={result.exit_code}, stdout={result.stdout}, "
                    f"stderr={result.stderr}"
                )

    def _servicing_wait(self, processes: Dict[str, Process], seconds: int) -> None:
        started = monotonic()

        def elapsed() -> bool:
            self._servicing_check_running(processes)
            return monotonic() - started >= seconds

        check_till_timeout(
            elapsed,
            timeout_message=f"observe active traffic for {seconds} seconds",
            timeout=seconds + 10,
        )

    @staticmethod
    def _servicing_remaining(deadline: float) -> int:
        # Round down so an individual command never receives more than remains.
        remaining = int(deadline - monotonic())
        if remaining <= 0:
            raise LisaTimeoutException(
                "Network servicing phase budget exhausted; inspect VF state, "
                "receive counters, and the SSH connection"
            )
        return remaining

    def _servicing_rx_packets(
        self, node: RemoteNode, nic_name: str, deadline: float
    ) -> int:
        path = (
            node.get_pure_path("/sys/class/net")
            / nic_name
            / "statistics"
            / "rx_packets"
        )
        result = node.tools[Cat].run(
            str(path),
            force_run=True,
            timeout=self._servicing_remaining(deadline),
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                f"Cannot read VF receive progress on {node.name}; inspect {path}"
            ),
        )
        value = result.stdout.strip()
        assert_that(value.isdigit()).described_as(
            f"Expected a numeric VF packet counter, got {value!r}; inspect {path}"
        ).is_true()
        return int(value)

    @staticmethod
    def _servicing_nic(node: RemoteNode) -> NicInfo:
        matches = [
            nic
            for nic in node.nics.nics.values()
            if nic.ip_addr == node.internal_address and not nic.is_infiniband
        ]
        assert_that(matches).described_as(
            f"Expected one NIC with internal IP {node.internal_address}; "
            "inspect guest NIC discovery"
        ).is_length(1)
        return matches[0]

    @staticmethod
    def _servicing_routes(node: RemoteNode) -> str:
        result = node.tools[Ip].run("route show", force_run=True, expected_exit_code=0)
        return "\n".join(sorted(result.stdout.splitlines()))

    def _servicing_check_network(self, node: RemoteNode, routes: str) -> None:
        nic = self._servicing_nic(node)
        assert_that(node.tools[Ip].get_ip_address(nic.name)).described_as(
            f"Internal address must remain unchanged on {node.name}; inspect ip addr"
        ).is_equal_to(node.internal_address)
        assert_that(self._servicing_routes(node)).described_as(
            f"Routes must remain unchanged on {node.name}; compare ip route output"
        ).is_equal_to(routes)

    @staticmethod
    def _servicing_stop_traffic(node: RemoteNode, port: int) -> None:
        result = node.tools[Lsof].run(
            f"-t -a -c iperf3 -i :{port}", sudo=True, force_run=True
        )
        result.assert_exit_code([0, 1], include_output=True)
        for pid in set(result.stdout.split()):
            assert_that(pid.isdigit()).described_as(
                f"Expected numeric iperf3 PID, got {pid!r}; inspect lsof output"
            ).is_true()
            node.tools[Kill].by_pid(pid, signum=constants.SIGINT, ignore_not_exist=True)

    @classmethod
    def _servicing_save_buffers(
        cls, processes: Dict[str, Process], log_path: Path
    ) -> None:
        timed_out: List[str] = []
        for name, process in processes.items():
            result = process.wait_result(
                timeout=cls._SERVICING_EXIT_TIMEOUT, raise_on_timeout=False
            )
            result.save_stdout_to_file(log_path / f"{name}.json")
            (log_path / f"{name}-stderr.log").write_text(
                result.stderr, encoding="utf-8"
            )
            (log_path / f"{name}.log").write_text(
                process.log_buffer.getvalue(), encoding="utf-8"
            )
            if result.is_timeout:
                timed_out.append(name)
        assert_that(timed_out).described_as(
            "Traffic must stop during cleanup; inspect iperf process and stderr logs"
        ).is_empty()

    @staticmethod
    def _servicing_save_dmesg(node: RemoteNode, log_path: Path) -> None:
        (log_path / f"{node.name}-dmesg.log").write_text(
            node.tools[Dmesg].get_output(force_run=True), encoding="utf-8"
        )

    @classmethod
    def _servicing_start_traffic(
        cls, receiver: RemoteNode, sender: RemoteNode, duration: int
    ) -> Dict[str, Process]:
        processes: Dict[str, Process] = {}
        for protocol, port in {"udp": 5201, "tcp": 5202}.items():
            processes[f"{protocol}_receiver"] = receiver.tools[
                Iperf3
            ].run_as_server_async(
                port=port,
                report_periodic=cls._SERVICING_INTERVAL_SECONDS,
                use_json_format=True,
                one_connection_only=True,
                daemon=False,
                interface_ip=receiver.internal_address,
            )
            processes[f"{protocol}_sender"] = sender.tools[Iperf3].run_as_client_async(
                server_ip=receiver.internal_address,
                client_ip=sender.internal_address,
                port=port,
                bitrate="1M",
                buffer_length=1200,  # Avoid fragmentation with standard MTUs.
                report_periodic=cls._SERVICING_INTERVAL_SECONDS,
                output_json=True,
                udp_mode=protocol == "udp",
                run_time_seconds=duration,
            )
        return processes

    @classmethod
    def _servicing_collect_results(
        cls,
        processes: Dict[str, Process],
        duration: int,
        log: Logger,
        log_path: Path,
    ) -> Dict[str, Dict[str, Any]]:
        results: Dict[str, Dict[str, Any]] = {}
        for protocol in ["udp", "tcp"]:
            for role in ["sender", "receiver"]:
                name = f"{protocol}_{role}"
                result = processes[name].wait_result(
                    timeout=(
                        duration + cls._SERVICING_EXIT_TIMEOUT
                        if role == "sender"
                        else cls._SERVICING_EXIT_TIMEOUT
                    )
                )
                result.save_stdout_to_file(log_path / f"{name}.json")
                result.assert_exit_code(0, include_output=True)
                results[name] = cls._servicing_iperf_result(result)
                log.info(f"{name} completed successfully with exit code 0")
        return results

    @classmethod
    def _servicing_iperf_result(cls, result: ExecutableResult) -> Dict[str, Any]:
        data: Dict[str, Any] = json.loads(result.stdout)
        assert_that(data).described_as(
            "iperf3 JSON must be an object; inspect the saved process output"
        ).is_instance_of(dict)
        assert_that(data).described_as(
            "iperf3 must complete without errors; inspect saved JSON and stderr"
        ).does_not_contain("error")
        assert_that(data["intervals"]).described_as(
            "iperf3 intervals must be a list; inspect saved JSON"
        ).is_instance_of(list).is_not_empty()
        for interval in data["intervals"]:
            sample = interval["sum"]
            assert_that(sample["seconds"]).described_as(
                f"iperf3 interval must have positive duration; inspect sample {sample}"
            ).is_greater_than(0)
            if sample["seconds"] >= cls._SERVICING_MIN_INTERVAL_SECONDS:
                assert_that(sample["bytes"]).described_as(
                    "Traffic must progress in every full interval; "
                    f"inspect sample {sample}"
                ).is_greater_than(0)
        assert_that(data["end"]).described_as(
            "iperf3 must produce a final summary; inspect saved JSON and stderr"
        ).is_instance_of(dict).is_not_empty()
        return data

    @classmethod
    def _servicing_report(
        cls,
        results: Dict[str, Dict[str, Any]],
        phases: Dict[str, Tuple[float, float]],
        enable_requested: float,
        log: Logger,
        log_path: Path,
        recovery_label: str = "enable",
        summary_filename: str = "network_servicing_summary.json",
    ) -> None:
        udp_end = results["udp_receiver"]["end"]
        udp_summary = (
            udp_end["sum_received"] if "sum_received" in udp_end else udp_end["sum"]
        )
        sent_end = results["udp_sender"]["end"]
        sent_summary = (
            sent_end["sum_sent"] if "sum_sent" in sent_end else sent_end["sum"]
        )
        assert_that(udp_summary["packets"]).described_as(
            "UDP receiver must receive datagrams; inspect receiver JSON"
        ).is_greater_than(0)
        assert_that(udp_summary["lost_packets"]).described_as(
            f"Receiver must report zero UDP loss; inspect summary {udp_summary}"
        ).is_zero()
        assert_that(udp_summary["packets"]).described_as(
            f"UDP counts must match; inspect sender summary {sent_summary}"
        ).is_equal_to(sent_summary["packets"])
        assert_that(results["tcp_sender"]["end"]["sum_sent"]["bytes"]).described_as(
            "TCP sender must complete a transfer; inspect sender JSON"
        ).is_greater_than(0)
        assert_that(
            results["tcp_receiver"]["end"]["sum_received"]["bytes"]
        ).described_as(
            "TCP receiver must complete a transfer; inspect receiver JSON"
        ).is_greater_than(
            0
        )
        log.info(
            f"UDP validation passed: sent={sent_summary['packets']}, "
            f"received={udp_summary['packets']}, lost={udp_summary['lost_packets']}"
        )
        log.info(
            "TCP validation passed: "
            f"sent_bytes={results['tcp_sender']['end']['sum_sent']['bytes']}, "
            "received_bytes="
            f"{results['tcp_receiver']['end']['sum_received']['bytes']}; "
            "all full traffic intervals made progress"
        )
        summary: Dict[str, Any] = {
            "phases_epoch_seconds": phases,
            "udp_receiver": udp_summary,
            "offered_bitrate_per_stream": "1M",
            "capacity_benchmark": False,
            "throughput": {},
        }
        for protocol in ["udp", "tcp"]:
            data = results[f"{protocol}_receiver"]
            origin = data["start"]["timestamp"]["timesecs"]
            samples = [interval["sum"] for interval in data["intervals"]]
            rates: Dict[str, float] = {}
            for phase, (start, end) in phases.items():
                # Receiver epochs have one-second resolution; exclude boundaries.
                selected = [
                    sample
                    for sample in samples
                    if origin + sample["start"]
                    >= start + cls._SERVICING_INTERVAL_SECONDS
                    and origin + sample["end"] <= end - cls._SERVICING_INTERVAL_SECONDS
                ]
                assert_that(selected).described_as(
                    f"Expected {protocol} receiver samples for {phase}; "
                    "inspect phase timestamps and receiver intervals"
                ).is_not_empty()
                rates[phase] = (
                    sum(sample["bytes"] for sample in selected)
                    * 8
                    / sum(sample["seconds"] for sample in selected)
                )
            assert_that(rates["baseline"]).described_as(
                f"Expected positive {protocol} baseline throughput; "
                "inspect receiver JSON"
            ).is_greater_than(0)
            change = 100 * (rates["restored"] / rates["baseline"] - 1)
            consecutive = 0
            recovery: Optional[float] = None
            for sample in samples:
                if (
                    origin + sample["start"]
                    < phases["restored"][0] + cls._SERVICING_INTERVAL_SECONDS
                ):
                    continue
                if sample["seconds"] < cls._SERVICING_MIN_INTERVAL_SECONDS:
                    continue
                if (
                    sample["bits_per_second"]
                    >= rates["baseline"] * cls._SERVICING_RECOVERY_RATIO
                ):
                    consecutive += 1
                else:
                    consecutive = 0
                if consecutive == cls._SERVICING_RECOVERY_INTERVALS:
                    recovery = origin + sample["end"] - enable_requested
                    break
            recovery_key = (
                f"five_intervals_at_90_percent_seconds_after_{recovery_label}"
            )
            summary["throughput"][protocol] = {
                "receiver_bps": rates,
                "restored_change_bps": rates["restored"] - rates["baseline"],
                "restored_change_percent": change,
                recovery_key: recovery,
            }
            log.info(
                f"{protocol.upper()} receiver throughput (offered load, not capacity): "
                f"{rates}; restored change={change:+.2f}%; "
                f"five-interval 90% recovery after {recovery_label}={recovery}s "
                "(diagnostic only)"
            )
        (log_path / summary_filename).write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
