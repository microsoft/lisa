# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import time
from typing import cast

from assertpy import assert_that
from randmac import RandMac  # type: ignore

from lisa import (
    LisaException,
    Logger,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    schema,
    simple_requirement,
)
from lisa.environment import Environment
from lisa.features import NetworkInterface, StartStop, Synthetic
from lisa.nic import Nics
from lisa.node import RemoteNode
from lisa.tools import Dhclient, Ip, KernelConfig, Wget
from lisa.tools.iperf3 import Iperf3
from lisa.tools.kill import Kill
from lisa.util import perf_timer

from .common import restore_extra_nics_per_node


@TestSuiteMetadata(
    area="network",
    category="functional",
    description="""
    This test suite validates basic functionalities of Network Interfaces.
    """,
)
class NetInterface(TestSuite):
    NETVSC_RELOAD_TEST_COUNT = 10
    NET_INTERFACE_RELOAD_TEST_COUNT = 4
    DHCLIENT_TIMEOUT = 15

    @TestCaseMetadata(
        description="""
            This test case verifies if synthetic network module - netvsc
                can be reloaded gracefully when done multiple times.

            Steps:
            1. Validate netvsc isn't built-in already. If it is then skip the test.
            2. Unload and load netvsc module multiple times in a loop.

        """,
        priority=1,
        requirement=simple_requirement(network_interface=Synthetic()),
    )
    def validate_netvsc_reload(self, node: Node) -> None:
        self._validate_netvsc_built_in(node)
        network_interface_feature = node.features[NetworkInterface]
        # Test loading and unloading netvsc driver
        test_count = 0
        while test_count < self.NETVSC_RELOAD_TEST_COUNT:
            test_count += 1
            # Unload and load hv_netvsc
            network_interface_feature.reload_module()

    @TestCaseMetadata(
        description="""
            This test case verifies if synthetic network interface can be
            brought up and brought down gracefully via ip link set commands.

            Steps:
            1. Validate netvsc isn't built-in already. If it is then skip the test.
            2. Ensure netvsc module is loaded.
            3. Change nic state to up and down multiple times using ifup-ifdown commands
                Each time after "up" state, verify ip address is assigned to nic
                and internet is accessible via nic.

        """,
        priority=1,
        requirement=simple_requirement(
            network_interface=schema.NetworkInterfaceOptionSettings(
                data_path=schema.NetworkDataPath.Synthetic,
            ),
        ),
    )
    def validate_network_interface_reload_via_ip_link(
        self, node: Node, log: Logger
    ) -> None:
        self._validate_netvsc_built_in(node)
        network_interface_feature = node.features[NetworkInterface]

        # Ensure netvsc module is loaded
        network_interface_feature.reload_module()

        node_nic_info = Nics(node)
        node_nic_info.initialize()
        default_nic = node_nic_info.default_nic
        default_route = node_nic_info.default_nic_route

        assert_that(default_nic).is_not_none()
        assert_that(default_route).is_not_none()

        test_count = 0
        ip = node.tools[Ip]
        while test_count < self.NET_INTERFACE_RELOAD_TEST_COUNT:
            test_count += 1
            ip.restart_device(default_nic, run_dhclient=True)
            if not node_nic_info.default_nic:
                # Add default route if missing after running ip link down/up
                node.execute(f"ip route add {default_route}", shell=True, sudo=True)
            if not node_nic_info.nics[default_nic].ip_addr:
                node.execute("kill $(pidof dhclient)", shell=True, sudo=True)
                dhclient = node.tools[Dhclient]
                dhclient.renew()

            timer = perf_timer.Timer()
            while timer.elapsed(stop=False) < self.DHCLIENT_TIMEOUT:
                node_nic_info.load_interface_info(default_nic)
                if node_nic_info.nics[default_nic].ip_addr:
                    break
                time.sleep(1)

            wget_tool = node.tools[Wget]
            if not wget_tool.verify_internet_access():
                raise LisaException(
                    "Cannot access internet from inside VM after test run."
                )

    @TestCaseMetadata(
        description="""
            This test case verifies if the second network interface can be brought up
             after setting static MAC address.

            Steps:
            1. Validate the second nic has IP address.
            2. Bring down the second nic.
            3. Set a random MAC address to the second nic.
            4. Bring up the second nic.

        """,
        priority=3,
        requirement=simple_requirement(
            network_interface=schema.NetworkInterfaceOptionSettings(
                nic_count=2,
            ),
        ),
    )
    def validate_set_static_mac(self, node: Node, log: Logger) -> None:
        ip = node.tools[Ip]
        node_nic_info = Nics(node)
        node_nic_info.initialize()
        origin_nic_count = len(node_nic_info)
        # attach one more nic for testing if only 1 nic by default
        if 1 == origin_nic_count:
            network_interface_feature = node.features[NetworkInterface]
            network_interface_feature.attach_nics(
                extra_nic_count=1, enable_accelerated_networking=True
            )
            node_nic_info = Nics(node)
            node_nic_info.initialize()
        # get one nic which is not eth0 for setting new mac address
        current_nic_count = len(node_nic_info)
        for index in range(0, current_nic_count):
            test_nic = node_nic_info.get_nic_by_index(index)
            test_nic_name = test_nic.upper
            if "eth0" == test_nic_name:
                continue
        assert_that(test_nic).is_not_none()
        assert_that(test_nic.ip_addr).is_not_none()
        assert_that(test_nic.mac_addr).is_not_none()
        origin_mac_address = test_nic.mac_addr
        try:
            random_mac_address = str(RandMac())
            ip.set_mac_address(test_nic_name, random_mac_address)
            node_nic_info.load_interface_info(test_nic_name)
            assert_that(test_nic.mac_addr).described_as(
                f"fail to set network interface {test_nic_name}'s mac "
                f"address into {random_mac_address}"
            ).is_equal_to(random_mac_address)
        finally:
            # restore the test nic state back to origin state
            ip.set_mac_address(test_nic_name, origin_mac_address)
            node_nic_info.load_interface_info(test_nic_name)
            assert_that(test_nic.mac_addr).described_as(
                f"fail to set network interface {test_nic}'s mac "
                f"address back into {origin_mac_address}"
            ).is_equal_to(origin_mac_address)
            # restore vm nics status if 1 extra nic attached
            if 1 == origin_nic_count:
                restore_extra_nics_per_node(node)
                node_nic_info = Nics(node)
                node_nic_info.initialize()

    @TestCaseMetadata(
        description="""
        This test case check IP is assigned to Physical Function (PF)

        Steps:
         1. Generate traffic in VM using iperf3
         2. Verify IP is assigned to PF in client VM
         2. Stop-Start VM
         3. Verify IP is assigned to PF in client VM

        """,
        priority=1,
        requirement=simple_requirement(supported_features=[StartStop], min_count=2),
    )
    def verify_pf_ip(self, environment: Environment, log: Logger) -> None:
        server = cast(RemoteNode, environment.nodes[0])
        client = cast(RemoteNode, environment.nodes[1])
        try:
            # Run traffic in the VM
            server.tools[Iperf3].run_as_server_async()
            client_iperf_process = client.tools[Iperf3].run_as_client_async(
                server.internal_address
            )

            assert_that(
                client_iperf_process.is_running(), "Network workload is not running"
            ).is_true()

            # Check if IP is assigned to client eth interface
            start_stop = client.features[StartStop]
            client_nic_info = Nics(client)
            client_nic_info.initialize()
            for _, node_nic in client_nic_info.nics.items():
                assert_that(node_nic.ip_addr).described_as(
                    f"This interface {node_nic.upper} does not have a IP address."
                ).is_not_empty()
            start_stop.stop()
            start_stop.start()
            for _, node_nic in client_nic_info.nics.items():
                assert_that(node_nic.ip_addr).described_as(
                    f"This interface {node_nic.upper} does not have a IP address."
                ).is_not_empty()
        finally:
            server.tools[Kill].by_name("iperf3", ignore_not_exist=True)
            client.tools[Kill].by_name("iperf3", ignore_not_exist=True)

    def _validate_netvsc_built_in(self, node: Node) -> None:
        if node.tools[KernelConfig].is_built_in("CONFIG_HYPERV_NET"):
            raise SkippedException("Skipping test since hv_netvsc module is built-in")
