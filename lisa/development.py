# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


from typing import List, Optional

from lisa import schema

_development_settings: Optional[schema.Development] = None


def load_development_settings(runbook: Optional[schema.Development]) -> None:
    global _development_settings
    if runbook and runbook.enabled:
        _development_settings = runbook


def is_mock_tcp_ping() -> bool:
    return _development_settings is not None and _development_settings.mock_tcp_ping


def is_trace_enabled() -> bool:
    return _development_settings is not None and _development_settings.enable_trace


def get_jump_boxes() -> List[schema.ProxyConnectionInfo]:
    if _development_settings and _development_settings.jump_boxes:
        return _development_settings.jump_boxes
    else:
        return []
