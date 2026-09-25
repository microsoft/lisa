# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Log analysis tools — parse, explain, and summarize LISA run logs."""

from __future__ import annotations

import ipaddress
import os
import re
import shutil
import socket
import stat
import tarfile
import tempfile
import time
import zipfile
from http.client import HTTPSConnection
from pathlib import Path
from typing import Any, BinaryIO, Optional
from urllib.parse import ParseResult, unquote, urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from mcp.server.mcpserver import MCPServer

from lisa_mcp.runtime import is_remote
from lisa_mcp.tools._repo import find_repo_root, load_context_file, load_docs_for_tool


def _load_ai_prompts() -> str:
    """Load the LISA AI log analyzer prompts from lisa/ai/prompts/default/.

    Returns the concatenated prompt text for log_search, code_search,
    final_answer, and user workflow — the same strategies the multi-agent
    log analyzer uses.
    """
    repo_root = find_repo_root()
    if not repo_root:
        return ""

    prompts_dir = repo_root / "lisa" / "ai" / "prompts" / "default"
    if not prompts_dir.is_dir():
        return ""

    prompt_files = [
        ("user.txt", "Overall Analysis Workflow"),
        ("log_search.txt", "Log Search Agent Strategy"),
        ("code_search.txt", "Code Search Agent Strategy"),
        ("final_answer.txt", "Final Answer Synthesis"),
    ]

    sections: list[str] = []
    for filename, heading in prompt_files:
        path = prompts_dir / filename
        if path.exists():
            content = path.read_text(encoding="utf-8", errors="replace")
            sections.append(f"## {heading}\n\n{content}")

    return "\n\n---\n\n".join(sections)


def register_log_analysis_tools(mcp: MCPServer) -> None:  # noqa: C901
    @mcp.tool()
    def lisa_analyze_log(
        log_content: Optional[str] = None,
        log_path: Optional[str] = None,
    ) -> str:
        """Parse a LISA run log to extract structured results — pass/fail/skip
        counts, failure details, and warnings.

        Provide either the log text directly or a file path.

        Args:
            log_content: Raw LISA log text (paste from terminal or file)
            log_path: Absolute path to a LISA log file on disk
        """
        text = _get_log_text(log_content, log_path)
        if text.startswith("Error:"):
            return text

        results = _extract_test_results(text)
        errors = _extract_errors(text)
        warnings = _extract_warnings(text)
        panics = _extract_kernel_panics(text)

        sections = []

        # Summary counts
        passed = sum(1 for r in results if r["status"] == "PASSED")
        failed = sum(1 for r in results if r["status"] == "FAILED")
        skipped = sum(1 for r in results if r["status"] == "SKIPPED")
        attempted = sum(1 for r in results if r["status"] == "ATTEMPTED")
        total = len(results)

        sections.append(
            f"**Run Summary:** {total} tests — "
            f"{passed} passed, {failed} failed, {skipped} skipped"
            + (f", {attempted} attempted" if attempted else "")
        )

        # Failed tests
        if failed:
            fail_lines = []
            for r in results:
                if r["status"] == "FAILED":
                    msg = r.get("message", "")
                    fail_lines.append(f"- **{r['name']}**: {msg[:200]}")
            sections.append("**Failures:**\n" + "\n".join(fail_lines))

        # Kernel panics
        if panics:
            sections.append(
                "**Kernel Panics Detected:**\n"
                + "\n".join(f"- {p[:200]}" for p in panics[:5])
            )

        # Errors (non-test)
        if errors:
            sections.append(
                f"**Errors ({len(errors)}):**\n"
                + "\n".join(f"- {e[:200]}" for e in errors[:10])
            )

        # Warnings
        if warnings:
            sections.append(
                f"**Warnings ({len(warnings)}):**\n"
                + "\n".join(f"- {w[:200]}" for w in warnings[:5])
            )

        if not sections:
            sections.append(
                "No structured test results found in the log. "
                "The log might not be a LISA run log, or the run "
                "may not have reached test execution."
            )

        return "\n\n".join(sections)

    @mcp.tool()
    def lisa_explain_failure(failure_text: str) -> str:
        """Given a LISA test failure block (stack trace, error message, or log
        snippet), classify the failure type and provide context for debugging.

        Categories:
        - **Framework error**: LISA infrastructure issue (SSH, provisioning)
        - **Test logic error**: Assertion failure in test code
        - **Infrastructure error**: VM/cloud platform issue
        - **Kernel error**: Kernel panic, oops, or bug

        Args:
            failure_text: The failure output — stack trace, error message, or
                          relevant log lines
        """
        categories = []
        explanations = []

        text_lower = failure_text.lower()

        # Kernel issues
        if any(
            k in text_lower
            for k in [
                "kernel panic",
                "kernel bug",
                "call trace",
                "rip:",
                "bug: soft lockup",
                "oops",
                "general protection fault",
            ]
        ):
            categories.append("Kernel Error")
            explanations.append(
                "The failure contains kernel-level errors. Check:\n"
                "- Serial console output for the full panic/oops\n"
                "- `dmesg` on the node if still accessible\n"
                "- Whether the kernel version is known-good for this distro\n"
                "- If custom kernel parameters were applied"
            )

        # SSH / connectivity
        if any(
            k in text_lower
            for k in [
                "tcpconnectionexception",
                "ssh",
                "connection refused",
                "connection timed out",
                "tcp port",
                "paramiko",
                "no route to host",
                "network is unreachable",
            ]
        ):
            categories.append("Framework Error — Connectivity")
            explanations.append(
                "SSH or TCP connection failure. Check:\n"
                "- Is the VM still running? (check platform portal)\n"
                "- Network security group / firewall rules\n"
                "- Whether the VM booted successfully (serial console)\n"
                "- If this is a new image, verify sshd is enabled"
            )

        # Provisioning
        if any(
            k in text_lower
            for k in [
                "provisioningerror",
                "deployment failed",
                "allocation failed",
                "overconstrainedallocationrequest",
                "operationnotallowed",
                "resourcenotfound",
                "quotaexceeded",
            ]
        ):
            categories.append("Infrastructure Error — Provisioning")
            explanations.append(
                "VM provisioning failed on the cloud platform. Check:\n"
                "- VM size availability in the target region\n"
                "- Subscription quota limits\n"
                "- Image availability in the marketplace\n"
                "- Whether the requested features (GPU, NVMe) are "
                "supported by the chosen VM size"
            )

        # Assertion failures
        if any(
            k in text_lower
            for k in [
                "assertionerror",
                "assert_that",
                "expected",
                "to be equal to",
                "to contain",
                "is not true",
                "is not false",
            ]
        ):
            categories.append("Test Logic Error — Assertion")
            explanations.append(
                "A test assertion failed. This typically means the system "
                "under test produced unexpected output. Check:\n"
                "- The expected vs actual values in the assertion\n"
                "- Whether the test assumptions match the target OS/distro\n"
                "- If the test has a `.described_as()` hint explaining the intent"
            )

        # Timeout
        if any(
            k in text_lower
            for k in [
                "timeout",
                "timed out",
                "time out",
                "deadline exceeded",
            ]
        ):
            categories.append("Timeout")
            explanations.append(
                "An operation timed out. Check:\n"
                "- Whether the VM was under heavy load\n"
                "- If the timeout value is appropriate for the operation\n"
                "- Network latency between LISA host and target\n"
                "- If the operation completed but detection failed"
            )

        # SkippedException (not a real failure)
        if "skippedexception" in text_lower:
            categories.append("Skipped (Not a Failure)")
            explanations.append(
                "The test was skipped due to unmet preconditions. This is "
                "expected behavior — the test prerequisites (OS, feature, "
                "hardware) were not met by the target environment."
            )

        # LisaException generic
        if "lisaexception" in text_lower and not categories:
            categories.append("Framework Error")
            explanations.append(
                "A LISA framework exception occurred. Read the exception "
                "message carefully — it should indicate what happened and "
                "how to investigate."
            )

        if not categories:
            categories.append("Unknown")
            explanations.append(
                "Could not automatically classify this failure. Provide more "
                "context (full stack trace, surrounding log lines) for better "
                "analysis."
            )

        result = f"**Failure Classification:** {', '.join(categories)}\n\n"
        result += "\n\n".join(explanations)

        # Append official troubleshooting guidance if available
        troubleshoot_docs = load_docs_for_tool("lisa_explain_failure")
        if troubleshoot_docs:
            result += (
                "\n\n---\n\n"
                "**From official LISA troubleshooting docs:**\n\n"
                + troubleshoot_docs[:2000]
            )

        return result

    @mcp.tool()
    def lisa_summarize_run(
        log_content: Optional[str] = None,
        log_path: Optional[str] = None,
    ) -> str:
        """Produce a concise, high-level summary of a LISA test run suitable
        for sharing in a report or PR comment.

        Args:
            log_content: Raw LISA log text
            log_path: Absolute path to a LISA log file
        """
        text = _get_log_text(log_content, log_path)
        if text.startswith("Error:"):
            return text

        results = _extract_test_results(text)
        panics = _extract_kernel_panics(text)

        passed = [r for r in results if r["status"] == "PASSED"]
        failed = [r for r in results if r["status"] == "FAILED"]
        skipped = [r for r in results if r["status"] == "SKIPPED"]

        lines = []
        lines.append("## LISA Run Summary")
        lines.append("")
        lines.append("| Status | Count |")
        lines.append("|--------|-------|")
        lines.append(f"| Passed | {len(passed)} |")
        lines.append(f"| Failed | {len(failed)} |")
        lines.append(f"| Skipped | {len(skipped)} |")
        lines.append(f"| **Total** | **{len(results)}** |")

        if failed:
            lines.append("")
            lines.append("### Failures")
            for r in failed:
                msg = r.get("message", "no message")
                lines.append(f"- **{r['name']}** — {msg[:150]}")

        if panics:
            lines.append("")
            lines.append(f"### Kernel Panics ({len(panics)})")
            for p in panics[:3]:
                lines.append(f"- {p[:150]}")

        if not results:
            lines.append("")
            lines.append(
                "*No test results extracted. The log may not contain "
                "structured LISA output.*"
            )

        # Extract run duration if available
        duration_match = re.search(
            r"(?:total|elapsed|duration)[:\s]+(\d+\.?\d*)\s*(?:s|seconds?|minutes?)",
            text,
            re.IGNORECASE,
        )
        if duration_match:
            lines.append("")
            lines.append(f"**Duration:** {duration_match.group(0)}")

        return "\n".join(lines)

    @mcp.tool()
    def lisa_download_logs(
        url: str,
        auth_token: Optional[str] = None,
    ) -> str:
        """Download log files from a URL so they can be investigated on the
        server with ``lisa_start_log_investigation`` and the file tools.

        Supports three URL formats:

        - **Azure Portal URLs** — paste directly from the portal Storage
          Browser.  The tool auto-converts them to blob API calls.
        - **Azure Blob URLs** — direct ``*.blob.core.windows.net`` URLs.
          If the path is a virtual directory (prefix), all blobs under
          it are downloaded.  Single-file blobs are also supported.
        - **Direct HTTPS URLs** — for publicly accessible files or
          archives.  Pass ``auth_token`` for bearer-token APIs.

        Azure Blob authentication uses ``DefaultAzureCredential``
        (managed identity on App Service, ``az login`` locally).
        The identity must have **Storage Blob Data Reader** role.

        Archives (``.tar.gz``, ``.tgz``, ``.zip``) are auto-extracted.

        Returns the absolute path to the downloaded log directory.

        Args:
            url: HTTPS URL, Azure Blob URL, or Azure Portal storage URL
            auth_token: Optional bearer token for non-Azure URLs
        """
        try:
            result_dir, count, size_mb = _download_url_to_dir(url, auth_token)
        except _download_error_types() as exc:
            return f"**Error:** Download failed — {type(exc).__name__}: {exc}"

        if size_mb is not None:
            header = (
                f"**Downloaded** {size_mb:.1f} MB → `{result_dir}`\n"
                f"**Files:** {count}\n\n"
            )
        else:
            header = f"**Downloaded** {count} file(s) → `{result_dir}`\n\n"
        return (
            header + "Use this path with:\n"
            f'- `lisa_start_log_investigation(log_path="{result_dir}")`\n'
            f'- `lisa_search_log_files(path="{result_dir}", ...)`\n'
            f'- `lisa_list_log_files(folder_path="{result_dir}")`'
        )

    @mcp.tool()
    def lisa_start_log_investigation(
        log_path: Optional[str] = None,
        log_url: Optional[str] = None,
        auth_token: Optional[str] = None,
        error_message: str = "",
        code_path: Optional[str] = None,
    ) -> str:
        """Bootstrap a root-cause investigation on LISA logs — returns the
        full analysis context so **you** (the caller LLM) can drive the
        same multi-step workflow the LISA AI log analyzer uses.

        This is the recommended entry-point for log analysis.  It gathers
        everything you need in a single call:

        1. Lists all files in the log directory
        2. Searches for the error message across all log files
        3. Searches for common failure patterns (error, warn, fail, panic)
        4. Locates serial console logs (critical for boot/kernel issues)
        5. Loads the expert analysis prompts (workflow, search strategy,
           code review strategy, output format)

        **Supports two input modes:**
        - ``log_path`` — local directory path (for stdio/local mode)
        - ``log_url``  — HTTPS URL to a log file or archive; the server
          downloads and extracts it automatically (for remote SSE mode).
          SAS URLs work — the token is embedded in the URL.

        After receiving the response, continue the investigation by calling:
        - ``lisa_read_log_file`` to read context around each match
        - ``lisa_search_log_files`` for additional targeted searches
        - ``lisa_explain_failure`` to classify specific failure blocks
        - ``lisa_diagnose_bug`` if you identify a failing test name

        Produce your final answer as JSON::

            {
                "summary": "3-4 sentences with verbatim error tokens and evidence",
                "problem": "≤30 words root cause",
                "problem_keywords": ["keyword1", "keyword2"],
                "code_recommendation": ""
            }

        Args:
            log_path: Absolute path to the LISA log directory (local mode)
            log_url: HTTPS URL to a log file or archive (remote mode)
            auth_token: Optional bearer token for URL authentication
            error_message: The error or failure text to investigate
            code_path: Path to LISA source code (auto-detected if omitted)
        """
        # Resolve log directory — either from local path or downloaded URL
        if log_url and not log_path:
            try:
                resolved_path, _count, _size_mb = _download_url_to_dir(
                    log_url, auth_token
                )
            except _download_error_types() as exc:
                return f"**Error:** Download failed — {type(exc).__name__}: {exc}"
        elif log_path:
            confined, err = _resolve_under_log_root(log_path)
            if err:
                return err
            resolved_path = str(confined)
        else:
            return (
                "**Error:** Provide either `log_path` (local directory) "
                "or `log_url` (HTTPS URL to log file/archive)."
            )

        path_obj = Path(resolved_path)
        if not path_obj.is_dir():
            return f"**Error:** Directory not found: {resolved_path}"

        sections: list[str] = []
        sections.append("# LISA Log Investigation Context\n")

        # --- 1. Expert analysis prompts ---
        prompts = _load_ai_prompts()
        if prompts:
            sections.append("## Expert Analysis Methodology\n")
            sections.append(prompts)
        else:
            sections.append(
                "*Expert prompts not available — follow the standard "
                "workflow: search → read context → hypothesize → verify.*\n"
            )

        # --- 2. Log file listing ---
        extensions = [".log", ".txt", ".out", ".xml", ".json"]
        all_files: list[str] = []
        serial_console: list[str] = []

        for root, _, files in os.walk(path_obj):
            for fname in files:
                fpath = os.path.join(root, fname)
                _, ext = os.path.splitext(fpath.lower())
                if ext in extensions:
                    abs_path = os.path.abspath(fpath)
                    all_files.append(abs_path)
                    if "serial_console" in fname.lower():
                        serial_console.append(abs_path)
                if len(all_files) >= 200:
                    break
            if len(all_files) >= 200:
                break

        sections.append(f"\n## Log Files ({len(all_files)} found)\n")
        for fp in all_files:
            sections.append(f"- `{fp}`")

        if serial_console:
            sections.append("\n### Serial Console Logs (prioritize these)\n")
            for fp in serial_console:
                sections.append(f"- `{fp}`")

        # --- 3. Error message search ---
        if error_message:
            sections.append(f"\n## Initial Error Search: `{error_message[:200]}`\n")
            error_matches = _search_in_files(
                error_message, path_obj, extensions, limit=50
            )
            if error_matches:
                for m in error_matches:
                    sections.append(f"- `{m['file']}` L{m['line']}: {m['text']}")
            else:
                sections.append("*No exact matches. Try broader search terms.*")

        # --- 4. Common pattern search ---
        patterns = ["error", "warn", "fail", "panic", "unable", "not found"]
        pattern_results: dict[str, int] = {}
        for pattern in patterns:
            matches = _search_in_files(pattern, path_obj, extensions, limit=20)
            pattern_results[pattern] = len(matches)

        sections.append("\n## Pattern Hit Counts (across all log files)\n")
        sections.append("| Pattern | Matches |")
        sections.append("|---------|---------|")
        for pattern, count in pattern_results.items():
            sections.append(f"| {pattern} | {count} |")

        # --- 5. Code path ---
        repo_root = find_repo_root()
        resolved_code = code_path or (str(repo_root) if repo_root else "")
        if resolved_code:
            sections.append(f"\n## Code Path\n`{resolved_code}`")
            sections.append(
                "Use ``lisa_diagnose_bug`` with a test name to inspect "
                "source code for defects."
            )

        # --- 6. Next steps ---
        sections.append("\n## Next Steps\n")
        sections.append(
            "1. **Read context** around error matches using "
            "``lisa_read_log_file``\n"
            "2. **Search** for specific patterns using "
            "``lisa_search_log_files``\n"
            "3. **Check serial console** if connectivity/boot issue\n"
            "4. **Classify failure** using ``lisa_explain_failure``\n"
            "5. **Inspect code** using ``lisa_diagnose_bug`` if a test name "
            "is identified\n"
            "6. **Produce final JSON** in the format shown above"
        )

        return "\n".join(sections)

    @mcp.tool()
    def lisa_get_log_analysis_prompts() -> str:
        """Return the LISA AI Log Analyzer's expert analysis strategies so
        **you** (the host AI) can perform root-cause analysis on LISA logs.

        Use this together with the file-investigation tools:
        - ``lisa_search_log_files`` — search for patterns across log files
        - ``lisa_read_log_file`` — read a range of lines from a specific file
        - ``lisa_list_log_files`` — discover files in a log directory

        **Recommended workflow:**
        1. Call ``lisa_get_log_analysis_prompts`` to load the expert methodology
        2. Call ``lisa_list_log_files`` to discover the log directory structure
        3. Call ``lisa_search_log_files`` with error patterns across all logs
        4. Call ``lisa_read_log_file`` to examine context around each match
        5. Synthesize findings following the Final Answer format

        The prompts cover:
        - **Overall Analysis Workflow** — 5-step root-cause analysis
        - **Log Search Strategy** — how to search LISA logs, serial
          console logs, and interpret the LISA log format
        - **Code Search Strategy** — how to review source code for defects
        - **Final Answer Synthesis** — structured JSON output format

        Returns:
            The concatenated prompt text from ``lisa/ai/prompts/default/``
        """
        prompts = _load_ai_prompts()
        if not prompts:
            return (
                "**Error:** Could not load AI log analysis prompts.\n\n"
                "Ensure the LISA repo root is accessible and "
                "``lisa/ai/prompts/default/`` exists."
            )

        return (
            "# LISA AI Log Analyzer — Agent Prompts\n\n"
            "These are the expert prompts used by the LISA AI multi-agent "
            "log analyzer. Use these strategies with the ``lisa_search_log_files``"
            ", ``lisa_read_log_file``, and ``lisa_list_log_files`` tools to perform "
            "the same analysis yourself.\n\n" + prompts
        )

    # ------------------------------------------------------------------
    # File-investigation tools
    # ------------------------------------------------------------------

    @mcp.tool()
    def lisa_search_log_files(
        search_string: str,
        path: str,
        file_extensions: str = ".log,.txt,.out",
    ) -> str:
        """Search for a string across log files in a directory tree.

        This replicates the LogSearchAgent's ``search_files`` capability.
        Use it to find error messages, patterns, or keywords in LISA log
        output, serial console logs, and other text files.

        Results include file path, line number, and matched text for each
        hit (up to 200 matches).

        Args:
            search_string: The text to search for (case-insensitive)
            path: Absolute path to the log directory to search in
            file_extensions: Comma-separated extensions to include
                             (default: ``.log,.txt,.out``)
        """
        resolved, err = _resolve_under_log_root(path)
        if err:
            return err
        path_obj = resolved
        if not path_obj.is_dir():
            return f"**Error:** Directory not found: {path}"

        search_lower = search_string.lower()
        extensions = [ext.strip().lower() for ext in file_extensions.split(",")]
        matches: list[dict[str, object]] = []

        for root, _, files in os.walk(path_obj):
            for fname in files:
                fpath = os.path.join(root, fname)
                if os.path.relpath(fpath, resolved).startswith("."):
                    continue
                if not _within_log_root(fpath):
                    continue
                _, ext = os.path.splitext(fpath.lower())
                if ext not in extensions:
                    continue
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        for i, line in enumerate(f, start=1):
                            if search_lower in line.lower():
                                matches.append(
                                    {
                                        "file": os.path.abspath(fpath),
                                        "line": i,
                                        "text": line.strip()[:500],
                                    }
                                )
                                if len(matches) >= _MAX_SEARCH_MATCHES:
                                    break
                except OSError:
                    continue
            if len(matches) >= _MAX_SEARCH_MATCHES:
                break

        if not matches:
            return (
                f"No matches for **{search_string}** in `{path}` "
                f"(extensions: {file_extensions})"
            )

        lines = [
            f"**Found {len(matches)} match(es)** for "
            f"**{search_string}** in `{path}`:\n"
        ]
        for m in matches:
            lines.append(f"- `{m['file']}` L{m['line']}: {m['text']}")

        if len(matches) >= _MAX_SEARCH_MATCHES:
            lines.append(
                f"\n*Results capped at {_MAX_SEARCH_MATCHES}. "
                f"Narrow your search for more targeted results.*"
            )

        return "\n".join(lines)

    @mcp.tool()
    def lisa_read_log_file(
        file_path: str,
        start_line: int = 1,
        line_count: int = 200,
    ) -> str:
        """Read a range of lines from a log file.

        This replicates the LogSearchAgent's ``read_text_file`` capability.
        Use it to examine context around matches found by
        ``lisa_search_log_files`` — the surrounding lines often reveal the
        root cause.

        **Tip:** Read at least 100 lines around an error to capture the
        full command execution sequence and timestamps.

        Args:
            file_path: Absolute path to the file to read
            start_line: Line number to start reading from (1-based, default 1)
            line_count: Number of lines to read (default 200, max 300)
        """
        resolved, err = _resolve_under_log_root(file_path)
        if err:
            return err
        p = resolved
        if not p.is_file():
            return f"**Error:** File not found: {file_path}"

        bounded_count = min(line_count, _MAX_READ_LINES)
        end_line = start_line + bounded_count - 1

        result_lines: list[str] = []
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, start=1):
                    if i < start_line:
                        continue
                    if i > end_line:
                        break
                    result_lines.append(f"({i}): {line.rstrip()}")
        except OSError as exc:
            return f"**Error:** Could not read file: {exc}"

        if not result_lines:
            return (
                f"**Error:** No lines in range {start_line}-{end_line} "
                f"for `{file_path}`"
            )

        text = "\n".join(result_lines)
        if len(text) > _MAX_READ_CHARS:
            text = (
                text[:_MAX_READ_CHARS]
                + f"\n...[truncated {len(text) - _MAX_READ_CHARS} chars]"
            )

        return (
            f"**`{file_path}`** lines {start_line}–"
            f"{start_line + len(result_lines) - 1}:\n```\n{text}\n```"
        )

    @mcp.tool()
    def lisa_list_log_files(
        folder_path: str,
        file_extensions: str = ".log,.txt,.out,.xml,.json",
        recursive: bool = True,
        max_files: int = 200,
    ) -> str:
        """List files in a log directory, optionally filtered by extension.

        This replicates the LogSearchAgent's ``list_files`` capability.
        Use it to discover the log directory structure before searching.

        **Tip:** Start here to understand what logs are available, then
        use ``lisa_search_log_files`` and ``lisa_read_log_file`` to dig in.

        Args:
            folder_path: Absolute path to the log directory
            file_extensions: Comma-separated extensions to include
                             (default: ``.log,.txt,.out,.xml,.json``)
            recursive: Whether to search subdirectories (default True)
            max_files: Maximum number of files to return (default 200)
        """
        resolved, err = _resolve_under_log_root(folder_path)
        if err:
            return err
        p = resolved
        if not p.is_dir():
            return f"**Error:** Directory not found: {folder_path}"

        extensions = [ext.strip().lower() for ext in file_extensions.split(",")]
        found: list[str] = []

        if recursive:
            for root, _, files in os.walk(p):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    if os.path.relpath(fpath, resolved).startswith("."):
                        continue
                    if not _within_log_root(fpath):
                        continue
                    _, ext = os.path.splitext(fpath.lower())
                    if ext in extensions:
                        found.append(os.path.abspath(fpath))
                        if len(found) >= max_files:
                            break
                if len(found) >= max_files:
                    break
        else:
            for item in sorted(p.iterdir()):
                if item.is_file() and _within_log_root(str(item)):
                    _, ext = os.path.splitext(item.name.lower())
                    if ext in extensions:
                        found.append(str(item.resolve()))
                        if len(found) >= max_files:
                            break

        if not found:
            return f"No files matching `{file_extensions}` in `{folder_path}`"

        lines = [
            f"**{len(found)} file(s)** in `{folder_path}` "
            f"(extensions: {file_extensions}):\n"
        ]
        for fp in found:
            lines.append(f"- `{fp}`")

        if len(found) >= max_files:
            lines.append(f"\n*Listing capped at {max_files} files.*")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Debugging / diagnosis tools (spec Section 6.4 — Analysis)
    # ------------------------------------------------------------------

    @mcp.tool()
    def lisa_diagnose_bug(
        test_name: str,
        failure_log: str,
    ) -> str:
        """Given a test name and its failure log, locate the test source code,
        correlate with the failure, and suggest a root cause and fix.

        Uses the LISA troubleshooting documentation and curated error patterns
        from the repo.

        Args:
            test_name: Exact test method name (e.g. "verify_sriov_failover")
            failure_log: The failure output — error message, stack trace, or
                         relevant log lines from the failed run
        """
        repo_root = find_repo_root()
        source_context = ""

        if repo_root:
            source_context = _find_test_source(repo_root, test_name)

        error_patterns = load_context_file("error_patterns.md")
        troubleshoot_docs = load_docs_for_tool("lisa_diagnose_bug")

        sections = []
        sections.append(f"## Diagnosis for `{test_name}`\n")

        if source_context:
            sections.append(f"### Test Source\n{source_context}")
        else:
            sections.append(
                f"*Test `{test_name}` not found in the repository. "
                "Provide the test file path if it's in a custom location.*"
            )

        classification = _classify_failure(failure_log)
        sections.append(f"### Failure Classification\n{classification}")

        matches = _match_known_patterns(failure_log, error_patterns)
        if matches:
            sections.append(f"### Known Pattern Matches\n{matches}")

        guidance = _generate_debug_guidance(failure_log, source_context)
        sections.append(f"### Debugging Steps\n{guidance}")

        if troubleshoot_docs:
            sections.append(
                "### Official Troubleshooting Documentation\n\n"
                + troubleshoot_docs[:2000]
            )

        return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_MAX_LOG_SIZE = 5 * 1024 * 1024  # 5 MB
_MAX_SEARCH_MATCHES = 200
_MAX_READ_LINES = 300
_MAX_READ_CHARS = 30000
# Cap remote downloads to defend against disk exhaustion in hosted SSE mode.
_MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB
_MAX_DOWNLOAD_BLOBS = 20000
# Separate budget for extraction: compression ratios mean a download well
# under the cap above can still fill the disk once unpacked.
_MAX_EXTRACT_BYTES = 4 * 1024 * 1024 * 1024  # 4 GB
_MAX_EXTRACT_FILES = 50000


def _resolve_under_log_root(path: str) -> tuple[Optional[Path], Optional[str]]:
    """Resolve *path* and confirm it lives under ``LISA_LOG_ROOT``.

    Local stdio sessions already run with the user's own privileges, so an
    unset root simply means "no restriction". A remote session is different:
    without a root every log tool becomes an arbitrary file reader, so the
    root is mandatory there.
    """
    log_root = os.environ.get("LISA_LOG_ROOT")
    try:
        resolved = Path(path).resolve()
    except (OSError, RuntimeError) as exc:
        return None, f"**Error:** Could not resolve path `{path}`: {exc}"
    if not log_root:
        if is_remote():
            return None, (
                "**Error:** LISA_LOG_ROOT is not configured. A remote server "
                "must confine log tools to a directory before it will read "
                "from disk. Set LISA_LOG_ROOT=/path/to/logs and restart."
            )
        return resolved, None
    try:
        root = Path(log_root).resolve()
    except (OSError, RuntimeError) as exc:
        return None, f"**Error:** LISA_LOG_ROOT misconfigured: {exc}"
    try:
        resolved.relative_to(root)
    except ValueError:
        return None, (
            f"**Error:** Path `{path}` is outside the configured "
            f"LISA_LOG_ROOT (`{root}`)."
        )
    return resolved, None


def _within_log_root(path: str) -> bool:
    """Whether *path*, with symlinks resolved, sits inside ``LISA_LOG_ROOT``.

    ``os.walk`` reports symlinked files as ordinary files, so a link planted
    inside the root would otherwise read straight through to anywhere on
    disk. Checking only the directory handed to the tool is not enough.
    """
    log_root = os.environ.get("LISA_LOG_ROOT")
    if not log_root:
        return True
    try:
        Path(path).resolve().relative_to(Path(log_root).resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _search_in_files(
    search_string: str,
    root_path: Path,
    extensions: list[str],
    limit: int = 50,
) -> list[dict[str, object]]:
    """Search for a string across files under *root_path*."""
    search_lower = search_string.lower()
    matches: list[dict[str, object]] = []
    for root, _, files in os.walk(root_path):
        for fname in files:
            fpath = os.path.join(root, fname)
            if not _within_log_root(fpath):
                continue
            _, ext = os.path.splitext(fpath.lower())
            if ext not in extensions:
                continue
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, start=1):
                        if search_lower in line.lower():
                            matches.append(
                                {
                                    "file": os.path.abspath(fpath),
                                    "line": i,
                                    "text": line.strip()[:500],
                                }
                            )
                            if len(matches) >= limit:
                                return matches
            except OSError:
                continue
    return matches


def _get_log_text(
    content: Optional[str],
    path: Optional[str],
) -> str:
    if content:
        return content
    if path:
        # Same sandbox as the other file tools — otherwise these two become
        # the easy way around LISA_LOG_ROOT.
        resolved, err = _resolve_under_log_root(path)
        if err:
            return err.replace("**Error:**", "Error:", 1)
        p = resolved
        if p is None or not p.exists():
            return f"Error: File not found — {path}"
        size = p.stat().st_size
        if size > _MAX_LOG_SIZE:
            return (
                f"Error: Log file is {size // (1024 * 1024)} MB, exceeding the "
                "5 MB limit. Provide a trimmed version or the relevant section."
            )
        return p.read_text(encoding="utf-8", errors="replace")
    return "Error: Provide either `log_content` or `log_path`."


def _extract_test_results(text: str) -> list[dict[str, str]]:
    """Extract test result entries from LISA log output.

    One entry per execution: a test repeated by `times` or `retry` appears
    once per attempt.
    """
    # Every pattern names its groups, so the meaning of a capture never
    # depends on the order it happens to appear in. Patterns are anchored at
    # line boundaries with explicit word edges to avoid spurious matches
    # (e.g. the substring "test" inside an identifier like "smoke_test" used
    # to drag pattern 3 into matching the adjacent pipe as a "test name").
    name = r"(?P<name>[A-Za-z_]\w*(?:\.\w+)*)"
    status = r"(?P<status>PASSED|FAILED|SKIPPED|ATTEMPTED)"
    patterns = [
        re.compile(
            rf"^\s*{name}\s*\|\s*{status}\b\s*(?:\|\s*(?P<message>.*))?$",
            re.IGNORECASE | re.MULTILINE,
        ),
        re.compile(
            rf"^\s*\[?{status}\]?\s+(?:test\s+)?{name}"
            r"(?:\s*[:\-]\s*(?P<message>.*))?$",
            re.IGNORECASE | re.MULTILINE,
        ),
        re.compile(
            rf"\b(?:test|case)\s+{name}\b.*?\b{status}\b"
            r"(?:\s*[:\-]\s*(?P<message>.*))?",
            re.IGNORECASE,
        ),
    ]

    # Deduplicate by the stretch of log a match covers, not by test name:
    # the patterns overlap each other, but a runbook's `times`/`retry` makes
    # the same test legitimately appear more than once, and collapsing those
    # would hide a retry that failed after an earlier attempt passed.
    claimed: list[tuple[int, int]] = []
    found: list[tuple[int, dict[str, str]]] = []
    for pattern in patterns:
        for m in pattern.finditer(text):
            start, end = m.span()
            if any(
                start < taken_end and taken_start < end
                for taken_start, taken_end in claimed
            ):
                continue
            claimed.append((start, end))
            found.append(
                (
                    start,
                    {
                        "name": m.group("name"),
                        "status": m.group("status").upper(),
                        "message": (m.group("message") or "").strip(),
                    },
                )
            )

    # Report in log order; the patterns are applied in priority order.
    return [entry for _, entry in sorted(found, key=lambda item: item[0])]


def _extract_errors(text: str) -> list[str]:
    """Extract ERROR-level log lines."""
    errors = []
    for line in text.split("\n"):
        if re.search(r"\bERROR\b", line):
            errors.append(line.strip())
    return errors


def _extract_warnings(text: str) -> list[str]:
    """Extract WARNING-level log lines."""
    warnings = []
    for line in text.split("\n"):
        if re.search(r"\bWARNING\b", line):
            warnings.append(line.strip())
    return warnings


def _extract_kernel_panics(text: str) -> list[str]:
    """Extract kernel panic indicators."""
    panics = []
    panic_patterns = [
        r"Kernel panic.*",
        r"BUG: soft lockup.*",
        r"general protection fault.*",
        r"Call Trace:.*",
        r"RIP:.*",
    ]
    for pattern in panic_patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            panics.append(m.group(0).strip())
    return panics


# ---------------------------------------------------------------------------
# Helpers moved from bug_fixing — used by lisa_diagnose_bug
# ---------------------------------------------------------------------------


def _find_test_source(repo_root: Path, test_name: str) -> str:
    """Find and return the source code for a test method."""
    testsuites_dirs = [
        repo_root / "lisa" / "microsoft" / "testsuites",
        repo_root / "lisa" / "examples" / "testsuites",
    ]

    for testsuites_dir in testsuites_dirs:
        if not testsuites_dir.exists():
            continue
        for py_file in testsuites_dir.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            pattern = rf"def\s+{re.escape(test_name)}\s*\("
            match = re.search(pattern, content)
            if not match:
                continue

            lines = content.split("\n")
            match_line = content[: match.start()].count("\n")
            start = max(0, match_line - 15)
            end = min(len(lines), match_line + 40)

            rel_path = py_file.relative_to(repo_root)
            source_block = "\n".join(lines[start:end])
            return (
                f"**Source: `{rel_path}` (lines {start + 1}\u2013{end})**\n\n"
                f"```python\n{source_block}\n```"
            )

    return ""


def _classify_failure(log: str) -> str:
    """Quick classification of failure type."""
    categories = []
    log_lower = log.lower()

    if any(k in log_lower for k in ["kernel panic", "oops", "call trace", "rip:"]):
        categories.append("Kernel Error")
    if any(k in log_lower for k in ["tcpconnection", "ssh", "connection refused"]):
        categories.append("Connectivity Error")
    if any(k in log_lower for k in ["assertionerror", "assert_that"]):
        categories.append("Assertion Failure")
    if any(k in log_lower for k in ["timeout", "timed out"]):
        categories.append("Timeout")
    if any(k in log_lower for k in ["skippedexception"]):
        categories.append("Skipped (not a real failure)")
    if any(k in log_lower for k in ["provisioning", "deployment failed"]):
        categories.append("Provisioning Error")

    if not categories:
        categories.append("Unclassified — provide more context for better analysis")

    return ", ".join(categories)


def _match_known_patterns(log: str, patterns_md: str) -> str:
    """Search error patterns doc for matches."""
    if "not found" in patterns_md.lower():
        return ""

    matches = []
    current_pattern = ""
    current_fix = ""

    for line in patterns_md.split("\n"):
        if line.startswith("### "):
            if current_pattern and current_pattern.lower() in log.lower():
                matches.append(f"- **{current_pattern}**: {current_fix}")
            current_pattern = line[4:].strip()
            current_fix = ""
        elif line.startswith("Fix:") or line.startswith("Resolution:"):
            current_fix = line.split(":", 1)[1].strip()

    if current_pattern and current_pattern.lower() in log.lower():
        matches.append(f"- **{current_pattern}**: {current_fix}")

    return "\n".join(matches) if matches else "No known error patterns matched."


def _generate_debug_guidance(failure_log: str, source: str) -> str:
    """Provide targeted debugging steps based on failure type."""
    steps = []
    log_lower = failure_log.lower()

    steps.append(
        "1. **Check the full stack trace** — the bottom of the traceback "
        "shows the actual error, frames above show how it got there."
    )

    if "assert" in log_lower:
        steps.append(
            "2. **Compare expected vs actual** — find the `assert_that()` call in "
            "the test source and check what value was actually produced."
        )
        steps.append(
            "3. **Run the underlying command manually** — SSH into the node and "
            "run the same command the test runs to see the raw output."
        )

    if "timeout" in log_lower:
        steps.append(
            "2. **Check node responsiveness** — is the VM still running? "
            "Can you SSH to it manually?"
        )
        steps.append(
            "3. **Increase timeout** — if the operation is legitimate but slow, "
            "increase the test's `timeout` parameter in `@TestCaseMetadata`."
        )

    if "ssh" in log_lower or "tcp" in log_lower:
        steps.append(
            "2. **Check serial console** — the VM may have panicked during boot."
        )
        steps.append("3. **Check NSG rules** — port 22 must be open.")

    if not any(k in log_lower for k in ["assert", "timeout", "ssh", "tcp"]):
        steps.append(
            "2. **Reproduce locally** — run the test with `lisa -r runbook.yml "
            '-v "testcase.name:<test_name>"` to reproduce.'
        )
        steps.append(
            "3. **Enable debug logging** — add `--log-level DEBUG` to the LISA "
            "command to get full command output."
        )

    return "\n".join(steps)


# ---------------------------------------------------------------------------
# Azure Blob + archive helpers
# ---------------------------------------------------------------------------


def _get_azure_imports() -> tuple:
    """Import Azure SDK packages, raising a clear error if missing."""
    try:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient
    except ImportError as exc:
        raise ImportError(
            "Azure Blob download requires azure-identity and "
            "azure-storage-blob packages. Install with:\n"
            "  pip install azure-identity azure-storage-blob"
        ) from exc
    return DefaultAzureCredential, BlobServiceClient


def _parse_portal_storage_url(url: str) -> Optional[dict[str, str]]:
    """Parse an Azure Portal storage URL into account/container/prefix.

    Accepts URLs like::

        https://portal.azure.com/#blade/Microsoft_Azure_Storage/
        ContainerMenuBlade/.../storageAccountId/%2F...%2F
        storageAccounts%2F<account>/path/<container>%2F<prefix>

    Returns ``None`` if the URL is not a portal storage URL.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").rstrip(".").lower()
    if host != "portal.azure.com":
        return None
    if not parsed.fragment:
        return None

    decoded = unquote(parsed.fragment)
    if "/storageAccountId/" not in decoded or "/path/" not in decoded:
        return None

    storage_and_path = decoded.split("/storageAccountId/", 1)[1]
    if "/path/" not in storage_and_path:
        return None
    storage_id_part, path_part = storage_and_path.split("/path/", 1)

    # Extract storage account name from the ARM resource ID
    segments = [s for s in storage_id_part.split("/") if s]
    try:
        sa_idx = segments.index("storageAccounts")
    except ValueError:
        return None
    if len(segments) <= sa_idx + 1:
        return None
    account = segments[sa_idx + 1]

    # Extract container and blob prefix from the path
    path_parts = [p for p in path_part.strip("/").split("/") if p]
    if not path_parts:
        return None
    container = path_parts[0]
    prefix = "/".join(path_parts[1:]) if len(path_parts) > 1 else ""

    return {"account": account, "container": container, "prefix": prefix}


def _download_error_types() -> tuple[type[BaseException], ...]:
    """Exception types a log download may legitimately raise.

    Catching these instead of bare ``Exception`` keeps genuine bugs (a typo
    in this module, say) crashing loudly instead of being reported to the
    caller as a download failure. azure-core is an optional extra, so its
    base error is only included when installed.
    """
    errors: list[type[BaseException]] = [
        ValueError,  # unsupported scheme, blocked host, size limit exceeded
        OSError,  # network and filesystem; URLError/HTTPError subclass this
        ImportError,  # the `azure` extra is not installed
        tarfile.TarError,
        zipfile.BadZipFile,
    ]
    try:
        from azure.core.exceptions import AzureError
    except ImportError:
        pass
    else:
        errors.append(AzureError)
    return tuple(errors)


def _resolve_public_address(hostname: str) -> str:
    """Resolve *hostname*, reject non-public results, return one address.

    Handing the address back is what closes the DNS-rebinding window: the
    caller connects to exactly what was checked instead of doing a second
    lookup that a hostile TTL-0 zone can answer differently.
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host '{hostname}': {exc}") from exc

    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        # `is_global` is the whole special-purpose registry in one predicate:
        # an explicit blocklist missed shared address space (100.64.0.0/10)
        # and the benchmark/TEST-NET ranges.
        if not address.is_global:
            raise ValueError(
                f"Refusing to download from '{hostname}' — it resolves to the "
                f"non-public address {address}. Only internet-reachable log "
                "storage is allowed."
            )
    return infos[0][4][0]


def _reject_internal_host(hostname: str) -> None:
    """Raise when *hostname* resolves to an address we must not fetch from.

    HTTPS proves nothing about the destination: a caller-supplied URL can
    still point at loopback, RFC1918, or the cloud metadata endpoint.
    """
    _resolve_public_address(hostname)


def _check_download_target(url: str) -> ParseResult:
    """Reject a download URL that is not a public HTTPS destination."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"Only HTTPS URLs are supported, got '{parsed.scheme}'")
    if not parsed.hostname:
        raise ValueError("Could not parse hostname from URL")
    _reject_internal_host(parsed.hostname)
    return parsed


def _same_origin(url: str, other: str) -> bool:
    """Whether two HTTPS URLs share scheme, host, and port."""
    a, b = urlparse(url), urlparse(other)
    return (
        a.scheme == b.scheme
        and (a.hostname or "").lower() == (b.hostname or "").lower()
        and (a.port or 443) == (b.port or 443)
    )


class _GuardedRedirectHandler(HTTPRedirectHandler):
    """Re-applies the SSRF check to every redirect target.

    Validating only the URL the caller passed is not enough: a public host
    can answer with a 302 to `http://169.254.169.254/...` and urllib will
    follow it without asking again.
    """

    def redirect_request(  # type: ignore[override]
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Optional[Request]:
        _check_download_target(newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and not _same_origin(req.full_url, newurl):
            # urllib carries Authorization across hosts; browsers and
            # requests strip it, otherwise any public redirect target
            # harvests the caller's bearer token.
            redirected.remove_header("Authorization")
        return redirected


class _PinnedHTTPSConnection(HTTPSConnection):
    """Connects only to an address that passed the SSRF check.

    TLS is untouched — the stdlib still verifies the certificate against
    ``self.host``, so pinning the address cannot be used to strip identity
    checking.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # HTTPConnection assigns this as an instance attribute, so a plain
        # method override on the subclass would be shadowed.
        self._create_connection = self._connect_to_validated_address

    def _connect_to_validated_address(
        self,
        address: tuple[str, int],
        timeout: Any,
        source_address: Any,
    ) -> socket.socket:
        host, port = address
        if self._tunnel_host:
            # An explicitly configured proxy is the egress policy; its own
            # address is often private and proves nothing about the target.
            return socket.create_connection((host, port), timeout, source_address)
        return socket.create_connection(
            (_resolve_public_address(host), port), timeout, source_address
        )


class _PinnedHTTPSHandler(HTTPSHandler):
    """Routes urllib's HTTPS requests through the address-pinning connection."""

    def https_open(self, req: Request) -> Any:
        return self.do_open(_PinnedHTTPSConnection, req, context=self._context)


def _open_download(req: Request) -> Any:
    """Open *req* with redirects and peer addresses held to the host policy."""
    opener = build_opener(_GuardedRedirectHandler(), _PinnedHTTPSHandler())
    return opener.open(req, timeout=120)


_DOWNLOAD_PREFIX = "lisa_logs_"
# Downloads are kept so the other log tools can read them, so something has
# to retire them. Tunable for operators with a bigger or smaller volume.
_DOWNLOAD_RETENTION_DAYS = float(os.environ.get("LISA_LOG_RETENTION_DAYS", "7"))
_MAX_RETAINED_DOWNLOADS = int(os.environ.get("LISA_LOG_MAX_DOWNLOADS", "20"))


def _prune_downloads(root: Path) -> None:
    """Retire old download directories under *root*.

    Nothing else deletes them: `_download_url_to_dir` only cleans up when a
    download fails, and on success the directory is handed to the caller. A
    remote client can otherwise fill the volume 2 GB at a time.
    """
    try:
        existing = [
            entry
            for entry in root.iterdir()
            if entry.is_dir() and entry.name.startswith(_DOWNLOAD_PREFIX)
        ]
    except OSError:
        return

    cutoff = time.time() - _DOWNLOAD_RETENTION_DAYS * 86400
    dated: list[tuple[float, Path]] = []
    for entry in existing:
        try:
            dated.append((entry.stat().st_mtime, entry))
        except OSError:
            continue

    dated.sort(reverse=True)
    # Keep the newest _MAX_RETAINED_DOWNLOADS, and within those drop anything
    # past the retention window.
    stale = [path for _, path in dated[_MAX_RETAINED_DOWNLOADS:]]
    stale += [path for mtime, path in dated[:_MAX_RETAINED_DOWNLOADS] if mtime < cutoff]
    for path in stale:
        shutil.rmtree(path, ignore_errors=True)


def _make_download_dir() -> str:
    """Create a scratch directory for a download.

    Hosted mode confines the log tools to ``LISA_LOG_ROOT``, so downloads
    have to land inside it — a path under the system temp dir would be
    rejected by every follow-up tool this one tells the caller to use.
    """
    log_root = os.environ.get("LISA_LOG_ROOT")
    if not log_root:
        if is_remote():
            # Successful downloads are kept for later investigation, so an
            # unbounded temp fallback lets a remote caller fill the host disk
            # 2 GB at a time — and hands back paths the file tools reject.
            raise ValueError(
                "LISA_LOG_ROOT is not configured. A remote server must be "
                "given a directory to store downloaded logs in before it "
                "will fetch them. Set LISA_LOG_ROOT=/path/to/logs and "
                "restart."
            )
        return tempfile.mkdtemp(prefix=_DOWNLOAD_PREFIX)

    root = Path(log_root)
    try:
        root.mkdir(parents=True, exist_ok=True)
        _prune_downloads(root)
        return tempfile.mkdtemp(prefix=_DOWNLOAD_PREFIX, dir=str(root))
    except OSError as exc:
        raise ValueError(
            f"Cannot create a download directory under LISA_LOG_ROOT "
            f"('{root}'): {exc}. Downloads are retained there so the other "
            "log tools can read them, so the log root must be writable \u2014 do "
            "not mount it read-only."
        ) from exc


def _download_url_to_dir(  # noqa: C901
    url: str,
    auth_token: Optional[str],
) -> tuple[str, int, Optional[float]]:
    """Download *url* to a fresh temp directory and return ``(dir, count, size_mb)``.

    ``size_mb`` is ``None`` for blob-prefix downloads (where individual blob
    sizes aren't summarised). Raises on failure; the caller is responsible
    for surfacing the error message. The temp directory is cleaned up only
    on failure — on success the caller owns it.
    """
    portal_info = _parse_portal_storage_url(url)
    if portal_info:
        download_dir = _make_download_dir()
        try:
            result_dir, count = _download_azure_blob_prefix(
                portal_info["account"],
                portal_info["container"],
                portal_info["prefix"],
                download_dir,
            )
            return result_dir, count, None
        except Exception:
            shutil.rmtree(download_dir, ignore_errors=True)
            raise

    parsed = _check_download_target(url)
    hostname = parsed.hostname or ""

    is_azure_blob = hostname.endswith(".blob.core.windows.net")
    has_sas = "sig=" in (parsed.query or "")

    if is_azure_blob and not auth_token and not has_sas:
        path_parts = [p for p in parsed.path.strip("/").split("/") if p]
        if len(path_parts) >= 2:
            container = path_parts[0]
            prefix = "/".join(path_parts[1:])
            account = hostname.split(".")[0]
            download_dir = _make_download_dir()
            try:
                result_dir, count = _download_azure_blob_prefix(
                    account, container, prefix, download_dir
                )
                return result_dir, count, None
            except Exception:
                shutil.rmtree(download_dir, ignore_errors=True)
                raise

    download_dir = _make_download_dir()
    filename = os.path.basename(parsed.path) or "logs"
    filename = re.sub(r"[^\w.\-]", "_", filename) or "logs"
    download_path = os.path.join(download_dir, filename)

    try:
        headers = {}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        req = Request(url, headers=headers)
        with _open_download(req) as resp:  # noqa: S310
            content_length = resp.headers.get("Content-Length")
            if content_length and int(content_length) > _MAX_DOWNLOAD_BYTES:
                raise ValueError(
                    f"Content-Length {int(content_length):,} exceeds the "
                    f"{_MAX_DOWNLOAD_BYTES:,}-byte download limit"
                )
            downloaded_bytes = 0
            with open(download_path, "wb") as f:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    downloaded_bytes += len(chunk)
                    if downloaded_bytes > _MAX_DOWNLOAD_BYTES:
                        raise ValueError(
                            f"Download exceeded "
                            f"{_MAX_DOWNLOAD_BYTES:,}-byte limit; aborted"
                        )
                    f.write(chunk)
        size_mb = os.path.getsize(download_path) / (1024 * 1024)
        result_dir = _extract_archive(download_path, download_dir)
        file_count = sum(1 for _, _, files in os.walk(result_dir) for _ in files)
        return result_dir, file_count, size_mb
    except Exception:
        shutil.rmtree(download_dir, ignore_errors=True)
        raise


def _allowed_storage_accounts() -> set[str]:
    """Storage accounts this server may authenticate to."""
    raw = os.environ.get("LISA_ALLOWED_STORAGE_ACCOUNTS", "")
    return {name.strip().lower() for name in raw.split(",") if name.strip()}


def _check_storage_account(account: str) -> None:
    """Refuse to send our Azure credential to an unapproved account.

    Both the portal-URL and the direct-blob paths derive the account from
    caller input, and the SDK then sends a bearer token scoped to *all* of
    storage.azure.com. Pointing that at an attacker's account hands them a
    replayable credential, so a remote server needs an explicit allowlist.
    """
    name = account.strip().lower()
    # The name is interpolated into the account URL, so a value like
    # "evil.com/#" would redirect the whole request. Azure allows 3-24
    # lowercase alphanumerics and nothing else.
    if not re.fullmatch(r"[a-z0-9]{3,24}", name):
        raise ValueError(
            f"'{account}' is not a valid Azure storage account name "
            "(3-24 lowercase letters and digits)."
        )
    allowed = _allowed_storage_accounts()
    if allowed:
        if name not in allowed:
            raise ValueError(
                f"Storage account '{account}' is not in "
                "LISA_ALLOWED_STORAGE_ACCOUNTS "
                f"({', '.join(sorted(allowed))}). Refusing to authenticate to "
                "it — the request would send this server's Azure credential "
                "to that account."
            )
        return
    if is_remote():
        raise ValueError(
            "LISA_ALLOWED_STORAGE_ACCOUNTS is not configured. A remote server "
            "will not authenticate to a caller-supplied storage account, "
            "because that sends its Azure credential wherever the caller "
            "points. Set LISA_ALLOWED_STORAGE_ACCOUNTS=acct1,acct2 and "
            "restart, or pass a SAS URL instead."
        )


def _download_azure_blob_prefix(
    account: str,
    container: str,
    prefix: str,
    download_dir: str,
) -> tuple[str, int]:
    """Download all blobs under a prefix to a local directory.

    Uses ``ContainerClient.list_blobs(name_starts_with=...)`` to enumerate
    blobs, then downloads each one preserving the directory structure.

    Returns ``(result_dir, file_count)``.
    """
    # Both callers derive `account` from the caller's URL, so this is the
    # one place that reliably gates every credentialed request.
    _check_storage_account(account)

    DefaultAzureCredential, BlobServiceClient = _get_azure_imports()  # noqa: N806

    account_url = f"https://{account}.blob.core.windows.net"

    # Use a pre-fetched token when the deployment injects one, otherwise fall
    # back to DefaultAzureCredential (managed identity, az login).
    storage_token = os.environ.get("AZURE_STORAGE_TOKEN")
    if storage_token:
        from azure.core.credentials import AccessToken, TokenCredential

        class _StaticTokenCredential(TokenCredential):
            """Wraps a pre-fetched token for the Azure SDK."""

            def get_token(self, *scopes, **kwargs):  # type: ignore[override]
                # Treat the injected token as valid for one hour. Setting
                # expiry to 0 caused some SDK versions to reject it as
                # already-expired.
                return AccessToken(storage_token, int(time.time()) + 3600)

        credential = _StaticTokenCredential()
    else:
        credential = DefaultAzureCredential()

    service_client = BlobServiceClient(account_url=account_url, credential=credential)
    container_client = service_client.get_container_client(container)

    starts_with = prefix
    if starts_with and not starts_with.endswith("/"):
        starts_with = f"{starts_with}/"

    blobs = list(container_client.list_blobs(name_starts_with=starts_with))

    # If no blobs with trailing slash, try the exact prefix (single blob)
    if not blobs and prefix:
        blobs = list(container_client.list_blobs(name_starts_with=prefix))

    if not blobs:
        raise FileNotFoundError(f"No blobs found under '{container}/{prefix}'.")

    # A prefix can address an entire container, so apply the same disk budget
    # the single-file path uses. Sizes come from the listing, so this is
    # checked before anything is written.
    total_bytes = sum(getattr(b, "size", 0) or 0 for b in blobs)
    if total_bytes > _MAX_DOWNLOAD_BYTES:
        raise ValueError(
            f"'{container}/{prefix}' holds {len(blobs)} blobs totalling "
            f"{total_bytes:,} bytes, over the {_MAX_DOWNLOAD_BYTES:,}-byte "
            "download limit. Point at a narrower prefix."
        )
    if len(blobs) > _MAX_DOWNLOAD_BLOBS:
        raise ValueError(
            f"'{container}/{prefix}' holds {len(blobs)} blobs, over the "
            f"{_MAX_DOWNLOAD_BLOBS:,}-file download limit. Point at a "
            "narrower prefix."
        )

    # Use the leaf folder name as the local root
    normalized = prefix.strip("/")
    prefix_with_sep = f"{normalized}/" if normalized else ""
    leaf_name = normalized.rsplit("/", maxsplit=1)[-1] if normalized else container
    result_dir = os.path.join(download_dir, leaf_name)

    downloaded = 0
    for blob in blobs:
        blob_name = blob.name
        relative = blob_name
        if prefix_with_sep and blob_name.startswith(prefix_with_sep):
            relative = blob_name[len(prefix_with_sep) :]
        if not relative:
            continue

        # Path traversal protection
        safe_parts = [p for p in relative.split("/") if p and p != "." and p != ".."]
        if not safe_parts:
            continue

        local_path = os.path.join(result_dir, *safe_parts)
        abs_result = os.path.abspath(result_dir)
        abs_local = os.path.abspath(local_path)
        if os.path.commonpath([abs_result, abs_local]) != abs_result:
            continue

        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            stream = container_client.download_blob(blob_name)
            for chunk in stream.chunks():
                f.write(chunk)
        downloaded += 1

    return result_dir, downloaded


class _Budget:
    """Running cap on uncompressed bytes and file count during extraction."""

    def __init__(self, max_bytes: int, max_files: int) -> None:
        self._max_bytes = max_bytes
        self._max_files = max_files
        self.bytes = 0
        self.files = 0

    def add_file(self) -> None:
        self.files += 1
        if self.files > self._max_files:
            raise ValueError(
                f"Archive expands to more than {self._max_files:,} files; "
                "refusing to extract it."
            )

    def spend(self, count: int) -> None:
        self.bytes += count
        if self.bytes > self._max_bytes:
            raise ValueError(
                f"Archive expands beyond the {self._max_bytes:,}-byte "
                "uncompressed limit; refusing to extract it."
            )


def _copy_within_budget(source: BinaryIO, target: str, budget: _Budget) -> None:
    """Stream *source* to *target*, aborting once the budget is spent.

    The byte count comes from what is actually written, not from the
    archive header, because a compression bomb declares whatever it likes.
    """
    with open(target, "wb") as out:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            budget.spend(len(chunk))
            out.write(chunk)


def _safe_extract_target(abs_extract: str, member_name: str) -> Optional[str]:
    """Absolute destination for *member_name*, or None when it escapes.

    Member names are attacker-controlled and may be absolute, contain
    `..`, or use the other platform's separator — `..\\evil` is a single
    legal filename on POSIX, so it slips past a containment check that
    only normalises native separators.
    """
    target = os.path.abspath(os.path.join(abs_extract, member_name.replace("\\", "/")))
    try:
        if os.path.commonpath([abs_extract, target]) != abs_extract:
            return None
    except ValueError:
        # Raised for different Windows drives, which is as outside as it gets.
        return None
    return target


def _zip_member_is_regular(info: zipfile.ZipInfo) -> bool:
    """Whether a zip entry is a plain file rather than a symlink or device.

    Only an explicitly non-regular type is rejected. Plenty of writers store
    permission bits with no type bits at all (``writestr`` uses ``0o600``,
    DOS-created entries use ``0``), and those are ordinary files.
    """
    file_type = stat.S_IFMT(info.external_attr >> 16)
    return file_type in (0, stat.S_IFREG)


def _make_member_dir(abs_extract: str, path: str, verified: set[str]) -> bool:
    """Create *path* as a directory and confirm it still resolves inside.

    `_safe_extract_target` is purely lexical, so it cannot see a parent that
    is a symlink out of the tree. Resolving each directory once keeps that
    assumption checked rather than assumed.
    """
    if path in verified:
        return True
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        # A malformed archive storing both `a` and `a/b` must not abort the
        # rest of the extraction.
        return False
    real_root = os.path.realpath(abs_extract)
    real_path = os.path.realpath(path)
    if real_path != real_root and not real_path.startswith(real_root + os.sep):
        return False
    verified.add(path)
    return True


def _extract_tar_members(
    download_path: str, abs_extract: str, budget: _Budget, verified: set[str]
) -> None:
    with tarfile.open(download_path) as tf:
        for m in tf:
            # Only plain files and directories. Symlinks, hardlinks, and
            # device nodes can redirect a write outside the extract dir even
            # when their own name looks contained.
            if not (m.isreg() or m.isdir()):
                continue
            target = _safe_extract_target(abs_extract, m.name)
            if target is None:
                continue
            if m.isdir():
                _make_member_dir(abs_extract, target, verified)
                continue
            extracted = tf.extractfile(m)
            if extracted is None:
                continue
            if not _make_member_dir(abs_extract, os.path.dirname(target), verified):
                continue
            budget.add_file()
            with extracted:
                _copy_within_budget(extracted, target, budget)


def _extract_zip_members(
    download_path: str, abs_extract: str, budget: _Budget, verified: set[str]
) -> None:
    with zipfile.ZipFile(download_path) as zf:
        for info in zf.infolist():
            target = _safe_extract_target(abs_extract, info.filename)
            if target is None:
                continue
            if info.is_dir():
                _make_member_dir(abs_extract, target, verified)
                continue
            # Without this, a stored symlink lands as a regular file holding
            # its target path, and collides with any member written through
            # it.
            if not _zip_member_is_regular(info):
                continue
            if not _make_member_dir(abs_extract, os.path.dirname(target), verified):
                continue
            budget.add_file()
            with zf.open(info) as source:
                _copy_within_budget(source, target, budget)


def _extract_archive(download_path: str, download_dir: str) -> str:
    """Extract tar.gz/zip archives, return the result directory path.

    Members are written one at a time against a running budget. `extractall`
    cannot do that: the 2 GB cap on the *download* says nothing about how far
    a highly compressed archive expands on disk.
    """
    if tarfile.is_tarfile(download_path):
        extract_members = _extract_tar_members
    elif zipfile.is_zipfile(download_path):
        extract_members = _extract_zip_members
    else:
        return download_dir

    extract_dir = os.path.join(download_dir, "extracted")
    os.makedirs(extract_dir, exist_ok=True)
    abs_extract = os.path.abspath(extract_dir)
    budget = _Budget(_MAX_EXTRACT_BYTES, _MAX_EXTRACT_FILES)
    try:
        extract_members(download_path, abs_extract, budget, set())
    except ValueError:
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise
    os.remove(download_path)
    return extract_dir
