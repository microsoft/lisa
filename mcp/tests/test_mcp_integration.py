# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""MCP protocol integration tests.

These tests start the LISA MCP server as a subprocess, connect over stdio
using the MCP client SDK, and invoke tools through the protocol — exactly
the way Claude Desktop or VS Code would.

Run:
    python -m pytest tests/test_mcp_integration.py -v
    python -m unittest tests.test_mcp_integration -v
"""

import asyncio
import sys
import unittest
from pathlib import Path

_MCP_DIR = Path(__file__).resolve().parent.parent
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Import MCP client SDK at module level — tests skip if unavailable.
try:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    _MCP_CLIENT_AVAILABLE = True
except ImportError:
    _MCP_CLIENT_AVAILABLE = False


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


def _make_server_params():
    """Create StdioServerParameters pointing at our server.py."""
    return StdioServerParameters(
        command=sys.executable,
        args=[str(_MCP_DIR / "server.py")],
        cwd=str(_MCP_DIR),
    )


class TestMCPProtocol(unittest.TestCase):
    """Test the MCP server over the real stdio protocol."""

    def setUp(self) -> None:
        if not _MCP_CLIENT_AVAILABLE:
            self.skipTest("MCP client SDK not available")

    async def _connect_and_call(self, tool_name: str, arguments: dict) -> str:
        """Start the MCP server, connect, call a tool, return the result text."""
        async with stdio_client(_make_server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = await session.call_tool(tool_name, arguments)
                texts = []
                for item in result.content:
                    if hasattr(item, "text"):
                        texts.append(item.text)
                return "\n".join(texts)

    async def _list_tools(self) -> list:
        """Start the server and list all available tools."""
        async with stdio_client(_make_server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return result.tools

    # -- Protocol-level tests --

    def test_server_starts_and_lists_tools(self) -> None:
        tools = _run(self._list_tools())
        names = {t.name for t in tools}
        self.assertEqual(len(names), 25, f"Expected 25 tools, got {len(names)}")
        self.assertIn("lisa_analyze_log", names)
        self.assertIn("lisa_write_test", names)
        self.assertIn("lisa_explain_concept", names)

    def test_call_explain_concept(self) -> None:
        result = _run(
            self._connect_and_call("lisa_explain_concept", {"concept": "runbook"})
        )
        self.assertIn("runbook", result.lower())
        self.assertIn("YAML", result)

    def test_call_analyze_log(self) -> None:
        log_text = "smoke_test | PASSED | ok\n" "verify_x | FAILED | assertion error\n"
        result = _run(
            self._connect_and_call("lisa_analyze_log", {"log_content": log_text})
        )
        self.assertIn("passed", result.lower())
        self.assertIn("failed", result.lower())

    def test_call_explain_failure(self) -> None:
        result = _run(
            self._connect_and_call(
                "lisa_explain_failure",
                {"failure_text": "TcpConnectionException: failed to connect"},
            )
        )
        self.assertIn("Connectivity", result)

    def test_call_validate_runbook(self) -> None:
        result = _run(
            self._connect_and_call(
                "lisa_validate_runbook",
                {
                    "runbook_content": FIXTURES_DIR.joinpath(
                        "sample_runbook.yml"
                    ).read_text()
                },
            )
        )
        self.assertIn("valid", result.lower())

    def test_call_scaffold_test_suite(self) -> None:
        result = _run(
            self._connect_and_call(
                "lisa_scaffold_test_suite",
                {
                    "area": "network",
                    "class_name": "SriovTest",
                    "description": "Test SR-IOV",
                },
            )
        )
        self.assertIn("class SriovTest", result)

    def test_call_generate_runbook(self) -> None:
        result = _run(
            self._connect_and_call(
                "lisa_generate_runbook",
                {"platform": "azure", "area": "provisioning"},
            )
        )
        self.assertIn("type: azure", result)

    def test_call_explain_error(self) -> None:
        result = _run(
            self._connect_and_call(
                "lisa_explain_error",
                {"error_text": "TcpConnectionException"},
            )
        )
        self.assertIn("TCP", result)

    def test_call_list_log_files(self) -> None:
        result = _run(
            self._connect_and_call(
                "lisa_list_log_files",
                {"folder_path": str(FIXTURES_DIR)},
            )
        )
        self.assertIn("sample_passing_run.log", result)

    def test_call_search_log_files(self) -> None:
        result = _run(
            self._connect_and_call(
                "lisa_search_log_files",
                {"search_string": "Kernel panic", "path": str(FIXTURES_DIR)},
            )
        )
        self.assertIn("match", result.lower())

    def test_call_read_log_file(self) -> None:
        result = _run(
            self._connect_and_call(
                "lisa_read_log_file",
                {"file_path": str(FIXTURES_DIR / "sample_passing_run.log")},
            )
        )
        self.assertIn("lisa_runner", result)

    def test_call_get_log_analysis_prompts(self) -> None:
        result = _run(self._connect_and_call("lisa_get_log_analysis_prompts", {}))
        self.assertIn("Log Search", result)


if __name__ == "__main__":
    unittest.main()
