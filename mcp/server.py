# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Convenience entrypoint — delegates to lisa_mcp.server.

Run directly:  python server.py [--transport stdio|sse] [--port 8080]
Installed:     lisa-mcp [--transport stdio|sse] [--port 8080]
"""

from lisa_mcp.server import main, mcp  # noqa: F401 — mcp re-exported for tests

if __name__ == "__main__":
    main()
