import itertools
import time
from collections import deque
from functools import partial
from typing import Any, Dict, List, Tuple, Union

from assertpy import assert_that
from semver import VersionInfo

from lisa import (
    Environment,
    LisaException,
    Logger,
    Node,
    RemoteNode,
    SkippedException,
    UnsupportedDistroException,
    UnsupportedKernelException,
    constants,
)
from lisa.base_tools.uname import Uname
from lisa.features import NetworkInterface
from lisa.nic import NicInfo
from lisa.operating_system import OperatingSystem, Ubuntu
from lisa.tools import (
    Dmesg,
    Echo,
    Firewall,
    Free,
    KernelConfig,
    Lscpu,
    Lsmod,
    Lspci,
    Modprobe,
    Mount,
    Ping,
    Timeout,
)
from lisa.tools.mkfs import FileSystem
from lisa.util.parallel import TaskManager, run_in_parallel, run_in_parallel_async
from microsoft.testsuites.dpdk.common import DPDK_STABLE_GIT_REPO, check_dpdk_support
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


# container class for test resources to be passed to run_testpmd_concurrent
class DpdkTestResources:
    def __init__(self, _node: Node, _testpmd: DpdkTestpmd) -> None:
        self.testpmd = _testpmd
        self.node = _node
        self.nic_controller = _node.features[NetworkInterface]
        self.dmesg = _node.tools[Dmesg]
        self._last_dmesg = ""
        self.switch_sriov = True


def init_hugepages(node: Node) -> None:
    mount = node.tools[Mount]
    mount.mount(name="nodev", point="/mnt/huge", fs_type=FileSystem.hugetlbfs)
    mount.mount(
        name="nodev",
        point="/mnt/huge-1G",
        fs_type=FileSystem.hugetlbfs,
        options="pagesize=1G",
    )
    _enable_hugepages(node)


def _enable_hugepages(node: Node) -> None:
    echo = node.tools[Echo]

    meminfo = node.tools[Free]
    nics_count = len(node.nics.get_upper_nics())

    numa_nodes = node.tools[Lscpu].get_numa_node_count()
    request_pages_2mb = (nics_count - 1) * 1024 * numa_nodes
    request_pages_1gb = (nics_count - 1) * numa_nodes
    memfree_2mb = meminfo.get_free_memory_mb()
    memfree_1mb = meminfo.get_free_memory_gb()

    # request 2iGB memory per nic, 1 of 2MiB pages and 1 GiB page
    # check there is enough memory on the device first.
    # default to enough for one nic if not enough is available
    # this should be fine for tests on smaller SKUs

    if memfree_2mb < request_pages_2mb:
        node.log.debug(
            "WARNING: Not enough 2MB pages available for DPDK! "
            f"Requesting {request_pages_2mb} found {memfree_2mb} free. "
            "Test may fail if it cannot allocate memory."
        )
        request_pages_2mb = 1024

    if memfree_1mb < (request_pages_1gb * 2):  # account for 2MB pages by doubling ask
        node.log.debug(
            "WARNING: Not enough 1GB pages available for DPDK! "
            f"Requesting {(request_pages_1gb * 2)} found {memfree_1mb} free. "
            "Test may fail if it cannot allocate memory."
        )
        request_pages_1gb = 1

    for i in range(numa_nodes):
        echo.write_to_file(
            f"{request_pages_2mb}",
            node.get_pure_path(
                f"/sys/devices/system/node/node{i}/hugepages/"
                "hugepages-2048kB/nr_hugepages"
            ),
            sudo=True,
        )

        echo.write_to_file(
            f"{request_pages_1gb}",
            node.get_pure_path(
                f"/sys/devices/system/node/node{i}/hugepages/"
                "hugepages-1048576kB/nr_hugepages"
            ),
            sudo=True,
        )


def _set_forced_source_by_distro(node: Node, variables: Dict[str, Any]) -> None:
    # DPDK packages 17.11 which is EOL and doesn't have the
    # net_vdev_netvsc pmd used for simple handling of hyper-v
    # guests. Force stable source build on this platform.
    # Default to 20.11 unless another version is provided by the
    # user. 20.11 is the latest dpdk version for 18.04.
    if isinstance(node.os, Ubuntu) and node.os.information.version < "20.4.0":
        variables["dpdk_source"] = variables.get("dpdk_source", DPDK_STABLE_GIT_REPO)
        variables["dpdk_branch"] = variables.get("dpdk_branch", "v20.11")


def _ping_all_nodes_in_environment(environment: Environment) -> None:
    # a quick connectivity check before the test.
    # this can help establish routes on some platforms before handing
    # all control of the VF over to Testpmd
    nodes = environment.nodes.list()
    for node in nodes:
        try:
            firewall = node.tools[Firewall]
            firewall.stop()
        except Exception as ex:
            node.log.debug(
                f"firewall is not enabled on OS {node.os.name} with exception {ex}"
            )

    node_permutations = itertools.permutations(nodes, 2)
    for node_pair in node_permutations:
        node_a, node_b = node_pair  # get nodes and nics
        nic_a, nic_b = [x.nics.get_nic_by_index(1) for x in node_pair]
        ip_a, ip_b = [x.ip_addr for x in [nic_a, nic_b]]  # get ips
        ping_a = node_a.tools[Ping].ping(target=ip_b, nic_name=nic_a.upper)
        ping_b = node_b.tools[Ping].ping(target=ip_a, nic_name=nic_b.upper)
        assert_that(ping_a and ping_b).described_as(
            (
                "VM ping test failed.\n"
                f"{node_a.name} {ip_a} -> {node_b.name} {ip_b} : {ping_a}\n"
                f"{node_b.name} {ip_b} -> {node_a.name} {ip_a} : {ping_b}\n"
            )
        ).is_true()


def generate_send_receive_run_info(
    pmd: str,
    sender: DpdkTestResources,
    receiver: DpdkTestResources,
    multiple_queues: bool = False,
    use_service_cores: int = 1,
) -> Dict[DpdkTestResources, str]:
    snd_nic, rcv_nic = [x.node.nics.get_secondary_nic() for x in [sender, receiver]]

    snd_cmd = sender.testpmd.generate_testpmd_command(
        snd_nic,
        0,
        "txonly",
        extra_args=f"--tx-ip={snd_nic.ip_addr},{rcv_nic.ip_addr}",
        multiple_queues=multiple_queues,
        service_cores=use_service_cores,
    )
    rcv_cmd = receiver.testpmd.generate_testpmd_command(
        rcv_nic,
        0,
        "rxonly",
        multiple_queues=multiple_queues,
        service_cores=use_service_cores,
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
    kconfig = node.tools[KernelConfig]
    uname = node.tools[Uname]

    # check if kernel config for Hyper-V VMBus is enabled
    config = "CONFIG_UIO_HV_GENERIC"
    if not kconfig.is_enabled(config):
        kversion = uname.get_linux_information().kernel_version
        if kversion < "4.10.0":
            raise UnsupportedKernelException(node.os)
        else:
            raise LisaException(
                f"The kernel config {config} is not set in kernel version {kversion}."
            )

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
    _set_forced_source_by_distro(node, variables)
    dpdk_source = variables.get("dpdk_source", PACKAGE_MANAGER_SOURCE)
    dpdk_branch = variables.get("dpdk_branch", "")
    log.info(
        "Dpdk initialize_node_resources running"
        f"found dpdk_source '{dpdk_source}' and dpdk_branch '{dpdk_branch}'"
    )

    network_interface_feature = node.features[NetworkInterface]
    sriov_is_enabled = network_interface_feature.is_enabled_sriov()
    if not sriov_is_enabled:
        network_interface_feature.switch_sriov(enable=True, wait=True)

    log.info(f"Node[{node.name}] Verify SRIOV is enabled: {sriov_is_enabled}")
    assert_that(sriov_is_enabled).described_as(
        f"SRIOV was not enabled for this test node ({node.name})"
    ).is_true()

    # dump some info about the pci devices before we start
    lspci = node.tools[Lspci]
    log.info(f"Node[{node.name}] LSPCI Info:\n{lspci.run().stdout}\n")

    # check compatibility first.
    try:
        check_dpdk_support(node)
    except UnsupportedDistroException as err:
        # forward message from distro exception
        raise SkippedException(err)

    # verify SRIOV is setup as-expected on the node after compat check
    node.nics.wait_for_sriov_enabled()

    # create tool, initialize testpmd tool (installs dpdk)
    testpmd: DpdkTestpmd = node.tools.get(
        DpdkTestpmd,
        dpdk_source=dpdk_source,
        dpdk_branch=dpdk_branch,
        sample_apps=sample_apps,
    )

    # init and enable hugepages (required by dpdk)
    init_hugepages(node)

    assert_that(len(node.nics)).described_as(
        "Test needs at least 1 NIC on the test node."
    ).is_greater_than_or_equal_to(1)

    test_nic = node.nics.get_secondary_nic()

    # check an assumption that our nics are bound to hv_netvsc
    # at test start.

    assert_that(test_nic.bound_driver).described_as(
        f"Error: Expected test nic {test_nic.upper} to be "
        f"bound to hv_netvsc. Found {test_nic.bound_driver}."
    ).is_equal_to("hv_netvsc")

    # netvsc pmd requires uio_hv_generic to be loaded before use
    if pmd == "netvsc":
        # this code makes changes to interfaces that will cause later tests to fail.
        # Therefore we mark the node dirty to prevent future testing on this environment
        node.mark_dirty()
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

        # disable sriov (and wait for change to apply)
        for node_resources in [x for x in test_kits if x.switch_sriov]:
            node_resources.nic_controller.switch_sriov(
                enable=False, wait=True, reset_connections=False
            )

        # let run for a bit with SRIOV disabled
        time.sleep(10)

        # re-enable sriov
        for node_resources in [x for x in test_kits if x.switch_sriov]:
            node_resources.nic_controller.switch_sriov(
                enable=True, wait=True, reset_connections=False
            )

        # run for a bit with SRIOV re-enabled
        time.sleep(10)

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
    # quick check when initializing, have each node ping the other nodes.
    # When binding DPDK directly to the VF this helps ensure l2/l3 routes
    # are established before handing all control over to testpmd.
    _ping_all_nodes_in_environment(environment)

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
    test_nic = node.nics.get_secondary_nic()

    testpmd_cmd = testpmd.generate_testpmd_command(
        test_nic,
        0,
        "txonly",
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
    use_service_cores: int = 1,
    multiple_queues: bool = False,
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

    # get test duration variable if set
    # enables long-running tests to shakeQoS and SLB issue
    test_duration: int = variables.get("dpdk_test_duration", 15)
    kill_timeout = test_duration + 5
    test_kits = init_nodes_concurrent(environment, log, variables, pmd)

    check_send_receive_compatibility(test_kits)

    sender, receiver = test_kits

    kit_cmd_pairs = generate_send_receive_run_info(
        pmd,
        sender,
        receiver,
        use_service_cores=use_service_cores,
        multiple_queues=multiple_queues,
    )
    receive_timeout = kill_timeout + 10
    receive_result = receiver.node.tools[Timeout].start_with_timeout(
        kit_cmd_pairs[receiver],
        receive_timeout,
        constants.SIGINT,
        kill_timeout=receive_timeout,
    )
    receive_result.wait_output("start packet forwarding")
    sender_result = sender.node.tools[Timeout].start_with_timeout(
        kit_cmd_pairs[sender],
        test_duration,
        constants.SIGINT,
        kill_timeout=kill_timeout,
    )

    results = dict()
    results[sender] = sender.testpmd.process_testpmd_output(sender_result.wait_result())
    results[receiver] = receiver.testpmd.process_testpmd_output(
        receive_result.wait_result()
    )

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
    environment: Environment,
    log: Logger,
    variables: Dict[str, Any],
    pmd: str,
    use_service_cores: int = 1,
) -> Tuple[DpdkTestResources, DpdkTestResources]:
    # get test duration variable if set
    # enables long-running tests to shakeQoS and SLB issue
    return verify_dpdk_send_receive(
        environment, log, variables, pmd, use_service_cores=1, multiple_queues=True
    )
