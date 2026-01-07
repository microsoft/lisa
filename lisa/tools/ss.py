# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from __future__ import annotations

import re

from lisa.executable import Tool


class Ss(Tool):
    """
    ss - socket statistics tool for investigating sockets
    """

    # Example output from ss -tn:
    # State   Recv-Q  Send-Q   Local Address:Port    Peer Address:Port
    # ESTAB   0       0        127.0.0.1:34567       127.0.0.1:45678
    _connection_pattern = re.compile(
        r"(?P<state>\S+)\s+\d+\s+\d+\s+"
        r"(?P<local_addr>[0-9a-f.:]+):(?P<local_port>\d+)\s+"
        r"(?P<peer_addr>[0-9a-f.:]+):(?P<peer_port>\d+)"
    )

    @property
    def command(self) -> str:
        return "ss"

    def _check_exists(self) -> bool:
        return True

    @property
    def can_install(self) -> bool:
        return False

    def has_kill_support(self) -> bool:
        """
        Check if ss supports the -K (kill) flag for INET_DIAG_DESTROY.
        """
        result = self.run("--help", force_run=True, expected_exit_code=0)
        return "-K" in result.stdout or "-K" in result.stderr

    def connection_exists(
        self,
        port: int,
        local_addr: str = "",
        state: str = "ESTAB",
        sport: bool = True,
    ) -> bool:
        """
        Check if a connection exists on the specified port.

        Args:
            port: Port number to check
            local_addr: Optional local address to filter
            state: Connection state (default: ESTAB)
            sport: If True, check source port; if False, check destination port

        Returns:
            True if connection exists, False otherwise
        """
        port_filter = f"sport = {port}" if sport else f"dport = {port}"
        cmd = f"-tn {port_filter}"

        result = self.run(
            cmd,
            shell=True,
            force_run=True,
            expected_exit_code=0,
        )

        if not result.stdout:
            return False

        # Check if the state exists in output
        if state not in result.stdout:
            return False

        # If local_addr specified, verify it matches
        if local_addr:
            return local_addr in result.stdout

        return True

    def kill_connection(
        self,
        port: int,
        sport: bool = True,
        sudo: bool = True,
    ) -> None:
        """
        Kill (destroy) a connection on the specified port using ss -K.
        Requires CONFIG_INET_DIAG_DESTROY kernel feature.

        Args:
            port: Port number of connection to kill
            sport: If True, filter by source port; if False, by destination port
            sudo: Whether to run with sudo (default: True, usually required)
        """
        port_filter = f"sport = {port}" if sport else f"dport = {port}"
        cmd = f"-K {port_filter}"

        self.run(
            cmd,
            shell=True,
            force_run=True,
            sudo=sudo,
            expected_exit_code=0,
        )

    def get_statistics(self) -> str:
        """
        Get socket statistics summary using ss -s.

        Returns:
            Statistics output as string
        """
        result = self.run("-s", force_run=True, expected_exit_code=0)
        return result.stdout
