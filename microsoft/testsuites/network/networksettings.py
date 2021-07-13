# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from assertpy import assert_that

from lisa import Node, TestCaseMetadata, TestSuite, TestSuiteMetadata
from lisa.tools import Ethtool
from lisa.util import LisaException, SkippedException, UnsupportedOperationException


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
            4. Revert back the rx and tx value to their orginal values.

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

            # selecting lesser values to avoid crossing max values of Rx and Tx.
            expected_rx = original_rx - 2
            expected_tx = original_tx - 2
            actual_settings = ethtool.change_device_ring_buffer_settings(
                interface, expected_rx, expected_tx
            )
            assert_that(
                actual_settings.current_ring_buffer_settings["RX"],
                "Changing RX Ringbuffer setting didn't succeed",
            ).is_equal_to(expected_rx)
            assert_that(
                actual_settings.current_ring_buffer_settings["TX"],
                "Changing TX Ringbuffer setting didn't succeed",
            ).is_equal_to(expected_tx)

            # Revert the settings back to original values
            reverted_settings = ethtool.change_device_ring_buffer_settings(
                interface, original_rx, original_tx
            )
            assert_that(
                reverted_settings.current_ring_buffer_settings["RX"],
                "Reverting RX Ringbuffer setting to original value didn't succeed",
            ).is_equal_to(original_rx)
            assert_that(
                reverted_settings.current_ring_buffer_settings["TX"],
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
    def validate_device_channels_change(self, node: Node) -> None:
        ethtool = node.tools[Ethtool]
        try:
            devices_channels = ethtool.get_all_device_channels_info()
        except UnsupportedOperationException as identifier:
            raise SkippedException(identifier)

        for interface_channels_info in devices_channels:
            interface = interface_channels_info.device_name
            channels = interface_channels_info.current_channels
            max_channels = interface_channels_info.max_channels

            for new_channels in range(1, max_channels + 1):
                channels_info = ethtool.change_device_channels_info(
                    interface, new_channels
                )
                assert_that(
                    channels_info.current_channels,
                    f"Setting channels count to {new_channels} didn't succeed",
                ).is_equal_to(new_channels)

            # revert back the channel count to original value
            channels_info = ethtool.change_device_channels_info(interface, channels)
            assert_that(
                channels_info.current_channels,
                f"Reverting channels count to its original value {channels}"
                f" didn't succeed. Current Value is {channels_info.current_channels}",
            ).is_equal_to(channels)

    @TestCaseMetadata(
        description="""
            This test case verifies required device features are enabled.

            Steps:
            1. Get the device's enabled features.
            2. Validate below features are in the list of enbaled features-
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
            "scater-gather",
            "tcp-segmentation-offload",
        ]
        ethtool = node.tools[Ethtool]
        devices_features = ethtool.get_all_device_enabled_features()

        for device_features in devices_features:
            enabled_features = device_features.enabled_features

            if not all(feature in enabled_features for feature in required_features):
                raise LisaException(
                    "Not all the required features (rx-checksumming, tx-checksumming,"
                    "scatter-gather, tcp-segmentation-offload) are enabled for"
                    f" device {device_features.device_name}."
                    f" Enabled features list - {enabled_features}"
                )
