# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Execution tools — run LISA tests locally (stdio mode only)."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def register_execution_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def lisa_run(
        runbook_path: str,
        variables: str = "",
    ) -> str:
        """Shell out to the LISA container and execute a test run locally.

        **Only available in stdio (local) mode.** If called against a remote
        SSE server, returns an error explaining that test execution is local
        only and instructs the user to run lisa-mcp locally.

        Args:
            runbook_path: Path to the LISA runbook YAML file
            variables: Space-separated LISA variables in key:value format
                       (e.g. "admin_username:azureuser subscription_id:xxx")
        """
        # TODO: Implement local execution via LISA container.
        # This tool is intentionally a placeholder — lisa_run requires
        # LISA and Docker installed locally and Azure credentials configured.
        # See spec Section 6.3 for the full design.
        return (
            "**lisa_run is not yet implemented.**\n\n"
            "This tool will shell out to the LISA container on your local "
            "machine to execute the specified runbook. It requires:\n"
            "- LISA installed locally (or via Docker)\n"
            "- Azure credentials configured in `~/.lisa/mcp_config.yaml`\n"
            "- stdio transport mode (not available on remote SSE servers)\n\n"
            "For now, run LISA manually:\n"
            "```bash\n"
            f"lisa -r {runbook_path}"
            + (
                f" {' '.join(f'-v {v}' for v in variables.split() if v)}"
                if variables
                else ""
            )
            + "\n```"
        )
