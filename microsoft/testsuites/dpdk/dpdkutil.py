import re
import time
from collections import deque
from functools import partial
from typing import Any, Dict, List, Tuple, Union

from assertpy import assert_that, fail
from semver import VersionInfo

from lisa import (
    Environment,
    LisaException,
    Logger,
    Node,
    RemoteNode,
    SkippedException,
    UnsupportedDistroException,
    constants,
)
from lisa.features import NetworkInterface
from lisa.nic import NicInfo
from lisa.operating_system import OperatingSystem
from lisa.tools import Dmesg, Echo, Lsmod, Lspci, Modprobe, Mount
from lisa.tools.mkfs import FileSystem
from lisa.util import perf_timer
from lisa.util.parallel import TaskManager, run_in_parallel, run_in_parallel_async
from microsoft.testsuites.dpdk.dpdktestpmd import PACKAGE_MANAGER_SOURCE, DpdkTestpmd


# DPDK added new flags in 19.11 that some tests rely on for send/recv
# Adding an exception so we don't have to catch all LisaExceptions
class UnsupportedPackageVersionException(LisaException):
    """
    Exception to indicate that a required package does not support a
    feature or function needed for a specific test.
    """

    def __init__(
        self,
        os: "OperatingSystem",
        package_name: str,
        package_version: VersionInfo,
        missing_feature: str,
        message: str = "",
    ) -> None:
        self.name = os.name
        self.version = os.information.full_version
        self._extended_message = message
        self.package_info = f"{package_name}: {str(package_version)}"
        self.missing_feature = missing_feature

    def __str__(self) -> str:
        message = (
            f"Detected incompatible package on: '{self.version}'."
            f"Package {self.package_info} does not support an operation "
            f"required for this test: {self.missing_feature}"
        )
        if self._extended_message:
            message = f"{message}. {self._extended_message}"
        return message


class DpdkTestResources:
    def __init__(self, _node: Node, _testpmd: DpdkTestpmd) -> None:
        self.testpmd = _testpmd
        self.node = _node
        self.nic_controller = _node.features[NetworkInterface]
        self.dmesg = _node.tools[Dmesg]
        self._last_dmesg = ""
        test_nic = self.node.nics.get_nic_by_index()
        # generate hotplug pattern for this specific nic
        self.vf_hotplug_regex = re.compile(
            f"{test_nic.upper}: Data path switched to VF:"
        )
        self.vf_slot_removal_regex = re.compile(f"{test_nic.upper}: VF unregistering:")

    def wait_for_dmesg_output(self, wait_for: str, timeout: int) -> bool:
        search_pattern = None
        if wait_for == "AN_DISABLE":
            search_pattern = self.vf_slot_removal_regex
        elif wait_for == "AN_REENABLE":
            search_pattern = self.vf_hotplug_regex
        else:
            raise LisaException(
                "Unknown search pattern specified in "
                "DpdkTestResources:wait_for_dmesg_output"
            )

        self.node.log.info(search_pattern.pattern)
        timer = perf_timer.Timer()
        while timer.elapsed(stop=False) < timeout:
            output = self.dmesg.get_output(force_run=True)
            if search_pattern.search(output.replace(self._last_dmesg, "")):
                self._last_dmesg = output  # save old output to filter next time
                self.node.log.info(
                    f"Found VF hotplug info after {timer.elapsed()} seconds"
                )
                return True
            else:
                time.sleep(1)
        return False


def init_hugepages(node: Node) -> None:
    mount = node.tools[Mount]
    mount.mount(name="nodev", point="/mnt/huge", type=FileSystem.hugetlbfs)
    mount.mount(
        name="nodev",
        point="/mnt/huge-1G",
        type=FileSystem.hugetlbfs,
        options="pagesize=1G",
    )
    _enable_hugepages(node)


def _enable_hugepages(node: Node) -> None:
    echo = node.tools[Echo]
    echo.write_to_file(
        "1024",
        node.get_pure_path(
            "/sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages"
        ),
        sudo=True,
    )
    echo.write_to_file(
        "1",
        node.get_pure_path(
            "/sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages"
        ),
        sudo=True,
    )


def generate_send_receive_run_info(
    pmd: str,
    sender: DpdkTestResources,
    receiver: DpdkTestResources,
    txq: int = 0,
    rxq: int = 0,
    core_count: int = 0,
) -> Dict[DpdkTestResources, str]:

    snd_nic, rcv_nic = [x.node.nics.get_nic_by_index() for x in [sender, receiver]]

    snd_cmd = sender.testpmd.generate_testpmd_command(
        snd_nic,
        0,
        "txonly",
        pmd,
        extra_args=f"--tx-ip={snd_nic.ip_addr},{rcv_nic.ip_addr}",
        txq=txq,
        rxq=rxq,
        use_core_count=core_count,
    )
    rcv_cmd = receiver.testpmd.generate_testpmd_command(
        rcv_nic,
        0,
        "macswap",  # receive packet, swap mac address for snd/rcv, and forward
        pmd,
        txq=txq,
        rxq=rxq,
        use_core_count=core_count,
    )

    kit_cmd_pairs = {
        sender: snd_cmd,
        receiver: rcv_cmd,
    }

    return kit_cmd_pairs


UIO_HV_GENERIC_SYSFS_PATH = "/sys/bus/vmbus/drivers/uio_hv_generic"
HV_NETVSC_SYSFS_PATH = "/sys/bus/vmbus/drivers/hv_netvsc"


def enable_uio_hv_generic_for_nic(node: Node, nic: NicInfo) -> None:

    # hv_uio_generic driver uuid, a constant value used by vmbus.
    # https://doc.dpdk.org/guides/nics/netvsc.html#installation
    hv_uio_generic_uuid = "f8615163-df3e-46c5-913f-f2d2f965ed0e"

    # using netvsc pmd directly for dpdk on hv counterintuitively requires
    # you to enable to uio_hv_generic driver, steps are found:
    # https://doc.dpdk.org/guides/nics/netvsc.html#installation

    echo = node.tools[Echo]
    lsmod = node.tools[Lsmod]
    modprobe = node.tools[Modprobe]
    # enable if it is not already enabled
    if not lsmod.module_exists("uio_hv_generic", force_run=True):
        modprobe.load("uio_hv_generic")
        # vmbus magic to enable uio_hv_generic
        echo.write_to_file(
            hv_uio_generic_uuid,
            node.get_pure_path("/sys/bus/vmbus/drivers/uio_hv_generic/new_id"),
            sudo=True,
        )


def initialize_node_resources(
    node: Node,
    log: Logger,
    variables: Dict[str, Any],
    pmd: str,
    sample_apps: Union[List[str], None] = None,
) -> DpdkTestResources:
    dpdk_source = variables.get("dpdk_source", PACKAGE_MANAGER_SOURCE)
    dpdk_branch = variables.get("dpdk_branch", "")
    log.info(
        "Dpdk initialize_node_resources running"
        f"found dpdk_source '{dpdk_source}' and dpdk_branch '{dpdk_branch}'"
    )

    network_interface_feature = node.features[NetworkInterface]
    sriov_is_enabled = network_interface_feature.is_enabled_sriov()
    log.info(f"Node[{node.name}] Verify SRIOV is enabled: {sriov_is_enabled}")
    assert_that(sriov_is_enabled).described_as(
        f"SRIOV was not enabled for this test node ({node.name})"
    ).is_true()

    # dump some info about the pci devices before we start
    lspci = node.tools[Lspci]
    log.info(f"Node[{node.name}] LSPCI Info:\n{lspci.run().stdout}\n")

    # initialize testpmd tool (installs dpdk)
    testpmd = DpdkTestpmd(node)
    testpmd.set_dpdk_source(dpdk_source)
    testpmd.set_dpdk_branch(dpdk_branch)
    testpmd.add_sample_apps_to_build_list(sample_apps)
    try:
        testpmd.install()
    except UnsupportedDistroException as err:
        # forward message from distro exception
        raise SkippedException(err)

    # init and enable hugepages (required by dpdk)
    init_hugepages(node)

    assert_that(len(node.nics)).described_as(
        "Test needs at least 1 NIC on the test node."
    ).is_greater_than_or_equal_to(1)

    test_nic = node.nics.get_nic_by_index()

    # check an assumption that our nics are bound to hv_netvsc
    # at test start.

    assert_that(test_nic.bound_driver).described_as(
        f"Error: Expected test nic {test_nic.upper} to be "
        f"bound to hv_netvsc. Found {test_nic.bound_driver}."
    ).is_equal_to("hv_netvsc")

    # netvsc pmd requires uio_hv_generic to be loaded before use
    if pmd == "netvsc":
        enable_uio_hv_generic_for_nic(node, test_nic)
        # if this device is paired, set the upper device 'down'
        if test_nic.lower:
            node.nics.unbind(test_nic)
            node.nics.bind(test_nic, UIO_HV_GENERIC_SYSFS_PATH)

    return DpdkTestResources(node, testpmd)


def check_send_receive_compatibility(test_kits: List[DpdkTestResources]) -> None:
    for kit in test_kits:
        if not kit.testpmd.has_tx_ip_flag():
            raise UnsupportedPackageVersionException(
                kit.node.os,
                "dpdk",
                kit.testpmd.get_dpdk_version(),
                "-tx-ip flag for ip forwarding",
            )


def run_testpmd_concurrent(
    node_cmd_pairs: Dict[DpdkTestResources, str],
    seconds: int,
    log: Logger,
    rescind_sriov: bool = False,
) -> Dict[DpdkTestResources, str]:
    output: Dict[DpdkTestResources, str] = dict()
    task_manager = start_testpmd_concurrent(node_cmd_pairs, seconds, log, output)
    if rescind_sriov:
        time.sleep(10)  # run testpmd for a bit before disabling sriov
        test_kits = node_cmd_pairs.keys()

        # disable sriov
        for node_resources in test_kits:
            node_resources.nic_controller.switch_sriov(enable=False, wait=False)

        # wait for disable to hit the vm
        for node_resources in test_kits:
            if not node_resources.wait_for_dmesg_output("AN_DISABLE", seconds // 3):
                fail(
                    "Accelerated Network disable not found in dmesg"
                    f" before timeout for node {node_resources.node.name}"
                )

        time.sleep(10)  # let testpmd run with sriov disabled

        # re-enable sriov
        for node_resources in test_kits:
            node_resources.nic_controller.switch_sriov(enable=True, wait=False)

        # wait for re-enable to hit vms
        for node_resources in test_kits:
            if not node_resources.wait_for_dmesg_output("AN_REENABLE", seconds // 2):
                fail(
                    "Accelerated Network re-enable not found "
                    f" in dmesg before timeout for node  {node_resources.node.name}"
                )

        time.sleep(15)  # let testpmd run with sriov re-enabled

        # kill the commands to collect the output early and terminate before timeout
        for node_resources in test_kits:
            node_resources.testpmd.kill_previous_testpmd_command()

    task_manager.wait_for_all_workers()

    return output


def start_testpmd_concurrent(
    node_cmd_pairs: Dict[DpdkTestResources, str],
    seconds: int,
    log: Logger,
    output: Dict[DpdkTestResources, str],
) -> TaskManager[Tuple[DpdkTestResources, str]]:
    cmd_pairs_as_tuples = deque(node_cmd_pairs.items())

    def _collect_dict_result(result: Tuple[DpdkTestResources, str]) -> None:
        output[result[0]] = result[1]

    def _run_command_with_testkit(
        run_kit: Tuple[DpdkTestResources, str]
    ) -> Tuple[DpdkTestResources, str]:
        testkit, cmd = run_kit
        return (testkit, testkit.testpmd.run_for_n_seconds(cmd, seconds))

    task_manager = run_in_parallel_async(
        [partial(_run_command_with_testkit, x) for x in cmd_pairs_as_tuples],
        _collect_dict_result,
    )

    return task_manager


def init_nodes_concurrent(
    environment: Environment, log: Logger, variables: Dict[str, Any], pmd: str
) -> List[DpdkTestResources]:
    # Use threading module to parallelize the IO-bound node init.
    test_kits = run_in_parallel(
        [
            partial(initialize_node_resources, node, log, variables, pmd)
            for node in environment.nodes.list()
        ],
        log,
    )
    return test_kits


def verify_dpdk_build(
    node: Node,
    log: Logger,
    variables: Dict[str, Any],
    pmd: str,
) -> None:
    # setup and unwrap the resources for this test
    test_kit = initialize_node_resources(node, log, variables, pmd)
    testpmd = test_kit.testpmd

    # grab a nic and run testpmd
    test_nic = node.nics.get_nic_by_index()

    testpmd_cmd = testpmd.generate_testpmd_command(
        test_nic,
        0,
        "txonly",
        pmd,
    )
    testpmd.run_for_n_seconds(testpmd_cmd, 10)
    tx_pps = testpmd.get_mean_tx_pps()
    log.info(
        f"TX-PPS:{tx_pps} from {test_nic.upper}/{test_nic.lower}:"
        + f"{test_nic.pci_slot}"
    )
    assert_that(tx_pps).described_as(
        f"TX-PPS ({tx_pps}) should have been greater than 2^20 (~1m) PPS."
    ).is_greater_than(2**20)


def verify_dpdk_send_receive(
    environment: Environment,
    log: Logger,
    variables: Dict[str, Any],
    pmd: str,
    core_count: int = 0,
) -> Tuple[DpdkTestResources, DpdkTestResources]:

    # helpful to have the public ips labeled for debugging
    external_ips = []
    for node in environment.nodes.list():
        if isinstance(node, RemoteNode):
            external_ips += node.connection_info[
                constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS
            ]
        else:
            raise SkippedException()
    log.debug((f"\nsender:{external_ips[0]}\nreceiver:{external_ips[1]}\n"))

    test_kits = init_nodes_concurrent(environment, log, variables, pmd)

    check_send_receive_compatibility(test_kits)

    sender, receiver = test_kits

    kit_cmd_pairs = generate_send_receive_run_info(
        pmd, sender, receiver, core_count=core_count
    )

    results = run_testpmd_concurrent(kit_cmd_pairs, 15, log)

    # helpful to have the outputs labeled
    log.debug(f"\nSENDER:\n{results[sender]}")
    log.debug(f"\nRECEIVER:\n{results[receiver]}")

    rcv_rx_pps = receiver.testpmd.get_mean_rx_pps()
    snd_tx_pps = sender.testpmd.get_mean_tx_pps()
    log.info(f"receiver rx-pps: {rcv_rx_pps}")
    log.info(f"sender tx-pps: {snd_tx_pps}")

    # differences in NIC type throughput can lead to different snd/rcv counts
    assert_that(rcv_rx_pps).described_as(
        "Throughput for RECEIVE was below the correct order-of-magnitude"
    ).is_greater_than(2**20)
    assert_that(snd_tx_pps).described_as(
        "Throughput for SEND was below the correct order of magnitude"
    ).is_greater_than(2**20)

    return sender, receiver


def verify_dpdk_send_receive_multi_txrx_queue(
    environment: Environment, log: Logger, variables: Dict[str, Any], pmd: str
) -> Tuple[DpdkTestResources, DpdkTestResources]:

    test_kits = init_nodes_concurrent(environment, log, variables, pmd)

    check_send_receive_compatibility(test_kits)

    sender, receiver = test_kits

    kit_cmd_pairs = generate_send_receive_run_info(
        pmd, sender, receiver, txq=16, rxq=16
    )

    results = run_testpmd_concurrent(kit_cmd_pairs, 15, log)

    # helpful to have the outputs labeled
    log.debug(f"\nSENDER:\n{results[sender]}")
    log.debug(f"\nRECEIVER:\n{results[receiver]}")

    rcv_rx_pps = receiver.testpmd.get_mean_rx_pps()
    snd_tx_pps = sender.testpmd.get_mean_tx_pps()
    log.info(f"receiver rx-pps: {rcv_rx_pps}")
    log.info(f"sender tx-pps: {snd_tx_pps}")

    # differences in NIC type throughput can lead to different snd/rcv counts
    # check that throughput it greater than 1m pps as a baseline
    assert_that(rcv_rx_pps).described_as(
        "Throughput for RECEIVE was below the correct order-of-magnitude"
    ).is_greater_than(2**20)
    assert_that(snd_tx_pps).described_as(
        "Throughput for SEND was below the correct order of magnitude"
    ).is_greater_than(2**20)

    return sender, receiver
