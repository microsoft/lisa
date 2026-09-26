# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Process-wide runtime state shared by the tool modules.

Several tools relax or tighten their behaviour depending on whether the
server is serving a local stdio client or a remote SSE client, so the
transport has to be readable from anywhere.
"""

from __future__ import annotations

_transport = "stdio"


def set_transport(transport: str) -> None:
    """Record the transport the server was started with."""
    global _transport
    _transport = transport


def get_transport() -> str:
    return _transport


def is_remote() -> bool:
    """True when the server is reachable over the network."""
    return _transport != "stdio"
