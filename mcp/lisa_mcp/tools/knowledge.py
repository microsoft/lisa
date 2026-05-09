# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Framework knowledge tools — concepts, API reference, examples, error lookup."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from lisa_mcp.tools._repo import (
    find_repo_root,
    load_context_file,
    load_doc_for_topic,
    load_docs_for_tool,
)


def register_knowledge_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def lisa_explain_concept(concept: str) -> str:
        """Explain a LISA framework concept in plain language with usage examples.

        Covers: runbook, environment, node, feature, tool, platform, tier/priority,
        test suite, test case, simple_requirement, notifier, transformer, combinator,
        extension, variable, search_space, and more.

        Uses the official LISA .rst documentation and curated knowledge base.

        Args:
            concept: The LISA concept to explain (e.g. "runbook", "feature",
                     "simple_requirement", "environment matching")
        """
        concept_lower = concept.lower().strip()

        # 1. Check curated context/concepts.md first (structured summaries)
        concepts_md = load_context_file("concepts.md")
        if "not found" not in concepts_md.lower():
            sections = concepts_md.split("\n## ")
            for section in sections:
                header = section.split("\n")[0].lower()
                if concept_lower in header:
                    rst_docs = load_doc_for_topic(concept_lower)
                    result = f"## {section}"
                    if rst_docs:
                        result += (
                            "\n\n---\n\n"
                            "**From official LISA documentation:**\n\n"
                            + rst_docs[:3000]
                        )
                    return result

        # 2. Check built-in inline knowledge
        builtin = _BUILTIN_CONCEPTS.get(concept_lower)
        if not builtin:
            for key, value in _BUILTIN_CONCEPTS.items():
                if concept_lower in key or key in concept_lower:
                    builtin = value
                    break

        # 3. Try the official .rst docs via topic index
        rst_docs = load_doc_for_topic(concept_lower)

        if builtin and rst_docs:
            return (
                builtin
                + "\n\n---\n\n"
                "**From official LISA documentation:**\n\n"
                + rst_docs[:3000]
            )
        if builtin:
            return builtin
        if rst_docs:
            return (
                f"## {concept}\n\n"
                "**From official LISA documentation:**\n\n"
                + rst_docs[:3000]
            )

        return (
            f"Concept `{concept}` not found in the knowledge base. "
            "Try one of: runbook, environment, node, feature, tool, platform, "
            "tier, test suite, test case, simple_requirement, notifier, "
            "transformer, combinator, extension, variable, search_space."
        )

    @mcp.tool()
    def lisa_get_api_reference(symbol: str) -> str:
        """Look up a LISA class, decorator, function, or tool and return its
        signature, docstring, and usage example.

        Args:
            symbol: Python symbol name (e.g. "TestSuiteMetadata",
                    "simple_requirement", "Node", "RemoteNode", "Echo")
        """
        repo_root = find_repo_root()
        if not repo_root:
            return "Could not locate LISA repository."

        search_paths = [
            repo_root / "lisa" / "testsuite.py",
            repo_root / "lisa" / "node.py",
            repo_root / "lisa" / "schema.py",
            repo_root / "lisa" / "feature.py",
            repo_root / "lisa" / "environment.py",
            repo_root / "lisa" / "platform_.py",
            repo_root / "lisa" / "notifier.py",
            repo_root / "lisa" / "runner.py",
            repo_root / "lisa" / "messages.py",
            repo_root / "lisa" / "__init__.py",
        ]

        tools_dir = repo_root / "lisa" / "tools"
        if tools_dir.exists():
            search_paths.extend(tools_dir.glob("*.py"))

        features_dir = repo_root / "lisa" / "features"
        if features_dir.exists():
            search_paths.extend(features_dir.glob("*.py"))

        results = []
        for path in search_paths:
            if not path.exists():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            patterns = [
                rf"^class\s+{re.escape(symbol)}\b",
                rf"^def\s+{re.escape(symbol)}\b",
                rf"^\s+def\s+{re.escape(symbol)}\b",
            ]

            for pat in patterns:
                for m in re.finditer(pat, content, re.MULTILINE):
                    lines = content.split("\n")
                    match_line = content[: m.start()].count("\n")

                    start = match_line
                    while start > 0 and (
                        lines[start - 1].strip().startswith("@")
                        or lines[start - 1].strip().startswith("#")
                        or not lines[start - 1].strip()
                    ):
                        start -= 1

                    indent = len(lines[match_line]) - len(lines[match_line].lstrip())
                    end = match_line + 1
                    while end < len(lines):
                        line = lines[end]
                        if line.strip() and not line[0].isspace():
                            break
                        if (
                            line.strip()
                            and (line.startswith(" " * indent) or line.startswith("\t" * (indent // 4 or 1)))
                            and not line.startswith(" " * (indent + 1))
                            and (line.strip().startswith("class ") or line.strip().startswith("def "))
                            and end > match_line + 1
                        ):
                            break
                        end += 1
                        if end - match_line > 60:
                            break

                    rel_path = path.relative_to(repo_root)
                    snippet = "\n".join(lines[start:end])
                    results.append(
                        f"**`{rel_path}` (line {start+1})**\n\n"
                        f"```python\n{snippet}\n```"
                    )

            if results:
                break

        if results:
            return f"## API Reference: `{symbol}`\n\n" + "\n\n---\n\n".join(results[:3])

        return (
            f"Symbol `{symbol}` not found. Try the full class name (e.g. "
            "`TestSuiteMetadata`, `RemoteNode`, `Echo`) or check spelling."
        )

    @mcp.tool()
    def lisa_find_examples(query: str, max_results: int = 5) -> str:
        """Search existing LISA test suites for examples matching a description.
        Useful for finding patterns to follow when writing new tests.

        Args:
            query: What you're looking for (e.g. "SRIOV test", "disk resize",
                   "network failover", "GPU validation")
            max_results: Maximum number of matching files to return (1-10)
        """
        repo_root = find_repo_root()
        if not repo_root:
            return "Could not locate LISA repository."

        max_results = min(max(1, max_results), 10)

        testsuites_dirs = [
            repo_root / "lisa" / "microsoft" / "testsuites",
            repo_root / "lisa" / "examples" / "testsuites",
        ]

        keywords = [
            w.lower()
            for w in re.split(r"\W+", query)
            if len(w) > 2 and w.lower() not in {"the", "and", "for", "test", "with"}
        ]

        if not keywords:
            return "Provide a more specific query with meaningful keywords."

        scored_files: list[tuple[int, Path, str]] = []

        for testsuites_dir in testsuites_dirs:
            if not testsuites_dir.exists():
                continue
            for py_file in testsuites_dir.rglob("*.py"):
                if py_file.name == "__init__.py":
                    continue
                try:
                    content = py_file.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue

                content_lower = content.lower()
                filename_lower = py_file.stem.lower()

                score = 0
                for kw in keywords:
                    if kw in filename_lower:
                        score += 10
                    if kw in str(py_file.parent.name).lower():
                        score += 8
                    score += min(content_lower.count(kw), 5)

                if score > 0:
                    class_match = re.search(
                        r"class\s+(\w+)\(TestSuite\)", content
                    )
                    area_match = re.search(
                        r'area\s*=\s*"([^"]+)"', content
                    )
                    summary = ""
                    if class_match:
                        summary += f"Class: {class_match.group(1)}"
                    if area_match:
                        summary += f", Area: {area_match.group(1)}"

                    methods = re.findall(
                        r"def\s+((?:verify_|test_)\w+)\s*\(", content
                    )
                    if methods:
                        summary += f"\nMethods: {', '.join(methods[:5])}"

                    scored_files.append((score, py_file, summary))

        scored_files.sort(key=lambda x: x[0], reverse=True)
        top = scored_files[:max_results]

        if not top:
            return (
                f"No test files matching `{query}` found. "
                "Try broader keywords or check the test suite directory structure."
            )

        results = [f"## Examples matching: \"{query}\"\n"]
        for score, path, summary in top:
            rel = path.relative_to(repo_root)
            results.append(f"### `{rel}`\n{summary}\n")

        return "\n".join(results)

    @mcp.tool()
    def lisa_list_tools() -> str:
        """List all available LISA tools (command wrappers) that can be used
        in test cases via `node.tools[ToolName]`.

        Returns the tool name and the underlying command it wraps.
        """
        repo_root = find_repo_root()
        if not repo_root:
            return "Could not locate LISA repository."

        tools_dir = repo_root / "lisa" / "tools"
        if not tools_dir.exists():
            return "LISA tools directory not found."

        tools = []
        for py_file in sorted(tools_dir.glob("*.py")):
            if py_file.name.startswith("_") or py_file.name == "__init__.py":
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            class_match = re.search(r"class\s+(\w+)\([^)]*\):", content)
            cmd_match = re.search(r'command\s*=\s*"([^"]+)"', content)
            if not cmd_match:
                cmd_match = re.search(
                    r"def\s+command\s*\(self\)[^:]*:\s*\n\s*return\s+\"([^\"]+)\"",
                    content,
                )

            if class_match:
                name = class_match.group(1)
                cmd = cmd_match.group(1) if cmd_match else "—"
                tools.append(f"- **{name}** → `{cmd}`")

        if not tools:
            return "No tools found in lisa/tools/."

        return (
            f"## LISA Tools ({len(tools)} available)\n\n"
            "Usage: `node.tools[ToolName].method()`\n\n"
            + "\n".join(tools)
        )

    @mcp.tool()
    def lisa_list_features() -> str:
        """List all available LISA features (platform capabilities) that can
        be used in test cases via `node.features[FeatureName]`.

        Returns the feature name, whether it can be disabled, and its purpose.
        """
        repo_root = find_repo_root()
        if not repo_root:
            return "Could not locate LISA repository."

        features_dir = repo_root / "lisa" / "features"
        if not features_dir.exists():
            return "LISA features directory not found."

        features = []
        for py_file in sorted(features_dir.glob("*.py")):
            if py_file.name.startswith("_") or py_file.name == "__init__.py":
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            for m in re.finditer(
                r"class\s+(\w+)\([^)]*Feature[^)]*\):", content
            ):
                name = m.group(1)
                after = content[m.end() :]
                doc_match = re.match(r'\s*"""([^"]+)"""', after)
                doc = doc_match.group(1).strip() if doc_match else ""
                features.append(f"- **{name}**" + (f" — {doc}" if doc else ""))

        if not features:
            return "No features found in lisa/features/."

        return (
            f"## LISA Features ({len(features)} available)\n\n"
            "Usage: `node.features[FeatureName]`\n"
            "Declare in test: `simple_requirement(supported_features=[FeatureName])`\n\n"
            + "\n".join(features)
        )

    # ------------------------------------------------------------------
    # Error explanation (moved from bug_fixing per spec file layout)
    # ------------------------------------------------------------------

    @mcp.tool()
    def lisa_explain_error(error_text: str) -> str:
        """Look up a LISA error message or exception type and explain what
        triggers it, common causes, and how to resolve it.

        Args:
            error_text: The error message, exception class name, or error code
                        (e.g. "TcpConnectionException", "SkippedException",
                        "OverconstrainedAllocationRequest")
        """
        error_patterns = load_context_file("error_patterns.md")

        explanations = []
        error_lower = error_text.lower()

        known_errors = {
            "tcpconnectionexception": {
                "what": "TCP connection to the target node failed.",
                "causes": [
                    "VM hasn't finished booting yet",
                    "SSH service (sshd) not running on the target",
                    "Network Security Group (NSG) blocking port 22",
                    "VM is in a failed provisioning state",
                    "Network configuration issue (wrong IP/subnet)",
                ],
                "fix": (
                    "1. Check VM status in the platform portal\n"
                    "2. Check serial console for boot errors\n"
                    "3. Verify NSG rules allow SSH (port 22)\n"
                    "4. Increase `wait_resource_timeout` if VM is slow to boot"
                ),
            },
            "skippedexception": {
                "what": "Test was skipped because prerequisites were not met.",
                "causes": [
                    "Target OS doesn't match `supported_os` requirement",
                    "Required feature (GPU, NVMe, etc.) not available",
                    "Target VM size doesn't meet min_core_count, min_nic_count, etc.",
                    "Required tool not available on the target OS",
                ],
                "fix": (
                    "This is normal behavior — the test correctly detected that "
                    "the environment doesn't meet its requirements. To run this "
                    "test, provision a node that matches its `simple_requirement()`."
                ),
            },
            "lisaexception": {
                "what": "General LISA framework exception.",
                "causes": [
                    "Test logic error — an unexpected condition was encountered",
                    "Missing configuration or variable",
                    "Platform-specific operation failed",
                ],
                "fix": (
                    "Read the exception message — LISA exceptions should include "
                    "what happened and how to investigate. If the message is "
                    "unhelpful, that's a bug in the error reporting."
                ),
            },
            "badenvironmentstateexception": {
                "what": "The test environment is in an unexpected state.",
                "causes": [
                    "A previous test left the environment dirty",
                    "VM was rebooted but didn't come back online",
                    "Environment was already cleaned up before test ran",
                ],
                "fix": (
                    "1. Check if the previous test called `node.mark_dirty()`\n"
                    "2. Try running the test with `use_new_environment: True`\n"
                    "3. Check platform logs for environment lifecycle issues"
                ),
            },
            "passedexception": {
                "what": "Test passed with warnings — a soft pass.",
                "causes": [
                    "A non-critical error occurred but the test still achieved "
                    "its primary objective",
                    "A retry succeeded after initial failure",
                ],
                "fix": "Review the warning message. The test passed but something "
                       "unexpected happened that should be investigated.",
            },
            "overconstrainedallocationrequest": {
                "what": "Azure couldn't allocate a VM matching the requirements.",
                "causes": [
                    "Requested VM size not available in the target region",
                    "Region capacity exhaustion",
                    "Conflicting requirements (e.g., specific zone + specific size)",
                ],
                "fix": (
                    "1. Try a different Azure region via `deploy_location`\n"
                    "2. Try a different VM size\n"
                    "3. Remove availability zone constraints\n"
                    "4. Check Azure capacity status for the region"
                ),
            },
            "quotaexceeded": {
                "what": "Azure subscription quota exceeded.",
                "causes": [
                    "Too many VMs already deployed in the subscription",
                    "Regional core quota reached",
                    "VM family-specific quota limit",
                ],
                "fix": (
                    "1. Clean up unused VMs and resources\n"
                    "2. Request a quota increase via Azure portal\n"
                    "3. Use a different subscription or region"
                ),
            },
        }

        for key, info in known_errors.items():
            if key in error_lower:
                explanations.append(
                    f"### {key}\n\n"
                    f"**What:** {info['what']}\n\n"
                    f"**Common Causes:**\n"
                    + "\n".join(f"- {c}" for c in info["causes"])
                    + f"\n\n**How to Fix:**\n{info['fix']}"
                )

        if error_patterns and "not found" not in error_patterns.lower():
            explanations.append(
                f"### Additional Context from Error Pattern Database\n\n"
                f"{_search_error_patterns(error_text, error_patterns)}"
            )

        troubleshoot_docs = load_docs_for_tool("explain_error")
        if troubleshoot_docs:
            explanations.append(
                "### Official Troubleshooting Documentation\n\n"
                + troubleshoot_docs[:2000]
            )

        if not explanations:
            return (
                f"No specific documentation found for `{error_text}`. "
                "Try providing the full exception class name or a longer "
                "snippet of the error message."
            )

        return "\n\n---\n\n".join(explanations)


# ---------------------------------------------------------------------------
# Built-in concept explanations
# ---------------------------------------------------------------------------

_BUILTIN_CONCEPTS = {
    "runbook": (
        "## Runbook\n\n"
        "A **runbook** is a YAML configuration file that controls everything about "
        "a LISA test execution — platform settings, test selection, variables, "
        "notifiers, and environment definitions.\n\n"
        "**Key fields:**\n"
        "- `platform`: List of platform configs (azure, hyperv, local, remote)\n"
        "- `testcase`: List of test selection criteria (area, priority, tags, name)\n"
        "- `variable`: Variables passed to tests and platform config\n"
        "- `extension`: Paths to load test suites and custom code from\n"
        "- `notifier`: Output handlers (console, html, junit)\n"
        "- `environment`: Pre-defined environments with specific nodes\n"
        "- `concurrency`: Number of parallel test environments\n\n"
        "**Usage:**\n```bash\nlisa -r runbook.yml -v key:value\n```\n\n"
        "Runbooks can include other runbooks via `include:` for composition."
    ),
    "environment": (
        "## Environment\n\n"
        "An **environment** is a set of nodes (VMs or physical machines) that LISA "
        "provisions and manages for test execution.\n\n"
        "- Each test case declares its requirements via `simple_requirement()`\n"
        "- LISA matches test requirements against available environments\n"
        "- Environments can be reused across tests or provisioned fresh per test\n"
        "- `use_new_environment=True` forces a fresh environment\n"
        "- `keep_environment` controls cleanup: `no`, `always`, or `failed`\n\n"
        "**Environment matching** compares the test's `NodeSpace` requirements "
        "(CPU, memory, features, OS) against what each platform can provide."
    ),
    "node": (
        "## Node\n\n"
        "A **Node** represents a single machine (VM or physical) in a LISA environment.\n\n"
        "**Types:**\n"
        "- `Node` — base class, can be local or remote\n"
        "- `RemoteNode` — connected via SSH, has connection_info\n"
        "- `LocalNode` — the machine running LISA itself\n\n"
        "**Key APIs:**\n"
        "- `node.tools[ToolName]` — access a tool (e.g., `node.tools[Echo]`)\n"
        "- `node.features[FeatureName]` — access a feature\n"
        "- `node.execute()` — run a shell command\n"
        "- `node.os` — operating system info (distro, version)\n"
        "- `node.mark_dirty()` — flag node for re-provisioning\n"
        "- `node.reboot()` — reboot the node\n"
        "- `node.get_pure_path()` — cross-OS path handling"
    ),
    "feature": (
        "## Feature\n\n"
        "A **Feature** represents a platform-specific capability that a node may "
        "or may not support (GPU, NVMe, SR-IOV, serial console, etc.).\n\n"
        "**Usage in tests:**\n"
        "1. Declare requirement: `simple_requirement(supported_features=[Gpu])`\n"
        "2. Access in test: `gpu = node.features[Gpu]`\n"
        "3. Check support: `node.features.is_supported(Gpu)`\n\n"
        "**Available features:** StartStop, Gpu, Nvme, NetworkInterface, "
        "SerialConsole, Resize, Hibernation, Disk, AvailabilityZone, "
        "Virtualization, and more in `lisa/features/`."
    ),
    "tool": (
        "## Tool\n\n"
        "A **Tool** wraps a system command (echo, mount, grep, etc.) as a Python "
        "class with typed methods.\n\n"
        "**Usage:**\n```python\nresult = node.tools[Echo].run('hello')\n"
        "info = node.tools[Uname].get_linux_information()\n"
        "node.tools[Mount].mount('/dev/sdb1', '/mnt/data')\n```\n\n"
        "~130 tools available in `lisa/tools/`. Prefer tools over raw "
        "`node.execute()` for reliability and cross-distro compatibility."
    ),
    "platform": (
        "## Platform\n\n"
        "A **Platform** provides environment provisioning for a specific "
        "infrastructure: Azure, Hyper-V, libvirt, bare metal, AWS, or local.\n\n"
        "Configured in the runbook's `platform:` section with type-specific fields.\n"
        "Each platform implements node creation, lifecycle, and capability reporting."
    ),
    "simple_requirement": (
        "## simple_requirement()\n\n"
        "Defines what a test case needs from its environment.\n\n"
        "```python\nsimple_requirement(\n"
        "    min_count=1,              # min nodes\n"
        "    min_core_count=2,         # min CPU cores per node\n"
        "    min_memory_mb=2048,       # min RAM per node\n"
        "    min_nic_count=2,          # min NICs\n"
        "    min_data_disk_count=1,    # min data disks\n"
        "    min_gpu_count=1,          # min GPUs\n"
        "    supported_os=[Posix],     # required OS types\n"
        "    unsupported_os=[],        # excluded OS types\n"
        "    supported_features=[Gpu], # required features\n"
        "    supported_platform_type=['azure'],\n"
        "    environment_status=EnvironmentStatus.Deployed,\n"
        "    disk=DiskPremiumSSDLRS(), # disk type requirement\n"
        "    network_interface=Sriov(),# NIC type requirement\n"
        ")\n```\n\n"
        "LISA's search_space module matches these against platform capabilities."
    ),
    "tier": (
        "## Tiers / Priority Levels\n\n"
        "LISA test cases have a `priority` field (0–3) that maps to test tiers:\n\n"
        "- **Priority 0 (T0)**: Critical smoke tests — must pass for any image\n"
        "- **Priority 1 (T1)**: High-priority functional tests\n"
        "- **Priority 2 (T2)**: Normal functional tests (default)\n"
        "- **Priority 3 (T3)**: Stress tests, long-running, niche scenarios\n\n"
        "Filter in runbook: `testcase: [{criteria: {priority: [0, 1]}}]`"
    ),
    "priority": None,  # alias — handled by tier
    "test suite": (
        "## Test Suite\n\n"
        "A **TestSuite** is a Python class decorated with `@TestSuiteMetadata` "
        "containing one or more test case methods.\n\n"
        "**Rules:**\n"
        "- One test class per file\n"
        "- Class inherits from `TestSuite`\n"
        "- PascalCase class name describing the feature\n"
        "- File at `lisa/microsoft/testsuites/<area>/<name>.py`\n"
        "- `before_case()` / `after_case()` for setup/cleanup\n"
        "- `@TestSuiteMetadata` must have `area`, `category`, `description`"
    ),
    "test case": (
        "## Test Case\n\n"
        "A **test case** is a method in a TestSuite class decorated with "
        "`@TestCaseMetadata`.\n\n"
        "**Rules:**\n"
        "- Method name prefixed with `verify_` or `test_`\n"
        "- `@TestCaseMetadata` with `description`, `priority`, `requirement`\n"
        "- Parameters: `self, node: Node, log: Logger` (minimum)\n"
        "- Also available: `environment`, `log_path`, `working_path`, `variables`\n"
        "- Use `assert_that()` from assertpy, not bare `assert`\n"
        "- Use `SkippedException` for unmet preconditions\n"
        "- Follow AAA pattern: Arrange → Act → Assert"
    ),
    "notifier": (
        "## Notifier\n\n"
        "A **Notifier** subscribes to LISA messages and processes results.\n\n"
        "**Built-in notifiers:**\n"
        "- `console` — real-time terminal output\n"
        "- `html` — HTML report generation\n\n"
        "Configured in runbook: `notifier: [{type: console}, {type: html}]`\n"
        "Custom notifiers can subscribe to TestRunMessage, TestResultMessage, etc."
    ),
    "transformer": (
        "## Transformer\n\n"
        "A **Transformer** runs before test execution to modify variables, "
        "download artifacts, or prepare the environment.\n\n"
        "Used for dynamic setup that can't be expressed in static YAML."
    ),
    "combinator": (
        "## Combinator\n\n"
        "A **Combinator** generates multiple variable sets from a matrix, "
        "enabling parameterized test runs across different configurations.\n\n"
        "Example: test across multiple VM sizes × multiple images."
    ),
    "extension": (
        "## Extension\n\n"
        "The `extension:` runbook field lists paths where LISA should search "
        "for test suites, custom platforms, notifiers, and transformers.\n\n"
        "```yaml\nextension:\n  - \"../../lisa/microsoft/testsuites\"\n  - \"./custom_tests\"\n```"
    ),
    "variable": (
        "## Variable\n\n"
        "**Variables** are key-value pairs passed to LISA via runbook `variable:` "
        "section or CLI `-v key:value`.\n\n"
        "- `is_secret: true` masks the value in logs\n"
        "- `is_case_visible: true` makes it available to test methods via `variables` param\n"
        "- Variables can reference files: `file: path/to/vars.yml`\n"
        "- CLI variables override runbook values"
    ),
    "search_space": (
        "## Search Space\n\n"
        "The **search_space** module handles requirement matching — comparing "
        "what a test needs against what a platform can provide.\n\n"
        "Supports ranges (`IntRange(min=2, max=8)`), sets, and complex "
        "capability negotiation for CPU, memory, disk, network, and features."
    ),
}

# Wire up alias
_BUILTIN_CONCEPTS["priority"] = _BUILTIN_CONCEPTS["tier"]


def _search_error_patterns(query: str, patterns_md: str) -> str:
    """Search error patterns document for relevant entries."""
    query_lower = query.lower()
    relevant = []

    for section in patterns_md.split("\n### "):
        if query_lower in section.lower():
            relevant.append(section.strip()[:300])

    if relevant:
        return "\n\n".join(relevant[:3])
    return "No matching patterns in error database."
