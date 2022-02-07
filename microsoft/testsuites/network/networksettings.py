# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from pathlib import PurePosixPath
from typing import Any, Dict, List, Union, cast

from assertpy import assert_that

from lisa import (
    Environment,
    LisaException,
    Logger,
    Node,
    RemoteNode,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    UnsupportedOperationException,
    node_requirement,
    schema,
)
from lisa.base_tools import Uname
from lisa.operating_system import Debian, Redhat, Suse
from lisa.tools import Cat, Ethtool, Iperf3, Modinfo, Nm
from lisa.util import find_patterns_in_lines
from microsoft.testsuites.network.common import cleanup_iperf3, stop_firewall


@TestSuiteMetadata(
    area="network",
    category="functional",
    description="""
    This test suite runs the ethtool related network test cases.
    """,
)
class NetworkSettings(TestSuite):

    # regex for filtering per vmbus channel stats from the full device statistics.
    # [{'name': 'tx_scattered', 'value': '0'},
    #  {'name': 'tx_no_memory', 'value': '0'},
    #  {'name': 'tx_no_space', 'value': '0'},
    #  {'name': 'tx_too_big', 'value': '0'},
    #  {'name': 'vf_rx_packets', 'value': '228'},
    #  {'name': 'vf_rx_bytes', 'value': '1158450'},
    #  {'name': 'vf_tx_packets', 'value': '966'},
    #  {'name': 'tx_queue_0_packets', 'value': '0'},
    #  {'name': 'tx_queue_0_bytes', 'value': '0'},
    #  {'name': 'rx_queue_0_packets', 'value': '91'},
    #  {'name': 'rx_queue_0_bytes', 'value': '28378'},
    #  {'name': 'rx_queue_0_xdp_drop', 'value': '0'},
    #  {'name': 'tx_queue_1_packets', 'value': '0'},
    #  {'name': 'tx_queue_1_bytes', 'value': '0'},
    #  {'name': 'rx_queue_1_packets', 'value': '1108'},
    #  {'name': 'rx_queue_1_bytes', 'value': '1415269'},
    #  {'name': 'rx_queue_1_xdp_drop', 'value': '0'},
    #  {'name': 'tx_queue_2_packets', 'value': '0'},]
    _queue_stats_regex = re.compile(r"[tr]x_queue_(?P<name>[\d]+)_packets")
    _tx_queue_stats_regex = re.compile(r"tx_queue_(?P<name>[\d]+)_packets")
    _rx_queue_stats_regex = re.compile(r"rx_queue_(?P<name>[\d]+)_packets")

    @TestCaseMetadata(
        description="""
            This test case verifies if ring buffer settings can be changed with ethtool.

            Steps:
            1. Get the current ring buffer settings.
            2. Change the rx and tx value to new_values using ethtool.
            3. Get the settings again and validate the current rx and tx
                values are equal to the new_values assigned.
            4. Revert back the rx and tx value to their original values.

        """,
        priority=1,
    )
    def validate_ringbuffer_settings_change(self, node: Node) -> None:
        ethtool = node.tools[Ethtool]
        try:
            devices_settings = ethtool.get_all_device_ring_buffer_settings()
        except UnsupportedOperationException as identifier:
            raise SkippedException(identifier)

        for interface_settings in devices_settings:
            interface = interface_settings.device_name
            original_rx = int(interface_settings.current_ring_buffer_settings["RX"])
            original_tx = int(interface_settings.current_ring_buffer_settings["TX"])

            # In the netvsc driver code, default sizes are defined like below -
            # Recieve Buffer, RX
            # NETVSC_RECEIVE_BUFFER_DEFAULT = (1024 * 1024 * 16)
            # NETVSC_RECV_SECTION_SIZE = 1728
            #
            # Send Buffer, TX
            # NETVSC_SEND_BUFFER_DEFAULT =  (1024 * 1024 * 1)
            # NETVSC_SEND_SECTION_SIZE = 6144
            original_rxbuffer = round((original_rx * 1728) / (1024 * 1024))
            original_txbuffer = round((original_tx * 6144) / (1024 * 1024))

            rxbuffer = (
                (original_rxbuffer - 2)
                if original_rxbuffer - 2 > 0
                else (original_rxbuffer + 2)
            )

            txbuffer = (
                (original_txbuffer - 2)
                if original_txbuffer - 2 > 0
                else (original_txbuffer + 2)
            )

            expected_rx = int((rxbuffer * 1024 * 1024) / 1728)
            expected_tx = int((txbuffer * 1024 * 1024) / 6144)
            actual_settings = ethtool.change_device_ring_buffer_settings(
                interface, expected_rx, expected_tx
            )
            assert_that(
                int(actual_settings.current_ring_buffer_settings["RX"]),
                "Changing RX Ringbuffer setting didn't succeed",
            ).is_equal_to(expected_rx)
            assert_that(
                int(actual_settings.current_ring_buffer_settings["TX"]),
                "Changing TX Ringbuffer setting didn't succeed",
            ).is_equal_to(expected_tx)

            # Revert the settings back to original values
            reverted_settings = ethtool.change_device_ring_buffer_settings(
                interface, original_rx, original_tx
            )
            assert_that(
                int(reverted_settings.current_ring_buffer_settings["RX"]),
                "Reverting RX Ringbuffer setting to original value didn't succeed",
            ).is_equal_to(original_rx)
            assert_that(
                int(reverted_settings.current_ring_buffer_settings["TX"]),
                "Reverting TX Ringbuffer setting to original value didn't succeed",
            ).is_equal_to(original_tx)

    @TestCaseMetadata(
        description="""
            This test case verifies changing device channels count with ethtool.

            Steps:
            1. Get the current device channels info.
            2   a. Keep Changing the channel count from min to max value using ethtool.
                b. Get the channel count info and validate the channel count
                    value is equal to the new value assigned.
            3. Revert back the channel count to its original value.

        """,
        priority=1,
    )
    def validate_device_channels_change(self, node: Node, log: Logger) -> None:
        ethtool = node.tools[Ethtool]
        try:
            devices_channels = ethtool.get_all_device_channels_info()
        except UnsupportedOperationException as identifier:
            raise SkippedException(identifier)

        skip_test = True
        for interface_channels_info in devices_channels:
            interface = interface_channels_info.device_name
            channels = interface_channels_info.current_channels
            max_channels = interface_channels_info.max_channels

            if max_channels <= 1:
                log.info(
                    f"Max channels for device {interface} is <= 1."
                    " Not attempting to change, Skipping."
                )
                continue

            skip_test = False
            for new_channels in range(1, max_channels + 1):
                channels_info = ethtool.change_device_channels_info(
                    interface, new_channels
                )
                assert_that(
                    channels_info.current_channels,
                    f"Setting channels count to {new_channels} didn't succeed",
                ).is_equal_to(new_channels)

            if new_channels != channels:
                # revert back the channel count to original value
                channels_info = ethtool.change_device_channels_info(interface, channels)
                assert_that(
                    channels_info.current_channels,
                    f"Reverting channels count to its original value {channels} didn't"
                    f" succeed. Current Value is {channels_info.current_channels}",
                ).is_equal_to(channels)

        if skip_test:
            raise SkippedException(
                "Max Channel count for all the devices is <=1 and cannot be"
                " tested for changing. Skipping test."
            )

    @TestCaseMetadata(
        description="""
            This test case verifies required device features are enabled.

            Steps:
            1. Get the device's enabled features.
            2. Validate below features are in the list of enabled features-
                rx-checksumming
                tx-checksumming
                tcp-segmentation-offload
                scatter-gather
        """,
        priority=1,
    )
    def validate_device_enabled_features(self, node: Node) -> None:
        required_features = [
            "rx-checksumming",
            "tx-checksumming",
            "scatter-gather",
            "tcp-segmentation-offload",
        ]
        ethtool = node.tools[Ethtool]
        devices_features = ethtool.get_all_device_enabled_features()

        for device_features in devices_features:
            enabled_features = device_features.enabled_features

            if not set(required_features).issubset(enabled_features):
                raise LisaException(
                    "Not all the required features (rx-checksumming, tx-checksumming,"
                    " scatter-gather, tcp-segmentation-offload) are enabled for"
                    f" device {device_features.device_name}."
                    f" Enabled features list - {enabled_features}"
                )

    @TestCaseMetadata(
        description="""
            This test case verifies changing device's GRO and LRO setting takes
            into affect.

            Steps:
            1. Get all the device's generic-receive-offload and large-receive-offload
                settings.
            2. If both GRO and LRO settings are "[fixed]" then skip testing specific
                device.
            3. Try flipping the GRO and LRO settings and validate it takes affect.
            4. Revert back the settings to original values.
        """,
        priority=1,
    )
    def validate_device_gro_lro_settings_change(self, node: Node, log: Logger) -> None:
        ethtool = node.tools[Ethtool]

        skip_test = True
        devices_gro_lro_settings = ethtool.get_all_device_gro_lro_settings()
        for settings in devices_gro_lro_settings:
            interface = settings.interface
            if settings.gro_fixed and settings.lro_fixed:
                log.info(
                    "The GRO and LRO settings are fixed and cannot be changed for"
                    f" device {interface}. Skipping test for this device"
                )
                continue

            skip_test = False
            original_gro_setting = settings.gro_setting
            original_lro_setting = settings.lro_setting

            new_gro_setting = (
                original_gro_setting if settings.gro_fixed else not original_gro_setting
            )
            new_lro_setting = (
                original_lro_setting if settings.lro_fixed else not original_lro_setting
            )

            new_settings = ethtool.change_device_gro_lro_settings(
                interface, new_gro_setting, new_lro_setting
            )
            assert_that(
                new_settings.gro_setting,
                "Changing GRO setting didn't succeed",
            ).is_equal_to(new_gro_setting)
            assert_that(
                new_settings.lro_setting,
                "Changing LRO setting didn't succeed",
            ).is_equal_to(new_lro_setting)

            # Revert the settings back to original values
            reverted_settings = ethtool.change_device_gro_lro_settings(
                interface, original_gro_setting, original_lro_setting
            )
            assert_that(
                reverted_settings.gro_setting,
                "Reverting GRO setting to original value didn't succeed",
            ).is_equal_to(original_gro_setting)
            assert_that(
                reverted_settings.lro_setting,
                "Reverting LRO setting to original value didn't succeed",
            ).is_equal_to(original_lro_setting)

        if skip_test:
            raise SkippedException(
                "GRO and LRO settings for all the devices are fixed and cannot be"
                " changed. Skipping test."
            )

    @TestCaseMetadata(
        description="""
            This test case verifies changing device's RSS hash key takes
            into affect.

            Steps:
            1. Skip the test if the kernel version is any less than LTS 5.
            2. Get all the device's RSS hash key values.
            3. Swap the last 2 characters of original hash key to make a new hash key.
            4. Validate changing the hash key setting using the new hash key.
            5. Revert back the settings to original values.
        """,
        priority=2,
    )
    def validate_device_rss_hash_key_change(self, node: Node, log: Logger) -> None:
        uname = node.tools[Uname]
        linux_info = uname.get_linux_information()

        if isinstance(node.os, Debian) or isinstance(node.os, Redhat):
            min_supported_kernel = "5.0.0"
        elif isinstance(node.os, Suse):
            min_supported_kernel = "4.12.14"
        else:
            # For other OS, it is not known which minimum kernel version
            # supports RSS Hash key change. This can be found and later
            # enhanced after running tests.
            min_supported_kernel = str(linux_info.kernel_version)

        if linux_info.kernel_version < min_supported_kernel:
            raise SkippedException(
                f"The kernel version {linux_info.kernel_version} does not support"
                " changing RSS hash key."
            )

        ethtool = node.tools[Ethtool]
        try:
            devices_rss_hkey_info = ethtool.get_all_device_rss_hash_key()
        except UnsupportedOperationException as identifier:
            raise SkippedException(identifier)

        for device_hkey_info in devices_rss_hkey_info:
            original_hkey = device_hkey_info.rss_hash_key
            # Swap the last 2 characters of the original hash key to make new hash key.
            split_hkey = original_hkey.rsplit(":", 1)
            swapped_part = "".join(
                [
                    split_hkey[1][x : x + 2][::-1]
                    for x in range(0, len(split_hkey[1]), 2)
                ]
            )

            expected_hkey = f"{split_hkey[0]}:{swapped_part}"
            new_settings = ethtool.change_device_rss_hash_key(
                device_hkey_info.interface, expected_hkey
            )
            assert_that(
                new_settings.rss_hash_key,
                "Changing RSS hash key didn't succeed",
            ).is_equal_to(expected_hkey)

            # Revert the settings back to original values
            reverted_settings = ethtool.change_device_rss_hash_key(
                device_hkey_info.interface, original_hkey
            )
            assert_that(
                reverted_settings.rss_hash_key,
                "Reverting RSS hash key to original value didn't succeed",
            ).is_equal_to(original_hkey)

    @TestCaseMetadata(
        description="""
            This test case verifies whether changing device's RX hash level
            for tcp and udp takes into affect.

            Steps:
                Note: Same steps are used for both TCP and UDP.
            1. Get all the device's RX hash level status.
            2. Depending on current setting, change to enabled/disabled.
            3. Validate changing the hash level setting.
            4. Revert back the settings to original values.
        """,
        priority=2,
    )
    def validate_device_rx_hash_level_change(self, node: Node, log: Logger) -> None:
        ethtool = node.tools[Ethtool]

        # Run the test for both TCP and UDP
        test_protocols = ["tcp4", "udp4"]

        for protocol in test_protocols:
            try:
                devices_rx_hlevel_info = ethtool.get_all_device_rx_hash_level(protocol)
            except UnsupportedOperationException as identifier:
                raise SkippedException(identifier)

            for device_hlevel_info in devices_rx_hlevel_info:
                interface = device_hlevel_info.interface
                original_hlevel = device_hlevel_info.protocol_hash_map[protocol]
                expected_hlevel = not original_hlevel

                new_settings = ethtool.change_device_rx_hash_level(
                    interface, protocol, expected_hlevel
                )
                assert_that(
                    new_settings.protocol_hash_map[protocol],
                    f"Changing RX hash level for {protocol} didn't succeed",
                ).is_equal_to(expected_hlevel)

                # Revert the settings back to original values
                reverted_settings = ethtool.change_device_rx_hash_level(
                    interface, protocol, original_hlevel
                )
                assert_that(
                    reverted_settings.protocol_hash_map[protocol],
                    f"Reverting RX hash level for {protocol} to original value"
                    " didn't succeed",
                ).is_equal_to(original_hlevel)

    @TestCaseMetadata(
        description="""
            This test case verifies whether setting/unsetting device's
            message level flag takes into affect.

            Steps:
            1. Verify Get/Set message level supported on kernel version.
            2. Get all the device's message level number and name setting.
            2. Depending on current setting, set/unset a message flag by number
                and name.
            3. Validate changing the message level flag setting.
            4. Revert back the setting to original value.
        """,
        priority=2,
    )
    def validate_device_msg_level_change(self, node: Node, log: Logger) -> None:
        # Check if feature is supported by the kernel
        self._check_msg_level_change_supported(node)

        msg_types: Dict[str, str] = {
            "probe": "0x0002",
            "tx_done": "0x0400",
            "rx_status": "0x0800",
        }

        ethtool = node.tools[Ethtool]
        devices_msg_level = ethtool.get_all_device_msg_level()

        for msg_level_info in devices_msg_level:
            interface = msg_level_info.device_name
            original_msg_level_number = msg_level_info.msg_level_number
            original_msg_level_name = msg_level_info.msg_level_name

            name_test_flag = []
            number_test_flag = 0

            for msg_key, msg_value in msg_types.items():
                if msg_key not in original_msg_level_name:
                    name_test_flag.append(msg_key)
                    number_test_flag += int(msg_value, 16)

            # variable to indicate set or unset
            set = True

            # if test message flags are already set, pick first test flag in list.
            # validate change by first unsetting the flag and then unsetting
            if not name_test_flag and not number_test_flag:
                first_pair = list(msg_types.items())[0]
                name_test_flag.append(first_pair[0])
                number_test_flag = int(first_pair[1], 16)
                set = False

            # Testing set/unset message level by name
            new_settings = ethtool.set_unset_device_message_flag_by_name(
                interface, name_test_flag, set
            )
            if set:
                assert_that(
                    new_settings.msg_level_name,
                    f"Setting msg flags - {' '.join(name_test_flag)} didn't"
                    f" succeed. Current value is {new_settings.msg_level_name}",
                ).contains(" ".join(name_test_flag))
            else:
                assert_that(
                    new_settings.msg_level_name,
                    f"Setting msg flags by name - {' '.join(name_test_flag)} didn't"
                    f" succeed. Current value is {new_settings.msg_level_name}",
                ).does_not_contain(" ".join(name_test_flag))

            reverted_settings = ethtool.set_unset_device_message_flag_by_name(
                interface, name_test_flag, not set
            )
            if not set:
                assert_that(
                    reverted_settings.msg_level_name,
                    f"Setting msg flags by name - {' '.join(name_test_flag)} didn't"
                    f" succeed. Current value is {reverted_settings.msg_level_name}",
                ).contains(" ".join(name_test_flag))
            else:
                assert_that(
                    reverted_settings.msg_level_name,
                    f"Setting msg flags by name - {' '.join(name_test_flag)} didn't"
                    f" succeed. Current value is {reverted_settings.msg_level_name}",
                ).does_not_contain(" ".join(name_test_flag))

            # Testing set message level by number
            new_settings = ethtool.set_device_message_flag_by_num(
                interface, str(hex(number_test_flag))
            )
            assert_that(
                int(new_settings.msg_level_number, 16),
                f"Setting msg flags by number - {str(hex(number_test_flag))} didn't"
                f" succeed. Current value is {new_settings.msg_level_number}",
            ).is_equal_to(number_test_flag)

            reverted_settings = ethtool.set_device_message_flag_by_num(
                interface, original_msg_level_number
            )
            assert_that(
                int(reverted_settings.msg_level_number, 16),
                f"Setting msg flags by number - {original_msg_level_number} didn't"
                f" succeed. Current value is {reverted_settings.msg_level_number}",
            ).is_equal_to(int(original_msg_level_number, 16))

    @TestCaseMetadata(
        description="""
            This test case verifies that device statistics can be captured.

            Steps:
            1. Get all the device's statistics.
            2. Validate device statistics lists per queue statistics as well.
            3. Run traffic using iperf3 and validate traffic is evenly distributed
                among different VMBUS channel queues.
        """,
        priority=2,
        requirement=node_requirement(
            node=schema.NodeSpace(
                node_count=2,
            )
        ),
    )
    def validate_device_statistics(self, environment: Environment, log: Logger) -> None:
        client_iperf3_log = "iperfResults.log"
        server_node = cast(RemoteNode, environment.nodes[0])
        client_node = cast(RemoteNode, environment.nodes[1])
        ethtool = client_node.tools[Ethtool]

        try:
            devices_statistics = ethtool.get_all_device_statistics()
        except UnsupportedOperationException as identifier:
            raise SkippedException(identifier)

        for device_stats in devices_statistics:
            per_queue_packets = {
                k: v
                for (k, v) in device_stats.items()
                if self._queue_stats_regex.search(k)
            }

            assert_that(
                per_queue_packets,
                "Statistics per VMBUS channel are empty. It might be because the driver"
                " is not supported or because of very old kernel.",
            ).is_not_empty()

        # preparation work before launch iperf3
        stop_firewall(environment)

        # run iperf3 on server side and client side
        # iperfResults.log stored client side log
        source_iperf3 = server_node.tools[Iperf3]
        dest_iperf3 = client_node.tools[Iperf3]
        source_iperf3.run_as_server_async()
        dest_iperf3.run_as_client(
            server_ip=server_node.internal_address,
            log_file=client_iperf3_log,
            parallel_number=64,
        )

        # wait for a while then check any error shown up in iperfResults.log
        dest_cat = client_node.tools[Cat]
        iperf_log = dest_cat.read(client_iperf3_log, sudo=True, force_run=True)
        assert_that(iperf_log).does_not_contain("error")

        # validate from the stats that traffic is evenly spread
        try:
            devices_statistics = ethtool.get_all_device_statistics()
        except UnsupportedOperationException as identifier:
            raise SkippedException(identifier)

        for device_stats in devices_statistics:
            per_tx_queue_packets = [
                v
                for (k, v) in device_stats.items()
                if self._tx_queue_stats_regex.search(k)
            ]

            # No queue should receive/transmit 30% more packets than other queues
            # If it does, failure should be reported
            min_tx_queue_packets = min(per_tx_queue_packets)
            # Avoid divide by 0 scenario while checking traffic spread among queues
            if min_tx_queue_packets == 0:
                min_tx_queue_packets = 1
            max_tx_queue_packets = max(per_tx_queue_packets)
            assert_that(
                ((max_tx_queue_packets - min_tx_queue_packets) / min_tx_queue_packets),
                "Statistics show traffic is not evenly distributed among tx queues",
            ).is_less_than_or_equal_to(0.3)

            per_rx_queue_packets = [
                v
                for (k, v) in device_stats.items()
                if self._rx_queue_stats_regex.search(k)
            ]

            min_rx_queue_packets = min(per_rx_queue_packets)
            # Avoid divide by 0 scenario while checking traffic spread among queues
            if min_rx_queue_packets == 0:
                min_rx_queue_packets = 1
            max_rx_queue_packets = max(per_rx_queue_packets)
            assert_that(
                ((max_rx_queue_packets - min_rx_queue_packets) / min_rx_queue_packets),
                "Statistics show traffic is not evenly distributed among rx queues",
            ).is_less_than_or_equal_to(0.3)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        environment: Environment = kwargs.pop("environment")
        cleanup_iperf3(environment)

    def _check_msg_level_change_supported(self, node: Node) -> None:
        msg_level_symbols: Union[str, List[str]]
        # name:           hv_netvsc
        # filename:       (builtin)
        # description:    Microsoft Hyper-V network driver
        # license:        GPL
        # parm:           ring_size:Ring buffer size (# of pages) (uint)
        # parm:           debug:Debug level (0=none,...,16=all) (int)
        build_in_pattern = re.compile(r"builtin", re.M)

        uname_tool = node.tools[Uname]
        kernel_version = uname_tool.get_linux_information().kernel_version

        modinfo = node.tools[Modinfo]
        netvsc_module = modinfo.get_filename("hv_netvsc")
        matched = find_patterns_in_lines(netvsc_module, [build_in_pattern])
        if not (matched[0]):
            # remove any escape character at the end of string
            netvsc_module = netvsc_module.strip()
            # if the module is archived as xz, extract it to check symbols
            if netvsc_module.endswith(".xz"):
                node.execute(
                    f"cp {netvsc_module} {node.working_path}/", cwd=node.working_path
                )
                node.execute(
                    f"xz -d {node.working_path}/{netvsc_module.rsplit('/', 1)[-1]}",
                    cwd=node.working_path,
                )
                netvsc_module = node.execute(
                    f"ls {node.working_path}/hv_netvsc*",
                    shell=True,
                    cwd=node.working_path,
                ).stdout

            assert node.shell.exists(
                PurePosixPath(netvsc_module)
            ), f"{netvsc_module} doesn't exist."

            nm = node.tools[Nm]
            msg_level_symbols = nm.get_symbol_table(netvsc_module)
        else:
            # if the module is builtin
            command = f"grep 'netvsc.*msglevel' '/boot/System.map-{kernel_version}'"
            result = node.execute(
                command,
                shell=True,
                sudo=True,
                expected_exit_code=0,
                expected_exit_code_failure_message="Couldn't get the message level"
                "symbols in System map.",
            )
            msg_level_symbols = result.stdout

        if ("netvsc_get_msglevel" not in msg_level_symbols) or (
            "netvsc_set_msglevel" not in msg_level_symbols
        ):
            raise SkippedException(
                f"Get/Set message level not supported on {kernel_version},"
                " Skipping test."
            )
