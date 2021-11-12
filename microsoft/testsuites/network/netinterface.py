# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import time

from assertpy import assert_that

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
from lisa.operating_system import CoreOs
from lisa.tools import Dhclient, Uname, Wget
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
        while test_count < self.NET_INTERFACE_RELOAD_TEST_COUNT:
            test_count += 1
            node_nic_info.reset_nic_state(default_nic)
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

    def _validate_netvsc_built_in(self, node: Node) -> None:
        uname_tool = node.tools[Uname]
        kernel_ver = uname_tool.get_linux_information().kernel_version
        config_path = f"/boot/config-{kernel_ver}"
        if isinstance(node.os, CoreOs):
            config_path = f"/usr/boot/config-{kernel_ver}"

        netvsc_builtin_result = node.execute(
            f"grep CONFIG_HYPERV_NET=y {config_path}", shell=True
        )
        if netvsc_builtin_result.exit_code == 0:
            SkippedException("Skipping test since hv_netvsc module is built-in")
