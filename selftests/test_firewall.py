# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import MagicMock

from lisa.tools import Iptables


class IptablesTestCase(TestCase):
    def test_forwarding_rules_always_execute_when_dhcp_ip_is_reused(self) -> None:
        iptables = Iptables.__new__(Iptables)
        iptables.run = MagicMock()
        guest_address = "192.168.122.10"

        iptables.start_forwarding(49152, guest_address, 22)
        iptables.stop_forwarding(49152, guest_address, 22)
        iptables.start_forwarding(49153, guest_address, 22)

        self.assertEqual(6, iptables.run.call_count)
        self.assertTrue(
            all(call.kwargs.get("force_run") for call in iptables.run.call_args_list)
        )
