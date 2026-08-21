# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import PurePosixPath
from unittest import TestCase
from unittest.mock import MagicMock, call, patch

from lisa.tools import Gcc, Git, Iperf3, Make


class Iperf3ToolTestCase(TestCase):
    def test_source_install_ensures_compiler_is_available(self) -> None:
        iperf3 = Iperf3.__new__(Iperf3)
        iperf3.node = MagicMock()
        iperf3.node.execute.return_value = MagicMock(unsafe=True)

        git = MagicMock()
        make = MagicMock()

        def get_tool(tool_type: object) -> MagicMock:
            if tool_type is Git:
                return git
            if tool_type is Make:
                return make
            return MagicMock()

        iperf3.node.tools.__getitem__.side_effect = get_tool

        with patch.object(
            Iperf3,
            "get_tool_path",
            return_value=PurePosixPath("/tmp/lisa/tool/iperf3"),
        ):
            iperf3._install_from_src()

        iperf3.node.tools.__getitem__.assert_has_calls(
            [call(Git), call(Gcc), call(Make)]
        )
        iperf3.node.execute.assert_any_call(
            "./configure", cwd=PurePosixPath("/tmp/lisa/tool/iperf3/iperf")
        )
