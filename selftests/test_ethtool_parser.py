# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import unittest

from lisa.tools.ethtool import DeviceChannel
from lisa.util import LisaException


class TestEthtoolChannelParser(unittest.TestCase):
    """Regression tests for ethtool channel parsing."""

    def test_device_channel_parsing_normal_output(self) -> None:
        """Test parsing of normal ethtool output."""
        raw_output = """Channel parameters for eth0:
Pre-set maximums:
RX:             0
TX:             0
Other:          0
Combined:       64
Current hardware settings:
RX:             0
TX:             0
Other:          0
Combined:       4"""

        channel_info = DeviceChannel("eth0", raw_output)
        self.assertEqual(channel_info.current_channels, 4)
        self.assertEqual(channel_info.max_channels, 64)

    def test_device_channel_parsing_with_trailing_spaces(self) -> None:
        """Test parsing when output has trailing spaces."""
        raw_output = (
            "Channel parameters for eth0:\nPre-set maximums:\n"
            "RX:             0\nTX:             0\nOther:          0\n"
            "Combined:       32   \n"
            "Current hardware settings:\n"
            "RX:             0\nTX:             0\nOther:          0\n"
            "Combined:       2   "  # noqa: W291
        )

        channel_info = DeviceChannel("eth0", raw_output)
        self.assertEqual(channel_info.current_channels, 2)
        self.assertEqual(channel_info.max_channels, 32)

    def test_device_channel_parsing_with_tabs(self) -> None:
        """Test parsing when output has tabs (potential edge case)."""
        raw_output = """Channel parameters for eth0:
Pre-set maximums:
RX:             0
TX:             0
Other:          0
Combined:	16
Current hardware settings:
RX:             0
TX:             0
Other:          0
Combined:	1"""

        channel_info = DeviceChannel("eth0", raw_output)
        self.assertEqual(channel_info.current_channels, 1)
        self.assertEqual(channel_info.max_channels, 16)

    def test_device_channel_parsing_with_extra_content(self) -> None:
        """Test rejecting output with extra content after the value."""
        raw_output = """Channel parameters for eth0:
Pre-set maximums:
RX:             0
TX:             0
Other:          0
Combined:       8 # comment or extra text
Current hardware settings:
RX:             0
TX:             0
Other:          0
Combined:       2 # another comment"""

        with self.assertRaises(LisaException):
            DeviceChannel("eth0", raw_output)

    def test_device_channel_parsing_large_numbers(self) -> None:
        """Test parsing with larger channel numbers."""
        raw_output = """Channel parameters for eth0:
Pre-set maximums:
RX:             0
TX:             0
Other:          0
Combined:       128
Current hardware settings:
RX:             0
TX:             0
Other:          0
Combined:       64"""

        channel_info = DeviceChannel("eth0", raw_output)
        self.assertEqual(channel_info.current_channels, 64)
        self.assertEqual(channel_info.max_channels, 128)


if __name__ == "__main__":
    unittest.main()
