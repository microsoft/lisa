#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
Test script for creating and maintaining a TCP server-client connection.
This script is used to test INET_DIAG_DESTROY functionality.
"""

import socket
import sys
import threading
import time
from typing import List

# Configuration
LOCALHOST = "127.0.0.1"
DEFAULT_PORT = 34567


def create_tcp_server_client(port: int, algo_output_path: str = "") -> None:
    """
    Create a TCP server-client connection and keep it alive.

    Args:
        port: The port number to use for the connection
    """
    # Create server socket
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((LOCALHOST, port))
    server.listen(1)

    # Create client socket
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # Accept connection in background
    accepted_conn: List[socket.socket] = []

    def accept_connection() -> None:
        conn, addr = server.accept()
        accepted_conn.append(conn)
        # Keep connection alive
        while True:
            time.sleep(1)

    accept_thread = threading.Thread(target=accept_connection, daemon=True)
    accept_thread.start()

    # Connect client
    client.connect((LOCALHOST, port))

    if algo_output_path:
        algo = client.getsockopt(
            socket.IPPROTO_TCP,
            socket.TCP_CONGESTION,  # type: ignore[attr-defined]
            64,
        )
        with open(algo_output_path, "w", encoding="utf-8") as algo_file:
            algo_file.write(algo.decode().strip("\x00"))

    print("CONNECTION_READY")
    sys.stdout.flush()

    # Keep script running to maintain connection
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        client.close()
        server.close()


if __name__ == "__main__":
    # Get port from command line argument, or use default
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    algo_output_path = sys.argv[2] if len(sys.argv) > 2 else ""
    create_tcp_server_client(port, algo_output_path)
