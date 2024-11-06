import itertools
import time
from collections import deque
from decimal import Decimal
from functools import partial
from typing import Any, Dict, List, Optional, Tuple, Union

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
    notifier,
)
from lisa.base_tools.uname import Uname
from lisa.features import NetworkInterface
from lisa.nic import NicInfo
from lisa.operating_system import Fedora, OperatingSystem, Ubuntu, CentOs
from lisa.tools import (
    Dmesg,
    Echo,
    Firewall,
    Free,
    Ip,
    KernelConfig,
    Kill,
    Lscpu,
    Lsmod,
    Lspci,
    Modprobe,
    Mount,
    Ntttcp,
    Ping,
    Sysctl,
    Tee,
    Timeout,
)
from lisa.tools.mkfs import FileSystem
from lisa.util.constants import SIGINT
from lisa.util.parallel import TaskManager, run_in_parallel, run_in_parallel_async
from microsoft.testsuites.dpdk.common import (
    AZ_ROUTE_ALL_TRAFFIC,
    DPDK_STABLE_GIT_REPO,
    check_dpdk_support,
)
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


def init_hugepages(node: Node, enable_gibibyte_hugepages: bool = False) -> None:
    mount = node.tools[Mount]
    if enable_gibibyte_hugepages:
        mount.mount(
            name="nodev",
            point="/mnt/huge-1G",
            fs_type=FileSystem.hugetlbfs,
            options="pagesize=1G",
        )
    else:
        mount.mount(name="nodev", point="/mnt/huge", fs_type=FileSystem.hugetlbfs)
    _enable_hugepages(node, enable_gibibyte_hugepages)


def _enable_hugepages(node: Node, enable_gibibyte_hugepages: bool = False) -> None:
    tee = node.tools[Tee]

    meminfo = node.tools[Free]
    nics_count = len(node.nics.get_nic_names())

    numa_nodes = node.tools[Lscpu].get_numa_node_count()
    request_pages_2mb = (nics_count - 1) * 1024 * numa_nodes
    request_pages_1gb = (nics_count - 1) * numa_nodes
    memfree_2mb = meminfo.get_free_memory_mb()
    memfree_1mb = meminfo.get_free_memory_gb()

    # request 2iGB memory per nic, 1 of 2MiB pages and 1 GiB page
    # check there is enough memory on the device first.
    # default to enough for one nic if not enough is available
    # this should be fine for tests on smaller SKUs

    if enable_gibibyte_hugepages:
        if memfree_1mb < (
            request_pages_1gb * 2
        ):  # account for 2MB pages by doubling ask
            node.log.debug(
                "WARNING: Not enough 1GB pages available for DPDK! "
                f"Requesting {(request_pages_1gb * 2)} found {memfree_1mb} free. "
                "Test may fail if it cannot allocate memory."
            )
        request_pages_1gb = 1
    else:
        if memfree_2mb < request_pages_2mb:
            node.log.debug(
                "WARNING: Not enough 2MB pages available for DPDK! "
                f"Requesting {request_pages_2mb} found {memfree_2mb} free. "
                "Test may fail if it cannot allocate memory."
            )
            request_pages_2mb = 1024

    for i in range(numa_nodes):
        if enable_gibibyte_hugepages:
            tee.write_to_file(
                f"{request_pages_1gb}",
                node.get_pure_path(
                    f"/sys/devices/system/node/node{i}/hugepages/"
                    "hugepages-1048576kB/nr_hugepages"
                ),
                sudo=True,
            )
        else:
            tee.write_to_file(
                f"{request_pages_2mb}",
                node.get_pure_path(
                    f"/sys/devices/system/node/node{i}/hugepages/"
                    "hugepages-2048kB/nr_hugepages"
                ),
                sudo=True,
            )


def _set_forced_source_by_distro(
    node: Node, variables: Dict[str, Any], examples: Optional[List[str]]
) -> None:
    # DPDK packages 17.11 which is EOL and doesn't have the
    # net_vdev_netvsc pmd used for simple handling of hyper-v
    # guests. Force stable source build on this platform.
    # Default to 20.11 unless another version is provided by the
    # user. 20.11 is the latest dpdk version for 18.04.
    if (
            (
             isinstance(node.os, Ubuntu)
             and node.os.information.version < "20.4.0"
            )
            or
            (
             isinstance(node.os, CentOs)
             and node.os.information.version < "8.0.0"
            )
        or examples != None
    ):
        variables["dpdk_source"] = variables.get("dpdk_source", DPDK_STABLE_GIT_REPO)
        if node.nics.is_mana_device_present():
            variables["dpdk_branch"] = variables.get("dpdk_branch", "v23.11")
        else:
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
        ping_a = node_a.tools[Ping].ping(target=ip_b, nic_name=nic_a.name)
        ping_b = node_b.tools[Ping].ping(target=ip_a, nic_name=nic_b.name)
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
    if multiple_queues:
        sender.testpmd.vf_helper.set_multiple_queue()
        receiver.testpmd.vf_helper.set_multiple_queue()

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

    tee = node.tools[Tee]
    lsmod = node.tools[Lsmod]
    modprobe = node.tools[Modprobe]
    uname = node.tools[Uname]

    # check if kernel config for Hyper-V VMBus is enabled
    try:
        kconfig = node.tools[KernelConfig]
        config = "CONFIG_UIO_HV_GENERIC"
        if not kconfig.is_enabled(config):
            kversion = uname.get_linux_information().kernel_version
            if kversion < "4.10.0":
                raise UnsupportedKernelException(node.os)
            else:
                raise LisaException(
                    f"The kernel config {config} is not set in kernel version {kversion}."
                )
    except LisaException:
        node.log.debug(
            "Attempt to check for CONFIG_UIO_HV_GENERIC failed. Proceeding..."
        )
    # enable if it is not already enabled
    if not lsmod.module_exists("uio_hv_generic", force_run=True):
        modprobe.load("uio_hv_generic")
    # vmbus magic to enable uio_hv_generic
    tee.write_to_file(
        hv_uio_generic_uuid,
        node.get_pure_path("/sys/bus/vmbus/drivers/uio_hv_generic/new_id"),
        sudo=True,
    )


def do_pmd_driver_setup(
    node: Node, test_nic: NicInfo, testpmd: DpdkTestpmd, pmd: str = "failsafe"
) -> None:
    if pmd == "netvsc":
        # setup system for netvsc pmd
        # https://doc.dpdk.org/guides/nics/netvsc.html
        enable_uio_hv_generic_for_nic(node, test_nic)
        node.nics.unbind(test_nic)
        node.nics.bind(test_nic, UIO_HV_GENERIC_SYSFS_PATH)

    # if mana is present, set VF interface down.
    # FIXME: add mana dpdk docs link when it's available.
    if testpmd.vf_helper.is_mana():
        ip = node.tools[Ip]
        if test_nic.lower and ip.is_device_up(test_nic.lower):
            ip.down(test_nic.lower)


def initialize_node_resources(
    node: Node,
    log: Logger,
    variables: Dict[str, Any],
    pmd: str,
    sample_apps: Union[List[str], None] = None,
    enable_gibibyte_hugepages: bool = False,
    extra_nics: Union[List[NicInfo], None] = None,
    build_release: bool = False,
) -> DpdkTestResources:
    _set_forced_source_by_distro(node, variables, examples=sample_apps)
    dpdk_source = variables.get("dpdk_source", PACKAGE_MANAGER_SOURCE)
    dpdk_branch = variables.get("dpdk_branch", "")
    rdma_core_source = variables.get("rdma_core_source", "")
    rdma_core_ref = variables.get("rdma_core_git_ref", "")
    update_kernel = variables.get("dpdk_update_kernel", True)
    force_net_failsafe_pmd = variables.get("dpdk_force_net_failsafe_pmd", False)
    enforce_strict_threshold = variables.get("dpdk_enforce_strict_threshold", False)
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
    node.nics.check_pci_enabled(pci_enabled=True)

    # create tool, initialize testpmd tool (installs dpdk)
    testpmd: DpdkTestpmd = node.tools.get(
        DpdkTestpmd,
        dpdk_source=dpdk_source,
        dpdk_branch=dpdk_branch,
        sample_apps=sample_apps,
        force_net_failsafe_pmd=force_net_failsafe_pmd,
        rdma_core_source=rdma_core_source,
        rdma_core_ref=rdma_core_ref,
        enforce_strict_threshold=enforce_strict_threshold,
        build_release=build_release,
        update_kernel=update_kernel,
    )

    # init and enable hugepages (required by dpdk)
    init_hugepages(node, enable_gibibyte_hugepages)

    assert_that(len(node.nics)).described_as(
        "Test needs at least 1 NIC on the test node."
    ).is_greater_than_or_equal_to(1)

    test_nic = node.nics.get_secondary_nic()

    # check an assumption that our nics are bound to hv_netvsc
    # at test start.

    assert_that(test_nic.module_name).described_as(
        f"Error: Expected test nic {test_nic.name} to be "
        f"bound to hv_netvsc. Found {test_nic.module_name}."
    ).is_equal_to("hv_netvsc")

    # netvsc pmd requires uio_hv_generic to be loaded before use
    do_pmd_driver_setup(node=node, test_nic=test_nic, testpmd=testpmd, pmd=pmd)
    if extra_nics:
        for extra_nic in extra_nics:
            do_pmd_driver_setup(node=node, test_nic=extra_nic, testpmd=testpmd, pmd=pmd)

    return DpdkTestResources(node, testpmd)


def check_send_receive_compatibility(test_kits: List[DpdkTestResources]) -> None:
    for kit in test_kits:
        # MANA nics only support > DPDK 22.11 so will always have the flag
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
    environment: Environment,
    log: Logger,
    variables: Dict[str, Any],
    pmd: str,
    enable_gibibyte_hugepages: bool = False,
    sample_apps: Union[List[str], None] = None,
    build_release: bool = False,
) -> List[DpdkTestResources]:
    # quick check when initializing, have each node ping the other nodes.
    # When binding DPDK directly to the VF this helps ensure l2/l3 routes
    # are established before handing all control over to testpmd.
    _ping_all_nodes_in_environment(environment)

    # Use threading module to parallelize the IO-bound node init.
    test_kits = run_in_parallel(
        [
            partial(
                initialize_node_resources,
                node,
                log,
                variables,
                pmd,
                enable_gibibyte_hugepages=enable_gibibyte_hugepages,
                sample_apps=sample_apps,
                build_release=build_release,
            )
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
    multiple_queues: bool = False,
    gibibyte_hugepages: bool = False,
    build_release: bool = False,
) -> DpdkTestResources:
    # setup and unwrap the resources for this test
    test_kit = initialize_node_resources(
        node,
        log,
        variables,
        pmd,
        enable_gibibyte_hugepages=gibibyte_hugepages,
        build_release=build_release,
    )
    testpmd = test_kit.testpmd
    # designate node as sender
    testpmd.vf_helper.set_sender()
    if multiple_queues:
        testpmd.vf_helper.set_multiple_queue()

    # grab a nic and run testpmd
    test_nic = node.nics.get_secondary_nic()

    testpmd_cmd = testpmd.generate_testpmd_command(
        test_nic, 0, "txonly", multiple_queues=multiple_queues
    )
    testpmd.run_for_n_seconds(testpmd_cmd, 10)
    tx_pps = testpmd.get_mean_tx_pps()
    log.info(
        f"TX-PPS:{tx_pps} from {test_nic.name}/{test_nic.lower}:"
        + f"{test_nic.pci_slot}"
    )

    threshold = testpmd.vf_helper.get_threshold_testpmd()
    hw_name = testpmd.vf_helper.get_hw_name()

    failure_msg = (
        f"TX-PPS ({tx_pps}) for {hw_name} should have been greater "
        f"than {threshold} PPS."
    )
    if testpmd.vf_helper.use_strict_checks:
        failure_msg = "STRICT CHECK ENABLED: " + failure_msg
    assert_that(tx_pps).described_as(failure_msg).is_greater_than(threshold)

    return DpdkTestResources(node, testpmd)


def verify_dpdk_send_receive(
    environment: Environment,
    log: Logger,
    variables: Dict[str, Any],
    pmd: str,
    use_service_cores: int = 1,
    multiple_queues: bool = False,
    gibibyte_hugepages: bool = False,
    build_release: bool = False,
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
    test_kits = init_nodes_concurrent(
        environment,
        log,
        variables,
        pmd,
        enable_gibibyte_hugepages=gibibyte_hugepages,
        build_release=build_release,
    )

    check_send_receive_compatibility(test_kits)

    sender, receiver = test_kits
    # designate sender/receiver before run
    sender.testpmd.vf_helper.set_sender()
    receiver.testpmd.vf_helper.set_receiver()
    # signal multiqueue run to vf helper
    if multiple_queues:
        sender.testpmd.vf_helper.set_multiple_queue()
        receiver.testpmd.vf_helper.set_multiple_queue()
    else:
        sender.testpmd.vf_helper.set_single_queue()
        receiver.testpmd.vf_helper.set_single_queue()

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
    found_error = False
    try:
        receive_result.wait_output("EAL: Error", timeout=5)
        found_error = True
    except LisaException:
        # we actually want this to be missing, so continue if it's not present.
        found_error = False
    if found_error:
        raise LisaException(
            "DPDK EAL hit an error during startup. Check program output for errors."
        )

    receive_result.wait_output("start packet forwarding", timeout=10)
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

    rx_threshold = receiver.testpmd.vf_helper.get_threshold_testpmd()
    tx_threshold = sender.testpmd.vf_helper.get_threshold_testpmd()
    hw_name = sender.testpmd.vf_helper.get_hw_name()
    # differences in NIC type throughput can lead to different snd/rcv counts
    assert_that(rcv_rx_pps).described_as(
        f"Throughput for RECEIVE on {hw_name} was below the expected threshold: {rx_threshold}"
    ).is_greater_than_or_equal_to(rx_threshold)
    assert_that(snd_tx_pps).described_as(
        f"Throughput for SEND on {hw_name} was below the expected threshold: {tx_threshold}"
    ).is_greater_than(tx_threshold)

    return sender, receiver


def verify_dpdk_send_receive_multi_txrx_queue(
    environment: Environment,
    log: Logger,
    variables: Dict[str, Any],
    pmd: str,
    use_service_cores: int = 1,
    build_release: bool = False,
    gb_hugepages: bool = False,
) -> Tuple[DpdkTestResources, DpdkTestResources]:
    # get test duration variable if set
    # enables long-running tests to shakeQoS and SLB issue
    return verify_dpdk_send_receive(
        environment,
        log,
        variables,
        pmd,
        use_service_cores=1,
        multiple_queues=True,
        build_release=build_release,
        gibibyte_hugepages=gb_hugepages,
    )


def do_parallel_cleanup(environment: Environment) -> None:
    def _parallel_cleanup(node: Node) -> None:
        node.reboot()
        interface = node.features[NetworkInterface]
        if not interface.is_enabled_sriov():
            interface.switch_sriov(enable=True, wait=False, reset_connections=True)
            # cleanup temporary hugepage and driver changes

    run_in_parallel(
        [partial(_parallel_cleanup, node) for node in environment.nodes.list()]
    )


# ipv4 network longest prefix match helper. Assumes 24bit mask
def ipv4_to_lpm(addr: str) -> str:
    return ".".join(addr.split(".")[:3]) + ".0/24"


# enable ip forwarding for secondary and tertiary nics in this test.
# run in parallel to save a bit of time on this net io step.
def __enable_ip_forwarding(node: Node) -> None:
    fwd_subnets = [
        node.nics.get_nic_by_index(nic_index).ip_addr for nic_index in [1, 2]
    ]
    for subnet_ip in fwd_subnets:
        node.features[NetworkInterface].switch_ip_forwarding(
            enable=True, private_ip_addr=subnet_ip
        )


# function to map ipv4 addresses to valid ipv6 addresses
# NOTE: DPDK doesn't like shortened ipv6 addresses.
def ipv4_to_ipv6_lpm(addr: str) -> str:
    # format to 0 prefixed 2 char hex
    parts = ["{:02x}".format(int(part)) for part in addr.split(".")]
    assert_that(parts).described_as(
        "IP address conversion failed, length of split array was unexpected"
    ).is_length(4)
    return "0000:0000:0000:0000:0000:FFFF:" f"{parts[0]}{parts[1]}:{parts[2]}00/56"


# disconnect two subnets
# add a new gateway from subnets a -> b through an arbitrary ip address
def setup_kernel_route_tables(
    node: Node,
    src_nic: NicInfo,
    dst_nic: NicInfo,
    new_gateway_nic: NicInfo,
) -> None:
    ip_tool = node.tools[Ip]
    forbidden_subnet = ipv4_to_lpm(dst_nic.ip_addr)

    # remove any routes through those devices
    # ip_tool.remove_all_routes_for_device(src_nic.name)

    if not ip_tool.route_exists(prefix=forbidden_subnet, dev=src_nic.name):
        ip_tool.add_route_to(
            dest=forbidden_subnet,
            via=new_gateway_nic.ip_addr,
            dev=src_nic.name,
            # src=src_nic.ip_addr,
        )

    # finally, set unneeded interfaces to DOWN after setting routes up
    # ip_tool.down(src_nic.name)


# calculate amount of tx/rx queues to use for the l3fwd test
def get_l3fwd_queue_count(
    available_cores: int, force_single_queue: bool = False, is_mana: bool = False
) -> int:
    # select queue amount based on size, allow force single queue
    queue_count = 1
    if force_single_queue:
        return queue_count
    elif available_cores <= 8:
        queue_count = 2
    elif available_cores <= 16:
        queue_count = 4
    elif available_cores <= 32:
        queue_count = 8
    elif not is_mana:
        queue_count = 16
    else:
        queue_count = 32
    return queue_count


def _find_common_subnet_nic(
    first: Node, second: Node, nic: NicInfo
) -> Optional[NicInfo]:
    # given a nic on the first node,
    # get the nic on the second node which shares the same subnet
    first.log.info(
        f"Looking for nic matching {nic.name} on {nic.ip_addr} {nic.module_name}"
    )
    first.tools[Ip].get_info()
    first.tools[Ip].get_info(nic.name)
    subnet = ipv4_to_lpm(nic.ip_addr)
    for nic_info in second.nics.nics.values():
        if nic_info.lower and subnet == ipv4_to_lpm(nic_info.ip_addr):
            first.log.info(
                f"found matching nic {nic_info.name} {nic_info.ip_addr} {nic_info.module_name}"
            )
            return nic_info
    return None


def verify_dpdk_l3fwd_ntttcp_tcp(
    environment: Environment,
    log: Logger,
    variables: Dict[str, Any],
    pmd: str = "netvsc",
    enable_gibibyte_hugepages: bool = False,
    force_single_queue: bool = False,
    is_perf_test: bool = False,
) -> None:
    # This is currently the most complicated DPDK test. There is a lot that can
    # go wrong, so we restrict the test to netvsc and only a few distros.
    # Current usage is checking for regressions in the host, not validating all distros.
    #
    #  l3 forward is also _not_ intuitive, and Azure net routing doesn't help.
    #  Azure primarily considers IP and not ethernet addresses.
    #  It's weirdly normal to see ARP requests providing inaccurate MAC addresses.
    #  Why? Beyond me at this time. -mm
    #
    # SUMMARY:
    #  The test attempts to change this initial default LISA setup:
    #   snd_VM      fwd_VM      rcv_VM
    #   |s_nic1 <-> |f_nic1 <-> |r_nic1    10.0.0.0/24 (Subnet A)
    #   |snd_nic_a <-> |f_nic2 <-> |r_nic2    10.0.1.0/24 (Subnet B)
    #   |s_nic3 <-> |f_nic3 <-> |rcv_nic_b    10.0.2.0/24 (Subnet C)
    # To this:
    #    snd_VM      fwd_VM      rcv_VM
    #    |s_nic1 <-> |f_nic1 <-> |r_nic1    10.0.0.0/24 (Subnet A)
    #    |snd_nic_a <-> |f_nic2     |          10.0.1.0/24 (Subnet B/C)
    #                | ↕ DPDK as NVA forwarding (and filtering) traffic
    #                |f_nic3 <-> |rcv_nic_b   10.0.2.0/24 (Subnet B/C)
    #
    #  With the goal of guaranteeing that snv_VM cannot reach
    #  rcv_VM on Subnet B/C without traffic being forwarded through
    #  DPDK on  fwd_VM
    #
    # Our key objectives are:
    # 1. intercepting traffic from  snd_nic_a bound for rcv_nic_b,
    #      sending it to f_nic2 (az routing table)
    #
    # 2. forwarding from f_nic2 to f_nic3 to bridge subnet b/c (DPDK)
    #
    # 3. enjoy the thrill of victory, ship a cloud net applicance.

    l3fwd_app_name = "dpdk-l3fwd"
    send_side = 1
    receive_side = 2
    test_duration: int = variables.get("dpdk_test_duration", 120)

    # arbitrarily pick fwd/snd/recv nodes.
    forwarder, sender, receiver = environment.nodes.list()
    forwarder_distro = forwarder.os
    is_recent_ubuntu = (
        isinstance(forwarder_distro, Ubuntu)
        and forwarder_distro.information.version >= "22.4.0"
    )
    is_recent_rhel = (
        isinstance(forwarder_distro, Fedora)
        and forwarder_distro.information.version >= "8.9.0"
    )
    if not (is_recent_ubuntu or is_recent_rhel):
        raise SkippedException("l3fwd test not compatible, use Ubuntu >= 22.04")

    # uninstall DPDK if it exists, l3fwd requires a source build.
    if (
        isinstance(forwarder_distro, Ubuntu) or isinstance(forwarder_distro, Fedora)
    ) and forwarder_distro.package_exists("dpdk"):
        forwarder_distro.uninstall_packages("dpdk")

    # get core count, quick skip if size is too small.
    available_cores = forwarder.tools[Lscpu].get_core_count()
    if available_cores < 8:
        raise SkippedException("l3 forward test needs >= 8 cores.")

    # ping everything before start
    forwarder.log.info("Running first ping...")
    # _ping_all_nodes_in_environment(environment)

    test_result = environment.source_test_result
    if not test_result:
        log.warn(
            "LISA environment does not have a pointer to the test result object."
            "performance data reporting for this test will be broken!"
        )

    # we're about to fully ruin this environment, so mark these dirty before we start
    for node in [forwarder, sender, receiver]:
        node.mark_dirty()

    # enable ip forwarding on secondary and tertiary nics
    # run_in_parallel([partial(__enable_ip_forwarding, node) for node in [forwarder]])
    __enable_ip_forwarding(forwarder)

    # We use ntttcp for snd/rcv which will respect the kernel route table.
    # SO: remove the unused interfaces and routes which could skip the forwarder

    def _run_removal(node: Node, keep_index: int) -> None:
        return node.features[NetworkInterface].remove_extra_nics(keep_index=keep_index)

    _print_all_nics(forwarder, sender, receiver)

    run_in_parallel(
        [
            partial(_run_removal, node, keep_index)
            for node, keep_index in [(sender, send_side), (receiver, receive_side)]
        ]
    )
    sender.close()
    receiver.close()
    sender.nics.reload()
    receiver.nics.reload()

    _print_all_nics(forwarder, sender, receiver)

    fwd_send_nic = forwarder.nics.get_nic_by_index(send_side)
    fwd_receiver_nic = forwarder.nics.get_nic_by_index(receive_side)
    subnet_a_snd = _find_common_subnet_nic(forwarder, sender, fwd_send_nic)
    subnet_b_rcv = _find_common_subnet_nic(forwarder, receiver, fwd_receiver_nic)
    if subnet_a_snd == None or subnet_b_rcv == None:
        raise LisaException(
            "Could not find subnet pairs for all nics on the test nodes."
        )

    forwarder.log.info("Running second ping...")
    check_forwarder_is_reachable(
        (forwarder, fwd_send_nic, fwd_receiver_nic),
        (sender, subnet_a_snd),
        (receiver, subnet_b_rcv),
        test_phase="after removal",
    )

    # organize our nics by subnet.
    # NOTE: we're ignoring the primary interfaces on each VM since we need it
    #  to service the ssh connection.
    # Subnet A is actually the secondary NIC.
    #  Subnet B is actually the tertiary NIC.
    # For the test, don't sweat it. A is send side, B is receive side.

    subnet_a_nics = {sender: subnet_a_snd, forwarder: fwd_send_nic}
    subnet_b_nics = {receiver: subnet_b_rcv, forwarder: fwd_receiver_nic}
    forwarder.log.info(
        f"subnet_a: sender {str(subnet_a_snd)} forwarder {str(fwd_send_nic)}"
    )
    forwarder.log.info(
        f"subnet_a: sender {str(subnet_b_rcv)} forwarder {str(fwd_receiver_nic)}"
    )

    check_receiver_is_unreachable(
        sender, receiver, subnet_a_nics, subnet_b_nics, "after initial subnet setup"
    )

    # AZ ROUTING TABLES
    # The kernel routes are not sufficient, since Azure also manages
    # the VNETs for the VMS. Azure doesn't really care about ethernet
    # addresses and looks at IP, so we must set up an azure route table
    # and apply it to our VNETs to send traffic to the DPDK forwarder.
    # see:
    # https://learn.microsoft.com/en-us/azure/virtual-network/
    #  tutorial-create-route-table-portal#create-a-route
    sender.features[NetworkInterface].create_route_table(
        nic_name=subnet_a_nics[forwarder].name,
        route_name="fwd-rx",
        subnet_mask=ipv4_to_lpm(subnet_b_nics[receiver].ip_addr),
        em_first_hop=ipv4_to_lpm(subnet_a_nics[sender].ip_addr),
        next_hop_type="VirtualAppliance",
        dest_hop=subnet_b_nics[forwarder].ip_addr,
    )
    receiver.features[NetworkInterface].create_route_table(
        nic_name=subnet_b_nics[forwarder].name,
        route_name="fwd-tx",
        subnet_mask=ipv4_to_lpm(subnet_a_nics[sender].ip_addr),
        em_first_hop=ipv4_to_lpm(subnet_b_nics[receiver].ip_addr),
        next_hop_type="VirtualAppliance",
        dest_hop=subnet_a_nics[forwarder].ip_addr,
    )
    # again, verify receiver is unreachable without dpdk forwarding
    check_receiver_is_unreachable(
        sender, receiver, subnet_a_nics, subnet_b_nics, "after route table creation"
    )

    # ping_forwader(forwarder, sender, receiver, subnet_a_nics, subnet_b_nics)
    # Do actual DPDK initialization, compile l3fwd and apply setup to
    # the extra forwarding nic
    fwd_kit = initialize_node_resources(
        forwarder,
        log,
        variables,
        pmd,
        sample_apps=["l3fwd"],
        extra_nics=[subnet_b_nics[forwarder]],
    )
    # enable hugepages needed for dpdk EAL on forwarder
    init_hugepages(forwarder, enable_gibibyte_hugepages=enable_gibibyte_hugepages)

    # tell threshold helper that we're testing the forwarder
    fwd_kit.testpmd.vf_helper.set_forwader()

    # NOTE: we're cheating here and not dynamically picking the port IDs
    # Why? You can't do it with the sdk tools for netvsc without writing your own app.
    # SOMEONE is supposed to publish an example to MSDN but I haven't yet. -mcgov
    # if fwd_kit.testpmd.vf_helper.is_mana():

    # NOTE: ports for DPDK are available for each interface.
    # This gets a little weird because Azure offers upper/lower pairs
    # by default for AccelNet. A synthetic interface may appear as a
    # usable port, even though we don't want to bind to them normally.
    # There isn't a good example of how to pick a port for a given interface.
    # see note above. On MANA and MLX we unbind the test interfaces.
    # We leave a single AccelNet interface open for SSH between LISA
    # and the test VM. This results in 4 interfaces for l3fwd.
    # 0 : synthetic or VF for eth0
    # 1 : synthetic or VF for eth0
    # 2: VF for eth1  <- nics used for testing
    # 3: VF for eth2  <- nics used for testing
    # Q: How do we know those numbers are accurate?
    # A: We do not. It's called cheating, it doesn't work every time.

    dpdk_port_a = 2
    dpdk_port_b = 3

    # SETUP FORWADING RULES
    # Set up DPDK forwarding rules:
    # see https://doc.dpdk.org/guides/sample_app_ug/
    #               l3_forward.html#parse-rules-from-file
    # for additional context
    setup_kernel_route_tables(
        node=sender,
        src_nic=subnet_a_snd,
        dst_nic=subnet_b_rcv,
        new_gateway_nic=fwd_send_nic,
    )
    setup_kernel_route_tables(
        node=receiver,
        src_nic=subnet_b_rcv,
        dst_nic=subnet_a_snd,
        new_gateway_nic=fwd_receiver_nic,
    )

    # again, check receiver is unreachable before l3fwd starts!
    check_receiver_is_unreachable(
        sender,
        receiver,
        subnet_a_nics,
        subnet_b_nics,
        "after kernel route creation, before l3fwd.",
    )

    create_l3fwd_rules_files(
        forwarder,
        sender,
        receiver,
        subnet_a_nics,
        subnet_b_nics,
        dpdk_port_a,
        dpdk_port_b,
    )

    # get binary path and dpdk device include args
    l3fwd_check = forwarder.execute(
        "command -v /usr/local/bin/dpdk-l3fwd", sudo=True, shell=True
    )
    if l3fwd_check.exit_code == 0:
        server_app_path = l3fwd_check.stdout.strip()
    else:
        assert (
            fwd_kit.testpmd.dpdk_build_path != None
        ), "DPDK build was not found, dpdk l3fwd was not found."
        examples_path = fwd_kit.testpmd.dpdk_build_path.joinpath("examples")
        server_app_path = examples_path.joinpath(
            l3fwd_app_name
        )  # generate the dpdk include arguments to add to our commandline

    # another MANA special case, provide pci slot and multiple macs instead of seperate vdev args
    if fwd_kit.testpmd.vf_helper.is_mana():
        vdev_combined = ",".join(
            [
                subnet_a_nics[forwarder].pci_slot,
                f"mac={subnet_a_nics[forwarder].mac_addr}",
                f"mac={subnet_b_nics[forwarder].mac_addr}",
            ]
        )
        include_devices = [f'--vdev="{vdev_combined}"']

    else:
        include_devices = [
            fwd_kit.testpmd.generate_testpmd_include(
                subnet_a_nics[forwarder], dpdk_port_a, force_netvsc=True
            ),
            fwd_kit.testpmd.generate_testpmd_include(
                subnet_b_nics[forwarder], dpdk_port_b, force_netvsc=True
            ),
        ]
    # Generating port,queue,core mappings for forwarder
    # NOTE: For DPDK 'N queues' means N queues * N PORTS
    # Each port P has N queues (really queue pairs for tx/rx)
    # Queue N for Port A and Port B will be assigned to the same core.
    # l3fwd rquires us to explicitly map these as a set of tuples.
    # Create a set of tuples (PortID,QueueID,CoreID)
    # These are minimally error checked, you can accidentally assign
    # cores and queues to unused ports etc. and only get runtime spew.
    queue_count = get_l3fwd_queue_count(
        available_cores,
        force_single_queue=force_single_queue,
        is_mana=fwd_kit.testpmd.vf_helper.is_mana(),
    )
    # signal multiq run to vf helper to adjust pass/fail threshold
    if queue_count > 1:
        fwd_kit.testpmd.vf_helper.set_multiple_queue()
    config_tups = []
    included_cores = []
    last_core = 1
    # create the list of tuples for p,q,c
    # 2 ports, N queues, N cores for MANA
    # 2 ports, N queues, 2N cores for MLX
    for q in range(queue_count):
        config_tups.append((dpdk_port_a, q, last_core))

        if not fwd_kit.testpmd.vf_helper.is_mana():
            included_cores.append(str(last_core))
            last_core += 1
        config_tups.append((dpdk_port_b, q, last_core))
        # add the core ID to our list of cores to include
        included_cores.append(str(last_core))
        last_core += 1

    # pick promiscuous mode arg, note mana doesn't support promiscuous mode
    if fwd_kit.testpmd.vf_helper.is_mana():
        promiscuous = ""
    else:
        promiscuous = "-P"
    dpdk_port_mask = fwd_kit.testpmd.get_dpdk_portmask([dpdk_port_a, dpdk_port_b])
    # join all our options into strings for use in the commmand
    joined_configs = ",".join([f"({p},{q},{c})" for (p, q, c) in config_tups])
    joined_include = " ".join(include_devices)
    # prefer the '-l 1,2,3' arg version over '-l 1-4' form to avoid a dpdk bug
    joined_core_list = ",".join(included_cores)
    fwd_cmd = (
        f"{server_app_path} {joined_include} -l {joined_core_list}  -- "
        f" {promiscuous} -p {dpdk_port_mask} "
        f' --lookup=lpm --config="{joined_configs}" '
        "--rule_ipv4=rules_v4  --rule_ipv6=rules_v6 --mode=poll --parse-ptype"
    )

    # create sender/receiver ntttcp instances
    ntttcp = {sender: sender.tools[Ntttcp], receiver: receiver.tools[Ntttcp]}

    # START THE TEST
    # finally, start the forwarder
    fwd_proc = forwarder.execute_async(
        fwd_cmd,
        sudo=True,
        shell=True,
    )
    try:
        fwd_proc.wait_output("L3FWD: entering main loop", timeout=30)
    except LisaException:
        raise LisaException(
            "L3fwd did not start. Check command output for incorrect flags, "
            "core dumps, or other setup/init issues."
        )

    # after starting DPDK, check for known driver errors
    fwd_kit.testpmd.check_for_driver_regressions()

    # start ntttcp client and server
    ntttcp_threads_count = 64
    # start the receiver

    receiver.execute("lspci; ip addr; ip link; ip route;", shell=True, sudo=True)
    sender.execute("lspci; ip addr; ip link; ip route;", shell=True, sudo=True)
    ports_count = 64
    receiver_proc = ntttcp[receiver].run_as_server_async(
        subnet_b_nics[receiver].name,
        run_time_seconds=test_duration + 15,
        buffer_size=1024,
        ports_count=ports_count,
        server_ip=subnet_b_nics[receiver].ip_addr,
    )
    receiver_proc.wait_output(f"INFO: {ports_count+1} threads created")
    # start the sender

    try:
        sender_result = ntttcp[sender].run_as_client(
            nic_name=subnet_a_nics[sender].name,
            server_ip=subnet_b_nics[receiver].ip_addr,
            threads_count=ntttcp_threads_count,
            run_time_seconds=test_duration,
        )
    except AssertionError:
        sender.log.warn("Retrying start  for sender...")
        sender_result = ntttcp[sender].run_as_client(
            nic_name=subnet_a_nics[sender].name,
            server_ip=subnet_b_nics[receiver].ip_addr,
            threads_count=ntttcp_threads_count,
            run_time_seconds=test_duration,
        )
    # collect, log, and process results
    receiver_result = ntttcp[receiver].wait_server_result(receiver_proc)
    log.debug(f"result: {receiver_result.stdout}")
    log.debug(f"result: {sender_result.stdout}")
    # kill l3fwd on forwarder
    forwarder.tools[Kill].by_name(l3fwd_app_name, signum=SIGINT, ignore_not_exist=True)
    forwarder.log.debug(f"Forwarder VM was: {forwarder.name}")
    forwarder.log.debug(f"Ran l3fwd cmd: {fwd_cmd}")
    ntttcp_results = {
        receiver: ntttcp[receiver].create_ntttcp_result(receiver_result),
        sender: ntttcp[sender].create_ntttcp_result(sender_result, "client"),
    }

    # check for driver regressions again after running the test
    fwd_kit.testpmd.check_for_driver_regressions()

    # send result to notifier if we found a test result to report with
    if test_result and is_perf_test:
        msg = ntttcp[sender].create_ntttcp_tcp_performance_message(
            server_result=ntttcp_results[receiver],
            client_result=ntttcp_results[sender],
            latency=Decimal(0),
            connections_num="64",
            buffer_size=64,
            test_case_name="verify_dpdk_l3fwd_ntttcp_tcp",
            test_result=test_result,
        )
        notifier.notify(msg)

    check_receiver_is_unreachable(
        sender, receiver, subnet_a_nics, subnet_b_nics, "after l3fwd stops"
    )
    # check the throughput and fail if it was unexpectedly low.
    # NOTE: only checking 0 and < 1 now. Once we have more data
    # there should be more stringest checks for each NIC type.
    throughput = ntttcp_results[receiver].throughput_in_gbps
    assert_that(throughput).described_as(
        "l3fwd test found 0Gbps througput. "
        "Either the test or DPDK forwarding is broken."
    ).is_greater_than(0)

    assert_that(throughput).described_as(
        f"l3fwd has very low throughput: {throughput}Gbps! "
        "Verify netvsc was used over failsafe, check netvsc init was succesful "
        "and the DPDK port IDs were correct."
    ).is_greater_than_or_equal_to(1)

    threshold = fwd_kit.testpmd.vf_helper.get_threshold_l3fwd()
    hw_name = fwd_kit.testpmd.vf_helper.get_hw_name()
    if fwd_kit.testpmd.vf_helper.use_strict_checks:
        assert_that(throughput).described_as(
            f"l3fwd strict throughput check failed, for hw {hw_name} "
            f"expected throughput >= {threshold} GBps!"
        ).is_greater_than_or_equal_to(threshold)


def check_forwarder_is_reachable(
    forwarder_info: Tuple[Node, NicInfo, NicInfo],
    sender_info: Tuple[Node, NicInfo],
    receiver_info: Tuple[Node, NicInfo],
    test_phase: str = "",
) -> None:
    forwarder, fwd_send_nic, fwd_receiver_nic = forwarder_info
    sender, subnet_a_snd = sender_info
    receiver, subnet_b_rcv = receiver_info
    forwarder.log.info(f"Running ping test {test_phase}...")
    forwarder.tools[Ping].ping(subnet_a_snd.ip_addr, fwd_send_nic.name)
    forwarder.tools[Ping].ping(subnet_b_rcv.ip_addr, fwd_receiver_nic.name)
    sender.tools[Ping].ping(fwd_send_nic.ip_addr, subnet_a_snd.name)
    receiver.tools[Ping].ping(fwd_receiver_nic.ip_addr, subnet_b_rcv.name)


def _print_all_nics(forwarder: Node, sender: Node, receiver: Node):
    for nic in sender.nics.nics.values():
        sender.log.info(f"Sender has nic: {str(nic)}")
    for nic in receiver.nics.nics.values():
        receiver.log.info(f"Receiver has nic: {str(nic)}")
    for nic in forwarder.nics.nics.values():
        forwarder.log.info(f"Forwader has nic: {str(nic)}")


def check_receiver_is_unreachable(
    sender: Node,
    receiver: Node,
    subnet_a_nics: Dict[Node, NicInfo],
    subnet_b_nics: Dict[Node, NicInfo],
    test_phase: str,
):
    if sender.tools[Ping].ping(
        subnet_b_nics[receiver].ip_addr,
        nic_name=subnet_a_nics[sender].name,
        ignore_error=True,
    ):
        raise LisaException(
            f"Sender and receiver can communicate {test_phase}! "
            f"{subnet_a_nics[sender].ip_addr} and {subnet_b_nics[receiver].ip_addr} "
            "must be on seperate, unreachable subnets!"
        )

    else:
        sender.log.debug(
            f"Confirmed sender/receiver cannot reach each other {test_phase}. "
        )


def ping_forwarder(
    ping_target: Node,
    ping_sources: List[Node],
    shared_subnets: List[Dict[Node, NicInfo]],
    test_phase: str = "",
) -> None:
    for source, subnet in zip(ping_sources, shared_subnets):
        source.log.debug(
            f"PING {test_phase}: {ping_target.name}:{subnet[ping_target].ip_addr} "
            f"< {source.name}:{subnet[source].name}"
            f":{subnet[source].ip_addr} "
        )
        source.tools[Ping].ping(subnet[ping_target].ip_addr, subnet[source].name)


def create_l3fwd_rules_files(
    forwarder: Node,
    sender: Node,
    receiver: Node,
    subnet_a_nics: Dict[Node, NicInfo],
    subnet_b_nics: Dict[Node, NicInfo],
    dpdk_port_a: int,
    dpdk_port_b: int,
) -> None:
    sample_rules_v4 = []
    sample_rules_v6 = []

    # we are routing  VM_A -> VM_B -> VM_C
    # by forwarding:
    # VM_A_NIC_A -> VM_B_NIC_A
    #                 ↕
    #               VM_B_NIC_B -> VM_C_NIC_B
    # with DPDK forwarding traffic between NIC_A and NIC_B
    #
    # l3fwd requires us to declare these routing rules in some route files.
    # There are a few options, I picked longest prefix matching since it's
    # very simple. The rule file declares:
    # "any traffic destined for this subnet, send it out on this port"

    # create our longest-prefix-match aka 'lpm' rules
    sample_rules_v4 += [
        f"R {ipv4_to_lpm(subnet_b_nics[receiver].ip_addr)} {dpdk_port_b}",
        f"R {ipv4_to_lpm(subnet_a_nics[sender].ip_addr)} {dpdk_port_a}",
    ]

    # Need to map ipv4 to ipv6 addresses, unused but the rules must be
    # provided. A valid ipv6 address needs to be in the ipv6 rules, but
    # ipv6 is not enabled in azure.
    sample_rules_v6 += [
        f"R {ipv4_to_ipv6_lpm(subnet_b_nics[receiver].ip_addr)} {dpdk_port_b}",
        f"R {ipv4_to_ipv6_lpm(subnet_a_nics[sender].ip_addr)} {dpdk_port_a}",
    ]

    # write them out to the rules files on the forwarder
    rules_v4, rules_v6 = [
        forwarder.get_pure_path(path) for path in ["rules_v4", "rules_v6"]
    ]
    forwarder.tools[Echo].write_to_file(
        "\n".join(sample_rules_v4), rules_v4, append=True
    )
    forwarder.tools[Echo].write_to_file(
        "\n".join(sample_rules_v6), rules_v6, append=True
    )
