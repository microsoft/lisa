# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Log analysis tools — parse, explain, and summarize LISA run logs."""

from __future__ import annotations

import os
import re
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from lisa_mcp.tools._repo import find_repo_root, load_context_file, load_docs_for_tool
from mcp.server.fastmcp import FastMCP


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


def register_log_analysis_tools(mcp: FastMCP) -> None:  # noqa: C901
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
        troubleshoot_docs = load_docs_for_tool("explain_failure")
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
        # Auto-convert Azure Portal URLs to blob prefix downloads
        portal_info = _parse_portal_storage_url(url)
        if portal_info:
            download_dir = tempfile.mkdtemp(prefix="lisa_logs_")
            try:
                result_dir, count = _download_azure_blob_prefix(
                    portal_info["account"],
                    portal_info["container"],
                    portal_info["prefix"],
                    download_dir,
                )
                return (
                    f"**Downloaded** {count} file(s) → `{result_dir}`\n\n"
                    f"Use this path with:\n"
                    f'- `lisa_start_log_investigation(log_path="{result_dir}")`\n'
                    f'- `lisa_search_log_files(path="{result_dir}", ...)`\n'
                    f'- `lisa_list_log_files(folder_path="{result_dir}")`'
                )
            except Exception as exc:
                shutil.rmtree(download_dir, ignore_errors=True)
                return f"**Error:** Download failed — {type(exc).__name__}: {exc}"

        parsed = urlparse(url)
        if parsed.scheme not in ("https",):
            return "**Error:** Only HTTPS URLs are supported."
        if not parsed.hostname:
            return "**Error:** Could not parse hostname from URL."

        is_azure_blob = parsed.hostname and parsed.hostname.endswith(
            ".blob.core.windows.net"
        )

        # Azure blob prefix (virtual directory) — list + download all
        if is_azure_blob and not auth_token:
            path_parts = [p for p in parsed.path.strip("/").split("/") if p]
            if len(path_parts) >= 2:
                container = path_parts[0]
                prefix = "/".join(path_parts[1:])
                account = parsed.hostname.split(".")[0]
                download_dir = tempfile.mkdtemp(prefix="lisa_logs_")
                try:
                    result_dir, count = _download_azure_blob_prefix(
                        account,
                        container,
                        prefix,
                        download_dir,
                    )
                    return (
                        f"**Downloaded** {count} file(s) → `{result_dir}`\n\n"
                        f"Use this path with:\n"
                        f"- `lisa_start_log_investigation"
                        f'(log_path="{result_dir}")`\n'
                        f"- `lisa_search_log_files"
                        f'(path="{result_dir}", ...)`\n'
                        f"- `lisa_list_log_files"
                        f'(folder_path="{result_dir}")`'
                    )
                except Exception as exc:
                    shutil.rmtree(download_dir, ignore_errors=True)
                    return (
                        f"**Error:** Download failed — " f"{type(exc).__name__}: {exc}"
                    )

        download_dir = tempfile.mkdtemp(prefix="lisa_logs_")
        filename = os.path.basename(parsed.path) or "logs"
        # Sanitize filename
        filename = re.sub(r"[^\w.\-]", "_", filename)
        if not filename:
            filename = "logs"
        download_path = os.path.join(download_dir, filename)

        try:
            headers = {}
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"
            req = Request(url, headers=headers)
            with urlopen(req, timeout=120) as resp:  # noqa: S310
                with open(download_path, "wb") as f:
                    shutil.copyfileobj(resp, f)

            size_mb = os.path.getsize(download_path) / (1024 * 1024)
            result_dir = _extract_archive(download_path, download_dir)

            file_count = sum(1 for _, _, files in os.walk(result_dir) for _ in files)

            return (
                f"**Downloaded** {size_mb:.1f} MB → `{result_dir}`\n"
                f"**Files:** {file_count}\n\n"
                f"Use this path with:\n"
                f'- `lisa_start_log_investigation(log_path="{result_dir}")`\n'
                f'- `lisa_search_log_files(path="{result_dir}", ...)`\n'
                f'- `lisa_list_log_files(folder_path="{result_dir}")`'
            )
        except Exception as exc:
            shutil.rmtree(download_dir, ignore_errors=True)
            return f"**Error:** Download failed — {type(exc).__name__}: {exc}"

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
            download_result = lisa_download_logs(url=log_url, auth_token=auth_token)
            if download_result.startswith("**Error:"):
                return download_result
            # Extract the path from the download result
            path_match = re.search(r"`(/[^`]+)`", download_result)
            if not path_match:
                return "**Error:** Could not determine downloaded log path."
            resolved_path = path_match.group(1)
        elif log_path:
            resolved_path = log_path
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
        path_obj = Path(path)
        if not path_obj.is_dir():
            return f"**Error:** Directory not found: {path}"

        search_lower = search_string.lower()
        extensions = [ext.strip().lower() for ext in file_extensions.split(",")]
        matches: list[dict[str, object]] = []

        for root, _, files in os.walk(path_obj):
            for fname in files:
                fpath = os.path.join(root, fname)
                if os.path.relpath(fpath, path).startswith("."):
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
        p = Path(file_path)
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
        p = Path(folder_path)
        if not p.is_dir():
            return f"**Error:** Directory not found: {folder_path}"

        extensions = [ext.strip().lower() for ext in file_extensions.split(",")]
        found: list[str] = []

        if recursive:
            for root, _, files in os.walk(p):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    if os.path.relpath(fpath, folder_path).startswith("."):
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
                if item.is_file():
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
        troubleshoot_docs = load_docs_for_tool("diagnose_test")

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
        p = Path(path)
        if not p.exists():
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
    """Extract test result entries from LISA log output."""
    results = []
    patterns = [
        re.compile(
            r"(\w+)\s*\|\s*(PASSED|FAILED|SKIPPED|ATTEMPTED)\s*(?:\|\s*(.*))?",
            re.IGNORECASE,
        ),
        re.compile(
            r"\[?(PASSED|FAILED|SKIPPED|ATTEMPTED)\]?\s+(?:test\s+)?(\w+)"
            r"(?:\s*[:\-]\s*(.*))?",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:test|case)\s+(\S+)\s+.*?(PASSED|FAILED|SKIPPED|ATTEMPTED)"
            r"(?:\s*[:\-]\s*(.*))?",
            re.IGNORECASE,
        ),
    ]

    seen = set()
    for pattern in patterns:
        for m in pattern.finditer(text):
            groups = m.groups()
            if groups[0].upper() in ("PASSED", "FAILED", "SKIPPED", "ATTEMPTED"):
                status, name = groups[0].upper(), groups[1]
                message = groups[2] if len(groups) > 2 else ""
            else:
                name, status = groups[0], groups[1].upper()
                message = groups[2] if len(groups) > 2 else ""

            if name not in seen:
                seen.add(name)
                results.append(
                    {
                        "name": name,
                        "status": status,
                        "message": (message or "").strip(),
                    }
                )

    return results


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
    if not parsed.hostname or not parsed.hostname.endswith("portal.azure.com"):
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
    DefaultAzureCredential, BlobServiceClient = _get_azure_imports()  # noqa: N806

    account_url = f"https://{account}.blob.core.windows.net"

    # Use pre-fetched token (run-local.sh injects this for Docker)
    # or fall back to DefaultAzureCredential (managed identity, az login)
    storage_token = os.environ.get("AZURE_STORAGE_TOKEN")
    if storage_token:
        from azure.core.credentials import AccessToken, TokenCredential

        class _StaticTokenCredential(TokenCredential):
            """Wraps a pre-fetched token for the Azure SDK."""

            def get_token(self, *scopes, **kwargs):  # type: ignore[override]
                return AccessToken(storage_token, 0)

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


def _extract_archive(download_path: str, download_dir: str) -> str:
    """Extract tar.gz/zip archives, return the result directory path."""
    extract_dir = os.path.join(download_dir, "extracted")

    if tarfile.is_tarfile(download_path):
        os.makedirs(extract_dir, exist_ok=True)
        with tarfile.open(download_path) as tf:
            safe_members = [
                m
                for m in tf.getmembers()
                if not m.name.startswith(("/", "..")) and ".." not in m.name
            ]
            tf.extractall(extract_dir, members=safe_members)
        os.remove(download_path)
        return extract_dir

    if zipfile.is_zipfile(download_path):
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(download_path) as zf:
            safe_names = [
                n
                for n in zf.namelist()
                if not n.startswith(("/", "..")) and ".." not in n
            ]
            for name in safe_names:
                zf.extract(name, extract_dir)
        os.remove(download_path)
        return extract_dir

    return download_dir
