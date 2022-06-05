# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import time

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
from lisa.features import NetworkInterface, Synthetic
from lisa.nic import Nics
from lisa.tools import Dhclient, Ip, KernelConfig, Wget
from lisa.util import perf_timer


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
            ip.restart_device(default_nic)
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
        test_nic = node_nic_info.get_nic_by_index()
        test_nic_name = test_nic.upper
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

    def _validate_netvsc_built_in(self, node: Node) -> None:
        if node.tools[KernelConfig].is_built_in("CONFIG_HYPERV_NET"):
            raise SkippedException("Skipping test since hv_netvsc module is built-in")
