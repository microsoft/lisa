# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from decimal import Decimal
from functools import partial
from typing import Any, Dict, List, Tuple

from assertpy import assert_that, fail

from lisa import (
    Environment,
    Logger,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    UnsupportedDistroException,
    notifier,
    schema,
    search_space,
)
from lisa.features import Infiniband, IsolatedResource, NetworkInterface, Sriov
from lisa.operating_system import BSD, CBLMariner, Windows
from lisa.testsuite import simple_requirement
from lisa.tools import Echo, Git, Ip, Kill, Lsmod, Make, Modprobe, Ntttcp
from lisa.util.constants import SIGINT
from lisa.util.parallel import run_in_parallel
from microsoft.testsuites.dpdk.common import DPDK_STABLE_GIT_REPO
from microsoft.testsuites.dpdk.dpdknffgo import DpdkNffGo
from microsoft.testsuites.dpdk.dpdkovs import DpdkOvs
from microsoft.testsuites.dpdk.dpdkutil import (
    UIO_HV_GENERIC_SYSFS_PATH,
    UnsupportedPackageVersionException,
    _ping_all_nodes_in_environment,
    check_send_receive_compatibility,
    do_pmd_driver_setup,
    enable_uio_hv_generic_for_nic,
    generate_send_receive_run_info,
    init_hugepages,
    init_nodes_concurrent,
    initialize_node_resources,
    run_testpmd_concurrent,
    verify_dpdk_build,
    verify_dpdk_send_receive,
    verify_dpdk_send_receive_multi_txrx_queue,
)
from microsoft.testsuites.dpdk.dpdkvpp import DpdkVpp

VDEV_TYPE = "net_vdev_netvsc"
MAX_RING_PING_LIMIT_NS = 200000
DPDK_VF_REMOVAL_MAX_TEST_TIME = 60 * 10


@TestSuiteMetadata(
    area="dpdk",
    category="functional",
    description="""
    This test suite check DPDK functionality
    """,
)
class Dpdk(TestSuite):
    # regex for parsing ring ping output for the final line,
    # grabbing the max latency of 99.999% of data in nanoseconds.
    # ex: percentile 99.999 = 12302
    _ring_ping_percentile_regex = re.compile(r"percentile 99.990 = ([0-9]+)")

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node: Node = kwargs["node"]
        if isinstance(node.os, BSD) or isinstance(node.os, Windows):
            raise SkippedException(f"{node.os} is not supported.")

    @TestCaseMetadata(
        description="""
            netvsc direct pmd version.
            This test case checks DPDK can be built and installed correctly.
            Prerequisites, accelerated networking must be enabled.
            The VM should have at least two network interfaces,
             with one interface for management.
            More details refer https://docs.microsoft.com/en-us/azure/virtual-network/setup-dpdk#prerequisites # noqa: E501
        """,
        priority=2,
        requirement=simple_requirement(
            min_core_count=8,
            min_nic_count=2,
            network_interface=Sriov(),
        ),
    )
    def verify_dpdk_build_netvsc(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        verify_dpdk_build(node, log, variables, "netvsc")

    @TestCaseMetadata(
        description="""
            failsafe (azure default, recommended) version.
            This test case checks DPDK can be built and installed correctly.
            Prerequisites, accelerated networking must be enabled.
            The VM should have at least two network interfaces,
            with one interface for management.
            More details: https://docs.microsoft.com/en-us/azure/virtual-network/setup-dpdk#prerequisites # noqa: E501
        """,
        priority=2,
        requirement=simple_requirement(
            min_core_count=8,
            min_nic_count=2,
            network_interface=Sriov(),
        ),
    )
    def verify_dpdk_build_failsafe(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        verify_dpdk_build(node, log, variables, "failsafe")

    @TestCaseMetadata(
        description="""
           Install and run OVS+DPDK functional tests
        """,
        priority=4,
        requirement=simple_requirement(
            min_core_count=8,
            min_nic_count=2,
            network_interface=Sriov(),
            supported_features=[IsolatedResource],
            disk=schema.DiskOptionSettings(
                data_disk_count=search_space.IntRange(min=1),
                data_disk_size=search_space.IntRange(min=32),
            ),
        ),
    )
    def verify_dpdk_ovs(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        # initialize DPDK first, OVS requires it built from source before configuring.
        self._force_dpdk_default_source(variables)
        test_kit = initialize_node_resources(node, log, variables, "failsafe")

        # checkout OpenVirtualSwitch
        ovs = node.tools[DpdkOvs]

        # provide ovs build with DPDK tool info and build
        ovs.build_with_dpdk(test_kit.testpmd)

        # enable hugepages needed for dpdk EAL
        init_hugepages(node)

        try:
            # run OVS tests, providing OVS with the NIC info needed for DPDK init
            ovs.setup_ovs(node.nics.get_secondary_nic().pci_slot)

            # validate if OVS was able to initialize DPDK
            node.execute(
                "ovs-vsctl get Open_vSwitch . dpdk_initialized",
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message=(
                    "OVS repoted that DPDK EAL failed to initialize."
                ),
            )
        finally:
            ovs.stop_ovs()

    @TestCaseMetadata(
        description="""
           Install and run ci test for NFF-Go on ubuntu
        """,
        priority=4,
        requirement=simple_requirement(
            min_core_count=8,
            min_nic_count=2,
            network_interface=Sriov(),
            supported_features=[IsolatedResource],
        ),
    )
    def verify_dpdk_nff_go(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        try:
            nff_go = node.tools[DpdkNffGo]
        except UnsupportedDistroException as err:
            raise SkippedException(err)

        # hugepages needed for dpdk tests
        init_hugepages(node)
        # run the nff-go tests
        nff_go.run_test()

    @TestCaseMetadata(
        description="""
           Build and run DPDK multiprocess client/server sample application.
           Requires 3 nics since client/server needs two ports + 1 nic for LISA
        """,
        priority=4,
        requirement=simple_requirement(
            min_nic_count=3,
            network_interface=Sriov(),
            supported_features=[IsolatedResource],
        ),
    )
    def verify_dpdk_multiprocess(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        # multiprocess test requires dpdk source.
        self._force_dpdk_default_source(variables)
        kill = node.tools[Kill]
        pmd = "failsafe"
        server_app_name = "dpdk-mp_server"
        client_app_name = "dpdk-mp_client"
        # initialize DPDK with sample applications selected for build
        test_kit = initialize_node_resources(
            node,
            log,
            variables,
            pmd,
            sample_apps=[
                "multi_process/client_server_mp/mp_server",
                "multi_process/client_server_mp/mp_client",
            ],
        )

        if test_kit.testpmd.is_connect_x3:
            raise SkippedException(
                "Unsupported Hardware: ConnectX3 does not support secondary process RX"
            )

        # enable hugepages needed for dpdk EAL
        init_hugepages(node)

        # setup and run mp_server application
        examples_path = test_kit.testpmd.dpdk_build_path.joinpath("examples")
        server_app_path = examples_path.joinpath(server_app_name)
        client_app_path = examples_path.joinpath(client_app_name)

        # EAL -l: start server on cores 1-2,
        # EAL -n: use 4 memory channels
        # APP: -p : set port bitmask to port 0 and 1
        # APP: -n : allow one client to connect
        server_proc = node.execute_async(
            (
                f"{server_app_path} -l 1-2 -n 4 "
                f"-b {node.nics.get_primary_nic().pci_slot} -- -p 3 -n 1"
            ),
            sudo=True,
            shell=True,
        )

        # Wait for server to finish init
        server_proc.wait_output("APP: Finished Process Init.", timeout=5)

        # EAL -l: start client on core 3,
        # EAL --proc-type: client runs as secondary process.
        # APP: -n : client index is 0
        client_result = node.execute(
            (
                f"timeout -s INT 2 {client_app_path} --proc-type=secondary -l 3 -n 4"
                f" -b {node.nics.get_primary_nic().pci_slot} -- -n 0"
            ),
            sudo=True,
            shell=True,
        )

        # client blocks and returns, kill server once client is finished.
        kill.by_name(str(server_app_name), signum=SIGINT)
        server_result = server_proc.wait_result()

        # perform the checks from v2
        assert_that(client_result.stdout).described_as(
            "Secondary process did not finish initialization"
        ).contains("APP: Finished Process Init")

        assert_that(client_result.stdout).described_as(
            "Secondary process did not start accepting packets from server"
        ).contains("Client process 0 handling packets")

        # mp_client returns a nonstandard positive number when killed w signal.
        # one would expect either 0 or 130 (killed by signal w sigint).
        # check that the nonsense number is at least the expected one.
        assert_that(client_result.exit_code).described_as(
            "dpdk-mp client exit code was unexpected"
        ).is_equal_to(124)
        assert_that(server_result.exit_code).is_equal_to(0)

    @TestCaseMetadata(
        description="""
            test sriov failsafe during vf revoke (receive side)
        """,
        priority=2,
        requirement=simple_requirement(
            min_core_count=8,
            min_nic_count=2,
            network_interface=Sriov(),
            min_count=2,
            supported_features=[IsolatedResource],
        ),
    )
    def verify_dpdk_sriov_rescind_failover_receiver(
        self, environment: Environment, log: Logger, variables: Dict[str, Any]
    ) -> None:
        test_kits = init_nodes_concurrent(environment, log, variables, "failsafe")

        try:
            check_send_receive_compatibility(test_kits)
        except UnsupportedPackageVersionException as err:
            raise SkippedException(err)

        sender, receiver = test_kits

        # Want to only switch receiver sriov to avoid timing weirdness
        receiver.switch_sriov = True
        sender.switch_sriov = False

        kit_cmd_pairs = generate_send_receive_run_info("failsafe", sender, receiver)

        run_testpmd_concurrent(
            kit_cmd_pairs, DPDK_VF_REMOVAL_MAX_TEST_TIME, log, rescind_sriov=True
        )

        rescind_tx_pps_set = receiver.testpmd.get_mean_rx_pps_sriov_rescind()
        self._check_rx_or_tx_pps_sriov_rescind("RX", rescind_tx_pps_set)

    @TestCaseMetadata(
        description="""
            test sriov failsafe during vf revoke (send only version)
        """,
        priority=2,
        requirement=simple_requirement(
            min_core_count=8,
            min_nic_count=2,
            network_interface=Sriov(),
            supported_features=[IsolatedResource],
        ),
    )
    def verify_dpdk_sriov_rescind_failover_send_only(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        test_kit = initialize_node_resources(node, log, variables, "failsafe")
        testpmd = test_kit.testpmd
        test_nic = node.nics.get_secondary_nic()
        testpmd_cmd = testpmd.generate_testpmd_command(test_nic, 0, "txonly")
        kit_cmd_pairs = {
            test_kit: testpmd_cmd,
        }

        run_testpmd_concurrent(
            kit_cmd_pairs, DPDK_VF_REMOVAL_MAX_TEST_TIME, log, rescind_sriov=True
        )

        rescind_tx_pps_set = testpmd.get_mean_tx_pps_sriov_rescind()
        self._check_rx_or_tx_pps_sriov_rescind("TX", rescind_tx_pps_set)

    def _check_rx_or_tx_pps_sriov_rescind(
        self, tx_or_rx: str, pps: Tuple[int, int, int]
    ) -> None:
        before_rescind, during_rescind, after_reenable = pps
        self._check_rx_or_tx_pps(tx_or_rx, before_rescind, sriov_enabled=True)
        self._check_rx_or_tx_pps(tx_or_rx, during_rescind, sriov_enabled=False)
        self._check_rx_or_tx_pps(tx_or_rx, after_reenable, sriov_enabled=True)

    def _check_rx_or_tx_pps(
        self, tx_or_rx: str, pps: int, sriov_enabled: bool = True
    ) -> None:
        if sriov_enabled:
            assert_that(pps).described_as(
                f"{tx_or_rx}-PPS ({pps}) should have been greater "
                "than 2^20 (~1m) PPS before sriov disable."
            ).is_greater_than(2**20)
        else:
            assert_that(pps).described_as(
                f"{tx_or_rx}-PPS ({pps}) should have been less "
                "than 2^20 (~1m) PPS after sriov disable."
            ).is_less_than(2**20)

    @TestCaseMetadata(
        description="""
            verify vpp is able to detect azure network interfaces
            1. run fd.io vpp install scripts
            2. install vpp from their repositories
            3. start vpp service
            4. check that azure interfaces are detected by vpp
        """,
        priority=4,
        requirement=simple_requirement(
            min_core_count=8,
            min_nic_count=2,
            network_interface=Sriov(),
        ),
    )
    def verify_dpdk_vpp(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        if isinstance(node.os, CBLMariner):
            raise SkippedException(
                UnsupportedDistroException(
                    node.os, "VPP test does not support Mariner installation."
                )
            )
        initialize_node_resources(node, log, variables, "failsafe")

        vpp = node.tools[DpdkVpp]
        vpp.install()

        net = node.nics
        nics_dict = {key: value for key, value in net.nics.items() if key != "eth0"}
        pci_slots = []
        # set devices to down and restart vpp service
        ip = node.tools[Ip]
        start_up_conf = vpp.get_start_up_file_content()
        for key, value in nics_dict.items():
            ip.down(key)
            if value.pci_slot not in start_up_conf:
                pci_slots.append(f"dev {value.pci_slot}")
        replace_str = "\n".join(pci_slots)
        vpp.set_start_up_file(replace_str)

        vpp.start()
        vpp.run_test()

    @TestCaseMetadata(
        description="""
            This test runs the dpdk ring ping utility from:
            https://github.com/shemminger/dpdk-ring-ping
            to measure the maximum latency for 99.999 percent of packets during
            the test run. The maximum should be under 200000 nanoseconds
            (.2 milliseconds).
            Not dependent on any specific PMD.
        """,
        priority=4,
        requirement=simple_requirement(
            min_core_count=8,
            min_nic_count=2,
            network_interface=Sriov(),
            supported_features=[IsolatedResource],
        ),
    )
    def verify_dpdk_ring_ping(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        # ring ping requires dpdk source to run, since default is package_manager
        # we special case here to use to dpdk-stable as the default.
        self._force_dpdk_default_source(variables)
        # setup and unwrap the resources for this test
        test_kit = initialize_node_resources(node, log, variables, "failsafe")
        testpmd = test_kit.testpmd

        # grab a nic and run testpmd
        git = node.tools[Git]
        make = node.tools[Make]
        echo = node.tools[Echo]
        rping_build_env_vars = [
            "export RTE_TARGET=build",
            f"export RTE_SDK={str(testpmd.dpdk_path)}",
        ]
        echo.write_to_file(
            ";".join(rping_build_env_vars), node.get_pure_path("~/.bashrc"), append=True
        )
        git_path = git.clone(
            "https://github.com/shemminger/dpdk-ring-ping.git", cwd=node.working_path
        )
        make.run(
            shell=True,
            cwd=git_path,
            expected_exit_code=0,
            expected_exit_code_failure_message="make could not build rping project.",
        ).assert_exit_code()
        # run ringping for 30 seconds
        runcmd = "./build/rping -c 0x03 -n 2 --no-pci --no-huge -- -d 5 -t 10"
        result = node.execute(
            runcmd,
            shell=True,
            cwd=git_path,
            expected_exit_code=0,
            expected_exit_code_failure_message="rping program failed to run correctly.",
        )
        result.assert_exit_code()
        # get the max latency for 99.999 percent of enqueued 'packets'.
        result_regex = self._ring_ping_percentile_regex.search(result.stdout)
        if result_regex and len(result_regex.groups()) == 1:
            max_ping_measured = int(result_regex.group(1))
            assert_that(max_ping_measured).described_as(
                (
                    f"RingPing measured {max_ping_measured} as maximum ping latency,"
                    f" maximum should be less than {MAX_RING_PING_LIMIT_NS}"
                )
            ).is_less_than(MAX_RING_PING_LIMIT_NS)
        else:
            fail(
                (
                    "Could not get latency data from rping result. "
                    f"Search was for 'percentile 99.999 = ([0-9]+)'\n{result.stdout}\n"
                )
            )

    @TestCaseMetadata(
        description="""
            Tests a basic sender/receiver setup for default failsafe driver setup.
            Sender sends the packets, receiver receives them.
            We check both to make sure the received traffic is within the
            expected order-of-magnitude.
        """,
        priority=2,
        requirement=simple_requirement(
            min_core_count=8,
            min_nic_count=2,
            network_interface=Sriov(),
            min_count=2,
        ),
    )
    def verify_dpdk_send_receive_multi_txrx_queue_failsafe(
        self, environment: Environment, log: Logger, variables: Dict[str, Any]
    ) -> None:
        try:
            verify_dpdk_send_receive_multi_txrx_queue(
                environment, log, variables, "failsafe"
            )
        except UnsupportedPackageVersionException as err:
            raise SkippedException(err)

    @TestCaseMetadata(
        description="""
            Tests a basic sender/receiver setup for default failsafe driver setup.
            Sender sends the packets, receiver receives them.
            We check both to make sure the received traffic is within the expected
            order-of-magnitude.
        """,
        priority=2,
        requirement=simple_requirement(
            min_core_count=8,
            min_nic_count=2,
            network_interface=Sriov(),
            min_count=2,
        ),
    )
    def verify_dpdk_send_receive_multi_txrx_queue_netvsc(
        self, environment: Environment, log: Logger, variables: Dict[str, Any]
    ) -> None:
        try:
            verify_dpdk_send_receive_multi_txrx_queue(
                environment, log, variables, "netvsc"
            )
        except UnsupportedPackageVersionException as err:
            raise SkippedException(err)

    @TestCaseMetadata(
        description="""
            Tests a basic sender/receiver setup for default failsafe driver setup.
            Sender sends the packets, receiver receives them.
            We check both to make sure the received traffic is within the expected
            order-of-magnitude.
        """,
        priority=2,
        requirement=simple_requirement(
            min_core_count=8,
            min_nic_count=2,
            network_interface=Sriov(),
            min_count=2,
        ),
    )
    def verify_dpdk_send_receive_failsafe(
        self, environment: Environment, log: Logger, variables: Dict[str, Any]
    ) -> None:
        try:
            verify_dpdk_send_receive(environment, log, variables, "failsafe")
        except UnsupportedPackageVersionException as err:
            raise SkippedException(err)

    @TestCaseMetadata(
        description="""
            Tests a basic sender/receiver setup for direct netvsc pmd setup.
            Sender sends the packets, receiver receives them.
            We check both to make sure the received traffic is within the expected
            order-of-magnitude.
        """,
        priority=2,
        requirement=simple_requirement(
            min_core_count=8,
            min_nic_count=2,
            network_interface=Sriov(),
            min_count=2,
        ),
    )
    def verify_dpdk_send_receive_netvsc(
        self, environment: Environment, log: Logger, variables: Dict[str, Any]
    ) -> None:
        try:
            verify_dpdk_send_receive(environment, log, variables, "netvsc")
        except UnsupportedPackageVersionException as err:
            raise SkippedException(err)

    @TestCaseMetadata(
        description="""
          Run the L3 forwarding test for DPDK
        """,
        priority=4,
        requirement=simple_requirement(
            min_core_count=8,
            min_count=3,
            min_nic_count=3,
            network_interface=Sriov(),
        ),
    )
    def verify_dpdk_l3_forward(
        self, environment: Environment, log: Logger, variables: Dict[str, Any]
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
        #   |s_nic2 <-> |f_nic2 <-> |r_nic2    10.0.1.0/24 (Subnet B)
        #   |s_nic3 <-> |f_nic3 <-> |r_nic3    10.0.2.0/24 (Subnet C)
        # To this:
        #    snd_VM      fwd_VM      rcv_VM
        #    |s_nic1 <-> |f_nic1 <-> |r_nic1    10.0.0.0/24 (Subnet A)
        #    |s_nic2 <-> |f_nic2     |          10.0.1.0/24 (Subnet B/C)
        #                | ↕ DPDK as NVA forwarding (and filtering) traffic
        #                |f_nic3 <-> |r_nic3   10.0.2.0/24 (Subnet B/C)
        #
        #  With the goal of guaranteeing that snv_VM cannot reach
        #  rcv_VM on Subnet B/C without traffic being forwarded through
        #  DPDK on  fwd_VM
        #
        # Our key objectives are:
        # 1. intercepting traffic from  s_nic2 bound for r_nic3,
        #      sending it to f_nic2 (az routing table)
        #
        # 2. forwarding from f_nic2 to f_nic3 to bridge subnet b/c (DPDK)
        #
        # 3. enjoy the thrill of victory, ship a cloud net applicance.

        # constants
        pmd = "netvsc"
        server_app_name = "dpdk-l3fwd"
        # l3_port = 0xD007
        dpdk_port_snd_side = 2
        dpdk_port_rcv_side = 3
        # ip_protocol = 0x6  # TCP

        self._force_dpdk_default_source(variables)
        _ping_all_nodes_in_environment(environment)
        test_result = environment.source_test_result
        if not test_result:
            log.warn(
                "LISA environment does not have a pointer to the test result object."
                "performance data reporting for this test will be broken!"
            )

        # ipv4 network prefix helper. Assumes 24bit mask
        def ipv4_lpm(addr: str) -> str:
            return ".".join(addr.split(".")[:3]) + ".0/24"

        # enable ip forwarding for secondary and tertiary nics in this test.
        # run in parallel to save a bit of time on this net io step.
        def __enable_ip_forwarding(node: Node) -> None:
            fwd_nic_private_ip = node.nics.get_secondary_nic().ip_addr
            node.features[NetworkInterface].switch_ip_forwarding(  # type: ignore
                enable=True, private_ip_addr=fwd_nic_private_ip
            )
            rcv_nic_private_ip = node.nics.get_tertiary_nic().ip_addr
            node.features[NetworkInterface].switch_ip_forwarding(  # type: ignore
                enable=True, private_ip_addr=rcv_nic_private_ip
            )

        run_in_parallel(
            [partial(__enable_ip_forwarding, node) for node in environment.nodes.list()]
        )

        # arbitrarily pick fwd/snd/recv nodes.
        forwarder, sender, receiver = environment.nodes.list()

        # get some basic node info

        # forwarder nics
        f_nic2 = forwarder.nics.get_secondary_nic()
        f_nic2_ip = f_nic2.ip_addr

        f_nic3 = forwarder.nics.get_tertiary_nic()
        f_nic3_ip = f_nic3.ip_addr

        # sender nic
        s_nic2 = sender.nics.get_secondary_nic()
        s_nic2_ip = s_nic2.ip_addr

        # receiver nic
        r_nic3 = receiver.nics.get_tertiary_nic()
        r_nic3_ip = r_nic3.ip_addr

        # We use ntttcp for snd/rcv which will respect kernel routes!
        # So: set these extra interfaces to DOWN
        _s_nic3 = sender.nics.get_tertiary_nic()
        _r_nic2 = receiver.nics.get_secondary_nic()
        sender.tools[Ip].down(_s_nic3.name)
        receiver.tools[Ip].down(_r_nic2.name)

        # AND: create kernel routing rules so traffic for subnet B/C gets routed through
        #      the FWDer no matter which subnet it originates from.

        # clear current route to subnet C on sender
        sender.execute(
            f"ip route del {ipv4_lpm(r_nic3_ip)}",
            sudo=True,
            shell=True,
        )
        # clear current route to subnet B on receiver
        receiver.execute(
            f"ip route del {ipv4_lpm(s_nic2_ip)}",
            sudo=True,
            shell=True,
        )
        # add routes to subnet B/C through forwarder on sender/receiver
        sender.execute(
            f"ip route add {ipv4_lpm(r_nic3_ip)} via {f_nic2.ip_addr} dev {s_nic2.name} ",
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Could not add route to sender",
        )
        receiver.execute(
            f"ip route add {ipv4_lpm(s_nic2_ip)} via {f_nic3.ip_addr} dev {r_nic3.name} ",
            sudo=True,
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="Could not add route to receiver",
        )

        ## AZ ROUTING TABLES
        #  The kernel routes are not sufficient, since Azure also manages the VNETs for the VMS.
        #  We must set up an azure route table and apply it to our VNETs to send traffic to the
        #  DPDK forwarder.

        # special constant, implies 'route all traffic'
        AZ_ROUTE_ALL_TRAFFIC = "0.0.0.0/0"

        # create our forwarding rules, all traffic on sender and receiver nic
        # subnets goes to the forwarder, our virtual appliance VM.
        sender.features[NetworkInterface].create_route_table(  # type: ignore
            nic_name=f_nic2.name,
            route_name="fwd-rx",
            subnet_mask=ipv4_lpm(s_nic2_ip),
            em_first_hop=AZ_ROUTE_ALL_TRAFFIC,
            next_hop_type="VirtualAppliance",
            dest_hop=f_nic2_ip,
        )
        receiver.features[NetworkInterface].create_route_table(  # type: ignore
            nic_name=f_nic3.name,
            route_name="fwd-tx",
            subnet_mask=ipv4_lpm(r_nic3_ip),
            em_first_hop=AZ_ROUTE_ALL_TRAFFIC,
            next_hop_type="VirtualAppliance",
            dest_hop=f_nic3_ip,
        )

        # Do actual DPDK initialization, compile l3fwd and apply setup to
        # the extra forwarding nic
        fwd_kit = initialize_node_resources(
            forwarder,
            log,
            variables,
            pmd,
            sample_apps=["l3fwd"],
            extra_nics=[f_nic3],
        )
        # enable hugepages needed for dpdk EAL
        init_hugepages(forwarder)

        # create sender/receiver ntttcp instances
        ntttcp = {sender: sender.tools[Ntttcp], receiver: receiver.tools[Ntttcp]}

        ### setup forwarding rules

        # Set up DPDK forwarding rules:
        # see https://doc.dpdk.org/guides/sample_app_ug/l3_forward.html#parse-rules-from-file
        # for additional context

        sample_rules_v4 = []
        sample_rules_v6 = []
        #
        # create our longest-prefix-match aka 'lpm' rules
        sample_rules_v4 += [
            f"R {ipv4_lpm(r_nic3_ip)} {dpdk_port_rcv_side}",
            f"R {ipv4_lpm(s_nic2_ip)} {dpdk_port_snd_side}",
        ]

        # need to map ipv4 to ipv6 addresses, unused but the rules must be provided.
        # a valid ipv6 address needs to be in the ipv6 rules, but ipv6 is not enabled in azure.
        # NOTE: DPDK doesn't like shortened ipv6 addresses.
        def ipv4_to_ipv6_lpm(addr: str) -> str:
            # format to 0 prefixed 2 char hex
            parts = ["{:02x}".format(int(part)) for part in addr.split(".")]
            assert_that(parts).described_as(
                "IP address conversion failed, length of split array was unexpected"
            ).is_length(4)
            return (
                "0000:0000:0000:0000:0000:FFFF:" f"{parts[0]}{parts[1]}:{parts[2]}00/56"
            )

        sample_rules_v6 += [
            f"R {ipv4_to_ipv6_lpm(r_nic3_ip)} {dpdk_port_snd_side}",
            f"R {ipv4_to_ipv6_lpm(s_nic2_ip)} {dpdk_port_rcv_side}",
        ]

        # write them out to the rules files on the forwarder
        rules_paths = [
            forwarder.get_pure_path(path) for path in ["rules_v4", "rules_v6"]
        ]
        forwarder.tools[Echo].write_to_file(
            "\n".join(sample_rules_v4), rules_paths[0], append=True
        )
        forwarder.tools[Echo].write_to_file(
            "\n".join(sample_rules_v6), rules_paths[1], append=True
        )

        # get binary path and start the forwarder
        examples_path = fwd_kit.testpmd.dpdk_build_path.joinpath("examples")
        server_app_path = examples_path.joinpath(server_app_name)
        # generate the dpdk include arguments to add to our commandline
        include_devices = [
            fwd_kit.testpmd.generate_testpmd_include(
                f_nic2, dpdk_port_snd_side, force_netvsc=True
            ),
            fwd_kit.testpmd.generate_testpmd_include(
                f_nic3, dpdk_port_rcv_side, force_netvsc=True
            ),
        ]

        ## Generating port,queue,core mappings for forwarder
        # NOTE: For DPDK '8 queues' means 8 queues * N PORTS
        # Each port P has N queues (really queue pairs for tx/rx)
        # Each core can receive one (1) queue id.
        # l3fwd rquires us to explicitly map these as a set of tuples.
        # Create a set of tuples (PortID,QueueID,CoreID)
        # These are minimally error checked, we can accidentally assign
        #  cores and queues to unused ports.
        queue_count = 8
        use_queues = range(queue_count)
        config_tups = []
        curent_core = 1
        # map port for forwarding sender-side traffic
        for q in use_queues:
            config_tups.append((dpdk_port_snd_side, q, curent_core))
            curent_core += 1
        # map port for forwarding receiver-side traffic
        for q in use_queues:
            config_tups.append((dpdk_port_rcv_side, q, curent_core))
            curent_core += 1

        configs = ",".join([f"({p},{q},{c})" for (p, q, c) in config_tups])

        def get_portmask(ports: List[int]) -> str:
            mask = 0
            for i in ports:
                mask |= 1 << i
            return hex(mask)

        # mana doesn't support promiscuous mode
        if fwd_kit.testpmd.is_mana:
            promiscuous = ""
        else:
            promiscuous = "-P"

        joined_include = " ".join(include_devices)

        ## START THE TEST
        # finally, start the forwarder
        fwd_cmd = (
            f"{server_app_path} {joined_include} -l 1-{curent_core}  -- "
            f" {promiscuous} -p {get_portmask([dpdk_port_snd_side,dpdk_port_rcv_side])} "
            f' --lookup=lpm --config="{configs}" '
            "--rule_ipv4=rules_v4  --rule_ipv6=rules_v6 "
            f" --parse-ptype "
            f"--mode=poll"
        )
        fwd_proc = forwarder.execute_async(
            fwd_cmd,
            sudo=True,
            shell=True,
        )
        fwd_proc.wait_output("L3FWD: entering main loop", timeout=30)

        # start the receiver
        receiver_proc = ntttcp[receiver].run_as_server_async(
            r_nic3.name,
            run_time_seconds=30,
            server_ip=r_nic3_ip,
        )
        # start the sender
        sender_result = ntttcp[sender].run_as_client(
            nic_name=s_nic2.name,
            server_ip=r_nic3_ip,
            threads_count=32,
            run_time_seconds=10,
        )

        receiver_result = ntttcp[receiver].wait_server_result(receiver_proc)
        log.debug(f"result: {receiver_result.stdout}")
        log.debug(f"result: {sender_result.stdout}")
        # kill l3fwd on forwarder
        forwarder.tools[Kill].by_name(
            server_app_name, signum=SIGINT, ignore_not_exist=True
        )
        forwarder.log.info(f"Forwarder: {forwarder.name}")
        forwarder.log.info(f"l3fwd cmd: {fwd_cmd}")
        ntttcp_results = {
            receiver: ntttcp[receiver].create_ntttcp_result(receiver_result),
            sender: ntttcp[sender].create_ntttcp_result(sender_result, "client"),
        }
        if test_result:
            msg = ntttcp[sender].create_ntttcp_tcp_performance_message(
                server_result=ntttcp_results[receiver],
                client_result=ntttcp_results[sender],
                latency=Decimal(0),
                connections_num="64",
                buffer_size=64,
                test_case_name="verify_dpdk_l3_forward",
                test_result=test_result,
            )
            notifier.notify(msg)
        throughput = ntttcp_results[receiver].throughput_in_gbps
        assert_that(throughput).described_as(
            "l3fwd test found 0Gbps througput. "
            "Either the test or DPDK forwarding is broken."
        ).is_greater_than(0)
        assert_that(throughput).described_as(
            f"l3fwd has very low throughput: {throughput}Gbps! "
            "Verify netvsc was used over failsafe, check netvsc init was succesful "
            "and the DPDK port IDs were correct."
        ).is_greater_than(1)

    @TestCaseMetadata(
        description="""
            UIO basic functionality test.
            - Bind interface to uio_hv_generic
            - check that sysfs entry is created
            - unbind
            - check that the driver is unloaded.
            - rebind to original driver
        """,
        priority=2,
        requirement=simple_requirement(
            min_nic_count=2,
            network_interface=Sriov(),
            supported_features=[IsolatedResource],
        ),
    )
    def verify_uio_binding(
        self, node: Node, log: Logger, variables: Dict[str, Any]
    ) -> None:
        lsmod = node.tools[Lsmod]
        modprobe = node.tools[Modprobe]
        nic = node.nics.get_secondary_nic()
        node.nics.get_nic_driver(nic.name)
        if nic.module_name == "hv_netvsc":
            enable_uio_hv_generic_for_nic(node, nic)

        original_driver = nic.driver_sysfs_path
        node.nics.unbind(nic)
        node.nics.bind(nic, UIO_HV_GENERIC_SYSFS_PATH)

        node.execute(
            "test -e /dev/uio0",
            shell=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=(
                "/dev/uio0 did not exist after driver bind"
            ),
        )
        assert_that(lsmod.module_exists("uio_hv_generic", force_run=True)).described_as(
            "uio_hv_generic was not found after bind"
        ).is_true()

        node.nics.unbind(nic)
        node.nics.bind(nic, str(original_driver))
        nic.module_name = node.nics.get_nic_driver(nic.name)

        assert_that(nic.module_name).described_as(
            (
                "Driver after unbind/rebind was unexpected. "
                f"Expected hv_netvsc, found {nic.module_name}"
            )
        ).is_equal_to("hv_netvsc")

        modprobe.remove(["uio_hv_generic"])
        node.execute(
            "test -e /dev/uio0",
            shell=True,
            expected_exit_code=1,
            expected_exit_code_failure_message=(
                "/dev/uio0 still exists after driver unload"
            ),
        )

    def _force_dpdk_default_source(self, variables: Dict[str, Any]) -> None:
        if not variables.get("dpdk_source", None):
            variables["dpdk_source"] = DPDK_STABLE_GIT_REPO

    # def after_case(self, log: Logger, **kwargs: Any) -> None:
    #     environment: Environment = kwargs.pop("environment")
    #     for node in environment.nodes.list():
    #         # reset SRIOV to enabled if left disabled
    #         interface = node.features[NetworkInterface]
    #         if not interface.is_enabled_sriov():
    #             log.debug("DPDK detected SRIOV was left disabled during cleanup.")
    #             interface.switch_sriov(enable=True, wait=False, reset_connections=True)

    #         # cleanup driver changes
    #         modprobe = node.tools[Modprobe]
    #         if modprobe.module_exists("uio_hv_generic"):
    #             node.tools[Service].stop_service("vpp")
    #             modprobe.remove(["uio_hv_generic"])
    #             node.close()
    #             modprobe.reload(["hv_netvsc"])
