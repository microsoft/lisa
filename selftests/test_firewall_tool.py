# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import call, patch

from lisa.tools import Iptables


class IptablesToolTestCase(TestCase):
    def test_forwarding_rules_bypass_command_cache(self) -> None:
        iptables = Iptables.__new__(Iptables)

        with patch.object(Iptables, "run") as run:
            iptables.start_forwarding(49169, "192.168.122.73", 22)
            iptables.stop_forwarding(49169, "192.168.122.73", 22)

        run.assert_has_calls(
            [
                call(
                    "-I FORWARD -o virbr0 -p tcp -d 192.168.122.73 "
                    "--dport 22 -j ACCEPT",
                    sudo=True,
                    force_run=True,
                    expected_exit_code=0,
                ),
                call(
                    "-t nat -I PREROUTING -p tcp --dport 49169 "
                    "-j DNAT --to 192.168.122.73:22",
                    sudo=True,
                    force_run=True,
                    expected_exit_code=0,
                ),
                call(
                    "-D FORWARD -o virbr0 -p tcp -d 192.168.122.73 "
                    "--dport 22 -j ACCEPT",
                    sudo=True,
                    force_run=True,
                    expected_exit_code=0,
                ),
                call(
                    "-t nat -D PREROUTING -p tcp --dport 49169 "
                    "-j DNAT --to 192.168.122.73:22",
                    sudo=True,
                    force_run=True,
                    expected_exit_code=0,
                ),
            ]
        )
