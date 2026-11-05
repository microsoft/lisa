# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import json
import re
from contextlib import ExitStack, contextmanager
from decimal import Decimal
from ipaddress import ip_address
from pathlib import Path, PurePosixPath
from time import monotonic
from types import TracebackType
from typing import Any, Dict, Iterator, List, Optional, Tuple, Type, cast

from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    Node,
    RemoteNode,
    SkippedException,
    TcpConnectionException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    constants,
    features,
    node_requirement,
    schema,
    search_space,
    simple_requirement,
)
from lisa.base_tools import Systemctl
from lisa.features import NetworkInterface, SerialConsole, StartStop
from lisa.microsoft.testsuites.network.common import (
    cleanup_iperf3,
    disable_enable_devices,
    initialize_nic_info,
    reload_modules,
    remove_extra_nics,
    restore_extra_nics,
    skip_if_pci_only_nics,
    sriov_basic_test,
    sriov_disable_enable,
    sriov_vf_connection_test,
)
from lisa.nic import NicInfo
from lisa.operating_system import BSD, Posix, Windows
from lisa.sut_orchestrator import AZURE, HYPERV
from lisa.sut_orchestrator.azure.common import AzureNodeSchema
from lisa.tools import (
    Cat,
    Date,
    Dmesg,
    Ethtool,
    FileSystem,
    Firewall,
    InterruptInspector,
    Ip,
    Iperf3,
    Journalctl,
    Kill,
    Ls,
    Lscpu,
    Lsof,
    Lspci,
    Mount,
    NetShaper,
    Ping,
    Readlink,
    Service,
    Timeout,
)
from lisa.tools.netshaper import NetShaperInfo
from lisa.util import (
    LisaException,
    LisaTimeoutException,
    UnsupportedDistroException,
    UnsupportedOperationException,
    check_till_timeout,
)
from lisa.util.process import ExecutableResult, Process
from lisa.util.shell import wait_tcp_port_ready


@TestSuiteMetadata(
    area="sriov",
    category="functional",
    description="""
    This test suite uses to verify accelerated network functionality.
    """,
)
class Sriov(TestSuite):
    TIME_OUT = 300
    COALESCE_PARAMETER = "rx-cqe-frames"
    # CQE packing implementations commonly expose single-frame mode and a
    # small fixed group size. Probe alternatives and use the first value the
    # driver accepts rather than assuming every device has the same range.
    COALESCE_CANDIDATES = (1, 4, 8, 2, 16)
    COALESCE_VALUE_REJECTION_PATTERNS = (
        "invalid argument",
        "not supported",
        "out of range",
    )
    # The netlink attribute is a u32, so this value cannot be represented and
    # must be rejected rather than truncated or clamped.
    INVALID_COALESCE_VALUE = 1 << 32
    # MANA uses rx_0_packets while mlx5 uses rx0_packets. Match only those base
    # queue packet counters so TSO and inner-packet counters are not included.
    _RX_QUEUE_PACKET_COUNTER_PATTERN = re.compile(r"^(?:rx_\d+_packets|rx\d+_packets)$")
    _TX_QUEUE_PACKET_COUNTER_PATTERN = re.compile(r"^(?:tx_\d+_packets|tx\d+_packets)$")
    # A successful echo request/reply contributes one TX and one RX packet.
    # One thousand packets is well above the ambient SSH traffic seen during
    # the sample interval, so a passing delta is attributable to this workload.
    _STATISTICS_PING_COUNT = 1000
    # GRO and driver receive coalescing can represent multiple echo replies in
    # one RX packet counter increment. Require at least half of the injected
    # count, which remains far above the measured ambient traffic.
    _MINIMUM_STATISTICS_PACKET_DELTA = _STATISTICS_PING_COUNT // 2
    DEBUGFS_PATH = "/sys/kernel/debug"
    # Reads are capped so a driver whose debugfs file streams without end
    # cannot hang the run. The cap sits far above the largest dump file seen
    # from any driver, so it bounds runaway reads without truncating real ones.
    DEBUGFS_READ_CAP_BYTES = 1048576
    # A single debugfs read that blocks is abandoned after this long, which
    # bounds a whole tree walk even when many files misbehave.
    DEBUGFS_READ_TIMEOUT_SECONDS = 5
    # Give a read one second to exit after TERM before `timeout` sends KILL.
    DEBUGFS_READ_KILL_GRACE_SECONDS = 1
    # Allow the tree enumeration, shell startup, and result transfer to finish
    # after accounting for the worst-case timeout of every candidate file.
    DEBUGFS_TREE_TIMEOUT_PADDING_SECONDS = 30
    # Leave ten minutes of the default one-hour case timeout for setup,
    # result parsing, assertions, and cleanup.
    DEBUGFS_TREE_MAX_TIMEOUT_SECONDS = 3000
    # `timeout` reports 124 when it has to signal the child, and 137 when that
    # signal had to be escalated to KILL. Either way the read never answered.
    DEBUGFS_READ_TIMEOUT_EXIT_CODES = (-124, -137)
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
    # Failed to rename network interface 3 from 'eth1' to 'enP45159s1': Device or resource busy # noqa: E501
    _device_rename_pattern = re.compile(
        r"Failed to rename network interface .* from '.*' "
        "to '.*': Device or resource busy",
        re.M,
    )

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        for node in environment.nodes.list():
            node.tools[Firewall].stop()
            node.features[NetworkInterface].switch_sriov(
                enable=True, wait=True, reset_connections=True
            )

    @TestCaseMetadata(
        description="""
        This case verifies all services state with Sriov enabled.

        Steps,
        1. Get overrall state from `systemctl status`, if no systemctl command,
           skip the testing
        2. The expected state should be `running`
        """,
        priority=1,
        requirement=simple_requirement(
            network_interface=features.Sriov(),
        ),
    )
    def verify_services_state(self, node: Node) -> None:
        try:
            check_till_timeout(
                lambda: node.tools[Systemctl].state() == "running",
                timeout_message="wait for systemctl status to be running",
            )
        except LisaTimeoutException:
            udevd_status = node.tools[Journalctl].logs_for_unit("systemd-udevd")
            matched = self._device_rename_pattern.search(udevd_status)
            if matched:
                raise LisaException(
                    f"{matched[0]}. "
                    "There is a race condition when rename VF nics, "
                    "it causes boot delay, it should be fixed in "
                    "systemd - 245.4-4ubuntu3.21"
                )
        except UnsupportedDistroException as e:
            raise SkippedException(e) from e

    @TestCaseMetadata(
        description="""
        This case verifies module of sriov network interface is loaded and each
         synthetic nic is paired with one VF.

        Steps,
        1. Check VF of synthetic nic is paired.
        2. Check module of sriov network device is loaded.
        3. Check VF counts listed from lspci is expected.
        """,
        priority=1,
        requirement=simple_requirement(
            min_count=2,
            network_interface=features.Sriov(),
        ),
    )
    def verify_sriov_basic(self, environment: Environment) -> None:
        initialize_nic_info(environment)
        sriov_basic_test(environment)

    @TestCaseMetadata(
        description="""
        This case verifies module of sriov network interface is loaded and
         each synthetic nic is paired with one VF, and check rx statistics of source
         and tx statistics of dest increase after send 200 Mb file from source to dest.

        Steps,
        1. Check VF of synthetic nic is paired.
        2. Check module of sriov network device is loaded.
        3. Check VF counts listed from lspci is expected.
        4. Setup SSH connection between source and dest with key authentication.
        5. Ping the dest IP from the source machine to check connectivity.
        6. Generate 200Mb file, copy from source to dest.
        7. Check rx statistics of source VF and tx statistics of dest VF is increased.
        """,
        priority=1,
        requirement=simple_requirement(
            min_count=2,
            network_interface=features.Sriov(),
        ),
    )
    def verify_sriov_single_vf_connection(self, environment: Environment) -> None:
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment)
        sriov_vf_connection_test(environment, vm_nics)

    @TestCaseMetadata(
        description="""
        This case needs 2 nodes and 64 Vcpus. And it verifies module of sriov network
         interface is loaded and each synthetic nic is paired with one VF, and check
         rx statistics of source and tx statistics of dest increase after send 200 Mb
         file from source to dest.

        Steps,
        1. Check VF of synthetic nic is paired.
        2. Check module of sriov network device is loaded.
        3. Check VF counts listed from lspci is expected.
        4. Setup SSH connection between source and dest with key authentication.
        5. Ping the dest IP from the source machine to check connectivity.
        6. Generate 200Mb file, copy from source to dest.
        7. Check rx statistics of source VF and tx statistics of dest VF is increased.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            min_core_count=64,
            network_interface=features.Sriov(),
        ),
    )
    def verify_sriov_single_vf_connection_max_cpu(
        self, environment: Environment
    ) -> None:
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment)
        sriov_vf_connection_test(environment, vm_nics)

    @TestCaseMetadata(
        description="""
        This case needs 2 nodes and max nics. And it verifies module of sriov network
         interface is loaded and each synthetic nic is paired with one VF, and check
         rx statistics of source and tx statistics of dest increase after send 200 Mb
         file from source to dest.

        Steps,
        1. Check VF of synthetic nic is paired.
        2. Check module of sriov network device is loaded.
        3. Check VF counts listed from lspci is expected.
        4. Setup SSH connection between source and dest with key authentication.
        5. Ping the dest IP from the source machine to check connectivity.
        6. Generate 200Mb file, copy from source to dest.
        7. Check rx statistics of source VF and tx statistics of dest VF is increased.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
                nic_count=search_space.IntRange(min=2, choose_max_value=True),
            ),
        ),
    )
    def verify_sriov_max_vf_connection(self, environment: Environment) -> None:
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment)
        sriov_vf_connection_test(environment, vm_nics)

    @TestCaseMetadata(
        description="""
        This case needs 2 nodes, max nics and 64 Vcpus. And it verifies module of sriov
         network interface is loaded and each synthetic nic is paired with one VF, and
         check rx statistics of source and tx statistics of dest increase after send 200
         Mb file from source to dest.

        Steps,
        1. Check VF of synthetic nic is paired.
        2. Check module of sriov network device is loaded.
        3. Check VF counts listed from lspci is expected.
        4. Setup SSH connection between source and dest with key authentication.
        5. Ping the dest IP from the source machine to check connectivity.
        6. Generate 200Mb file, copy from source to dest.
        7. Check rx statistics of source VF and tx statistics of dest VF is increased.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            min_core_count=64,
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
                nic_count=search_space.IntRange(min=2, choose_max_value=True),
            ),
        ),
    )
    def verify_sriov_max_vf_connection_max_cpu(self, environment: Environment) -> None:
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment)
        sriov_vf_connection_test(environment, vm_nics)

    @TestCaseMetadata(
        description="""
        This case verify VM works well after disable and enable accelerated network in
        network interface through sdk.

        Steps,
        1. Do the basic sriov check.
        2. Set enable_accelerated_networking as False to disable sriov.
        3. Set enable_accelerated_networking as True to enable sriov.
        4. Do the basic sriov check.
        5. Do step 2 ~ step 4 for 2 times.
        """,
        priority=1,
        requirement=simple_requirement(
            network_interface=features.Sriov(),
            supported_platform_type=[AZURE, HYPERV],
        ),
    )
    def verify_sriov_disable_enable(self, environment: Environment) -> None:
        skip_if_pci_only_nics(environment)

        sriov_disable_enable(environment)

    @TestCaseMetadata(
        description="""
        Validate one accelerated-to-synthetic-to-accelerated servicing cycle under
        uninterrupted, paced UDP and TCP traffic between two IPv4 Linux VMs.

        Establish a 120-second baseline, request AN disable on the receiver,
        hold the confirmed synthetic path for 30 seconds, then re-enable AN.
        Confirm VF receive counters increase and observe at least 30 more seconds.
        Require zero receiver-reported UDP loss, matching sent/received datagram
        counts, continuing receiver progress, and successful TCP completion.
        IP addresses, routes, and existing kernel-error state must be preserved.

        Each stream offers 1 Mbit/sec, not a capacity benchmark. Report throughput
        differences and recovery timing without a performance pass/fail threshold.
        Traffic has a 1140-second overall budget and completes naturally to preserve
        final receiver loss accounting. Individual servicing waits allow 300 seconds.
        This simulates the guest network-path transition, not host servicing.
        Save raw results, kernel diagnostics, and phase timings in the log directory.
        """,
        priority=2,
        timeout=2400,
        requirement=simple_requirement(
            min_count=2,
            network_interface=features.Sriov(),
            supported_platform_type=[AZURE],
            unsupported_os=[BSD, Windows],
        ),
    )
    def network_servicing_validation(
        self, environment: Environment, log: Logger, log_path: Path
    ) -> None:
        receiver = cast(RemoteNode, environment.nodes[0])
        sender = cast(RemoteNode, environment.nodes[1])
        nodes = [receiver, sender]
        if any(ip_address(node.internal_address).version != 4 for node in nodes):
            raise SkippedException(
                "Network servicing validation supports IPv4 only; select an "
                "IPv4 environment for NIC discovery, traffic, and route validation"
            )
        skip_if_pci_only_nics(environment)
        initialize_nic_info(environment)
        sriov_basic_test(environment)
        ports = {"udp": 5201, "tcp": 5202}
        baseline_duration = self._SERVICING_BASELINE_SECONDS
        # Budget disable, enable, and VF receive-progress waits independently.
        duration = (
            baseline_duration
            + 3 * self.TIME_OUT
            + 2 * self._SERVICING_PHASE_SECONDS
            + self._SERVICING_COMPLETION_MARGIN_SECONDS
        )
        processes: Dict[str, Process] = {}
        phases: Dict[str, Tuple[float, float]] = {}
        results: Dict[str, Dict[str, Any]] = {}
        network = receiver.features[NetworkInterface]
        original_enabled = network.is_enabled_sriov()
        routes: Dict[str, str] = {}
        kernel_errors: Dict[str, str] = {}
        for node in nodes:
            for port in ports.values():
                if node.tools[Lsof].is_port_opened(port):
                    raise SkippedException(
                        f"Servicing test port {port} is already in use on {node.name}"
                    )
        for node in nodes:
            # Finish package installation before either traffic stream starts.
            _ = node.tools[Iperf3]
            routes[node.name] = self._servicing_routes(node)
            kernel_errors[node.name] = node.tools[Dmesg].check_kernel_errors(
                force_run=True, throw_error=False
            )
            (log_path / f"{node.name}-dmesg-before.log").write_text(
                node.tools[Dmesg].get_output(force_run=True), encoding="utf-8"
            )

        baseline_vf = self._servicing_nic(receiver).lower
        assert_that(baseline_vf).described_as(
            "Receiver must have a paired VF before servicing; inspect NIC discovery"
        ).is_not_empty()
        baseline_packets = receiver.nics.get_packets(baseline_vf, "rx_packets")
        receiver.mark_dirty()
        with self._servicing_cleanup(log) as cleanup:
            cleanup.callback(self._servicing_switch, receiver, original_enabled, {})
            cleanup.callback(self._servicing_save_buffers, processes, log_path)
            for node in nodes:
                for port in ports.values():
                    cleanup.callback(self._servicing_stop_traffic, node, port)
                cleanup.callback(self._servicing_save_dmesg, node, log_path)
            for protocol, port in ports.items():
                processes[f"{protocol}_receiver"] = receiver.tools[
                    Iperf3
                ].run_as_server_async(
                    port=port,
                    report_periodic=self._SERVICING_INTERVAL_SECONDS,
                    use_json_format=True,
                    one_connection_only=True,
                    daemon=False,
                    interface_ip=receiver.internal_address,
                )
                processes[f"{protocol}_sender"] = sender.tools[
                    Iperf3
                ].run_as_client_async(
                    server_ip=receiver.internal_address,
                    client_ip=sender.internal_address,
                    port=port,
                    bitrate="1M",
                    buffer_length=1200,  # Avoid fragmentation with standard MTUs.
                    report_periodic=self._SERVICING_INTERVAL_SECONDS,
                    output_json=True,
                    udp_mode=protocol == "udp",
                    run_time_seconds=duration,
                )

            baseline_start = receiver.tools[Date].current().timestamp()
            log.info(
                f"Observing {baseline_duration} seconds of traffic before disabling AN"
            )
            self._servicing_wait(processes, baseline_duration)
            baseline_end = receiver.tools[Date].current().timestamp()
            phases["baseline"] = (baseline_start, baseline_end)
            assert_that(
                receiver.nics.get_packets(baseline_vf, "rx_packets")
            ).described_as(
                "Baseline VF must receive traffic; inspect VF counters and iperf logs"
            ).is_greater_than(
                baseline_packets
            )

            log.info("Disabling AN while UDP and TCP traffic remain active")
            disable_start = monotonic()
            synthetic_vf = self._servicing_switch(receiver, False, processes)
            disable_seconds = monotonic() - disable_start
            synthetic_start = receiver.tools[Date].current().timestamp()
            synthetic_nic = self._servicing_nic(receiver)
            assert_that(synthetic_vf).described_as(
                "VF must detach after AN disable; inspect NIC discovery and Azure state"
            ).is_empty()
            synthetic_packets = receiver.nics.get_packets(
                synthetic_nic.name, "rx_packets"
            )
            self._servicing_wait(processes, self._SERVICING_PHASE_SECONDS)
            assert_that(
                receiver.nics.get_packets(synthetic_nic.name, "rx_packets")
            ).described_as(
                "Synthetic NIC must receive traffic; inspect counters and iperf logs"
            ).is_greater_than(
                synthetic_packets
            )
            self._servicing_check_network(receiver, routes[receiver.name])
            enable_requested = receiver.tools[Date].current().timestamp()
            phases["synthetic"] = (synthetic_start, enable_requested)

            log.info("Re-enabling AN without restarting either traffic stream")
            enable_start = monotonic()
            restored_vf = self._servicing_switch(receiver, True, processes)
            vf_present_seconds = monotonic() - enable_start
            vf_present_at = receiver.tools[Date].current().timestamp()
            assert_that(restored_vf).described_as(
                "VF must return after AN enable; inspect NIC discovery and Azure state"
            ).is_not_empty()
            receive_deadline = monotonic() + self.TIME_OUT
            restored_packets = self._servicing_rx_packets(
                receiver, restored_vf, receive_deadline
            )

            def vf_receiving() -> bool:
                self._servicing_check_running(processes)
                return (
                    self._servicing_rx_packets(receiver, restored_vf, receive_deadline)
                    > restored_packets
                )

            check_till_timeout(
                vf_receiving,
                timeout_message="restored VF must receive active traffic",
                timeout=self._servicing_remaining(receive_deadline),
            )
            vf_traffic_seconds = monotonic() - enable_start
            self._servicing_wait(processes, self._SERVICING_PHASE_SECONDS)
            phases["restored"] = (
                vf_present_at,
                receiver.tools[Date].current().timestamp(),
            )
            log.info(
                f"AN disable confirmed in {disable_seconds:.3f}s; "
                f"VF restored in {vf_present_seconds:.3f}s after enable request; "
                f"VF receive progress observed in {vf_traffic_seconds:.3f}s. "
                "Waiting for natural traffic completion and receiver loss reports."
            )
            for protocol in ports:
                for role in ["sender", "receiver"]:
                    name = f"{protocol}_{role}"
                    result = processes[name].wait_result(
                        timeout=(
                            duration + self._SERVICING_EXIT_TIMEOUT
                            if role == "sender"
                            else self._SERVICING_EXIT_TIMEOUT
                        )
                    )
                    result.save_stdout_to_file(log_path / f"{name}.json")
                    result.assert_exit_code(0, include_output=True)
                    results[name] = self._servicing_iperf_result(result)
                    log.info(f"{name} completed successfully with exit code 0")

            receiver.nics.reload()
            for node in nodes:
                self._servicing_check_network(node, routes[node.name])
                errors = node.tools[Dmesg].check_kernel_errors(
                    force_run=True, throw_error=False
                )
                new_errors = set(errors.splitlines()) - set(
                    kernel_errors[node.name].splitlines()
                )
                assert_that(new_errors).described_as(
                    f"No new detected kernel errors on {node.name}; "
                    "compare before/after dmesg logs"
                ).is_empty()
                log.info(
                    f"{node.name}: internal IP {node.internal_address} and routes "
                    "unchanged; no new detected kernel errors"
                )
            sriov_basic_test(environment)
            self._servicing_report(results, phases, enable_requested, log, log_path)

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

    def _servicing_switch(
        self,
        receiver: RemoteNode,
        enable: bool,
        processes: Dict[str, Process],
    ) -> str:
        self._servicing_check_running(processes)
        nic = self._servicing_nic(receiver)
        ls = receiver.tools[Ls]
        nic_path = receiver.get_pure_path("/sys/class/net") / nic.name
        # Submit the Azure change without entering its nested guest-state retries.
        # Keep SSH open so the same traffic sessions survive the transition.
        deadline = monotonic() + self.TIME_OUT
        receiver.features[NetworkInterface].switch_sriov(
            enable=enable, wait=False, reset_connections=False
        )
        vf_name = ""

        def completed() -> bool:
            nonlocal vf_name
            self._servicing_check_running(processes)
            # One sysfs listing avoids unbounded commands inside Nics.reload().
            result = ls.run(
                f"-1 {nic_path}",
                force_run=True,
                timeout=self._servicing_remaining(deadline),
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    f"Cannot probe VF pairing on {receiver.name}; "
                    f"inspect {nic_path} and the SSH connection"
                ),
            )
            lower = [
                entry[len("lower_") :]
                for entry in result.stdout.splitlines()
                if entry.startswith("lower_")
            ]
            if lower:
                assert_that(lower).described_as(
                    f"Expected one paired VF on {receiver.name}; inspect {nic_path}"
                ).is_length(1)
            vf_name = lower[0] if lower else ""
            return bool(vf_name) == enable

        check_till_timeout(
            completed,
            timeout_message=(
                f"AN servicing enable={enable} on {receiver.name}; "
                "inspect Azure NIC state and guest VF discovery"
            ),
            timeout=self._servicing_remaining(deadline),
        )
        return vf_name

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
        self, node: RemoteNode, vf_name: str, deadline: float
    ) -> int:
        path = (
            node.get_pure_path("/sys/class/net") / vf_name / "statistics" / "rx_packets"
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
            summary["throughput"][protocol] = {
                "receiver_bps": rates,
                "restored_change_bps": rates["restored"] - rates["baseline"],
                "restored_change_percent": change,
                "five_intervals_at_90_percent_seconds_after_enable": recovery,
            }
            log.info(
                f"{protocol.upper()} receiver throughput (offered load, not capacity): "
                f"{rates}; restored change={change:+.2f}%; "
                f"five-interval 90% recovery after enable={recovery}s (diagnostic only)"
            )
        (log_path / "network_servicing_summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )

    @TestCaseMetadata(
        description="""
        This case verify VM works well after disable and enable PCI device inside VM.

        Steps,
        1. Disable sriov PCI device inside the VM.
        2. Enable sriov PCI device inside the VM.
        3. Do the basic sriov check.
        4. Do VF connection test.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            network_interface=features.Sriov(),
        ),
    )
    def verify_sriov_disable_enable_pci(self, environment: Environment) -> None:
        skip_if_pci_only_nics(environment)

        disable_enable_devices(environment)
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment)
        sriov_vf_connection_test(environment, vm_nics)

    @TestCaseMetadata(
        description="""
        This case verify VM works well after down the VF nic and up VF nic inside VM.

        Steps,
        1. Do the basic sriov check.
        2. Do network connection test with bring down the VF nic.
        3. After copy 200Mb file from source to desc.
        4. Check rx statistics of source synthetic nic and tx statistics of dest
         synthetic nic is increased.
        5. Bring up VF nic.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            network_interface=features.Sriov(),
        ),
    )
    def verify_sriov_disable_enable_on_guest(self, environment: Environment) -> None:
        skip_if_pci_only_nics(environment)

        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment)
        sriov_vf_connection_test(environment, vm_nics, turn_off_lower=True)

    @TestCaseMetadata(
        description="""
        This test case verifies if the ring buffer settings of an SR-IOV VF
        can be changed with ethtool.

        Steps:
        1. Get the current ring buffer settings of every VF on the node.
        2. Change the rx and tx value to new_values using ethtool.
        3. Get the settings again and validate the current rx and tx
           values are equal to the new_values assigned.
        4. Revert back the rx and tx value to their original values.

        This test is generated by the lisa_test_writer prompt.
        """,
        priority=2,
        maturity="preview",
        requirement=simple_requirement(
            network_interface=features.Sriov(),
            unsupported_os=[BSD, Windows],
        ),
        tags=["ai-generated"],
    )
    def verify_sriov_ethtool_ring_buffer_settings(
        self, node: Node, log: Logger
    ) -> None:
        ethtool = node.tools[Ethtool]
        vf_nics = self._get_vf_nics(node, log, "ring buffer settings")

        for vf_nic in vf_nics:
            try:
                interface_settings = ethtool.get_device_ring_buffer_settings(
                    vf_nic, force_run=True
                )
            except UnsupportedOperationException as e:
                raise SkippedException(e)

            original_rx = int(interface_settings.current_ring_buffer_settings["RX"])
            original_tx = int(interface_settings.current_ring_buffer_settings["TX"])
            max_rx = int(interface_settings.max_ring_buffer_settings["RX"])
            max_tx = int(interface_settings.max_ring_buffer_settings["TX"])

            expected_rx = self._get_supported_ring_size(original_rx, max_rx)
            expected_tx = self._get_supported_ring_size(original_tx, max_tx)

            node.mark_dirty()
            restore_required = True
            try:
                try:
                    ethtool.set_device_ring_buffer_settings(
                        vf_nic, expected_rx, expected_tx
                    )
                except UnsupportedOperationException as identifier:
                    restore_required = False
                    raise SkippedException(identifier) from identifier
                actual_settings = ethtool.get_device_ring_buffer_settings(
                    vf_nic, force_run=True
                )
                # A VF driver reports back the ring size it was given, so
                # this is an equality check rather than a range.
                assert_that(
                    int(actual_settings.current_ring_buffer_settings["RX"])
                ).described_as(
                    f"{vf_nic} did not apply the requested RX ring size."
                ).is_equal_to(
                    expected_rx
                )
                assert_that(
                    int(actual_settings.current_ring_buffer_settings["TX"])
                ).described_as(
                    f"{vf_nic} did not apply the requested TX ring size."
                ).is_equal_to(
                    expected_tx
                )
            finally:
                # Restore even when the checks above fail, so a failure does
                # not hand a resized ring to the cases that follow.
                if restore_required:
                    reverted_settings = ethtool.change_device_ring_buffer_settings(
                        vf_nic, original_rx, original_tx
                    )

            assert_that(
                int(reverted_settings.current_ring_buffer_settings["RX"])
            ).described_as(
                f"{vf_nic} RX ring size was not restored to its original value."
            ).is_equal_to(
                original_rx
            )
            assert_that(
                int(reverted_settings.current_ring_buffer_settings["TX"])
            ).described_as(
                f"{vf_nic} TX ring size was not restored to its original value."
            ).is_equal_to(
                original_tx
            )

    def _get_vf_nics(self, node: Node, log: Logger, purpose: str) -> List[str]:
        node.nics.reload()
        # A VF is reachable either standalone or as the lower device of a
        # synthetic NIC, so select on AN being enabled and let pci_device_name
        # resolve to whichever applies. Every VF is returned, so a multi vport
        # VM is validated end to end.
        vf_nics = list(
            dict.fromkeys(
                nic.pci_device_name
                for nic in node.nics.nics.values()
                if nic.is_pci_module_enabled and not nic.is_infiniband
            )
        )
        if not vf_nics:
            raise SkippedException(
                f"No SR-IOV VF interface found on the node, {purpose} "
                "cannot be validated."
            )
        log.info(f"Validating {purpose} on VF interfaces {vf_nics}")
        return vf_nics

    def _get_supported_ring_size(self, current: int, maximum: int) -> int:
        # One step rather than the maximum: rings are preallocated, so the
        # maximum can cost about 1 GB on a 32 queue VF and fail on -ENOMEM.
        # Powers of two because a driver may round the request up to one.
        if maximum <= 0:
            raise SkippedException(
                f"The VF reports a non-tunable ring maximum of {maximum}; "
                "there is no supported alternate ring size to validate."
            )
        ceiling = 1 << (maximum.bit_length() - 1)
        step_up = 1 << current.bit_length()
        if step_up <= ceiling:
            candidate = step_up
        else:
            # Already at the largest power of two the device allows.
            candidate = max(ceiling // 2, 1)
        if candidate == current:
            raise SkippedException(
                f"The VF ring is fixed at {current}; there is no supported "
                "alternate ring size to validate."
            )
        return candidate

    def _require_device_up(self, ip: Ip, vf_nic: str, log: Logger) -> None:
        # Several ethtool set operations, RSS in particular, are rejected with
        # EOPNOTSUPP while the port is down, so the interface has to be up
        # before the settings are exercised.
        if ip.is_device_up(vf_nic):
            return
        log.info(f"{vf_nic} is down, bringing it up before changing its settings.")
        ip.node.mark_dirty()
        ip.up(vf_nic)
        check_till_timeout(
            lambda: ip.is_device_up(vf_nic) is True,
            timeout_message=f"{vf_nic} did not come up, its settings cannot be "
            "changed while the port is down.",
        )

    @TestCaseMetadata(
        description="""
        This case verifies the SR-IOV VF driver reports and applies its RSS hash
        key correctly.

        The RSS hash key determines how received traffic is spread across
        queues. Operators change it to alter that distribution, so it must
        round-trip exactly.

        Steps,
        1. Get the VF interface and read its current RSS hash key.
        2. Verify the key is a valid colon-separated sequence of bytes.
        3. Set a new hash key of the same length and read it back.
        4. Verify the key read back matches the key written exactly.
        5. Restore the original hash key and verify the interface remains up.

        This test is generated by the lisa_test_writer prompt.
        """,
        priority=2,
        maturity="preview",
        requirement=simple_requirement(
            network_interface=features.Sriov(),
            unsupported_os=[BSD, Windows],
        ),
        tags=["ai-generated"],
    )
    def verify_sriov_ethtool_rss_hash_key(self, node: Node, log: Logger) -> None:
        ethtool = node.tools[Ethtool]
        ip = node.tools[Ip]

        vf_nics = self._get_vf_nics(node, log, "RSS hash key")

        node.mark_dirty()
        for vf_nic in vf_nics:
            self._verify_vf_rss_hash_key(ethtool, ip, vf_nic, log)

    def _verify_vf_rss_hash_key(
        self, ethtool: Ethtool, ip: Ip, vf_nic: str, log: Logger
    ) -> None:
        device_was_up = ip.is_device_up(vf_nic)
        try:
            self._require_device_up(ip, vf_nic, log)
            try:
                original = ethtool.get_device_rss_hash_key(vf_nic, force_run=True)
            except UnsupportedOperationException as identifier:
                raise SkippedException(identifier) from identifier

            original_key = original.rss_hash_key.lower()
            log.debug(f"{vf_nic} RSS hash key: {original_key}")
            assert_that(original_key).described_as(
                f"{vf_nic} reported an empty RSS hash key, the VF driver does not "
                "expose the key that steers received traffic."
            ).is_not_empty()

            key_bytes = original_key.split(":")
            malformed = [item for item in key_bytes if len(item) != 2]
            assert_that(malformed).described_as(
                f"{vf_nic} RSS hash key contains fields that are not single "
                f"hex bytes: {malformed}."
            ).is_empty()

            new_key = self._get_alternate_hash_key(key_bytes)
            log.info(f"Setting {vf_nic} RSS hash key to {new_key}")
            restore_required = True
            try:
                try:
                    ethtool.set_device_rss_hash_key(vf_nic, new_key)
                except UnsupportedOperationException as identifier:
                    restore_required = False
                    raise SkippedException(identifier) from identifier
                changed = ethtool.get_device_rss_hash_key(vf_nic, force_run=True)
                assert_that(changed.rss_hash_key.lower()).described_as(
                    f"{vf_nic} did not apply the RSS hash key exactly as written, "
                    "the key does not round-trip through the driver."
                ).is_equal_to(new_key)
            finally:
                if restore_required:
                    log.info(f"Restoring {vf_nic} RSS hash key to {original_key}")
                    restored = ethtool.change_device_rss_hash_key(vf_nic, original_key)

            assert_that(restored.rss_hash_key.lower()).described_as(
                f"{vf_nic} RSS hash key was not restored to its original value."
            ).is_equal_to(original_key)
            assert_that(ip.is_device_up(vf_nic)).described_as(
                f"{vf_nic} is not up after restoring the RSS hash key."
            ).is_true()
            log.info(f"RSS hash key of {vf_nic} validated and restored.")
        finally:
            if ip.is_device_up(vf_nic) != device_was_up:
                original_state = "up" if device_was_up else "down"
                log.info(f"Restoring {vf_nic} to its original {original_state} state.")
                if device_was_up:
                    ip.up(vf_nic)
                else:
                    ip.down(vf_nic)

    def _get_alternate_hash_key(self, key_bytes: List[str]) -> str:
        # Reversing keeps the exact byte count the driver expects. A
        # palindromic key would map to itself and make the round-trip check
        # meaningless, so flip the first byte in that case.
        new_bytes = list(reversed(key_bytes))
        if new_bytes == key_bytes:
            new_bytes[0] = f"{int(new_bytes[0], 16) ^ 0xFF:02x}"
        return ":".join(new_bytes)

    @TestCaseMetadata(
        description="""
        This case verifies the SR-IOV VF driver reports its RSS indirection
        table and accepts a valid redistribution across receive queues.

        The indirection table maps hash buckets to receive queues. The driver
        must report a consistent table and reject entries pointing at queues
        that do not exist.

        Steps,
        1. Get the VF interface and read its RSS indirection table.
        2. Verify the parsed rows are complete and every entry indexes a valid
           receive queue.
        3. Redistribute the table evenly across a subset of queues and verify
           it is applied.
        4. Try to redistribute across more queues than the device has and
           verify it is rejected.
          5. If the original table is the driver default, restore that default and
              verify it matches the original table exactly.

        This test is generated by the lisa_test_writer prompt.
        """,
        priority=2,
        maturity="preview",
        requirement=simple_requirement(
            network_interface=features.Sriov(),
            unsupported_os=[BSD, Windows],
        ),
        tags=["ai-generated"],
    )
    def verify_sriov_ethtool_rss_indirection_table(
        self, node: Node, log: Logger
    ) -> None:
        ethtool = node.tools[Ethtool]
        ip = node.tools[Ip]

        vf_nics = self._get_vf_nics(node, log, "RSS indirection table")

        node.mark_dirty()
        for vf_nic in vf_nics:
            self._verify_vf_rss_indirection_table(ethtool, ip, vf_nic, log)

    def _verify_vf_rss_indirection_table(
        self, ethtool: Ethtool, ip: Ip, vf_nic: str, log: Logger
    ) -> None:
        device_was_up = ip.is_device_up(vf_nic)
        try:
            self._require_device_up(ip, vf_nic, log)
            try:
                original = ethtool.get_device_rss_indirection_table(
                    vf_nic, force_run=True
                )
            except UnsupportedOperationException as identifier:
                raise SkippedException(identifier) from identifier

            ring_count = original.rx_ring_count
            log.debug(
                f"{vf_nic} RSS indirection table holds {len(original.table)} "
                f"entries across {ring_count} RX ring(s)"
            )

            # The entry count and RX ring count are different numbers in the
            # same output, so each is checked against its own source.
            assert_that(original.table).described_as(
                f"{vf_nic} returned an RSS indirection table whose entry count "
                f"disagrees with the {original.indirection_size} entries its own "
                "row offsets report."
            ).is_length(original.indirection_size)
            assert_that(ring_count).described_as(
                f"{vf_nic} reported zero RX rings, the indirection table cannot "
                "reference any receive queue."
            ).is_greater_than(0)
            out_of_range = sorted(
                {entry for entry in original.table if entry < 0 or entry >= ring_count}
            )
            assert_that(out_of_range).described_as(
                f"{vf_nic} RSS indirection table points at receive queues that "
                f"do not exist, the device has {ring_count} RX ring(s)."
            ).is_empty()

            if ring_count < 2:
                raise SkippedException(
                    f"{vf_nic} exposes {ring_count} RX ring, the indirection table "
                    "cannot be redistributed across a subset of queues."
                )

            default_table = [index % ring_count for index in range(len(original.table))]
            if original.table != default_table:
                raise SkippedException(
                    f"{vf_nic} starts with a custom RSS indirection table. "
                    "ethtool can restore the driver default but cannot replay "
                    "an arbitrary bucket table, so the test will not mutate it."
                )

            target_queues = ring_count // 2
            try:
                self._redistribute_indirection_table(
                    ethtool, vf_nic, target_queues, log
                )
                self._reject_oversized_indirection_table(
                    ethtool, vf_nic, ring_count, log
                )
            finally:
                log.info(f"Restoring {vf_nic} RSS indirection table to the default")
                restored = ethtool.change_device_rss_indirection_table(
                    vf_nic, "default"
                )

            assert_that(restored.table).described_as(
                f"{vf_nic} RSS indirection table was not restored to the driver "
                "default it reported before the test."
            ).is_equal_to(original.table)
            assert_that(ip.is_device_up(vf_nic)).described_as(
                f"{vf_nic} is not up after restoring the RSS indirection table."
            ).is_true()
            log.info(f"RSS indirection table of {vf_nic} validated and restored.")
        finally:
            if ip.is_device_up(vf_nic) != device_was_up:
                original_state = "up" if device_was_up else "down"
                log.info(f"Restoring {vf_nic} to its original {original_state} state.")
                if device_was_up:
                    ip.up(vf_nic)
                else:
                    ip.down(vf_nic)

    def _redistribute_indirection_table(
        self, ethtool: Ethtool, vf_nic: str, target_queues: int, log: Logger
    ) -> None:
        log.info(
            f"Spreading {vf_nic} RSS indirection table evenly across "
            f"{target_queues} receive queue(s)"
        )
        changed = ethtool.change_device_rss_indirection_table(
            vf_nic, f"equal {target_queues}"
        )
        assert_that(sorted(set(changed.table))).described_as(
            f"{vf_nic} did not restrict the RSS indirection table to the first "
            f"{target_queues} receive queue(s)."
        ).is_equal_to(list(range(target_queues)))

        occurrences = [changed.table.count(queue) for queue in range(target_queues)]
        assert_that(max(occurrences) - min(occurrences)).described_as(
            f"{vf_nic} spread the RSS indirection table unevenly across "
            f"{target_queues} queue(s), entries per queue: {occurrences}."
        ).is_less_than_or_equal_to(1)

    def _reject_oversized_indirection_table(
        self, ethtool: Ethtool, vf_nic: str, ring_count: int, log: Logger
    ) -> None:
        before = ethtool.get_device_rss_indirection_table(vf_nic, force_run=True)
        too_many = ring_count + 1
        log.info(
            f"Spreading {vf_nic} RSS indirection table across {too_many} queues, "
            "it is expected to fail."
        )
        result = ethtool.set_device_rss_indirection_table(vf_nic, f"equal {too_many}")
        assert_that(result.exit_code).described_as(
            f"{vf_nic} accepted an RSS indirection table spread across "
            f"{too_many} queues while the device exposes only {ring_count} RX "
            "ring(s), entries pointing at a missing queue drop traffic."
        ).is_not_equal_to(0)

        after = ethtool.get_device_rss_indirection_table(vf_nic, force_run=True)
        assert_that(after.table).described_as(
            f"{vf_nic} RSS indirection table changed after a rejected request."
        ).is_equal_to(before.table)

    @TestCaseMetadata(
        description="""
        This case verifies the SR-IOV VF driver reports and applies receive CQE
        coalescing settings correctly.

        CQE coalescing reduces completion traffic by representing several
        received frames with one completion entry. The driver must apply valid
        group sizes and reject values outside its supported modes.

        Steps,
        1. Get every VF interface and read its receive CQE coalescing setting.
        2. Change the setting to another value accepted by the driver and
           verify the value is reported back.
        3. Try an unsupported value and verify it is rejected without changing
           the active setting.
        4. Restore the original setting and interface state.

        This test is generated by the lisa_test_writer prompt.
        """,
        priority=2,
        maturity="preview",
        requirement=simple_requirement(
            network_interface=features.Sriov(),
            unsupported_os=[BSD, Windows],
        ),
        tags=["ai-generated"],
    )
    def verify_sriov_ethtool_coalesce_settings(self, node: Node, log: Logger) -> None:
        ethtool = node.tools[Ethtool]
        ip = node.tools[Ip]
        vf_nics = self._get_vf_nics(node, log, "receive CQE coalescing settings")

        node.mark_dirty()
        for vf_nic in vf_nics:
            self._verify_vf_coalesce_settings(ethtool, ip, vf_nic, log)

    def _verify_vf_coalesce_settings(
        self, ethtool: Ethtool, ip: Ip, vf_nic: str, log: Logger
    ) -> None:
        parameter = self.COALESCE_PARAMETER
        device_was_up = ip.is_device_up(vf_nic)
        try:
            self._require_device_up(ip, vf_nic, log)
            # An older client cannot distinguish a missing netlink attribute
            # from missing driver support, so select a capable client first.
            if not ethtool.supports_rx_cqe_frames():
                log.info(
                    f"The installed ethtool does not expose {parameter}; building "
                    "a release that supports the kernel attribute."
                )
                try:
                    ethtool.ensure_rx_cqe_frames_support()
                except UnsupportedDistroException as identifier:
                    raise SkippedException(identifier) from identifier

            try:
                original = ethtool.get_device_coalesce_settings(vf_nic, force_run=True)
            except UnsupportedOperationException as identifier:
                raise SkippedException(identifier) from identifier

            log.debug(
                f"{vf_nic} coalescing settings: {original.settings}; "
                f"not applicable: {original.not_applicable}"
            )
            if parameter not in original.settings:
                raise SkippedException(
                    f"{vf_nic} does not expose {parameter} as a numeric tunable. "
                    f"It reports {sorted(original.settings)} as numeric and "
                    f"{original.not_applicable} as not applicable."
                )
            original_value = original.settings[parameter]

            try:
                target = self._set_alternate_coalesce_value(
                    ethtool, vf_nic, original_value
                )
                log.info(
                    f"Changed {vf_nic} {parameter} from {original_value} to {target}"
                )
                changed = ethtool.get_device_coalesce_settings(vf_nic, force_run=True)
                assert_that(changed.settings[parameter]).described_as(
                    f"{vf_nic} accepted {parameter}={target} but did not report "
                    "the value as active."
                ).is_equal_to(target)

                self._reject_invalid_coalesce_value(
                    ethtool, vf_nic, parameter, target, log
                )
            finally:
                log.info(f"Restoring {vf_nic} {parameter} to {original_value}")
                ethtool.set_device_coalesce_setting(
                    vf_nic, parameter, original_value
                ).assert_exit_code(
                    message=f"Couldn't restore {vf_nic} {parameter} to "
                    f"{original_value}. Inspect the driver and ethtool error "
                    "output."
                )

            restored = ethtool.get_device_coalesce_settings(vf_nic, force_run=True)
            assert_that(restored.settings[parameter]).described_as(
                f"{vf_nic} {parameter} was not restored to its original value."
            ).is_equal_to(original_value)
            assert_that(ip.is_device_up(vf_nic)).described_as(
                f"{vf_nic} is not up after restoring its CQE coalescing setting."
            ).is_true()
            log.info(f"CQE coalescing setting of {vf_nic} validated and restored.")
        finally:
            if ip.is_device_up(vf_nic) != device_was_up:
                original_state = "up" if device_was_up else "down"
                log.info(f"Restoring {vf_nic} to its original {original_state} state.")
                if device_was_up:
                    ip.up(vf_nic)
                else:
                    ip.down(vf_nic)

    def _set_alternate_coalesce_value(
        self, ethtool: Ethtool, vf_nic: str, original_value: int
    ) -> int:
        parameter = self.COALESCE_PARAMETER
        for candidate in self.COALESCE_CANDIDATES:
            if candidate == original_value:
                continue
            result = ethtool.set_device_coalesce_setting(vf_nic, parameter, candidate)
            if result.exit_code == 0:
                return candidate
            output = f"{result.stdout}\n{result.stderr}".lower()
            if not any(
                pattern in output for pattern in self.COALESCE_VALUE_REJECTION_PATTERNS
            ):
                result.assert_exit_code(
                    message=(
                        f"Couldn't set {vf_nic} {parameter} to {candidate}. "
                        "Verify the driver exposes this setting through ethtool "
                        "netlink and inspect the command output."
                    ),
                    include_output=True,
                )
            after_rejection = ethtool.get_device_coalesce_settings(
                vf_nic, force_run=True
            )
            assert_that(after_rejection.settings.get(parameter)).described_as(
                f"{vf_nic} {parameter} changed after rejecting candidate "
                f"{candidate}."
            ).is_equal_to(original_value)

        raise SkippedException(
            f"{vf_nic} accepted none of the alternate {parameter} values "
            f"{self.COALESCE_CANDIDATES}; there is no driver-independent way "
            "to infer another supported value."
        )

    def _reject_invalid_coalesce_value(
        self,
        ethtool: Ethtool,
        vf_nic: str,
        parameter: str,
        expected_value: int,
        log: Logger,
    ) -> None:
        log.info(
            f"Setting {vf_nic} {parameter} to {self.INVALID_COALESCE_VALUE}; "
            "the request is expected to fail."
        )
        invalid = ethtool.set_device_coalesce_setting(
            vf_nic, parameter, self.INVALID_COALESCE_VALUE
        )
        assert_that(invalid.exit_code).described_as(
            f"{vf_nic} accepted {parameter}={self.INVALID_COALESCE_VALUE}, which "
            "is outside the parameter's u32 range."
        ).is_not_equal_to(0)

        after_invalid = ethtool.get_device_coalesce_settings(vf_nic, force_run=True)
        assert_that(after_invalid.settings[parameter]).described_as(
            f"{vf_nic} {parameter} changed after a rejected request."
        ).is_equal_to(expected_value)

    @TestCaseMetadata(
        description="""
        This case verifies the SR-IOV VF driver reports and applies its combined
        channel count correctly.

        Channel count controls how many queue pairs the NIC uses and how work
        spreads across CPUs. Changing it rebuilds the datapath, so it must leave
        a working interface behind.

        Steps,
        1. Get the VF interface and read its channel configuration.
        2. Verify the effective maximum is non-zero and the current count does
           not exceed it.
        3. Set every combined channel count from one through the effective
           maximum and verify each value is applied.
        4. Verify the interface still passes traffic.
        5. Restore the original channel count and verify it is applied.

        This test is generated by the lisa_test_writer prompt.
        """,
        priority=2,
        maturity="preview",
        requirement=simple_requirement(
            min_count=2,
            network_interface=features.Sriov(),
            unsupported_os=[BSD, Windows],
        ),
        tags=["ai-generated"],
    )
    def verify_sriov_ethtool_channels(
        self, environment: Environment, log: Logger
    ) -> None:
        node = cast(RemoteNode, environment.nodes[0])
        ethtool = node.tools[Ethtool]

        vf_nics = self._get_vf_nics(node, log, "channel configuration")

        original_counts: Dict[str, int] = {}
        restoration_failures: List[str] = []
        try:
            for vf_nic in vf_nics:
                try:
                    original = ethtool.get_device_channels_info(vf_nic, force_run=True)
                except UnsupportedOperationException as identifier:
                    raise SkippedException(identifier) from identifier

                # Schedule the restore before changing the device. A command
                # can succeed while its readback assertion fails.
                original_counts[vf_nic] = original.current_channels
                node.mark_dirty()
                self._verify_vf_channel_counts(
                    ethtool,
                    vf_nic,
                    original.current_channels,
                    original.max_channels,
                    log,
                    original_counts,
                )
            # The rebuilt datapath has to keep carrying traffic on every VF.
            vm_nics = initialize_nic_info(environment)
            sriov_vf_connection_test(environment, vm_nics)
        finally:
            for vf_nic, original_count in original_counts.items():
                try:
                    restored = ethtool.change_device_channels_info(
                        vf_nic, original_count
                    )
                    if restored.current_channels != original_count:
                        message = (
                            f"{vf_nic} combined channel count was not restored "
                            f"to its original value {original_count}; the driver "
                            f"reported {restored.current_channels}. Inspect the "
                            "driver and ethtool output."
                        )
                        log.error(message)
                        restoration_failures.append(message)
                except (AssertionError, LisaException) as identifier:
                    message = (
                        f"Failed to restore {vf_nic} combined channel count to "
                        f"{original_count}: {identifier}. Inspect the driver and "
                        "ethtool output."
                    )
                    log.error(message)
                    restoration_failures.append(message)

            assert_that(restoration_failures).described_as(
                "One or more SR-IOV VFs retained a modified channel count after "
                "all restoration attempts."
            ).is_empty()
        log.info(f"Channel configuration of {vf_nics} validated and restored.")

    def _verify_vf_channel_counts(
        self,
        ethtool: Ethtool,
        vf_nic: str,
        current: int,
        effective_maximum: int,
        log: Logger,
        original_counts: Dict[str, int],
    ) -> None:
        # Ethtool caps max_channels at the node's vCPU count, so it is an
        # effective ceiling rather than the driver's raw advertised maximum.
        log.debug(
            f"{vf_nic} combined channels current/effective maximum: "
            f"{current}/{effective_maximum}"
        )

        assert_that(effective_maximum).described_as(
            f"{vf_nic} reported a zero effective maximum combined channel "
            "count, so the VF driver does not expose a tunable channel count."
        ).is_greater_than(0)
        assert_that(current).described_as(
            f"{vf_nic} current combined channel count exceeds the vCPU-capped "
            "effective maximum."
        ).is_less_than_or_equal_to(effective_maximum)

        if effective_maximum <= 1:
            original_counts.pop(vf_nic, None)
            raise SkippedException(
                f"{vf_nic} has an effective maximum of {effective_maximum} "
                "combined channel, so there is no alternate count to validate."
            )

        for new_channels in range(1, effective_maximum + 1):
            log.info(f"Setting {vf_nic} combined channels to {new_channels}")
            try:
                ethtool.set_device_channels_info(vf_nic, new_channels)
            except UnsupportedOperationException as identifier:
                if new_channels == 1:
                    original_counts.pop(vf_nic, None)
                    raise SkippedException(identifier) from identifier
                raise
            changed = ethtool.get_device_channels_info(vf_nic, force_run=True)
            assert_that(changed.current_channels).described_as(
                f"{vf_nic} did not apply combined channel count {new_channels}."
            ).is_equal_to(new_channels)

    @TestCaseMetadata(
        description="""
        This case verifies the SR-IOV VF driver reports per-queue statistics
        correctly.

        Driver statistics are the first thing checked when diagnosing packet
        loss or throughput problems, so the counter set must be complete,
        consistently named, and must advance by the known packet count when
        controlled traffic flows through the VF.

        Steps,
        1. Read statistics from every VF interface.
        2. Verify that every statistic has a name and value, and that RX and TX
           per-queue packet counters are present.
        3. Record a baseline snapshot of the counters.
        4. Send 1,000 successful echo requests and replies through each VF.
        5. Verify the packet counters advance beyond background traffic.

        This test is generated by the lisa_test_writer prompt.
        """,
        priority=2,
        maturity="preview",
        requirement=simple_requirement(
            min_count=2,
            network_interface=features.Sriov(),
            unsupported_os=[BSD, Windows],
        ),
        tags=["ai-generated"],
    )
    def verify_sriov_ethtool_statistics(
        self, environment: Environment, log: Logger
    ) -> None:
        node = cast(RemoteNode, environment.nodes[0])
        ethtool = node.tools[Ethtool]

        vf_nics = self._get_vf_nics(node, log, "device statistics")
        baselines = {
            vf_nic: self._verify_vf_statistics_shape(ethtool, vf_nic, log)
            for vf_nic in vf_nics
        }

        for affected_node in environment.nodes.list():
            affected_node.mark_dirty()
        vm_nics = initialize_nic_info(environment)
        for vf_nic in vf_nics:
            self._send_vf_statistics_traffic(environment, vm_nics, vf_nic)

        for vf_nic, baseline in baselines.items():
            self._verify_vf_statistics_advanced(ethtool, vf_nic, baseline, log)

    def _send_vf_statistics_traffic(
        self,
        environment: Environment,
        vm_nics: Dict[str, Dict[str, NicInfo]],
        vf_nic: str,
    ) -> None:
        source_node = cast(RemoteNode, environment.nodes[0])
        destination_node = cast(RemoteNode, environment.nodes[1])
        source_info = next(
            (
                nic
                for nic in vm_nics[source_node.name].values()
                if nic.pci_device_name == vf_nic and nic.ip_addr
            ),
            None,
        )
        assert_that(source_info).described_as(
            f"No IP-bearing synthetic interface is paired with VF {vf_nic} "
            f"on {source_node.name}. Inspect the Accelerated Networking pairing."
        ).is_not_none()
        source_info = cast(NicInfo, source_info)

        # Azure test networks use an IPv4 /24 for each primary NIC subnet.
        source_subnet = source_info.ip_addr.rsplit(".", maxsplit=1)[0]
        destination_info = next(
            (
                nic
                for nic in vm_nics[destination_node.name].values()
                if not nic.is_infiniband
                and nic.ip_addr
                and nic.ip_addr.rsplit(".", maxsplit=1)[0] == source_subnet
            ),
            None,
        )
        assert_that(destination_info).described_as(
            f"No destination interface on {destination_node.name} shares the "
            f"subnet of {source_info.ip_addr}. Inspect the test network topology."
        ).is_not_none()
        destination_info = cast(NicInfo, destination_info)

        source_node.tools[Ping].ping(
            target=destination_info.ip_addr,
            nic_name=source_info.name,
            count=self._STATISTICS_PING_COUNT,
            # A short interval keeps 1,000 controlled packets bounded to about
            # ten seconds while sudo permits Linux intervals below 200 ms.
            interval=0.01,
            # Stay below the standard Ethernet MTU while exercising non-trivial
            # payload accounting on every request and reply.
            package_size=1400,
            sudo=True,
        )

    def _verify_vf_statistics_shape(
        self, ethtool: Ethtool, vf_nic: str, log: Logger
    ) -> Dict[str, int]:
        try:
            statistics = ethtool.get_device_statistics(vf_nic, force_run=True)
        except UnsupportedOperationException as identifier:
            raise SkippedException(identifier) from identifier

        # A driver whose ETH_SS_STATS string table is shorter than the value
        # array it reports prints trailing entries with an empty name. Those
        # all parse to the same empty key, so they collapse into a single
        # counter and have to be counted in the raw output instead. This is
        # checked first because shifted names would misattribute later deltas.
        unnamed = self._count_unnamed_counters(statistics.raw_output)
        assert_that(unnamed).described_as(
            f"{vf_nic} printed {unnamed} statistics with an empty name, so the "
            "VF driver's ethtool string table is shorter than the value array "
            "it reports. Inspect the driver string and statistics tables."
        ).is_equal_to(0)

        counters = {name: value for name, value in statistics.counters.items() if name}
        assert_that(counters).described_as(
            f"{vf_nic} reported no statistics. Verify the VF driver implements "
            "ethtool statistics and inspect the ethtool output."
        ).is_not_empty()

        valueless = self._get_valueless_counters(statistics.raw_output, counters)
        assert_that(valueless).described_as(
            f"{vf_nic} reported statistics without a readable value: {valueless}. "
            "Inspect the driver statistics output and string table."
        ).is_empty()

        rx_per_queue = [
            name
            for name in counters
            if self._RX_QUEUE_PACKET_COUNTER_PATTERN.search(name)
        ]
        tx_per_queue = [
            name
            for name in counters
            if self._TX_QUEUE_PACKET_COUNTER_PATTERN.search(name)
        ]
        assert_that(rx_per_queue).described_as(
            f"{vf_nic} reported no RX per-queue packet counters. Verify the VF "
            "driver exposes queue statistics for receive-path diagnosis."
        ).is_not_empty()
        assert_that(tx_per_queue).described_as(
            f"{vf_nic} reported no TX per-queue packet counters. Verify the VF "
            "driver exposes queue statistics for transmit-path diagnosis."
        ).is_not_empty()

        log.debug(
            f"{vf_nic} exposes {len(counters)} counters, including "
            f"{len(rx_per_queue)} RX and {len(tx_per_queue)} TX queue packet "
            "counters"
        )
        return dict(counters)

    def _count_unnamed_counters(self, raw_output: str) -> int:
        unnamed = 0
        for line in raw_output.splitlines():
            stripped = line.strip()
            if not stripped or stripped == "NIC statistics:":
                continue
            name, separator, _ = stripped.partition(":")
            if separator and not name.strip():
                unnamed += 1
        return unnamed

    def _get_valueless_counters(
        self, raw_output: str, counters: Dict[str, int]
    ) -> List[str]:
        valueless: List[str] = []
        for line in raw_output.splitlines():
            stripped = line.strip()
            if not stripped or stripped == "NIC statistics:":
                continue
            name, separator, _ = stripped.partition(":")
            if separator and name.strip() not in counters:
                valueless.append(stripped)
        return valueless

    def _verify_vf_statistics_advanced(
        self,
        ethtool: Ethtool,
        vf_nic: str,
        baseline: Dict[str, int],
        log: Logger,
    ) -> None:
        delta = ethtool.get_device_statistics_delta(vf_nic, baseline)
        rx_delta = sum(
            value
            for name, value in delta.items()
            if self._RX_QUEUE_PACKET_COUNTER_PATTERN.search(name)
        )
        tx_delta = sum(
            value
            for name, value in delta.items()
            if self._TX_QUEUE_PACKET_COUNTER_PATTERN.search(name)
        )
        log.debug(
            f"{vf_nic} per-queue packet counter delta RX/TX: " f"{rx_delta}/{tx_delta}"
        )

        assert_that(rx_delta).described_as(
            f"{vf_nic} RX per-queue packet counters advanced by only {rx_delta} "
            f"after {self._STATISTICS_PING_COUNT} successful echo replies. Verify "
            "traffic traverses the VF and the driver accounts received packets."
        ).is_greater_than_or_equal_to(self._MINIMUM_STATISTICS_PACKET_DELTA)
        assert_that(tx_delta).described_as(
            f"{vf_nic} TX per-queue packet counters advanced by only {tx_delta} "
            f"after {self._STATISTICS_PING_COUNT} successful echo requests. Verify "
            "traffic traverses the VF and the driver accounts transmitted packets."
        ).is_greater_than_or_equal_to(self._MINIMUM_STATISTICS_PACKET_DELTA)
        log.info(f"Statistics of {vf_nic} validated after traffic.")

    @TestCaseMetadata(
        description="""
        This case verifies that whatever the SR-IOV VF driver exposes in
        debugfs can actually be read back. debugfs is the primary first-look
        diagnostic when a VF misbehaves in production, so a file that is
        published there and then refuses to answer is a defect in the driver
        regardless of what it was meant to report.

        Steps,
        1. Ensure debugfs is mounted at /sys/kernel/debug.
        2. Identify the SR-IOV VF and resolve its bound driver from sysfs.
         If no driver is bound, fail when the kernel logged a probe failure
         against the VF, since a driver was present and refused it and the
         VM has lost accelerated networking, and skip when it logged none,
         since no driver in this kernel claims the VF at all.
        3. Locate the driver's debugfs directory. Skip if it exposes none,
         since the driver then implements no debugfs diagnostics at all.
        4. Read every readable regular file in that tree, with each read
         bounded by a byte cap and a timeout. Write-only nodes, such as
         command-staging interfaces, are not read.
        5. Skip if the tree holds no readable file, every file comes back
         empty, or every content read is refused. These cases provide no
         diagnostic content to validate.
        6. Assert that no read hung. A read that returns an error is logged
         rather than asserted on, since some entries are command interfaces
         that answer only once a command has been staged through them, and
         since a kernel in lockdown refuses any debugfs file that is not
         read-only. A read that never answers has no such innocent
         explanation and blocks whoever is diagnosing the VF.

        This test is generated by the lisa_test_writer prompt.
        """,
        priority=2,
        maturity="preview",
        requirement=simple_requirement(
            network_interface=features.Sriov(),
            # debugfs is a Linux kernel filesystem, so there is nothing for
            # this case to inspect on any other OS.
            unsupported_os=[BSD, Windows],
        ),
        tags=["ai-generated"],
    )
    def verify_sriov_debugfs_diagnostics(self, node: Node, log: Logger) -> None:
        mount = node.tools[Mount]
        if not mount.check_mount_point_exist(self.DEBUGFS_PATH):
            log.info("mounting debugfs for SR-IOV diagnostics")
            try:
                mount.mount(
                    name="debugfs",
                    point=self.DEBUGFS_PATH,
                    fs_type=FileSystem.debugfs,
                )
            except AssertionError as error:
                raise SkippedException(
                    f"unable to mount debugfs at {self.DEBUGFS_PATH}: {error}. "
                    "Verify the kernel is built with CONFIG_DEBUG_FS."
                ) from error
            if not mount.check_mount_point_exist(self.DEBUGFS_PATH):
                raise SkippedException(
                    f"debugfs is not mounted at {self.DEBUGFS_PATH} after "
                    "mount attempt. Verify the kernel is built with "
                    "CONFIG_DEBUG_FS."
                )

        vf_slots = node.tools[Lspci].get_device_names_by_type(
            constants.DEVICE_TYPE_SRIOV, force_run=True
        )
        assert_that(vf_slots).described_as(
            "an SR-IOV VF PCI device must be present to inspect its debugfs "
            "diagnostics"
        ).is_not_empty()
        vf_slot = vf_slots[0]

        # A logged probe failure means a driver refused the VF and the VM has
        # lost accelerated networking. Silence means no driver ever claimed
        # it, so this kernel predates the VF.
        ls = node.tools[Ls]
        driver_link = f"/sys/bus/pci/devices/{vf_slot}/driver"
        if not ls.path_exists(driver_link, sudo=True):
            modalias = node.tools[Cat].read(
                f"/sys/bus/pci/devices/{vf_slot}/modalias",
                sudo=True,
                force_run=True,
            )
            probe_failures = [
                line
                for line in node.tools[Dmesg].get_output(force_run=True).splitlines()
                if vf_slot in line and "probe of" in line and "failed" in line
            ]
            if not probe_failures:
                raise SkippedException(
                    f"SR-IOV VF {vf_slot} (modalias {modalias}) has no driver "
                    "bound to it and the kernel logged no probe failure "
                    "against it, so no driver in this kernel claims the VF "
                    "and the distro predates it."
                )
            raise LisaException(
                f"SR-IOV VF {vf_slot} (modalias {modalias}) has no driver "
                "bound to it because its driver probe failed, so the VM has "
                f"lost accelerated networking: {probe_failures[-1]}"
            )

        driver_path = node.tools[Readlink].get_canonical_path(driver_link, sudo=True)
        driver_name = PurePosixPath(driver_path).name

        # The driver's debugfs tree is always rooted directly under
        # /sys/kernel/debug/<name>. Some drivers register under a shortened
        # module name that drops a trailing component naming the sub-driver,
        # so every prefix of the module name is tried, longest first, rather
        # than a fixed list of suffixes that only covers known drivers.
        parts = driver_name.split("_")
        candidates = ["_".join(parts[:count]) for count in range(len(parts), 0, -1)]

        debugfs_root = next(
            (
                f"{self.DEBUGFS_PATH}/{candidate}"
                for candidate in candidates
                if ls.path_exists(f"{self.DEBUGFS_PATH}/{candidate}", sudo=True)
            ),
            "",
        )
        if not debugfs_root:
            raise SkippedException(
                f"driver {driver_name} of SR-IOV VF {vf_slot} exposes no "
                f"debugfs directory under {self.DEBUGFS_PATH}. This driver "
                "does not implement debugfs diagnostics."
            )
        log.info(f"inspecting debugfs tree {debugfs_root} of VF {vf_slot}")

        # `timeout` reports 124 when it has to signal the child, and 137 when
        # that signal had to be escalated to KILL. Either way the read never
        # answered.
        timeout_codes = self.DEBUGFS_READ_TIMEOUT_EXIT_CODES

        read_results = self._read_debugfs_tree(node, debugfs_root)

        non_empty_reads = [path for path, size in read_results if size > 0]
        timed_out_reads = [path for path, size in read_results if size in timeout_codes]
        refused_reads = [
            path
            for path, size in read_results
            if size < 0 and size not in timeout_codes
        ]

        # Nothing readable, or nothing but empty files, means the driver
        # published no diagnostic content for this case to read back. That is
        # a property of the driver rather than a fault, so it is reported as
        # not applicable.
        if not read_results:
            raise SkippedException(
                f"driver {driver_name} of SR-IOV VF {vf_slot} exposes "
                f"{debugfs_root} but it holds no readable regular file, so "
                "there is no diagnostic content to read back."
            )

        assert_that(timed_out_reads).described_as(
            f"these files under {debugfs_root} are advertised as readable by "
            f"{driver_name} but never answered, and were abandoned after "
            f"{self.DEBUGFS_READ_TIMEOUT_SECONDS}s. A debugfs read that hangs "
            "blocks whoever is diagnosing this VF in production, and holds "
            "any driver lock it took for as long as it hangs. Check dmesg for "
            "a lockup or a driver error raised by these reads"
        ).is_empty()

        if not non_empty_reads:
            if refused_reads:
                raise SkippedException(
                    f"driver {driver_name} of SR-IOV VF {vf_slot} exposes "
                    f"{len(read_results)} readable files under {debugfs_root}, "
                    f"but {len(refused_reads)} returned errors and none returned "
                    "diagnostic content. Check for command interfaces or kernel "
                    f"lockdown. Refused paths: {refused_reads[:5]}"
                )
            raise SkippedException(
                f"driver {driver_name} of SR-IOV VF {vf_slot} exposes "
                f"{len(read_results)} readable files under {debugfs_root} and "
                "every one of them is empty, so it publishes no diagnostic "
                "content for this case to read back."
            )

        # A read that comes back with an error is not treated as a fault. Some
        # entries are command interfaces rather than diagnostics and answer
        # only once a command has been staged through them, and a kernel in
        # lockdown refuses every debugfs file that is not read-only. Both are
        # logged for triage instead of asserted on.
        if refused_reads:
            log.info(
                f"{len(refused_reads)} of {len(read_results)} files under "
                f"{debugfs_root} returned an error rather than content, which "
                "is expected of command interfaces and of any writable entry "
                f"when the kernel is locked down: {refused_reads[:5]}"
            )

        # The byte counts are logged rather than asserted on. Drivers differ
        # by orders of magnitude in what they publish, from a single value a
        # few bytes long to a queue dump of tens of KiB, so size carries no
        # verdict.
        log.info(
            f"read {len(read_results)} debugfs files under {debugfs_root}, "
            f"{len(non_empty_reads)} of which returned data"
        )

    @TestCaseMetadata(
        description="""
        This case verifies MANA VF netdev/bps bandwidth shapers with handle id 1
        on SKU Standard_ND128isr_NDR_GB200_v6 only.

        Steps,
        1. Require the exact GB200 SKU before tools.
        2. Select only VFs whose driver is mana; skip if none are present.
        3. Verify handle id 1 is absent, then SET each 100Mbps-multiple candidate.
              Verify each bandwidth cap is applied successfully.
        4. Check each candidate's reported bandwidth at CLI displayed precision.
        5. Delete each successful SET even if readback fails, and verify absence.

        This test is generated by the lisa_test_writer prompt.
        """,
        priority=2,
        requirement=simple_requirement(
            network_interface=features.Sriov(),
            unsupported_os=[BSD, Windows],
            supported_platform_type=[AZURE],
        ),
        tags=["ai-generated"],
    )
    def verify_sriov_netshaper_bandwidth_clamp(self, node: Node, log: Logger) -> None:
        scope = "netdev"
        shaper_id = 1
        metric = "bps"
        # MANA netdev/bps handle 1 accepts bandwidths in 100Mbps multiples.
        bw_candidates = (100000000, 1000000000)
        supported_vm_size = "Standard_ND128isr_NDR_GB200_v6"
        vm_size = node.capability.get_extended_runbook(AzureNodeSchema, AZURE).vm_size
        if vm_size != supported_vm_size:
            raise SkippedException(
                f"MANA bandwidth clamping is validated only on "
                f"{supported_vm_size}, not {vm_size}. Select the validated "
                "GB200 SKU and confirm cluster host support."
            )
        vf_nics = self._get_vf_nics(node, log, "net_shaper bandwidth clamping")
        ethtool = node.tools[Ethtool]
        vf_nics = [
            vf_nic
            for vf_nic in vf_nics
            if ethtool.get_device_driver(vf_nic).strip() == "mana"
        ]
        if not vf_nics:
            raise SkippedException(
                "No MANA VF found. Select a validated GB200 node with a MANA VF; "
                "mlx and other VF drivers are outside this case's scope."
            )
        net_shaper = node.tools[NetShaper]
        ip = node.tools[Ip]

        for vf_nic in vf_nics:
            self._require_device_up(ip, vf_nic, log)
            self._verify_vf_netshaper_clamp(
                node, net_shaper, vf_nic, log, scope, shaper_id, metric, bw_candidates
            )

    def _verify_vf_netshaper_clamp(
        self,
        node: Node,
        net_shaper: NetShaper,
        vf_nic: str,
        log: Logger,
        scope: str,
        shaper_id: int,
        metric: str,
        bw_candidates: Tuple[int, ...],
    ) -> None:
        existing = net_shaper.get_shapers(vf_nic, scope, shaper_id)

        assert_that(existing).described_as(
            f"{vf_nic} already has the shapers {[item.raw for item in existing]} "
            "attached before this case applied one. A leftover cap throttles "
            "the VF and makes the rest of this validation meaningless."
        ).is_empty()

        node.mark_dirty()
        for candidate in bw_candidates:
            result = net_shaper.set_shaper(
                vf_nic,
                candidate,
                scope,
                shaper_id,
                metric,
            )
            # Verify each bandwidth cap is applied successfully.
            result.assert_exit_code(
                message=f"SET failed on {vf_nic}: scope={scope}, "
                f"id={shaper_id}, metric={metric}, "
                f"requested={candidate} bps: {net_shaper.get_error(result)}. "
                "Investigate guest dmesg and host logs on the validated cluster."
            )
            try:
                log.info(f"Applied a {candidate} bps bandwidth clamp on {vf_nic}")
                self._verify_netshaper_bandwidth(
                    net_shaper,
                    vf_nic,
                    candidate,
                    "the clamp was applied",
                    scope,
                    shaper_id,
                    metric,
                )
            finally:
                log.info(f"Removing the net_shaper bandwidth clamp from {vf_nic}")
                net_shaper.delete_shaper(vf_nic, scope, shaper_id).assert_exit_code(
                    message=f"Couldn't delete the netdev scope shaper of {vf_nic}. "
                    "Investigate guest dmesg and host logs and remove the clamp."
                )

                remaining = net_shaper.get_shapers(vf_nic, scope, shaper_id)
                assert_that(remaining).described_as(
                    f"{vf_nic} still reports the shapers "
                    f"{[item.raw for item in remaining]} after deletion. Investigate "
                    "guest dmesg and host logs and remove the remaining cap."
                ).is_empty()
        log.info(f"net_shaper bandwidth clamping of {vf_nic} validated and removed.")

    def _verify_netshaper_bandwidth(
        self,
        net_shaper: NetShaper,
        vf_nic: str,
        expected: int,
        context: str,
        scope: str,
        shaper_id: int,
        metric: str,
    ) -> NetShaperInfo:
        shapers = net_shaper.get_shapers(vf_nic, scope, shaper_id)
        assert_that(shapers).described_as(
            f"{vf_nic} does not report exactly one shaper after {context}, it "
            f"reports {[item.raw for item in shapers]}."
        ).is_length(1)
        reported = shapers[0].bw_max
        if reported is None:
            raise LisaException(
                f"{vf_nic} reports no bw-max after {context}: {shapers[0].raw}. "
                "Check the driver's net_shaper bandwidth attributes."
            )
        assert_that(shapers[0].bw_max).described_as(
            f"{vf_nic} reports a maximum bandwidth inconsistent with "
            f"{expected} {metric} "
            f"at CLI precision after {context}: {shapers[0].raw}. "
            "Investigate the driver's bandwidth readback."
        ).is_equal_to(Decimal(expected))
        return shapers[0]

    @TestCaseMetadata(
        description="""
        This case verify VM works well after attached the max sriov nics after
         provision.

        Steps,
        1. Attach 7 extra sriov nic into the VM.
        2. Do the basic sriov testing.
        """,
        priority=2,
        use_new_environment=True,
        requirement=simple_requirement(
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
                max_nic_count=search_space.IntRange(min=8),
            ),
        ),
    )
    def verify_sriov_add_max_nics(
        self, log_path: Path, log: Logger, environment: Environment
    ) -> None:
        remove_extra_nics(environment)
        try:
            node = cast(RemoteNode, environment.nodes[0])
            network_interface_feature = node.features[NetworkInterface]
            network_interface_feature.attach_nics(extra_nic_count=7)
            is_ready, tcp_error_code = wait_tcp_port_ready(
                node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS],
                node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_PORT],
                log=log,
                timeout=self.TIME_OUT,
            )
            if is_ready:
                initialize_nic_info(environment)
                sriov_basic_test(environment)
            else:
                serial_console = node.features[SerialConsole]
                serial_console.check_panic(
                    saved_path=log_path, stage="after_attach_nics"
                )
                raise TcpConnectionException(
                    node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS],
                    node.connection_info[constants.ENVIRONMENTS_NODES_REMOTE_PORT],
                    tcp_error_code,
                    "no panic found in serial log after attach nics",
                )
        finally:
            restore_extra_nics(environment)

    @TestCaseMetadata(
        description="""
        This case verify VM works well when provisioning with max sriov nics.

        Steps,
        1. Provision VM with max network interfaces with enabling accelerated network.
        2. Do the basic sriov testing.
        """,
        priority=2,
        requirement=simple_requirement(
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
                nic_count=search_space.IntRange(min=2, choose_max_value=True),
            ),
        ),
    )
    def verify_sriov_provision_with_max_nics(self, environment: Environment) -> None:
        initialize_nic_info(environment)
        sriov_basic_test(environment)

    @TestCaseMetadata(
        description="""
        This case verify VM works well when provisioning with max sriov nics.

        Steps,
        1. Provision VM with max network interfaces with enabling accelerated network.
        2. Do the basic sriov testing.
        3. Reboot VM from guest.
        4. Do the basic sriov testing.
        """,
        priority=2,
        requirement=simple_requirement(
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
                nic_count=search_space.IntRange(min=2, choose_max_value=True),
            ),
        ),
    )
    def verify_sriov_provision_with_max_nics_reboot(
        self, environment: Environment
    ) -> None:
        initialize_nic_info(environment)
        sriov_basic_test(environment)
        for node in environment.nodes.list():
            node.reboot()
        initialize_nic_info(environment)
        sriov_basic_test(environment)

    @TestCaseMetadata(
        description="""
        This case verify VM works well when provisioning with max sriov nics.

        Steps,
        1. Provision VM with max network interfaces with enabling accelerated network.
        2. Do the basic sriov testing.
        3. Reboot VM from API.
        4. Do the basic sriov testing.
        """,
        priority=2,
        requirement=simple_requirement(
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
                nic_count=search_space.IntRange(min=2, choose_max_value=True),
            ),
        ),
    )
    def verify_sriov_provision_with_max_nics_reboot_from_platform(
        self, environment: Environment
    ) -> None:
        initialize_nic_info(environment)
        sriov_basic_test(environment)
        for node in environment.nodes.list():
            start_stop = node.features[StartStop]
            start_stop.restart()
        initialize_nic_info(environment)
        sriov_basic_test(environment)

    @TestCaseMetadata(
        description="""
        This case verify VM works well when provisioning with max sriov nics.

        Steps,
        1. Provision VM with max network interfaces with enabling accelerated network.
        2. Do the basic sriov testing.
        3. Stop and Start VM from API.
        4. Do the basic sriov testing.
        """,
        priority=2,
        requirement=simple_requirement(
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
                nic_count=search_space.IntRange(min=2, choose_max_value=True),
            ),
        ),
    )
    def verify_sriov_provision_with_max_nics_stop_start_from_platform(
        self, environment: Environment
    ) -> None:
        initialize_nic_info(environment)
        sriov_basic_test(environment)
        for node in environment.nodes.list():
            start_stop = node.features[StartStop]
            start_stop.stop()
            start_stop.start()
        initialize_nic_info(environment)
        sriov_basic_test(environment)

    @TestCaseMetadata(
        description="""
        This case verify VM works well during remove and load sriov modules.

        Steps,
        1. Provision VM with max network interfaces with enabling accelerated network.
        2. Do the basic sriov testing.
        3. Remove sriov module, check network traffic through synthetic nic.
        4. Load sriov module, check network traffic through VF.
        """,
        priority=1,
        requirement=simple_requirement(
            min_count=2,
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Sriov,
                nic_count=search_space.IntRange(min=2, choose_max_value=True),
            ),
        ),
    )
    def verify_sriov_reload_modules(self, environment: Environment) -> None:
        vm_nics = initialize_nic_info(environment)
        sriov_basic_test(environment)

        module_in_used: Dict[str, List[str]] = {}
        for node in environment.nodes.list():
            module_name_list: List[str] = []
            for module_name in node.nics.get_used_modules(["hv_netvsc"]):
                if node.nics.is_module_reloadable(module_name):
                    module_name_list.extend(node.nics.unload_module(module_name))
            module_in_used[node.name] = module_name_list

        for node in environment.nodes.list():
            if module_in_used[node.name]:
                remove_module = True
            else:
                remove_module = False

        sriov_vf_connection_test(environment, vm_nics, remove_module=remove_module)

        for node in environment.nodes.list():
            for module_name in module_in_used[node.name]:
                node.nics.load_module(module_name)

        vm_nics = initialize_nic_info(environment)
        sriov_vf_connection_test(environment, vm_nics)

    @TestCaseMetadata(
        description="""
        This case verify below two kernel patches.
        1. hv_netvsc: Sync offloading features to VF NIC
           https://github.com/torvalds/linux/commit/68622d071e555e1528f3e7807f30f73311c1acae#diff-007213ba7199932efdb096be47d209a2f83e4d425c486b3adaba861d0a0c80c5 # noqa: E501
        2. hv_netvsc: Allow scatter-gather feature to be tunable
           https://github.com/torvalds/linux/commit/b441f79532ec13dc82d05c55badc4da1f62a6141#diff-007213ba7199932efdb096be47d209a2f83e4d425c486b3adaba861d0a0c80c5 # noqa: E501

        Steps,
        1. Change scatter-gather feature on synthetic nic,
         verify the the feature status sync to the VF dynamically.
        2. Disable and enable sriov,
         check the scatter-gather feature status keep consistent in VF.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            network_interface=schema.NetworkInterfaceOptionSettings(
                nic_count=search_space.IntRange(min=3),
                data_path=schema.NetworkDataPath.Sriov,
            ),
            # BSD is unsupported since this is testing to patches to the linux kernel
            unsupported_os=[BSD, Windows],
        ),
    )
    def verify_sriov_ethtool_offload_setting(self, environment: Environment) -> None:
        client_iperf3_log = "iperfResults.log"
        server_node = cast(RemoteNode, environment.nodes[0])
        client_node = cast(RemoteNode, environment.nodes[1])
        client_ethtool = client_node.tools[Ethtool]
        vm_nics = initialize_nic_info(environment)

        # skip test if scatter-gather can't be updated
        for client_nic_info in vm_nics[client_node.name].values():
            device_sg_settings = client_ethtool.get_device_sg_settings(
                client_nic_info.name, True
            )
            if device_sg_settings.sg_fixed:
                raise SkippedException(
                    "scatter-gather is fixed, it cannot be changed for device"
                    f" {client_nic_info.name}. Skipping test."
                )
            else:
                break
        # save original enabled features
        device_enabled_features_origin = client_ethtool.get_all_device_enabled_features(
            True
        )

        # run iperf3 on server side and client side
        # iperfResults.log stored client side log
        source_iperf3 = server_node.tools[Iperf3]
        dest_iperf3 = client_node.tools[Iperf3]
        source_iperf3.run_as_server_async()
        dest_iperf3.run_as_client_async(
            server_ip=server_node.internal_address,
            log_file=client_iperf3_log,
            run_time_seconds=self.TIME_OUT,
        )

        # wait for a while then check any error shown up in iperfResults.log
        dest_cat = client_node.tools[Cat]
        iperf_log = dest_cat.read(client_iperf3_log, sudo=True, force_run=True)
        assert_that(iperf_log).does_not_contain("error")

        # disable and enable VF in pci level
        disable_enable_devices(environment)
        # check VF still paired with synthetic nic
        vm_nics = initialize_nic_info(environment)

        # get the enabled features after disable and enable VF
        # make sure there is not any change
        device_enabled_features_after = client_ethtool.get_all_device_enabled_features(
            True
        )
        assert_that(device_enabled_features_origin[0].enabled_features).is_equal_to(
            device_enabled_features_after[0].enabled_features
        )

        # set on for scatter-gather feature for synthetic nic
        # verify vf scatter-gather feature has value 'on'
        for client_nic_info in vm_nics[client_node.name].values():
            new_settings = client_ethtool.change_device_sg_settings(
                client_nic_info.name, True
            )
            device_vf_sg_settings = client_ethtool.get_device_sg_settings(
                client_nic_info.pci_device_name, True
            )
            assert_that(
                new_settings.sg_setting,
                "sg setting is not sync into VF.",
            ).is_equal_to(device_vf_sg_settings.sg_setting)

        # set off for scatter-gather feature for synthetic nic
        # verify vf scatter-gather feature has value 'off'
        for client_nic_info in vm_nics[client_node.name].values():
            new_settings = client_ethtool.change_device_sg_settings(
                client_nic_info.name, False
            )
            device_vf_sg_settings = client_ethtool.get_device_sg_settings(
                client_nic_info.pci_device_name, True
            )
            assert_that(
                new_settings.sg_setting,
                "sg setting is not sync into VF.",
            ).is_equal_to(device_vf_sg_settings.sg_setting)

        #  disable and enable VF in pci level
        disable_enable_devices(environment)
        # check VF still paired with synthetic nic
        vm_nics = initialize_nic_info(environment)

        # check VF's scatter-gather feature keep consistent with previous status
        for client_nic_info in vm_nics[client_node.name].values():
            device_vf_sg_settings = client_ethtool.get_device_sg_settings(
                client_nic_info.pci_device_name, True
            )
            assert_that(
                device_vf_sg_settings.sg_setting,
                "sg setting is not sync into VF.",
            ).is_equal_to(False)

        # disable and enable sriov in network interface level
        sriov_disable_enable(environment, 3)
        # check VF still paired with synthetic nic
        vm_nics = initialize_nic_info(environment)

        # check VF's scatter-gather feature keep consistent with previous status
        for client_nic_info in vm_nics[client_node.name].values():
            device_vf_sg_settings = client_ethtool.get_device_sg_settings(
                client_nic_info.pci_device_name, True
            )
            assert_that(
                device_vf_sg_settings.sg_setting,
                "sg setting is not sync into VF.",
            ).is_equal_to(False)

        # reload sriov modules
        if reload_modules(environment):
            # check VF still paired with synthetic nic
            vm_nics = initialize_nic_info(environment)

            # check VF's scatter-gather feature keep consistent with previous status
            for client_nic_info in vm_nics[client_node.name].values():
                device_vf_sg_settings = client_ethtool.get_device_sg_settings(
                    client_nic_info.pci_device_name, True
                )
                assert_that(
                    device_vf_sg_settings.sg_setting,
                    "sg setting is not sync into VF.",
                ).is_equal_to(False)

        # check there is no error happen in iperf3 log
        # after above operations
        dest_cat = client_node.tools[Cat]
        iperf_log = dest_cat.read(client_iperf3_log, sudo=True, force_run=True)
        assert_that(iperf_log).does_not_contain("error")

    @TestCaseMetadata(
        description="""
        This test case verifies that irq rebalance is running.
        When irqbalance is in debug mode, it will log “Selecting irq xxx for
        rebalancing” when it selects an irq for rebalancing. We expect to see
        this irq rebalancing when VM is under heavy network load.

        An issue was previously seen in irqbalance 1.8.0-1build1 on Ubuntu.
        When IRQ rebalance is not running, we expect to see poor network
        performance and high package loss. Contact the distro publisher if
        this is the case.

        Steps,
        1. Stop irqbalance service.
        2. Start irqbalance as a background process with debug mode.
        3. Generate some network traffic.
        4. Check irqbalance output for “Selecting irq xxx for rebalancing”.
        """,
        priority=2,
        requirement=simple_requirement(
            min_count=2,
            min_core_count=4,
            network_interface=features.Sriov(),
        ),
    )
    def verify_irqbalance(self, environment: Environment, log: Logger) -> None:
        err_msg: str = ""

        server_node = cast(RemoteNode, environment.nodes[0])
        client_node = cast(RemoteNode, environment.nodes[1])

        if (
            server_node.execute(
                "command -v irqbalance", shell=True, sudo=True
            ).exit_code
            != 0
        ):
            if not isinstance(
                server_node.os, Posix
            ) or not server_node.os.is_package_in_repo("irqbalance"):
                raise SkippedException("irqbalance is not available")
            server_node.os.install_packages("irqbalance")

        # Get the irqbalance version if we can
        if isinstance(server_node.os, Posix):
            try:
                log.debug(
                    "irqbalance version: "
                    f"{server_node.os.get_package_information('irqbalance')}"
                )
            except Exception as e:
                log.debug("irqbalance version: not found")
                err_msg += (
                    "\nPotential issues getting irqbalance version, "
                    "check logs for details."
                )
                log.debug("Exception: " + str(e))

        server_node.tools[Service].stop_service("irqbalance")

        irqbalance = server_node.execute_async("irqbalance --debug", sudo=True)

        server_iperf3 = server_node.tools[Iperf3]
        client_iperf3 = client_node.tools[Iperf3]

        server_iperf3.run_as_server_async()
        try:
            client_iperf3.run_as_client(
                server_ip=server_node.internal_address,
                run_time_seconds=240,
                parallel_number=128,
                client_ip=client_node.internal_address,
            )
        except AssertionError as e:
            # We don't care about the iperf3 results, we just want to generate
            # network traffic.
            log.debug(f"iperf3 failed: {e}")
            err_msg += "\nPotential issues running iperf3, check logs for details."

        irqbalance.kill()
        # The kill() above sends SIGKILL to the spur-tracked process (the
        # sudo/sh wrapper), but irqbalance itself is a child that can survive
        # as an orphan.  Explicitly kill it by name to ensure it is gone
        # before waiting for the result, so wait_result() does not time out.
        server_node.tools[Kill].by_name("irqbalance", ignore_not_exist=True)
        result = irqbalance.wait_result(raise_on_timeout=False)

        # Check that irqbalance actively rebalanced an IRQ.
        selecting_match = re.search(
            "Selecting irq [0-9]+ for rebalancing",
            result.stdout,
        )
        if not selecting_match:
            # On high-core-count VMs with managed IRQs (e.g. MANA NICs on v6
            # SKUs), the kernel handles IRQ affinity and irqbalance correctly
            # determines no rebalancing is needed. In this case, verify that
            # irqbalance successfully completed at least one scan cycle by
            # checking for interrupt enumeration output.
            assert re.search(
                r"Interrupt \d+ node_num",
                result.stdout,
            ), (
                "irqbalance is not rebalancing irqs" + err_msg
            )
            log.debug(
                "irqbalance did not select any IRQ for rebalancing "
                "(likely managed IRQs on high-core-count VM), "
                "but scan cycle completed successfully"
            )

    @TestCaseMetadata(
        description="""
        This case is to verify interrupts count increased after network traffic
         went through the VF, if CPU is less than 8, it can't verify the interrupts
         spread to CPU evenly, when CPU is more than 16, the traffic is too light to
         make sure interrupts distribute to every CPU.

        Steps,
        1. Start iperf3 on server node.
        2. Get initial interrupts sum per irq and cpu number on client node.
        3. Start iperf3 for 120 seconds with 128 threads on client node.
        4. Get final interrupts sum per irq number on client node.
        5. Compare interrupts changes, expected to see interrupts increased.
        6. Get final interrupts sum per cpu on client node.
        7. Collect cpus which don't have interrupts count increased.
        8. Compare interrupts count changes, expected half of cpus' interrupts
         increased.
        """,
        priority=2,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=2,
                core_count=search_space.IntRange(min=8, max=16),
                network_interface=features.Sriov(),
            )
        ),
    )
    def verify_sriov_interrupts_change(self, environment: Environment) -> None:
        server_node = cast(RemoteNode, environment.nodes[0])
        client_node = cast(RemoteNode, environment.nodes[1])
        client_lscpu = client_node.tools[Lscpu]
        client_thread_count = client_lscpu.get_thread_count()

        vm_nics = initialize_nic_info(environment)

        server_iperf3 = server_node.tools[Iperf3]
        client_iperf3 = client_node.tools[Iperf3]
        # 1. Start iperf3 on server node.
        server_iperf3.run_as_server_async()
        client_interrupt_inspector = client_node.tools[InterruptInspector]
        for _, client_nic_info in vm_nics[client_node.name].items():
            if client_nic_info.is_pci_module_enabled:
                # Skip InfiniBand and NICs without IP (enslaved VFs, etc.)
                if client_nic_info.is_infiniband or not client_nic_info.ip_addr:
                    continue
                # 2. Get initial interrupts sum per irq and cpu number on client node.
                # only collect 'Completion Queue Interrupts' irqs
                initial_pci_interrupts_by_irqs = (
                    client_interrupt_inspector.sum_cpu_counter_by_irqs(
                        client_nic_info.pci_slot,
                        exclude_key_words=["pages", "cmd", "async", "hwc"],
                    )
                )

                initial_pci_interrupts_by_cpus = (
                    client_interrupt_inspector.sum_cpu_counter_by_index(
                        client_nic_info.pci_slot
                    )
                )
                if isinstance(client_node.os, BSD):
                    assert_that(len(initial_pci_interrupts_by_cpus)).described_as(
                        "initial cpu count of interrupts should be equal to cpu count"
                        " plus one to account for control queue"
                    ).is_equal_to(client_thread_count + 1)
                else:
                    assert_that(len(initial_pci_interrupts_by_cpus)).described_as(
                        "initial cpu count of interrupts should be equal to cpu count"
                    ).is_equal_to(client_thread_count)
                matched_server_nic_info: Optional[NicInfo] = None
                for _, server_nic_info in vm_nics[server_node.name].items():
                    # Skip NICs without IP addresses (IB, enslaved VFs, etc.)
                    if not server_nic_info.ip_addr:
                        continue
                    if server_nic_info.is_infiniband:
                        continue
                    if (
                        server_nic_info.ip_addr.rsplit(".", maxsplit=1)[0]
                        == client_nic_info.ip_addr.rsplit(".", maxsplit=1)[0]
                    ):
                        matched_server_nic_info = server_nic_info
                        break
                assert matched_server_nic_info, (
                    "not found the server nic has the same subnet of"
                    f" {client_nic_info.ip_addr}"
                )

                # 3. Start iperf3 for 120 seconds with 128 threads on client node.
                client_iperf3.run_as_client(
                    server_ip=matched_server_nic_info.ip_addr,
                    run_time_seconds=120,
                    parallel_number=128,
                    client_ip=client_nic_info.ip_addr,
                )
                # 4. Get final interrupts sum per irq number on client node.
                final_pci_interrupts_by_irqs = (
                    client_interrupt_inspector.sum_cpu_counter_by_irqs(
                        client_nic_info.pci_slot,
                        exclude_key_words=["pages", "cmd", "async", "hwc"],
                    )
                )
                assert_that(len(final_pci_interrupts_by_irqs)).described_as(
                    "final irqs count should be greater than 0"
                ).is_greater_than(0)
                for init_interrupts_irq in initial_pci_interrupts_by_irqs:
                    init_irq_number = list(init_interrupts_irq)[0]
                    init_interrupts_value = init_interrupts_irq[init_irq_number]
                    for final_interrupts in final_pci_interrupts_by_irqs:
                        final_irq_number = list(final_interrupts)[0]
                        final_interrupts_value = final_interrupts[final_irq_number]
                        if init_irq_number == final_irq_number:
                            break
                    # 5. Compare interrupts changes, expected to see interrupts
                    # increased.
                    assert_that(final_interrupts_value).described_as(
                        f"irq {init_irq_number} didn't have an increased interrupts "
                        " count after iperf3 run!"
                    ).is_greater_than(init_interrupts_value)
                # 6. Get final interrupts sum per cpu on client node.
                final_pci_interrupts_by_cpus = (
                    client_interrupt_inspector.sum_cpu_counter_by_index(
                        client_nic_info.pci_slot
                    )
                )
                if isinstance(client_node.os, BSD):
                    assert_that(len(final_pci_interrupts_by_cpus)).described_as(
                        "initial cpu count of interrupts should be equal to cpu count"
                        " plus one to account for control queue"
                    ).is_equal_to(client_thread_count + 1)
                else:
                    assert_that(len(final_pci_interrupts_by_cpus)).described_as(
                        "initial cpu count of interrupts should be equal to cpu count"
                    ).is_equal_to(client_thread_count)
                unused_cpu = 0
                for (
                    cpu,
                    init_interrupts_value,
                ) in initial_pci_interrupts_by_cpus.items():
                    final_interrupts_value = final_pci_interrupts_by_cpus[cpu]
                    # 7. Collect cpus which don't have interrupts count increased.
                    if final_interrupts_value == init_interrupts_value:
                        unused_cpu += 1
                # 8. Compare interrupts count changes, expected half of cpus' interrupts
                #    increased.
                assert_that(client_thread_count / 2).described_as(
                    f"More than half of the vCPUs {unused_cpu} didn't have increased "
                    "interrupt count!"
                ).is_greater_than(unused_cpu)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        cleanup_iperf3(environment)

    def _read_debugfs_tree(
        self, node: Node, debugfs_root: str
    ) -> List[Tuple[str, int]]:
        # Emits "<byte_count>\t<path>" per readable file and
        # "ERR<exit_code>\t<path>" per file whose read fails.
        timeout = node.tools[Timeout]
        timeout.run(
            parameters=(
                f"-k {self.DEBUGFS_READ_KILL_GRACE_SECONDS} "
                f"{self.DEBUGFS_READ_TIMEOUT_SECONDS} true"
            ),
            force_run=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "timeout must support -k before reading debugfs. Install GNU "
                "coreutils or verify that the timeout command supports a KILL "
                "grace period."
            ),
        )

        # -k escalates to KILL a second after the read declines to stop, so a
        # read that ignores the first signal cannot stall the whole walk.
        per_file = (
            f"if {timeout.command} -k {self.DEBUGFS_READ_KILL_GRACE_SECONDS} "
            f"{self.DEBUGFS_READ_TIMEOUT_SECONDS} "
            f'head -c {self.DEBUGFS_READ_CAP_BYTES} "$1" > "$2" 2>/dev/null; '
            'then printf "%s\\t%s\\n" "$(wc -c < "$2")" "$1"; '
            'else printf "ERR%s\\t%s\\n" "$?" "$1"; fi'
        )

        candidates = node.execute(
            f"find '{debugfs_root}' -type f -perm -u+r -print0",
            sudo=True,
            shell=True,
            no_info_log=True,
        )
        candidates.assert_exit_code(
            0,
            message=(
                f"failed to enumerate readable debugfs files under "
                f"{debugfs_root}. Verify the path exists and is readable "
                "with sudo."
            ),
            include_output=True,
        )
        candidate_count = len(
            [path for path in candidates.stdout.split("\x00") if path]
        )
        overall_timeout = min(
            (
                candidate_count
                * (
                    self.DEBUGFS_READ_TIMEOUT_SECONDS
                    + self.DEBUGFS_READ_KILL_GRACE_SECONDS
                )
                + self.DEBUGFS_TREE_TIMEOUT_PADDING_SECONDS
            ),
            self.DEBUGFS_TREE_MAX_TIMEOUT_SECONDS,
        )
        try:
            result = node.execute(
                "umask 077; "
                'scratch="$(mktemp /tmp/lisa_debugfs_read.XXXXXX)" || exit $?; '
                "cleanup() { status=$?; trap - 0 HUP INT TERM; "
                'rm -f "$scratch"; exit "$status"; }; '
                "trap cleanup 0 HUP INT TERM; "
                f"find '{debugfs_root}' -type f -perm -u+r "
                f"-exec sh -c '{per_file}' _ {{}} \"$scratch\" \\;",
                sudo=True,
                shell=True,
                no_info_log=True,
                timeout=overall_timeout,
            )
        except LisaTimeoutException as error:
            raise LisaException(
                f"reading {candidate_count} debugfs files under {debugfs_root} "
                f"did not finish within {overall_timeout} seconds. At least one "
                "diagnostic entry is blocked or too slow to inspect; check dmesg "
                "for a driver error or lockup."
            ) from error
        result.assert_exit_code(
            0,
            message=(
                f"failed to enumerate and read debugfs files under "
                f"{debugfs_root}. Verify the path exists and is readable "
                "with sudo."
            ),
            include_output=True,
        )

        read_results: List[Tuple[str, int]] = []
        for line in result.stdout.splitlines():
            token, _, path = line.partition("\t")
            if not path:
                continue
            if token.startswith("ERR"):
                # A failed read is carried as the negated exit code, which
                # keeps one integer per file while preserving the reason.
                try:
                    read_results.append((path, -int(token[len("ERR") :])))
                except ValueError:
                    read_results.append((path, -1))
                continue
            try:
                read_results.append((path, int(token)))
            except ValueError:
                # Unexpected output for this path, treated as a failed read.
                read_results.append((path, -1))
        return read_results
