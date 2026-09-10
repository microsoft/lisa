# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Helpers for locating the LISA repo and loading context files."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml

# Cache parsed manifest so it's loaded once per process
_manifest_cache: Optional[dict[str, Any]] = None

# The lisa_mcp/ package dir is two levels up from lisa_mcp/tools/_repo.py
_PACKAGE_DIR = Path(__file__).resolve().parent.parent

# The mcp/ directory is three levels up from lisa_mcp/tools/_repo.py
_MCP_DIR = _PACKAGE_DIR.parent


def find_repo_root() -> Optional[Path]:
    """Walk up from this file to find the LISA repository root.

    The repo root is identified by having a ``lisa/`` package directory
    and a ``pyproject.toml``.
    """
    # mcp/ lives alongside lisa/ at the repo root
    candidate = _MCP_DIR.parent
    if (candidate / "lisa").is_dir() and (candidate / "pyproject.toml").is_file():
        return candidate

    # Fallback: check LISA_REPO_ROOT env var
    env_root = os.environ.get("LISA_REPO_ROOT")
    if env_root:
        p = Path(env_root)
        if p.is_dir():
            return p

    return None


def load_context_file(name: str) -> str:
    """Load a markdown file from the ``lisa_mcp/context/`` directory."""
    context_dir = _PACKAGE_DIR / "context"
    path = context_dir / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"(Context file '{name}' not found at {path})"


def load_test_writer_prompt() -> str:
    """Load the lisa_test_writer.prompt.md from the repo's .github/prompts/."""
    repo_root = find_repo_root()
    if not repo_root:
        return "(Could not locate LISA repo root to load test writer prompt.)"

    prompt_path = repo_root / ".github" / "prompts" / "lisa_test_writer.prompt.md"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return f"(Test writer prompt not found at {prompt_path})"


# ---------------------------------------------------------------------------
# Docs manifest helpers
# ---------------------------------------------------------------------------


def _load_manifest() -> dict[str, Any]:
    """Parse ``mcp/docs_index.yaml`` and cache the result."""
    global _manifest_cache
    if _manifest_cache is not None:
        return _manifest_cache

    manifest_path = _PACKAGE_DIR / "docs_index.yaml"
    if not manifest_path.exists():
        _manifest_cache = {}
        return _manifest_cache

    with open(manifest_path, encoding="utf-8") as f:
        _manifest_cache = yaml.safe_load(f) or {}
    return _manifest_cache


def load_docs_for_tool(tool_name: str) -> str:
    """Load the .rst/.md documentation mapped to *tool_name* in docs_index.yaml.

    Returns the concatenated content of the primary doc and any supplementary
    docs.  Files are read as plain text — .rst is perfectly usable by LLMs
    without conversion.
    """
    manifest = _load_manifest()
    tool_entry = (manifest.get("tools") or {}).get(tool_name)
    if not tool_entry:
        return ""

    repo_root = find_repo_root()
    if not repo_root:
        return ""

    paths: list[str] = []
    primary = tool_entry.get("primary")
    if primary:
        paths.append(primary)
    supplementary = tool_entry.get("supplementary") or []
    paths.extend(supplementary)

    sections: list[str] = []
    for rel_path in paths:
        full = repo_root / rel_path
        if full.exists():
            try:
                content = full.read_text(encoding="utf-8", errors="replace")
                sections.append(f"--- [{rel_path}] ---\n{content}")
            except OSError:
                pass

    return "\n\n".join(sections)


def load_doc_for_topic(topic: str) -> str:
    """Look up a topic keyword in the ``topics`` section of docs_index.yaml
    and return the content of the mapped doc file.
    """
    manifest = _load_manifest()
    topics = manifest.get("topics") or {}

    # Exact match first
    rel_path = topics.get(topic.lower().strip())

    # Fuzzy: check if topic is a substring of any key or vice-versa
    if not rel_path:
        topic_lower = topic.lower().strip()
        for key, path in topics.items():
            if topic_lower in key or key in topic_lower:
                rel_path = path
                break

    if not rel_path:
        return ""

    repo_root = find_repo_root()
    if not repo_root:
        return ""

    full = repo_root / rel_path
    if full.exists():
        try:
            return full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass

    return ""
