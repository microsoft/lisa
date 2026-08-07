# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import ipaddress
import re
import shlex
from functools import partial
from pathlib import PurePosixPath
from typing import Any, Dict, List

from assertpy import assert_that
from microsoft.testsuites.dpdk.common import Pmd
from microsoft.testsuites.dpdk.dpdkutil import (
    DpdkTestResources,
    annotate_dpdk_test_result,
    check_dpdk_is_running,
    get_dpdk_pids,
    get_vmbus_network_device_ids,
    init_nodes_concurrent,
    rebind_uio_devices_to_hv_netvsc,
)

from lisa import (
    Environment,
    Logger,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.features import Gpu, Infiniband, Sriov
from lisa.nic import NicInfo
from lisa.operating_system import BSD, Windows
from lisa.testsuite import TestResult, simple_requirement
from lisa.tools import Cat, Dmesg, Kill, Ls, Mkdir, RemoteCopy, Rm
from lisa.tools.hugepages import HugePageSize
from lisa.util import LisaException, LisaTimeoutException, check_till_timeout
from lisa.util.constants import SIGINT, SIGKILL
from lisa.util.parallel import run_in_parallel

# Directory on the test node holding the artifacts of the persistent run.
# The second phase can run in a separate LISA invocation, so the testpmd
# output (and the command line which produced it) is written to the node
# itself instead of being kept in memory. The running processes are found
# by name, so no pid state has to survive between the two phases.
PERSISTENT_RUN_DIR = "/tmp/lisa-dpdk-persistent"

# testpmd's forward mode is global per process, so each node runs two
# processes: one transmitting to the peer and one receiving from it.
TX_ROLE = "tx"
RX_ROLE = "rx"
ROLES = [TX_ROLE, RX_ROLE]

# Subnets used to pair the send/receive nics between the two nodes are
# discovered at runtime, see get_test_nic_pairs().

# testpmd emits this line once the forwarding cores are running.
TESTPMD_FORWARDING_STARTED = "start packet forwarding"

# Give each testpmd process a dedicated pair of lcores so the two
# processes on a node don't contend for the same cores.
TESTPMD_CORES_PER_PROCESS = 2
ROLE_CORE_OFFSET = {TX_ROLE: 0, RX_ROLE: TESTPMD_CORES_PER_PROCESS}

# Preallocate a fixed amount of hugepage memory per process so the first
# testpmd to start can't consume the pages the second one needs.
EAL_MEMORY_MB = 1024

# Strong indicators that testpmd died or corrupted itself.
TESTPMD_CRASH_PATTERNS = [
    re.compile(r"segmentation fault", re.IGNORECASE),
    re.compile(r"core dumped", re.IGNORECASE),
    re.compile(r"rte_panic", re.IGNORECASE),
    re.compile(r"PANIC in "),
    re.compile(r"stack smashing detected", re.IGNORECASE),
    re.compile(r"double free or corruption", re.IGNORECASE),
    re.compile(r"free\(\): invalid", re.IGNORECASE),
    re.compile(r"malloc\(\): (invalid|corrupted|memory corruption)", re.IGNORECASE),
    re.compile(r"buffer overflow detected", re.IGNORECASE),
    re.compile(r"assertion .* failed", re.IGNORECASE),
    re.compile(r"terminated by signal", re.IGNORECASE),
    re.compile(r"bus error", re.IGNORECASE),
    re.compile(r"\bAborted\b"),
]

# Drivers involved in the DPDK datapath on Azure. dmesg lines mentioning
# any of these are inspected for errors after the host event.
WATCHED_DRIVERS = {
    "hv_netvsc": re.compile(r"\b(hv_netvsc|netvsc)\b", re.IGNORECASE),
    "mana": re.compile(r"\bmana(_ib|_en)?\b", re.IGNORECASE),
    "hv_pci": re.compile(r"\b(hv_pci|pci_hyperv|hv_pci_probe)\b", re.IGNORECASE),
    "vmbus": re.compile(r"\b(vmbus|hv_vmbus)\b", re.IGNORECASE),
}

DRIVER_ERROR_KEYWORDS = re.compile(
    r"(error|fail(ed|ure|s)?|timed out|timeout|unable to|cannot |can't |"
    r"panic|oops|call trace|bug|corrupt|denied|abort|fatal)",
    re.IGNORECASE,
)

TESTPMD_STATS_PATTERNS = {
    "tx_pps": re.compile(r"Tx-pps:\s+([0-9]+)"),
    "rx_pps": re.compile(r"Rx-pps:\s+([0-9]+)"),
    "tx_total_packets": re.compile(r"TX-packets:\s+([0-9]+)"),
    "rx_total_packets": re.compile(r"RX-packets:\s+([0-9]+)"),
    "tx_dropped": re.compile(r"TX-dropped:\s+([0-9]+)"),
    "rx_dropped": re.compile(r"RX-dropped:\s+([0-9]+)"),
}


def get_log_path(role: str) -> str:
    return f"{PERSISTENT_RUN_DIR}/testpmd-{role}.log"


def get_command_path(role: str) -> str:
    return f"{PERSISTENT_RUN_DIR}/testpmd-{role}.cmd"


def get_eal_args(test_kit: DpdkTestResources, role: str, nic: NicInfo) -> str:
    """
    EAL arguments which keep the two testpmd processes on a node from
    fighting over the same devices and hugepages.
    """
    # each process needs its own hugepage file prefix and its own slice of
    # memory to coexist with the other primary process on the same node.
    args = [f"--file-prefix=lisa_{role}", f"-m {EAL_MEMORY_MB}"]

    # the vmbus bus scan probes every netvsc device bound to uio_hv_generic,
    # so without this both processes try to open every test nic and whichever
    # starts second hangs in hn_nvs_init(). Block everything except this
    # process's own device.
    for other in get_blocked_vmbus_uuids(test_kit, nic):
        args.append(f"-b {other}")

    return " ".join(args)


def get_blocked_vmbus_uuids(test_kit: DpdkTestResources, nic: NicInfo) -> List[str]:
    nics = test_kit.node.nics
    return [
        nics.nics[name].dev_uuid
        for name in nics.get_nic_names()
        if name != nic.name and nics.nics[name].dev_uuid
    ]


def generate_tx_command(
    test_kit: DpdkTestResources, tx_nic: NicInfo, peer_nic: NicInfo
) -> str:
    cmd = test_kit.testpmd.generate_testpmd_command(
        [tx_nic],
        0,
        "txonly",
        extra_args=f"--tx-ip={tx_nic.ip_addr},{peer_nic.ip_addr}",
        core_offset=ROLE_CORE_OFFSET[TX_ROLE],
        extra_eal_args=get_eal_args(test_kit, TX_ROLE, tx_nic),
    )
    return cmd


def generate_rx_command(test_kit: DpdkTestResources, rx_nic: NicInfo) -> str:
    cmd = test_kit.testpmd.generate_testpmd_command(
        [rx_nic],
        0,
        "rxonly",
        core_offset=ROLE_CORE_OFFSET[RX_ROLE],
        extra_eal_args=get_eal_args(test_kit, RX_ROLE, rx_nic),
    )
    return cmd


def get_test_nic_pairs(
    node_a: DpdkTestResources, node_b: DpdkTestResources
) -> Dict[str, NicInfo]:
    """
    Pick two test nics per node and pair them by subnet so every sender has a
    receiver listening on the same wire.

    The subnets aren't hardcoded, they are discovered from the nics which
    aren't carrying the lisa ssh session. node_a transmits on the first test
    subnet and receives on the second, node_b does the reverse.
    """
    a_nics = get_test_nics(node_a)
    assert_that(len(a_nics)).described_as(
        f"{node_a.node.name} needs two test nics in addition to the management "
        "nic to send and receive at the same time."
    ).is_greater_than_or_equal_to(2)

    a_tx_nic, a_rx_nic = a_nics[0], a_nics[1]
    # the peer's roles are swapped, but the nics have to be on the same
    # subnets or the traffic never arrives.
    b_rx_nic = node_b.node.nics.get_nic_by_subnet(get_subnet(a_tx_nic))
    b_tx_nic = node_b.node.nics.get_nic_by_subnet(get_subnet(a_rx_nic))

    return {
        "a_tx": a_tx_nic,
        "a_rx": a_rx_nic,
        "b_tx": b_tx_nic,
        "b_rx": b_rx_nic,
    }


def get_test_nics(test_kit: DpdkTestResources) -> List[NicInfo]:
    nics = test_kit.node.nics
    primary = nics.get_primary_nic()
    return [
        nics.nics[name]
        for name in nics.get_nic_names()
        if name != primary.name and nics.nics[name].ip_addr
    ]


def get_subnet(nic: NicInfo) -> str:
    # testpmd only needs the two nics to be on the same wire, a /24 is what
    # azure hands out for a test subnet.
    return str(ipaddress.ip_network(f"{nic.ip_addr}/24", strict=False))


def generate_bidirectional_run_info(
    node_a: DpdkTestResources, node_b: DpdkTestResources
) -> Dict[DpdkTestResources, Dict[str, str]]:
    nic_pairs = get_test_nic_pairs(node_a, node_b)
    a_tx_nic = nic_pairs["a_tx"]
    a_rx_nic = nic_pairs["a_rx"]
    b_tx_nic = nic_pairs["b_tx"]
    b_rx_nic = nic_pairs["b_rx"]

    return {
        node_a: {
            TX_ROLE: generate_tx_command(node_a, a_tx_nic, b_rx_nic),
            RX_ROLE: generate_rx_command(node_a, a_rx_nic),
        },
        node_b: {
            TX_ROLE: generate_tx_command(node_b, b_tx_nic, a_rx_nic),
            RX_ROLE: generate_rx_command(node_b, b_rx_nic),
        },
    }


def read_persistent_log(node: Node, role: str) -> str:
    log_file = get_log_path(role)
    if not node.tools[Ls].path_exists(log_file, sudo=True):
        return ""
    return node.tools[Cat].read(log_file, sudo=True, force_run=True, no_debug_log=True)


def start_persistent_testpmd(node: Node, role: str, command: str, log: Logger) -> None:
    log_file = get_log_path(role)
    node.tools[Mkdir].create_directory(PERSISTENT_RUN_DIR, sudo=True)
    for stale_file in [log_file, get_command_path(role)]:
        node.tools[Rm].remove_file(stale_file, sudo=True)

    # save the command line next to the log, the second phase runs without
    # any of the state generated here.
    node.execute(
        f"echo {shlex.quote(command)} > {get_command_path(role)}",
        sudo=True,
        shell=True,
    )

    # nohup + background + redirected io lets testpmd outlive both the ssh
    # session and this test case.
    log.info(f"{node.name}: starting persistent testpmd ({role}): {command}")
    node.execute(
        f"nohup {command} > {log_file} 2>&1 < /dev/null &",
        sudo=True,
        shell=True,
    )


def wait_for_testpmd_forwarding(
    node: Node, role: str, log: Logger, timeout: int = 300
) -> None:
    log_file = get_log_path(role)

    def _forwarding_started() -> bool:
        if not check_dpdk_is_running(node):
            raise LisaException(
                f"{node.name}: testpmd ({role}) exited before forwarding "
                f"started. Output:\n{read_persistent_log(node, role)}"
            )
        result = node.execute(
            f"grep -q '{TESTPMD_FORWARDING_STARTED}' {log_file}",
            sudo=True,
            shell=True,
        )
        return result.exit_code == 0

    check_till_timeout(
        _forwarding_started,
        f"{node.name}: testpmd ({role}) did not start packet forwarding",
        timeout=timeout,
        interval=2,
    )
    log.info(f"{node.name}: testpmd ({role}) is forwarding packets")


def stop_persistent_testpmd(node: Node, log: Logger) -> None:
    # any testpmd running on the node was started by phase one, so the roles
    # don't have to be told apart to shut the run down.
    pids = get_dpdk_pids(node)
    if not pids:
        log.debug(f"{node.name}: no testpmd process is running, nothing to stop")
        return
    kill = node.tools[Kill]
    # SIGINT first, testpmd prints its final port statistics on a clean exit.
    for pid in pids:
        kill.by_pid(pid, signum=SIGINT, ignore_not_exist=True)
    try:
        check_till_timeout(
            lambda: not check_dpdk_is_running(node),
            f"{node.name}: testpmd did not exit after SIGINT",
            timeout=60,
            interval=2,
        )
    except LisaTimeoutException:
        log.debug(
            f"{node.name}: testpmd ignored SIGINT, sending SIGKILL. "
            "Final port statistics will not be available."
        )
        for pid in get_dpdk_pids(node):
            kill.by_pid(pid, signum=SIGKILL, ignore_not_exist=True)


def collect_persistent_testpmd_output(node: Node, role: str) -> str:
    output = read_persistent_log(node, role)
    log_file = get_log_path(role)
    if output:
        node.tools[RemoteCopy].copy_to_local(
            PurePosixPath(log_file), node.local_log_path, sudo=True
        )
    return output


def find_testpmd_crashes(output: str) -> List[str]:
    crashes: List[str] = []
    for line in output.splitlines():
        for pattern in TESTPMD_CRASH_PATTERNS:
            if pattern.search(line):
                crashes.append(line.strip())
                break
    return crashes


def find_driver_dmesg_errors(node: Node) -> Dict[str, List[str]]:
    dmesg_output = node.tools[Dmesg].get_output(force_run=True)
    found: Dict[str, List[str]] = {}
    for line in dmesg_output.splitlines():
        if not DRIVER_ERROR_KEYWORDS.search(line):
            continue
        for driver, driver_pattern in WATCHED_DRIVERS.items():
            if driver_pattern.search(line):
                found.setdefault(driver, []).append(line.strip())
                break
    return found


def parse_testpmd_stats(output: str) -> Dict[str, int]:
    stats: Dict[str, int] = {}
    for key, pattern in TESTPMD_STATS_PATTERNS.items():
        samples = [int(match) for match in pattern.findall(output)]
        if not samples:
            continue
        # pps is sampled every stats period, the packet counters are running
        # totals so the last sample is the interesting one.
        stats[key] = max(samples) if key.endswith("_pps") else samples[-1]
    return stats


@TestSuiteMetadata(
    area="dpdk",
    category="functional",
    description="""
    This test suite runs DPDK testpmd traffic across two nodes in two
    separate phases so an external event (host servicing, host crash,
    live migration, VF revoke, etc.) can be injected while DPDK owns the
    datapath.

    The phases are separate test cases on purpose: the traffic is left
    running when the first case ends, and the second case can be run from a
    different LISA invocation against the same (predefined) environment once
    the host side event is done.
    """,
    requirement=simple_requirement(unsupported_os=[BSD, Windows]),
)
class DpdkHostEvent(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs["environment"]
        for node in environment.nodes.list():
            if isinstance(node.os, BSD) or isinstance(node.os, Windows):
                raise SkippedException(f"{node.os} is not supported.")

    @TestCaseMetadata(
        description="""
            Phase one of the host event test.

            Runs the standard DPDK node setup (initialize_node_resources) on
            both nodes, then starts two testpmd processes per node so each
            node is sending to and receiving from its peer at the same time.
            The two test nics (everything except the nic carrying the lisa
            ssh session) are paired by subnet:
              node_a: txonly on test subnet 1 -> node_b, rxonly on subnet 2
              node_b: txonly on test subnet 2 -> node_a, rxonly on subnet 1

            The processes are started with nohup and no timeout, and are
            deliberately NOT killed when the test case ends. An external
            actor triggers the host side event, then
            verify_dpdk_persistent_traffic_results collects and grades the
            run.

            NOTE: use a predefined environment (or keep_environment) with
            this case, otherwise the nodes are deallocated when the run ends.
        """,
        priority=4,
        requirement=simple_requirement(
            min_core_count=8,
            min_nic_count=3,
            network_interface=Sriov(),
            unsupported_features=[Gpu, Infiniband],
            min_count=2,
        ),
    )
    def verify_dpdk_start_persistent_traffic(
        self,
        environment: Environment,
        log: Logger,
        variables: Dict[str, Any],
        result: TestResult,
    ) -> None:
        test_kits = init_nodes_concurrent(
            environment,
            log,
            variables,
            Pmd.NETVSC,
            hugepage_size=HugePageSize.HUGE_2MB,
            test_nic_count=2,
        )
        assert_that(len(test_kits)).described_as(
            "This test needs exactly two nodes to generate bidirectional traffic."
        ).is_equal_to(2)
        node_a, node_b = test_kits
        annotate_dpdk_test_result(test_kit=node_a, test_result=result, log=log)

        run_info = generate_bidirectional_run_info(node_a, node_b)

        # bring the receivers up first so no traffic is lost at startup.
        for role in [RX_ROLE, TX_ROLE]:
            run_in_parallel(
                [
                    partial(
                        start_persistent_testpmd,
                        test_kit.node,
                        role,
                        run_info[test_kit][role],
                        log,
                    )
                    for test_kit in test_kits
                ],
                log,
            )
            run_in_parallel(
                [
                    partial(wait_for_testpmd_forwarding, test_kit.node, role, log)
                    for test_kit in test_kits
                ],
                log,
            )

        for test_kit in test_kits:
            pids = get_dpdk_pids(test_kit.node)
            result.information[f"{test_kit.node.name}_testpmd_pids"] = ",".join(pids)

        log.info(
            "DPDK traffic is running on both nodes and will be left running. "
            f"testpmd output is at {PERSISTENT_RUN_DIR} on each node. Run "
            "verify_dpdk_persistent_traffic_results to stop the run and "
            "collect the results."
        )

    @TestCaseMetadata(
        description="""
            Phase two of the host event test.

            Reconnects to both nodes, verifies the testpmd processes started
            by verify_dpdk_start_persistent_traffic are still running, stops
            them, then collects the testpmd output from each node and checks
            it for crashes. Also checks dmesg on each node for errors from
            hv_netvsc, mana, hv_pci and vmbus.

            NOTE: throughput grading is stubbed out, the parsed statistics
            are only annotated on the test result for now.
        """,
        priority=5,
        requirement=simple_requirement(
            min_core_count=8,
            min_nic_count=3,
            network_interface=Sriov(),
            unsupported_features=[Gpu, Infiniband],
            min_count=2,
        ),
    )
    def verify_dpdk_persistent_traffic_results(
        self,
        environment: Environment,
        log: Logger,
        variables: Dict[str, Any],
        result: TestResult,
    ) -> None:
        nodes = list(environment.nodes.list())
        assert_that(len(nodes)).described_as(
            "This test needs the same two nodes used to start the traffic."
        ).is_greater_than_or_equal_to(2)

        # the host event may have broken the ssh sessions, force a reconnect
        # before touching anything else on the nodes.
        run_in_parallel([partial(self._reconnect, node, log) for node in nodes], log)

        issues: List[str] = []

        # phase one is expected to still be running when we get here, a
        # missing process is the failure this test is looking for.
        for node in nodes:
            issues += self._check_testpmd_is_running(node, log)

        for node in nodes:
            stop_persistent_testpmd(node, log)

        for node in nodes:
            issues += self._collect_testpmd_results(node, log, result)

        for node in nodes:
            issues += self._check_dmesg(node)

        # dpdk leaves the test nics bound to uio_hv_generic with no address,
        # which breaks the next run's nic discovery. hand them back to
        # hv_netvsc before asserting, so the environment is reusable even
        # when this case fails.
        run_in_parallel([partial(self._reset_node, node, log) for node in nodes], log)

        # TODO: grading is stubbed out. The throughput/packet drop data is
        # parsed and annotated above, add pass/fail thresholds once the
        # expected behavior across a host event is settled.

        assert_that(issues).described_as(
            "DPDK traffic did not survive the host event cleanly:\n" + "\n".join(issues)
        ).is_empty()

    def _check_testpmd_is_running(self, node: Node, log: Logger) -> List[str]:
        # any testpmd on the node belongs to phase one, so the presence of the
        # processes is all this check needs, not which role they are playing.
        pids = get_dpdk_pids(node)
        if not pids:
            return [
                f"{node.name}: no testpmd process was running when the results "
                "were collected. The node may have rebooted, testpmd may have "
                "died during the host event, or phase one "
                "(verify_dpdk_start_persistent_traffic) never ran."
            ]
        if len(pids) < len(ROLES):
            return [
                f"{node.name}: expected {len(ROLES)} testpmd processes "
                f"(one per role: {', '.join(ROLES)}) but only {len(pids)} "
                f"were still running (pids {', '.join(pids)})."
            ]
        log.info(f"{node.name}: testpmd still running, pids {', '.join(pids)}")
        return []

    def _collect_testpmd_results(
        self, node: Node, log: Logger, result: TestResult
    ) -> List[str]:
        issues: List[str] = []
        for role in ROLES:
            output = collect_persistent_testpmd_output(node, role)
            if not output:
                issues.append(
                    f"{node.name}: no testpmd ({role}) output was found at "
                    f"{get_log_path(role)}."
                )
                continue

            crashes = find_testpmd_crashes(output)
            if crashes:
                issues.append(
                    f"{node.name}: testpmd ({role}) output contains "
                    f"{len(crashes)} crash indicator(s): " + " | ".join(crashes[:5])
                )

            stats = parse_testpmd_stats(output)
            log.info(f"{node.name}: testpmd ({role}) stats: {stats}")
            for key, value in stats.items():
                result.information[f"{node.name}_{role}_{key}"] = value
        return issues

    def _check_dmesg(self, node: Node) -> List[str]:
        issues: List[str] = []
        driver_errors = find_driver_dmesg_errors(node)
        for driver, lines in driver_errors.items():
            issues.append(
                f"{node.name}: found {len(lines)} {driver} error(s) in dmesg: "
                + " | ".join(lines[:5])
            )
        kernel_errors = node.tools[Dmesg].check_kernel_errors(
            force_run=True, throw_error=False
        )
        if kernel_errors:
            issues.append(f"{node.name}: dmesg kernel errors: {kernel_errors}")
        return issues

    def _reconnect(self, node: Node, log: Logger) -> None:
        node.close()
        uptime = node.execute("uptime").stdout.strip()
        log.debug(f"{node.name}: reconnected, uptime: {uptime}")

    def _reset_node(self, node: Node, log: Logger) -> None:
        # hand the nics back to hv_netvsc instead of rebooting, dpdk leaves
        # them bound to uio_hv_generic without an address which breaks nic
        # discovery for the next run.
        devices = get_vmbus_network_device_ids(node, filter_driver="uio_hv_generic")
        if not devices:
            log.debug(f"{node.name}: no nics are bound to uio_hv_generic")
            return
        log.info(f"{node.name}: rebinding {devices} from uio_hv_generic to hv_netvsc")
        rebind_uio_devices_to_hv_netvsc(node, devices)
        node.nics.reload()
