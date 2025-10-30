# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import time
from pathlib import Path

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
from lisa.features import NetworkInterface, SerialConsole, Synthetic
from lisa.operating_system import FreeBSD
from lisa.tools import Ip, KernelConfig, Uname, Wget
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
    def validate_netvsc_reload(self, node: Node, log_path: Path) -> None:
        self._validate_netvsc_built_in(node)
        network_interface_feature = node.features[NetworkInterface]
        # Test loading and unloading netvsc driver
        test_count = 0
        while test_count < self.NETVSC_RELOAD_TEST_COUNT:
            test_count += 1
            # Unload and load hv_netvsc
            try:
                network_interface_feature.reload_module()
            except Exception as e:
                # It has two kinds of known exceptions. One is SSHException "SSH session
                # not active". Another is "cannot connect to TCP port". The SSHException
                # can be ignorable. If no panic is detected, close the node and retry.
                # If it is the second exception, retrying is useless, so just raise an
                # exception. Having the second exception is not clear if the image has
                # an issue. The test result can be set as "Attempted". For now, we just
                # found an image gigamon-inc gigamon-fm-5_16_00 vseries-1-node 1.7.3
                # truly fails the case because of the second exception. It has a veth0
                # created by openvswitch, which doesn't seem to be able to properly
                # handle the removal/addition of the netvsc interface eth0. Restart
                # openvswitch-switch service can recover the network.
                serial_console = node.features[SerialConsole]
                serial_console.check_panic(
                    saved_path=log_path, stage="after_reload_netvsc", force_run=True
                )
                if str(e) == "SSH session not active":
                    node.log.debug(f"This exception '{e}' is ignorable. Try again")
                    node.close()
                elif "cannot connect to TCP port" in str(e):
                    raise LisaException(
                        f"After reloading netvsc module {test_count - 1} times, "
                        f"encounter exception '{e}'. It is not clear if"
                        " the image has an issue. Please rerun this case."
                    )
                else:
                    raise LisaException(
                        f"After reloading netvsc module {test_count - 1} times, "
                        f"encounter exception '{e}'."
                    )

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
    def verify_network_interface_reload_via_ip_link(
        self, node: Node, log: Logger
    ) -> None:
        self._validate_netvsc_built_in(node)
        network_interface_feature = node.features[NetworkInterface]

        # Ensure netvsc module is loaded
        network_interface_feature.reload_module()

        node_nic_info = node.nics
        node_nic_info.reload()
        default_nic = node_nic_info.default_nic
        default_route = node_nic_info.default_nic_route

        assert_that(default_nic).is_not_none()
        assert_that(default_route).is_not_none()

        test_count = 0
        ip = node.tools[Ip]
        while test_count < self.NET_INTERFACE_RELOAD_TEST_COUNT:
            test_count += 1
            ip.restart_device(
                default_nic, run_dhclient=True, default_route=default_route
            )

            timer = perf_timer.Timer()
            while timer.elapsed(stop=False) < self.DHCLIENT_TIMEOUT:
                node_nic_info.load_nics_info(default_nic)
                if node_nic_info.nics[default_nic].ip_addr:
                    break
                time.sleep(1)

            wget_tool = node.tools[Wget]
            if not wget_tool.verify_internet_access():
                raise LisaException(
                    "Cannot access internet from inside VM after test run."
                )

    def _validate_netvsc_built_in(self, node: Node) -> None:
        if isinstance(node.os, FreeBSD):
            # Use command "config -x /boot/kernel/kernel | grep hyperv" can also check
            # if netvsc is build-in. The output "device hyperv" means the the hyperv
            # drivers includes vmbus,kvp,netvsc,storvsc are built-in to the kernel.
            # Here use command "kldstat | grep hv_netvsc" to check.
            is_built_in_module = (
                node.execute(
                    "kldstat | grep hv_netvsc", sudo=True, shell=True
                ).exit_code
                != 0
            )
        else:
            try:
                is_built_in_module = node.tools[KernelConfig].is_built_in(
                    "CONFIG_HYPERV_NET"
                )
            except LisaException as e:
                # Some image's kernel config is inconsistent with the kernel version.
                # E.g. fatpipe-inc fatpipe-wanopt 10 0.0.3, then it has the exception.
                # If so, check if netvsc is built-in using below way.
                node.log.debug(e)
                uname = node.tools[Uname]
                kernel = uname.get_linux_information().kernel_version_raw
                is_built_in_module = (
                    node.execute(
                        f"grep hv_netvsc /lib/modules/{kernel}/modules.builtin",
                        sudo=True,
                        shell=True,
                    ).exit_code
                    == 0
                )
        if is_built_in_module:
            raise SkippedException("Skipping test since hv_netvsc module is built-in")
