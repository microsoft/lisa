# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from assertpy import assert_that

from lisa import (
    LisaException,
    Logger,
    Node,
    SkippedException,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    UnsupportedOperationException,
)
from lisa.base_tools import Uname
from lisa.operating_system import Debian, Redhat, Suse
from lisa.tools import Ethtool


@TestSuiteMetadata(
    area="network",
    category="functional",
    description="""
    This test suite runs the ethtool related network test cases.
    """,
)
class NetworkSettings(TestSuite):
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

        if isinstance(node.os, Debian):
            min_supported_kernel = "5.0.0"
        elif isinstance(node.os, Redhat):
            min_supported_kernel = "4.0.0"
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
