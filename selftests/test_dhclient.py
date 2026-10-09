# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import MagicMock

from lisa.base_tools import Cat
from lisa.tools import Dhclient
from lisa.tools.ls import Ls


class DhclientTestCase(TestCase):
    def test_get_timeout_uses_dhcpcd_configuration(self) -> None:
        dhclient = Dhclient.__new__(Dhclient)
        dhclient._command = "dhcpcd"
        dhclient._log = MagicMock()
        dhclient.node = MagicMock()

        ls = MagicMock()
        ls.path_exists.return_value = True
        cat = MagicMock()
        cat.read.return_value = "# dhcpcd configuration\ntimeout 300\n"
        dhclient.node.tools = {Ls: ls, Cat: cat}

        timeout = dhclient.get_timeout()

        self.assertEqual(300, timeout)
        ls.path_exists.assert_called_once_with("/etc/dhcpcd.conf", sudo=True)
        cat.read.assert_called_once_with("/etc/dhcpcd.conf", sudo=True)
        dhclient.node.execute.assert_not_called()