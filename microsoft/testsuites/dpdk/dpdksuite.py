# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from collections import deque
from typing import Dict, List, Tuple

from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    Node,
    RemoteNode,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.features import NetworkInterface, Sriov
from lisa.nic import Nics
from lisa.testsuite import simple_requirement
from lisa.tools import Echo, Lspci, Mount
from lisa.util import constants
from lisa.util.parallel import Task, TaskManager
from microsoft.testsuites.dpdk.dpdktestpmd import DpdkTestpmd

VDEV_TYPE = "net_vdev_netvsc"


@TestSuiteMetadata(
    area="dpdk",
    category="functional",
    description="""
    This test suite check DPDK functionality
    """,
)
class Dpdk(TestSuite):
    @TestCaseMetadata(
        description="""
            This test case checks DPDK can be built and installed correctly.
            Prerequisites, accelerated networking must be enabled.
            The VM should have at least two network interfaces,
             with one interface for management.
            More detailes refer https://docs.microsoft.com/en-us/azure/virtual-network/setup-dpdk#prerequisites # noqa: E501
        """,
        priority=2,
        requirement=simple_requirement(
            min_nic_count=2,
            network_interface=Sriov(),
        ),
    )
    def verify_dpdk_build(self, node: Node, log: Logger) -> None:
        # setup and unwrap the resources for this test
        test_kit = initialize_node_resources(node, log)
        node_nic_info, testpmd = test_kit.node_nic_info, test_kit.testpmd

        # grab a nic and run testpmd
        test_nic_id, test_nic = node_nic_info.get_test_nic()
        testpmd_cmd = testpmd.generate_testpmd_command(test_nic, test_nic_id, "txonly")
        testpmd.run_for_n_seconds(testpmd_cmd, 10)
        tx_pps = testpmd.get_tx_pps()
        log.info(
            f"TX-PPS:{tx_pps} from {test_nic.upper}/{test_nic.lower}:"
            + f"{test_nic.pci_slot}"
        )
        assert_that(tx_pps).described_as(
            f"TX-PPS ({tx_pps}) should have been greater than 2^20 (~1m) PPS."
        ).is_greater_than(2 ** 20)

    @TestCaseMetadata(
        description="""
            Tests a basic sender/receiver setup.
            Sender sends the packets, receiver receives them.
            We check both to make sure the received traffic is within the expected
            order-of-magnitude.
        """,
        priority=2,
        requirement=simple_requirement(
            min_nic_count=2,
            network_interface=Sriov(),
            min_count=2,
        ),
    )
    def verify_dpdk_send_receive(self, environment: Environment, log: Logger) -> None:
        external_ips = []
        for node in environment.nodes.list():
            if isinstance(node, RemoteNode):
                external_ips += node.connection_info[
                    constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS
                ]
            else:
                raise SkippedException()
        log.debug((f"\nsender:{external_ips[0]}\nreceiver:{external_ips[1]}\n"))

        test_kits = _init_nodes_concurrent(environment, log)
        sender, receiver = test_kits

        # helpful to have the public ip for debugging
        (snd_id, snd_nic), (rcv_id, rcv_nic) = [
            x.node_nic_info.get_test_nic() for x in test_kits
        ]

        snd_cmd = sender.testpmd.generate_testpmd_command(
            snd_nic,
            snd_id,
            "txonly",
            extra_args=f"--tx-ip={snd_nic.ip_addr},{rcv_nic.ip_addr}",
        )
        rcv_cmd = receiver.testpmd.generate_testpmd_command(rcv_nic, rcv_id, "rxonly")

        kit_cmd_pairs = {
            sender: snd_cmd,
            receiver: rcv_cmd,
        }

        results = _run_testpmd_concurrent(kit_cmd_pairs, 15, log)

        log.info(f"\nSENDER:\n{results[sender]}")

        log.info(f"\nRECEIVER:\n{results[receiver]}")

        rcv_rx_pps = receiver.testpmd.get_rx_pps()
        snd_tx_pps = sender.testpmd.get_tx_pps()
        log.info(f"receiver rx-pps: {rcv_rx_pps}")
        log.info(f"sender tx-pps: {snd_tx_pps}")

        # differences in NIC model throughput can lead to different snd/rcv counts
        assert_that(rcv_rx_pps).described_as(
            "Throughput for RECEIVE was below the correct order-of-magnitude"
        ).is_greater_than(2 ** 20)
        assert_that(snd_tx_pps).described_as(
            "Throughput for SEND was below the correct order of magnitude"
        ).is_greater_than(2 ** 20)


def _init_hugepages(node: Node) -> None:
    mount = node.tools[Mount]
    mount.mount(disk_name="nodev", point="/mnt/huge", type="hugetlbfs")
    mount.mount(
        disk_name="nodev",
        point="/mnt/huge-1G",
        type="hugetlbfs",
        options="pagesize=1G",
    )
    _enable_hugepages(node)


def _enable_hugepages(node: Node) -> None:
    echo = node.tools[Echo]
    echo.write_to_file(
        "1024",
        "/sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages",
        sudo=True,
    )
    echo.write_to_file(
        "1",
        "/sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages",
        sudo=True,
    )


class DpdkTestResources:
    def __init__(
        self, _node: Node, _node_nic_info: Nics, _testpmd: DpdkTestpmd
    ) -> None:
        self.node_nic_info = _node_nic_info
        self.testpmd = _testpmd
        self.node = _node


def initialize_node_resources(node: Node, log: Logger) -> DpdkTestResources:
    network_interface_feature = node.features[NetworkInterface]
    sriov_is_enabled = network_interface_feature.is_enabled_sriov()
    log.info(f"Node[{node.name}] Verify SRIOV is enabled: {sriov_is_enabled}")
    assert_that(sriov_is_enabled).described_as(
        f"SRIOV was not enabled for this test node ({node.name})"
    ).is_true()

    # dump some info about the pci devices before we start
    lspci = node.tools[Lspci]
    log.info(f"Node[{node.name}] LSPCI Info:\n{lspci.run().stdout}\n")
    # init and enable hugepages (required by dpdk)
    _init_hugepages(node)

    # initialize testpmd tool (installs dpdk)
    testpmd = DpdkTestpmd(node)
    testpmd.install()

    # initialize node nic info class (gathers info about nic devices)
    node_nic_info = Nics(node)
    node_nic_info.initialize()
    assert_that(len(node_nic_info)).described_as(
        "Test needs at least 2 NICs on the test node."
    ).is_greater_than_or_equal_to(2)
    return DpdkTestResources(node, node_nic_info, testpmd)


def _run_testpmd_concurrent(
    node_cmd_pairs: Dict[DpdkTestResources, str],
    seconds: int,
    log: Logger,
) -> Dict[DpdkTestResources, str]:
    output: Dict[DpdkTestResources, str] = dict()
    cmd_pairs_as_tuples = deque(node_cmd_pairs.items())

    def thread_callback(result: Tuple[DpdkTestResources, str]) -> None:
        output[result[0]] = result[1]

    def _run_node_init() -> Tuple[DpdkTestResources, str]:
        # TaskManager doesn't let you pass parameters to your threads
        testkit, cmd = cmd_pairs_as_tuples.pop()
        return (testkit, testkit.testpmd.run_for_n_seconds(cmd, seconds))

    task_manager = TaskManager[Tuple[DpdkTestResources, str]](
        len(cmd_pairs_as_tuples), thread_callback
    )

    for i in range(len(node_cmd_pairs)):
        task_manager.submit_task(
            Task[Tuple[DpdkTestResources, str]](i, _run_node_init, log)
        )

    task_manager.wait_for_all_workers()

    return output


def _init_nodes_concurrent(
    environment: Environment, log: Logger
) -> List[DpdkTestResources]:
    # Use threading module to parallelize the IO-bound node init.
    test_kits: List[DpdkTestResources] = []
    nodes = deque(environment.nodes.list())

    def thread_callback(output: DpdkTestResources) -> None:
        test_kits.append(output)

    def run_node_init() -> DpdkTestResources:
        # pop a node from the deque and initialize it.
        node = nodes.pop()
        return initialize_node_resources(node, log)

    task_manager = TaskManager[DpdkTestResources](
        len(environment.nodes), thread_callback
    )

    for i in range(len(environment.nodes)):
        task_manager.submit_task(Task[DpdkTestResources](i, run_node_init, log))

    task_manager.wait_for_all_workers()

    return test_kits
