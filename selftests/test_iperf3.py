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

        with patch.object(iperf3, "_install", return_value=True) as install:
            self.assertTrue(iperf3.install())

        tools.get.assert_has_calls([call(Git), call(Make), call(Gcc)])
        install.assert_called_once_with()
