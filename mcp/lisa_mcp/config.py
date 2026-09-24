# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Local MCP configuration stored outside the repo (``~/.lisa/mcp_config.yaml``).

Holds the Azure settings LISA needs to provision test VMs. The file lives in
the user's home directory so credentials are never committed to the repo.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml

CONFIG_ENV_VAR = "LISA_MCP_CONFIG"

# setting name -> (description, default)
REQUIRED_AZURE_SETTINGS: dict[str, tuple[str, Optional[str]]] = {
    "subscription_id": ("Azure Subscription ID for VM provisioning", None),
    "resource_group": ("Azure Resource Group to deploy test VMs into", None),
    "location": ("Azure region", "eastus"),
    "vm_size": ("VM size for test nodes", "Standard_DS2_v2"),
}


def config_path() -> Path:
    """Return the path of the MCP config file."""
    override = os.environ.get(CONFIG_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".lisa" / "mcp_config.yaml"


def load_config() -> dict[str, Any]:
    """Load the config file. Returns an empty dict when it does not exist."""
    path = config_path()
    if not path.is_file():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def save_azure_config(settings: dict[str, str]) -> Path:
    """Merge *settings* into the ``azure`` section and persist the config.

    The file is written with owner-only permissions because it carries
    subscription identifiers.
    """
    config = load_config()
    azure = dict(config.get("azure") or {})
    azure.update({k: v for k, v in settings.items() if v})
    config["azure"] = azure

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        # Best effort — Windows filesystems may not support POSIX modes.
        pass
    return path


def get_azure_config() -> dict[str, str]:
    """Return the effective Azure settings, with spec defaults applied."""
    azure = dict(load_config().get("azure") or {})
    for name, (_, default) in REQUIRED_AZURE_SETTINGS.items():
        if not azure.get(name) and default:
            azure[name] = default
    return azure


def missing_azure_settings() -> list[str]:
    """Return the names of required settings that have no value and no default."""
    azure = get_azure_config()
    return [name for name in REQUIRED_AZURE_SETTINGS if not azure.get(name)]


def render_config_prompt(missing: list[str]) -> str:
    """Build the structured prompt the client LLM surfaces to the user."""
    rows = [
        f"- `{name}` — {REQUIRED_AZURE_SETTINGS[name][0]}"
        + (
            f" (default: `{REQUIRED_AZURE_SETTINGS[name][1]}`)"
            if REQUIRED_AZURE_SETTINGS[name][1]
            else " (required)"
        )
        for name in missing
    ]
    return (
        "**LISA MCP is not configured for test execution yet.**\n\n"
        "Ask the user for the following settings, then persist them by calling "
        "`lisa_save_config`. They are stored in "
        f"`{config_path()}` and will not be requested again.\n\n" + "\n".join(rows)
    )
