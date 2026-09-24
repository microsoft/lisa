# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""LISA MCP Server — AI-native developer tools for the LISA test framework."""

import argparse
import logging
from typing import Any

from mcp.server.mcpserver import MCPServer

from lisa_mcp.auth import ApiKeyMiddleware
from lisa_mcp.tools.execution import register_execution_tools, set_transport
from lisa_mcp.tools.knowledge import register_knowledge_tools
from lisa_mcp.tools.log_analysis import register_log_analysis_tools
from lisa_mcp.tools.runbook import register_runbook_tools
from lisa_mcp.tools.test_writer import register_test_writer_tools

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("lisa-mcp")

mcp = MCPServer(
    "lisa-mcp",
    instructions="""
    You are the LISA MCP server — a developer productivity tool for the LISA
    (Linux Integrated System Analyzer) test automation framework.

    LISA is a Python-based test framework for validating Linux distributions on
    cloud platforms (Azure, Hyper-V, bare metal). It uses YAML runbooks for
    configuration and Python test suites with metadata decorators.

    Available capabilities:
    - **Test Authoring**: Write LISA tests following the lisa_test_writer prompt
      workflow (Gather → Research → Design Plan → Code). Start with
      lisa_write_test or lisa_get_test_writer_guidelines, then persist the
      generated file with lisa_save_test. Use lisa_list_tests to check what
      already exists before writing a new case.
    - **Log Analysis**: Parse and explain LISA run logs and failures.
      Start with lisa_start_log_investigation to bootstrap a full
      root-cause analysis — it returns expert prompts, file listings,
      initial search hits, and next-step instructions.  Then use
      lisa_search_log_files / lisa_read_log_file / lisa_list_log_files
      to dig deeper — you (the host AI) act as the reasoning engine.
    - **Runbook**: Generate, validate, and fix LISA YAML runbooks.
    - **Debugging**: Diagnose test failures with source correlation
    - **Execution**: Run LISA tests locally with lisa_run (stdio mode only).
      It needs Azure settings — lisa_get_config reports what is missing and
      lisa_save_config persists the user's answers to ~/.lisa/mcp_config.yaml.
    - **Framework Knowledge**: Explain LISA concepts, find examples, API reference

    All tools follow the lisa_{verb}_{noun} naming convention.
    """,
)

register_test_writer_tools(mcp)
register_runbook_tools(mcp)
register_log_analysis_tools(mcp)
register_knowledge_tools(mcp)
register_execution_tools(mcp)


def _build_sse_app() -> Any:
    """Assemble the Starlette app serving MCP over SSE."""
    import os

    from starlette.middleware.trustedhost import TrustedHostMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "server": "lisa-mcp"})

    # The SDK factory keeps /sse and /messages/ consistent. Hand-mounting the
    # two halves separately breaks the session: connect_sse advertises
    # root_path + message_path to the client, so a Mount("/sse", ...) makes
    # clients POST to /sse/messages/ and the handshake never completes.
    app = mcp.sse_app(sse_path="/sse", message_path="/messages/")
    app.router.routes.insert(0, Route("/health", endpoint=health, methods=["GET"]))

    # Trusted hosts for Host header validation behind a reverse proxy.
    # Set ALLOWED_HOSTS="host1,host2" in your deployment environment.
    # Defaults to localhost only (for local development).
    default_hosts = "localhost,127.0.0.1"
    allowed_hosts = os.environ.get("ALLOWED_HOSTS", default_hosts).split(",")

    # Optional shared-secret auth. When LISA_MCP_API_KEY is set, every request
    # except /health must carry a matching X-API-Key header.
    wrapped: Any = app
    api_key = os.environ.get("LISA_MCP_API_KEY", "").strip()
    if api_key:
        wrapped = ApiKeyMiddleware(wrapped, api_key=api_key)
    else:
        log.warning(
            "LISA_MCP_API_KEY is not set — the SSE endpoint is unauthenticated. "
            "Set it before exposing this server outside localhost."
        )

    return TrustedHostMiddleware(wrapped, allowed_hosts=allowed_hosts)


def main() -> None:
    """Entry point for the LISA MCP server.

    Supports two transport modes per the deployment strategy:
    - stdio (default): For local use with Claude Desktop, VS Code Copilot
    - sse: For hosted deployment serving agent-to-agent pipelines over HTTP
    """
    parser = argparse.ArgumentParser(
        prog="lisa-mcp",
        description="LISA MCP Server — AI-native tools for LISA test framework",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport mode: stdio (local, default) or sse (hosted HTTP)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind for SSE transport (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for SSE/HTTP transport (default: 8080)",
    )
    args = parser.parse_args()

    set_transport(args.transport)
    log.info(f"Starting LISA MCP server (transport={args.transport})")

    if args.transport == "sse":
        import os

        try:
            import uvicorn
        except ImportError:
            raise SystemExit(
                "SSE transport needs the optional server dependencies. "
                "Install them with: pip install 'lisa-mcp[sse]'"
            )

        # Restrict which proxy IPs may set X-Forwarded-* headers. Set
        # FORWARDED_ALLOW_IPS to your reverse proxy's IP(s) in deployment.
        # Defaults to loopback to prevent client-side spoofing of the
        # forwarded client IP.
        forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")

        uvicorn.run(
            _build_sse_app(),
            host=args.host,
            port=args.port,
            log_level="info",
            forwarded_allow_ips=forwarded_allow_ips,
            proxy_headers=True,
        )
    else:
        mcp.run()


if __name__ == "__main__":
    main()
