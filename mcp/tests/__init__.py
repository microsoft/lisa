# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Test package for the LISA MCP server.

Several tools change behaviour based on ambient environment variables, and
some are read at module import time. Clearing them here — before any test
module body runs — keeps a developer's or CI runner's environment from
altering results. Tests that need one of these set it explicitly and restore
it afterwards. `LISA_MCP_RUN_TESTS`, `LISA_MCP_CONTAINER_URL` and
`LISA_REPO_ROOT` are deliberately left alone: those are the runner's contract.
"""

import os

for _name in (
    "LISA_LOG_ROOT",
    "LISA_ALLOWED_STORAGE_ACCOUNTS",
    "LISA_LOG_RETENTION_DAYS",
    "LISA_LOG_MAX_DOWNLOADS",
    "LISA_MCP_API_KEY",
    "LISA_MCP_CONFIG",
    "ALLOWED_HOSTS",
    "FORWARDED_ALLOW_IPS",
):
    os.environ.pop(_name, None)
