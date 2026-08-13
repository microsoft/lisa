# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import MagicMock, call, patch

from lisa.tools import Gcc, Git, Make
from lisa.tools.iperf3 import Iperf3


class Iperf3TestCase(TestCase):
    def test_install_loads_source_build_dependencies(self) -> None:
        tools = MagicMock()
        iperf3 = Iperf3.__new__(Iperf3)
        iperf3.node = MagicMock(tools=tools)
        iperf3._log = MagicMock()

        parent = MagicMock()
        parent.attach_mock(tools.get, "get")

        with patch.object(iperf3, "_install", return_value=True) as install:
            parent.attach_mock(install, "install")
            self.assertTrue(iperf3.install())

        parent.assert_has_calls(
            [call.get(Git), call.get(Make), call.get(Gcc), call.install()]
        )
