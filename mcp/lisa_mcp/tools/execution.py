# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Execution tools — run LISA tests locally (stdio mode only)."""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import yaml
from mcp.server.mcpserver import MCPServer

from lisa_mcp.config import (
    REQUIRED_AZURE_SETTINGS,
    config_path,
    get_azure_config,
    missing_azure_settings,
    render_config_prompt,
    save_azure_config,
)
from lisa_mcp.runtime import get_transport
from lisa_mcp.tools._repo import find_repo_root

# LISA variables are "name:value"; secrets use the "s:name:value" form.
_VARIABLE_RE = re.compile(r"^(s:)?[A-Za-z_][A-Za-z0-9_]*:.+$", re.DOTALL)

# Cap a single run so a hung deployment cannot block the MCP session forever.
_RUN_TIMEOUT_SECONDS = 4 * 60 * 60

# Keep the returned log small enough for a model context window.
_MAX_LOG_CHARS = 60_000

# Config key -> the variable name LISA runbooks actually declare. Only
# resource_group differs; see lisa/microsoft/runbook/azure.yml.
_VARIABLE_NAMES = {"resource_group": "resource_group_name"}


def _runbook_platform_types(runbook: Path) -> set[str]:
    """Return the platform types a runbook declares, lowercased.

    An empty set means "unknown" — an unreadable runbook, or one that pulls
    its platform in through `include`. Callers must treat unknown as
    possibly-Azure rather than assuming a local run.
    """
    try:
        data = yaml.safe_load(runbook.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return set()
    if not isinstance(data, dict):
        return set()

    platform = data.get("platform")
    entries = platform if isinstance(platform, list) else [platform]
    return {
        entry["type"].strip().lower()
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("type"), str)
    }


def _runbook_node_types(runbook: Path) -> set[str]:
    """Return the node types declared under ``environment.environments``.

    A runbook that pins its own nodes (the `hello_world.yml` style) has no
    `platform` section at all \u2014 LISA falls back to `ready`. Reading the node
    types is what tells those apart from a runbook whose platform simply
    lives in an `include`.
    """
    try:
        data = yaml.safe_load(runbook.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return set()
    if not isinstance(data, dict):
        return set()

    environment = data.get("environment")
    if not isinstance(environment, dict):
        return set()
    environments = environment.get("environments")
    if not isinstance(environments, list):
        return set()

    types: set[str] = set()
    for env in environments:
        if not isinstance(env, dict):
            continue
        for node in env.get("nodes") or []:
            if isinstance(node, dict) and isinstance(node.get("type"), str):
                types.add(node["type"].strip().lower())
    return types


# Node types that never provision cloud resources.
_LOCAL_NODE_TYPES = {"local", "remote", "ready"}


def _needs_azure_config(runbook: Path) -> bool:
    """Whether a run of *runbook* should be gated on Azure settings.

    Errs toward prompting: an include-based or unparseable runbook has an
    unknown platform, and launching what turns out to be an Azure run with
    no subscription or resource group just fails late and confusingly.
    """
    platform_types = _runbook_platform_types(runbook)
    if platform_types:
        return "azure" in platform_types

    # No platform section. If the runbook supplies its own non-cloud nodes,
    # there is nothing for Azure settings to do.
    node_types = _runbook_node_types(runbook)
    if node_types and node_types <= _LOCAL_NODE_TYPES:
        return False

    return True


def _normalize_exit_code(code: int) -> int:
    """Windows reports exit codes as unsigned 32-bit, so -1 arrives as 4294967295."""
    return code - 0x100000000 if code > 0x7FFFFFFF else code


def _parse_variables(variables: str) -> tuple[list[str], Optional[str]]:
    """Split a space-separated ``name:value`` string into ``-v`` arguments."""
    guidance = (
        "Variables must be `name:value` pairs, e.g. "
        "`admin_username:azureuser location:eastus`. Use `s:name:value` "
        "for secrets."
    )
    try:
        tokens = shlex.split(variables)
    except ValueError as exc:
        # An unmatched quote would otherwise surface as an MCP transport
        # error instead of the documented validation response.
        return [], f"Could not parse variables ({exc}). {guidance}"

    args: list[str] = []
    for token in tokens:
        if not _VARIABLE_RE.match(token):
            return [], f"Invalid variable `{token}`. {guidance}"
        args.extend(["-v", token])
    return args, None


def _lisa_command(repo_root: Optional[Path]) -> list[str]:
    """Return the base command used to invoke LISA."""
    executable = shutil.which("lisa")
    if executable:
        return [executable]
    if repo_root and (repo_root / "lisa" / "__main__.py").is_file():
        return [sys.executable, "-m", "lisa"]
    return []


def _truncate(text: str) -> str:
    if len(text) <= _MAX_LOG_CHARS:
        return text
    head_size = _MAX_LOG_CHARS // 4
    tail_size = _MAX_LOG_CHARS - head_size
    dropped = len(text) - _MAX_LOG_CHARS
    return (
        f"{text[:head_size]}\n\n... [truncated {dropped} characters] ...\n\n"
        f"{text[-tail_size:]}"
    )


def register_execution_tools(mcp: MCPServer) -> None:  # noqa: C901
    @mcp.tool()
    def lisa_get_config() -> str:
        """Show the local LISA MCP configuration used by `lisa_run`.

        Reports which required Azure settings are still missing, so the caller
        can collect them from the user before attempting a run.
        """
        azure = get_azure_config()
        missing = missing_azure_settings()

        lines = [f"**Config file:** `{config_path()}`", "", "**Azure settings:**"]
        for name, (description, _) in REQUIRED_AZURE_SETTINGS.items():
            value = azure.get(name) or "*(not set)*"
            lines.append(f"- `{name}`: {value} — {description}")

        if missing:
            lines.extend(["", render_config_prompt(missing)])
        return "\n".join(lines)

    @mcp.tool()
    def lisa_save_config(
        subscription_id: str = "",
        resource_group: str = "",
        location: str = "",
        vm_size: str = "",
    ) -> str:
        """Persist Azure settings to `~/.lisa/mcp_config.yaml`.

        Call this once the user has supplied the settings requested by
        `lisa_run` or `lisa_get_config`. Only non-empty arguments are written,
        so it can also update a single setting. The file lives outside the
        repo and is never committed.

        Args:
            subscription_id: Azure Subscription ID for VM provisioning
            resource_group: Azure Resource Group to deploy test VMs into
            location: Azure region (default: eastus)
            vm_size: VM size for test nodes (default: Standard_DS2_v2)
        """
        settings = {
            "subscription_id": subscription_id.strip(),
            "resource_group": resource_group.strip(),
            "location": location.strip(),
            "vm_size": vm_size.strip(),
        }
        provided = [name for name, value in settings.items() if value]
        if not provided:
            return "No settings provided — nothing was written."

        path = save_azure_config(settings)
        result = f"Saved {', '.join(provided)} to `{path}`."
        missing = missing_azure_settings()
        if missing:
            result += "\n\n" + render_config_prompt(missing)
        return result

    @mcp.tool()
    def lisa_run(
        runbook_path: str,
        variables: str = "",
        debug: bool = False,
    ) -> str:
        """Execute a LISA runbook on the local machine and return the run log.

        **Only available in stdio (local) mode.** A remote SSE server has no
        Azure credentials, so this returns an error telling the user to run
        `lisa-mcp` locally instead.

        The log is returned raw — interpret it with `lisa_summarize_run`,
        `lisa_analyze_log`, or `lisa_diagnose_bug`.

        Args:
            runbook_path: Path to the LISA runbook YAML file, absolute or
                relative to the repo root
            variables: Space-separated LISA variables in name:value format
                       (e.g. "admin_username:azureuser marketplace_image:...")
            debug: Emit DEBUG level logs to the console
        """
        if get_transport() != "stdio":
            return (
                "**`lisa_run` is not available on a remote MCP server.**\n\n"
                "Test execution needs LISA, Docker, and your Azure credentials "
                "on the machine running the tests, and the remote server has "
                "none of them. Install and start the server locally instead:\n\n"
                "```bash\n"
                "pip install "
                "git+https://github.com/microsoft/lisa.git#subdirectory=mcp\n"
                "lisa-mcp --transport stdio\n"
                "```"
            )

        repo_root = find_repo_root()

        runbook = Path(runbook_path).expanduser()
        if not runbook.is_absolute() and repo_root:
            runbook = repo_root / runbook
        if not runbook.is_file():
            return (
                f"Runbook not found: `{runbook}`. Pass the path of an existing "
                "runbook YAML file, or create one with `lisa_generate_runbook`."
            )

        missing = missing_azure_settings()
        if missing and _needs_azure_config(runbook):
            return render_config_prompt(missing)

        base_command = _lisa_command(repo_root)
        if not base_command:
            return (
                "LISA is not installed on this machine. Install it first — see "
                "`docs/install.rst` — or start the LISA container, then retry."
            )

        variable_args, error = _parse_variables(variables)
        if error:
            return error

        command = [*base_command, "-r", str(runbook.resolve())]
        if debug:
            command.append("-d")
        for name, value in get_azure_config().items():
            command.extend(["-v", f"{_VARIABLE_NAMES.get(name, name)}:{value}"])
        command.extend(variable_args)

        try:
            completed = subprocess.run(
                command,
                cwd=str(repo_root) if repo_root else None,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_RUN_TIMEOUT_SECONDS,
                check=False,
            )
        except FileNotFoundError:
            return f"Could not execute `{base_command[0]}` — LISA is not on PATH."
        except subprocess.TimeoutExpired:
            return (
                f"The run exceeded the {_RUN_TIMEOUT_SECONDS // 3600}h limit and "
                "was terminated. Inspect the runbook for a node that never "
                "finished deploying, or split the run into fewer test cases."
            )

        output = _truncate((completed.stdout or "") + (completed.stderr or ""))
        exit_code = _normalize_exit_code(completed.returncode)
        status = "succeeded" if exit_code == 0 else "failed"
        # Variable values are omitted — they carry subscription IDs and secrets.
        return (
            f"**LISA run {status}** (exit code {exit_code})\n\n"
            f"Runbook: `{runbook}`\n\n"
            f"```\n{output}\n```"
        )
