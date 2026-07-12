# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import cast
from unittest import TestCase
from unittest.mock import patch

from lisa import schema
from lisa.node import RemoteNode
from lisa.util import TcpConnectionException
from lisa.util.shell import SshShell


class SshShellTestCase(TestCase):
    def test_instance_jump_boxes_follow_development_jump_boxes(self) -> None:
        connection = schema.ConnectionInfo(
            address="10.0.0.2",
            username="guest-user",
            password="guest-password",
        )
        development_proxy = schema.ProxyConnectionInfo(
            address="198.51.100.10",
            username="development-user",
            password="development-password",
        )
        parent_proxy = schema.ProxyConnectionInfo(
            address="203.0.113.10",
            port=50001,
            username="parent-user",
            password="parent-password",
        )
        shell = SshShell(connection, jump_boxes=[parent_proxy])

        with patch(
            "lisa.util.shell.development.get_jump_boxes",
            return_value=[development_proxy],
        ):
            jump_boxes = shell._get_jump_boxes()

        self.assertEqual([development_proxy, parent_proxy], jump_boxes)

    def test_initialize_probes_first_jump_box(self) -> None:
        connection = schema.ConnectionInfo(
            address="10.0.0.2",
            username="guest-user",
            password="guest-password",
        )
        parent_proxy = schema.ProxyConnectionInfo(
            address="203.0.113.10",
            port=50001,
            username="parent-user",
            password="parent-password",
        )
        shell = SshShell(connection, jump_boxes=[parent_proxy])

        with patch(
            "lisa.util.shell.development.get_jump_boxes",
            return_value=[],
        ), patch(
            "lisa.util.shell.wait_tcp_port_ready",
            return_value=(False, 10060),
        ) as wait_port:
            with self.assertRaises(TcpConnectionException):
                shell._initialize()

        wait_port.assert_called_once_with("203.0.113.10", 50001)

    def test_remote_node_passes_jump_boxes_to_ssh_shell(self) -> None:
        parent_proxy = schema.ProxyConnectionInfo(
            address="203.0.113.10",
            port=50001,
            username="parent-user",
            password="parent-password",
        )
        node = cast(RemoteNode, RemoteNode.__new__(RemoteNode))

        with patch("lisa.node.SshShell") as ssh_shell:
            node.set_connection_info(
                address="10.0.0.2",
                username="guest-user",
                password="guest-password",
                jump_boxes=[parent_proxy],
            )

        ssh_shell.assert_called_once_with(
            node._connection_info,
            jump_boxes=[parent_proxy],
        )
