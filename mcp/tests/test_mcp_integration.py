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
import os
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

_MCP_DIR = Path(__file__).resolve().parent.parent
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Import MCP client SDK at module level — tests skip if unavailable.
try:
    from mcp.client.session import ClientSession
    from mcp.client.sse import sse_client
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
        self.assertEqual(len(names), 29, f"Expected 29 tools, got {len(names)}")
        self.assertIn("lisa_analyze_log", names)
        self.assertIn("lisa_write_test", names)
        self.assertIn("lisa_save_test", names)
        self.assertIn("lisa_list_tests", names)
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


class TestSSETransport(unittest.TestCase):
    """Exercise the hosted SSE deployment over real HTTP.

    A stdio-only suite cannot catch SSE routing faults: the client learns the
    POST endpoint from the server's `endpoint` event, so a mismatch between
    the advertised path and the mounted handler only shows up mid-handshake.
    """

    def setUp(self) -> None:
        if not _MCP_CLIENT_AVAILABLE:
            self.skipTest("MCP client SDK not available")
        try:
            import starlette  # noqa: F401
            import uvicorn  # noqa: F401
        except ImportError:
            self.skipTest("SSE extras not installed")

    async def _serve_and_connect(self, api_key: str) -> list:
        import uvicorn
        from mcp.client.sse import sse_client

        from lisa_mcp.server import _build_sse_app

        previous = os.environ.get("LISA_MCP_API_KEY")
        os.environ["LISA_MCP_API_KEY"] = api_key
        os.environ["ALLOWED_HOSTS"] = "localhost,127.0.0.1"
        try:
            # Port 0 lets the OS pick a free port, so parallel runs don't clash.
            config = uvicorn.Config(
                _build_sse_app(), host="127.0.0.1", port=0, log_level="warning"
            )
            server = uvicorn.Server(config)
            serve_task = asyncio.create_task(server.serve())
            while not server.started:
                await asyncio.sleep(0.05)
            port = server.servers[0].sockets[0].getsockname()[1]

            try:
                url = f"http://127.0.0.1:{port}/sse"
                headers = {"X-API-Key": api_key} if api_key else None
                async with sse_client(url, headers=headers) as (read, write):
                    async with ClientSession(read, write) as session:
                        await asyncio.wait_for(session.initialize(), timeout=30)
                        result = await asyncio.wait_for(
                            session.list_tools(), timeout=30
                        )
                        return [t.name for t in result.tools]
            finally:
                server.should_exit = True
                await serve_task
        finally:
            if previous is None:
                os.environ.pop("LISA_MCP_API_KEY", None)
            else:
                os.environ["LISA_MCP_API_KEY"] = previous

    def test_sse_handshake_completes(self) -> None:
        names = _run(self._serve_and_connect(api_key=""))
        self.assertIn("lisa_write_test", names)
        self.assertGreater(len(names), 20)

    def test_sse_handshake_with_api_key(self) -> None:
        names = _run(self._serve_and_connect(api_key="test-key"))
        self.assertIn("lisa_explain_concept", names)

    def test_health_and_auth(self) -> None:
        from starlette.testclient import TestClient

        from lisa_mcp.server import _build_sse_app

        previous = os.environ.get("LISA_MCP_API_KEY")
        os.environ["LISA_MCP_API_KEY"] = "test-key"
        os.environ["ALLOWED_HOSTS"] = "localhost,127.0.0.1"
        try:
            client = TestClient(_build_sse_app(), base_url="http://localhost")

            response = client.get("/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "ok")

            # /messages/ needs the key; /health must stay probe-friendly.
            self.assertEqual(client.post("/messages/").status_code, 401)
            self.assertEqual(
                client.post("/messages/", headers={"X-API-Key": "nope"}).status_code,
                401,
            )
            self.assertEqual(
                client.get("/health", headers={"Host": "evil.example"}).status_code,
                400,
            )
        finally:
            if previous is None:
                os.environ.pop("LISA_MCP_API_KEY", None)
            else:
                os.environ["LISA_MCP_API_KEY"] = previous


class TestRealExecution(unittest.TestCase):
    """Actually spawn LISA through lisa_run.

    Opt-in: needs LISA installed in the same environment as the server, and
    takes tens of seconds. Enable with LISA_MCP_RUN_TESTS=1.
    """

    RUNBOOK = "lisa/examples/runbook/hello_world.yml"

    def setUp(self) -> None:
        if not _MCP_CLIENT_AVAILABLE:
            self.skipTest("MCP client SDK not available")
        if os.environ.get("LISA_MCP_RUN_TESTS") != "1":
            self.skipTest("set LISA_MCP_RUN_TESTS=1 to run real LISA executions")

        self._tmp = tempfile.TemporaryDirectory()
        self._repo = _MCP_DIR.parent
        self._env = {
            "LISA_REPO_ROOT": str(self._repo),
            "LISA_MCP_CONFIG": str(Path(self._tmp.name) / "config.yaml"),
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        }

    def tearDown(self) -> None:
        if hasattr(self, "_tmp"):
            self._tmp.cleanup()

    async def _session(self, body):  # type: ignore[no-untyped-def]
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(_MCP_DIR / "server.py")],
            cwd=str(_MCP_DIR),
            env=self._env,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.call_tool(
                    "lisa_save_config",
                    {
                        "subscription_id": "00000000-0000-0000-0000-000000000000",
                        "resource_group": "integration-test-rg",
                    },
                )
                return await body(session)

    @staticmethod
    def _text(result) -> str:  # type: ignore[no-untyped-def]
        return "".join(getattr(i, "text", "") for i in result.content)

    def test_hello_world_runs_and_log_is_captured(self) -> None:
        async def body(session):  # type: ignore[no-untyped-def]
            return self._text(
                await session.call_tool("lisa_run", {"runbook_path": self.RUNBOOK})
            )

        output = _run(self._session(body))
        self.assertIn("exit code 0", output)
        self.assertIn("hello_world.yml", output)
        # The raw LISA log has to come back, not just a status line.
        self.assertGreater(len(output), 500)

    def test_long_run_does_not_block_other_tools(self) -> None:
        async def body(session):  # type: ignore[no-untyped-def]
            task = asyncio.create_task(
                session.call_tool("lisa_run", {"runbook_path": self.RUNBOOK})
            )
            await asyncio.sleep(1.0)

            start = time.monotonic()
            other = await session.call_tool(
                "lisa_explain_concept", {"concept": "runbook"}
            )
            latency = time.monotonic() - start
            overlapped = not task.done()

            await task
            return latency, overlapped, self._text(other)

        latency, overlapped, other = _run(self._session(body))
        self.assertTrue(overlapped, "lisa_run finished too fast to prove overlap")
        self.assertLess(latency, 5.0, f"parallel call took {latency:.1f}s")
        self.assertGreater(len(other), 100)


class TestContainerDeployment(unittest.TestCase):
    """Smoke-test a running lisa-mcp container over HTTP/SSE.

    Opt-in: start the container first, then point the suite at it.

        docker run -d --name lisa-mcp -p 8080:8080 \\
          -e LISA_MCP_API_KEY=demo-secret \\
          -e ALLOWED_HOSTS=localhost,127.0.0.1 lisa-mcp:local

        LISA_MCP_CONTAINER_URL=http://localhost:8080 \\
        LISA_MCP_CONTAINER_KEY=demo-secret python run_tests.py
    """

    def setUp(self) -> None:
        if not _MCP_CLIENT_AVAILABLE:
            self.skipTest("MCP client SDK not available")
        self.base = os.environ.get("LISA_MCP_CONTAINER_URL", "").rstrip("/")
        if not self.base:
            self.skipTest("set LISA_MCP_CONTAINER_URL to test a running container")
        self.key = os.environ.get("LISA_MCP_CONTAINER_KEY", "")

    def _get(self, path: str, headers: Optional[dict] = None) -> tuple:
        request = urllib.request.Request(
            f"{self.base}{path}", headers=headers or {}, method="GET"
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", errors="replace")

    def _post(self, path: str, headers: Optional[dict] = None) -> int:
        request = urllib.request.Request(
            f"{self.base}{path}", data=b"{}", headers=headers or {}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_health_endpoint(self) -> None:
        status, body = self._get("/health")
        self.assertEqual(status, 200)
        self.assertIn('"status":"ok"', body.replace(" ", ""))

    def test_health_needs_no_api_key(self) -> None:
        # Load balancers probe /health without credentials.
        status, _ = self._get("/health")
        self.assertEqual(status, 200)

    def test_messages_requires_api_key(self) -> None:
        if not self.key:
            self.skipTest("container started without LISA_MCP_API_KEY")
        self.assertEqual(self._post("/messages/"), 401)
        self.assertEqual(self._post("/messages/", {"X-API-Key": "wrong"}), 401)

    def test_rejects_unknown_host_header(self) -> None:
        status, _ = self._get("/health", {"Host": "evil.example"})
        self.assertEqual(status, 400)

    def test_sse_session_exposes_tools(self) -> None:
        async def body():  # type: ignore[no-untyped-def]
            headers = {"X-API-Key": self.key} if self.key else None
            async with sse_client(f"{self.base}/sse", headers=headers) as (rd, wr):
                async with ClientSession(rd, wr) as session:
                    await asyncio.wait_for(session.initialize(), timeout=30)
                    tools = await asyncio.wait_for(session.list_tools(), timeout=30)
                    # Proves the repo clone baked into the image is readable.
                    result = await asyncio.wait_for(
                        session.call_tool("lisa_list_tests", {"max_results": 1}),
                        timeout=60,
                    )
                    text = "".join(getattr(i, "text", "") for i in result.content)
                    return [t.name for t in tools.tools], text

        names, listing = _run(body())
        self.assertIn("lisa_run", names)
        self.assertIn("lisa_write_test", names)
        self.assertGreater(len(names), 20)
        self.assertIn("matching test case", listing)


if __name__ == "__main__":
    unittest.main()
