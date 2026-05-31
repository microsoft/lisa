# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Test authoring tools — scaffold suites, cases, and write tests."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

from lisa_mcp.tools._repo import find_repo_root, load_test_writer_prompt
from mcp.server.fastmcp import FastMCP


def register_test_writer_tools(mcp: FastMCP) -> None:  # noqa: C901
    @mcp.tool()
    def lisa_get_test_writer_guidelines() -> str:
        """Return the full LISA test writer guidelines prompt. This is the
        authoritative reference for writing LISA test suites and test cases.

        The prompt enforces:
        - Validation-first thinking (no code before design plan)
        - Pattern matching before generation (search existing tools/features)
        - Mandatory Arrange → Act → Assert structure
        - Logging, assertion, and cleanup standards
        - Cost awareness and node hygiene

        Call this tool FIRST before writing any LISA test code. The guidelines
        describe a mandatory three-stage workflow:
        1. Gather — search existing Tools, Features, and similar TestSuites
        2. Research — verify API signatures, never hallucinate
        3. Design Plan — present Arrange → Act → Assert summary for user approval
        """
        prompt = load_test_writer_prompt()
        if prompt.startswith("("):
            return prompt
        return (
            "# LISA Test Writer Guidelines\n\n"
            "**IMPORTANT**: Follow these guidelines for ALL test authoring. "
            "Do NOT write code until the design plan is confirmed.\n\n" + prompt
        )

    @mcp.tool()
    def lisa_scaffold_test_suite(
        area: str,
        class_name: str,
        description: str,
        category: str = "functional",
    ) -> str:
        """Generate a complete LISA test suite skeleton with correct decorators,
        imports, and structure following the lisa_test_writer guidelines.

        IMPORTANT: Before calling this tool, call get_test_writer_guidelines
        first and follow the mandatory workflow (Gather → Research → Design Plan).

        Args:
            area: Test area (e.g. "networking", "storage", "provisioning")
            class_name: PascalCase class name (e.g. "MyNewFeature")
            description: Human-readable description of what this suite tests
            category: Test category — "functional", "stress", or "performance"
        """
        snake_name = _to_snake_case(class_name)

        code = f'''\
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import Posix


@TestSuiteMetadata(
    area="{area}",
    category="{category}",
    description="""
    {description}
    """,
    requirement=simple_requirement(supported_os=[Posix]),
)
class {class_name}(TestSuite):
    @TestCaseMetadata(
        description="""
        TODO: Describe what this test case verifies.
        Include the observable signal that proves the test passed.
        """,
        priority=2,
        requirement=simple_requirement(
            supported_os=[Posix],
        ),
    )
    def verify_{snake_name}(self, node: Node, log: Logger) -> None:
        # --- Arrange ---
        # Acquire tools/features. Use node.tools[ToolName] and node.features[Feature].
        # Verify environment meets preconditions.

        # --- Act ---
        # Perform minimal actions to trigger the behavior under test.

        # --- Assert ---
        # Explicitly verify expected outcomes using assert_that().
        # Each assertion should map to a requirement in metadata.
        pass

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        pass

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        # Guaranteed cleanup. Call node.mark_dirty() if you modified
        # kernel params, drivers, network config, or need a reboot.
        pass
'''
        file_path = f"lisa/microsoft/testsuites/{area}/{snake_name}.py"
        return (
            f"Generated test suite skeleton for `{class_name}` in area `{area}`.\n"
            f"Suggested file path: {file_path}\n\n"
            "**Before filling in test logic**, follow the lisa_test_writer workflow:\n"
            "1. **Gather**: Search `lisa/tools/` and `lisa/features/` for existing "
            "tools and features you need.\n"
            "2. **Research**: Verify API signatures \u2014 "
            "never invent APIs that don't exist.\n"
            "3. **Design Plan**: Present the Arrange → Act → Assert plan and get "
            "user confirmation before writing the implementation.\n\n"
            "Call `lisa_get_test_writer_guidelines` "
            "for the full authoring protocol.\n\n"
            f"```python\n{code}```"
        )

    @mcp.tool()
    def lisa_scaffold_test_case(
        area: str,
        method_name: str,
        description: str,
        priority: int = 2,
        supported_os: str = "Posix",
        supported_features: Optional[str] = None,
        min_core_count: Optional[int] = None,
        min_nic_count: Optional[int] = None,
        min_data_disk_count: Optional[int] = None,
    ) -> str:
        """Generate a single LISA test case method with correct decorators
        and requirement specification, following the lisa_test_writer guidelines.

        IMPORTANT: Before calling this tool, call get_test_writer_guidelines
        first and follow the mandatory workflow (Gather → Research → Design Plan).

        Args:
            area: Test area this case belongs to
            method_name: snake_case method name (e.g. "verify_sriov_failover")
            description: What this test case verifies
            priority: 0=critical, 1=high, 2=normal, 3=stress/long-running
            supported_os: Comma-separated OS types — "Posix", "Windows", or both
            supported_features: Comma-separated feature classes (e.g. "Gpu,Nvme,Sriov")
            min_core_count: Minimum CPU cores required
            min_nic_count: Minimum network interfaces required
            min_data_disk_count: Minimum data disks required
        """
        if not method_name.startswith(("verify_", "test_")):
            method_name = f"verify_{method_name}"

        # Build requirement kwargs
        req_parts = []
        os_list = [o.strip() for o in supported_os.split(",")]
        req_parts.append(f"supported_os=[{', '.join(os_list)}]")

        if supported_features:
            features = [f.strip() for f in supported_features.split(",")]
            req_parts.append(f"supported_features=[{', '.join(features)}]")
        if min_core_count:
            req_parts.append(f"min_core_count={min_core_count}")
        if min_nic_count:
            req_parts.append(f"min_nic_count={min_nic_count}")
        if min_data_disk_count:
            req_parts.append(f"min_data_disk_count={min_data_disk_count}")

        req_str = ",\n            ".join(req_parts)

        # Build feature imports
        feature_imports = ""
        if supported_features:
            features = [f.strip() for f in supported_features.split(",")]
            feature_imports = (
                f"\n# Add to imports:\n"
                f"# from lisa.features import {', '.join(features)}\n"
            )

        code = f'''\
{feature_imports}
    @TestCaseMetadata(
        description="""
        {description}
        """,
        priority={priority},
        requirement=simple_requirement(
            {req_str},
        ),
    )
    def {method_name}(self, node: Node, log: Logger) -> None:
        # --- Arrange ---
        # Acquire tools/features. Use node.tools[ToolName] and node.features[Feature].
        # Verify environment meets preconditions.

        # --- Act ---
        # Perform minimal actions to trigger the behavior under test.

        # --- Assert ---
        # Explicitly verify expected outcomes using assert_that().
        # Each assertion should map to a requirement in metadata.
        pass
'''
        return (
            f"Generated test case `{method_name}` for area `{area}`.\n"
            f"Add this method to your TestSuite class.\n\n"
            "**Before filling in test logic**, follow the lisa_test_writer workflow:\n"
            "1. Search `lisa/tools/` for existing tools you need "
            "(use `lisa_list_tools`).\n"
            "2. Search `lisa/features/` for required features "
            "(use `lisa_list_features`).\n"
            "3. Verify API signatures \u2014 never invent APIs that don't exist.\n"
            "4. Present the Design Plan (Arrange \u2192 Act \u2192 Assert) "
            "for user confirmation.\n\n"
            f"```python\n{code}```"
        )

    @mcp.tool()
    def lisa_list_test_requirements(test_name: str) -> str:
        """Search the LISA repo for a test method and return its requirement
        specification, explaining what platform/node capabilities it needs.

        Args:
            test_name: Exact test method name (e.g. "smoke_test",
                "verify_sriov_failover")
        """
        repo_root = find_repo_root()
        if not repo_root:
            return "Could not locate LISA repository root."

        testsuites_dir = repo_root / "lisa" / "microsoft" / "testsuites"
        if not testsuites_dir.exists():
            testsuites_dir = repo_root / "lisa" / "examples" / "testsuites"

        results = []
        for py_file in testsuites_dir.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            # Look for the method definition
            pattern = rf"def\s+{re.escape(test_name)}\s*\("
            match = re.search(pattern, content)
            if not match:
                continue

            # Extract the @TestCaseMetadata block above it
            lines = content[: match.start()].split("\n")
            decorator_start = len(lines) - 1
            paren_depth = 0
            found_decorator = False
            for i in range(len(lines) - 1, -1, -1):
                line = lines[i]
                paren_depth += line.count(")") - line.count("(")
                if "@TestCaseMetadata" in line:
                    decorator_start = i
                    found_decorator = True
                    break

            if found_decorator:
                method_end = content.find("\n    def ", match.end())
                if method_end == -1:
                    method_end = min(match.end() + 500, len(content))

                decorator_block = "\n".join(lines[decorator_start:])
                method_body = content[match.start() : method_end]

                rel_path = py_file.relative_to(repo_root)
                results.append(
                    f"**Found in `{rel_path}`:**\n\n"
                    f"```python\n{decorator_block}\n{method_body}\n```"
                )

        if not results:
            return (
                f"Test method `{test_name}` not found in the LISA test suites.\n"
                f"Searched in: {testsuites_dir}"
            )

        return f"**Requirements for `{test_name}`:**\n\n" + "\n\n---\n\n".join(results)

    @mcp.tool()
    def lisa_write_test(
        description: str,
        area: str,
        feature: Optional[str] = None,
        tier: Optional[int] = None,
        platform: Optional[str] = None,
        distro_notes: Optional[str] = None,
        class_name: Optional[str] = None,
        method_name: Optional[str] = None,
    ) -> str:
        """Generate a complete, production-quality LISA test case from a
        description of what to validate.

        This is the primary tool for writing LISA tests. It performs the
        three-pillar validation from the lisa_test_writer prompt:
        1. GATHER — searches the repo for relevant tools, features, and
           existing test suites that match the request
        2. RESEARCH — collects API signatures for the discovered tools/features
        3. DESIGN PLAN — produces an Arrange → Act → Assert plan with
           workspace references, ready for user confirmation

        Returns structured metadata alongside the design plan — file path,
        class name, test method name, required features and tools — so
        calling agents can construct a PR without parsing free text.

        Args:
            description: What to validate — the Linux capability or behavior
                being tested (e.g. "Verify VF count stable after VM hot-resize")
            area: The LISA test area (e.g. "network", "storage", "kernel",
                "provisioning", "core")
            feature: LISA feature class name (e.g. "Sriov", "Nvme", "StartStop",
                "Gpu", "Resize", "Hibernate"). Optional.
            tier: Test priority tier 0–4 (0=critical, 1=high, 2=normal,
                3=stress, 4=long-running). Optional.
            platform: Target platform — "azure", "hyperv", "ready", or None
                for platform-agnostic. Optional.
            distro_notes: Any distro-specific failure context or requirements
                (e.g. "Ubuntu 24.04 only", "Fails on RHEL 9 with kernel 6.x").
                Optional.
            class_name: Optional PascalCase suite class name (auto-generated
                if omitted)
            method_name: Optional snake_case test method name (auto-generated
                if omitted)
        """
        # Backward-compatible aliases
        what_to_validate = description
        feature_area = area

        repo_root = find_repo_root()

        # --- Stage 1: GATHER ---
        gather_results = []

        search_query = what_to_validate + " " + feature_area
        if feature:
            search_query += " " + feature

        found_tools = _search_repo_symbols(repo_root, "lisa/tools", search_query)
        found_features = _search_repo_symbols(repo_root, "lisa/features", search_query)
        found_suites = _search_repo_symbols(
            repo_root,
            "lisa/microsoft/testsuites",
            search_query,
        )

        if found_tools:
            gather_results.append(
                "**Relevant Tools found in `lisa/tools/`:**\n"
                + "\n".join(f"- `{t}`" for t in found_tools[:10])
            )
        if found_features:
            gather_results.append(
                "**Relevant Features found in `lisa/features/`:**\n"
                + "\n".join(f"- `{f}`" for f in found_features[:10])
            )
        if found_suites:
            gather_results.append(
                "**Similar TestSuites found in `lisa/microsoft/testsuites/`:**\n"
                + "\n".join(f"- `{s}`" for s in found_suites[:10])
            )

            # Extract existing test methods from matched suites
            if repo_root:
                existing = _extract_existing_tests(repo_root, found_suites)
                query_kws = set(
                    w.lower() for w in re.split(r"\W+", search_query) if len(w) > 2
                )
                # Only flag methods matching specific (non-common) keywords
                specific_kws = query_kws - {
                    "verify",
                    "test",
                    "check",
                    "module",
                    "kernel",
                    "functional",
                    "basic",
                    "config",
                    "storage",
                    "network",
                    "core",
                    "should",
                    "whether",
                }
                flag_kws = specific_kws if specific_kws else query_kws
                for suite_info in existing:
                    methods = suite_info["methods"]
                    rel_path = suite_info["rel_path"]
                    cls = suite_info["class_name"]
                    method_lines = []
                    matching_methods = []
                    for m in methods:
                        desc_part = f" — {m['description']}" if m["description"] else ""
                        method_lower = str(m["name"]).lower()
                        has_match = any(kw in method_lower for kw in flag_kws)
                        prefix = "  - **→**" if has_match else "  -"
                        method_lines.append(
                            f"{prefix} `{m['name']}` (L{m['line']}){desc_part}"
                        )
                        if has_match:
                            matching_methods.append(str(m["name"]))

                    section = (
                        f"\n**Existing tests in `{rel_path}` "
                        f"(class `{cls}`):**\n" + "\n".join(method_lines)
                    )
                    if matching_methods:
                        section += (
                            f"\n\n> **RELATED TEST ALREADY EXISTS: "
                            f"`{'`, `'.join(matching_methods)}` in "
                            f"`{rel_path}`.** You MUST add your new method "
                            f"to class `{cls}` in this file. Do NOT create "
                            "a new file."
                        )
                    else:
                        section += (
                            "\n\n> **IMPORTANT: Add your new test method to "
                            f"this existing class `{cls}` in `{rel_path}` "
                            "instead of creating a new file.** LISA convention "
                            "is one test class per file. Only create a new file "
                            "if the scope is clearly different from this suite."
                        )
                    gather_results.append(section)

        if not gather_results:
            gather_results.append(
                "*No directly matching tools/features/suites found. "
                "You may need to create new Tool or Feature classes.*"
            )

        # --- Stage 2: RESEARCH ---
        api_refs = []
        if repo_root:
            for tool_file in found_tools[:3]:
                snippet = _extract_class_signature(
                    repo_root / "lisa" / "tools" / tool_file
                )
                if snippet:
                    api_refs.append(f"**`{tool_file}`:**\n```python\n{snippet}\n```")

            for feat_file in found_features[:3]:
                snippet = _extract_class_signature(
                    repo_root / "lisa" / "features" / feat_file
                )
                if snippet:
                    api_refs.append(f"**`{feat_file}`:**\n```python\n{snippet}\n```")

        # --- Stage 3: DESIGN PLAN ---
        # If existing suites were found, recommend adding to the best match
        existing_suite_info = None
        if repo_root and found_suites:
            existing = _extract_existing_tests(repo_root, found_suites)
            if existing:
                # Prefer suite with method names matching query keywords.
                # Weight rare/specific keywords higher than common ones
                # (e.g. "cifs" is more distinctive than "module").
                query_kws = [
                    w.lower() for w in re.split(r"\W+", search_query) if len(w) > 2
                ]
                common_words = {
                    "verify",
                    "test",
                    "check",
                    "module",
                    "kernel",
                    "functional",
                    "basic",
                    "config",
                    "storage",
                    "network",
                    "core",
                    "should",
                    "whether",
                }
                best_score = -1
                for suite in existing:
                    score = 0
                    has_specific_match = False
                    for m in suite["methods"]:
                        method_lower = str(m["name"]).lower()
                        for kw in query_kws:
                            if kw in method_lower:
                                if kw in common_words:
                                    score += 5
                                else:
                                    score += 20
                                    has_specific_match = True
                    # Bonus for having a specific (non-common) keyword match
                    if has_specific_match:
                        score += 100
                    if score > best_score:
                        best_score = score
                        existing_suite_info = suite

        if existing_suite_info:
            # Use the existing suite's file and class
            file_path = str(existing_suite_info["rel_path"])
            if not class_name:
                class_name = str(existing_suite_info["class_name"])
        else:
            if not class_name:
                words = re.split(r"[\s_-]+", feature_area)
                class_name = "".join(w.capitalize() for w in words) + "Validation"
            snake_name = _to_snake_case(class_name)
            file_path = f"lisa/microsoft/testsuites/{feature_area}/{snake_name}.py"

        if not method_name:
            clean = re.sub(r"[^a-zA-Z0-9\s]", "", what_to_validate)
            words = clean.lower().split()[:5]
            # Avoid double prefix (e.g. "verify_verify_...")
            if words and words[0] in ("verify", "test"):
                words = words[1:]
            method_name = "verify_" + "_".join(words)

        dirty_keywords = [
            "kernel",
            "grub",
            "driver",
            "reboot",
            "module",
            "modprobe",
            "sysctl",
            "network config",
            "insmod",
            "rmmod",
        ]
        needs_mark_dirty = any(kw in what_to_validate.lower() for kw in dirty_keywords)

        sections = []
        sections.append("# LISA Test Design Plan\n")

        meta_lines = [
            f"**Validation Target:** {what_to_validate}",
            f"**Area:** {feature_area}",
        ]
        if feature:
            meta_lines.append(f"**Feature:** {feature}")
        if tier is not None:
            meta_lines.append(f"**Tier:** {tier}")
        if platform:
            meta_lines.append(f"**Platform:** {platform}")
        if distro_notes:
            meta_lines.append(f"**Distro Notes:** {distro_notes}")
        if existing_suite_info:
            meta_lines.append(
                f"**Target file (EXISTING):** `{file_path}` — "
                f"add method `{method_name}` to class `{class_name}`"
            )
        else:
            meta_lines.append(f"**Suggested file (NEW):** `{file_path}`")
        meta_lines.append(f"**Class:** `{class_name}` | **Method:** `{method_name}`")
        meta_lines.append(
            f"**Required Features:** "
            f"{', '.join(found_features[:5]) if found_features else 'none detected'}"
        )
        meta_lines.append(
            f"**Required Tools:** "
            f"{', '.join(found_tools[:5]) if found_tools else 'none detected'}"
        )
        sections.append("\n".join(meta_lines) + "\n")

        sections.append("## Stage 1: Gathered Context\n")
        sections.extend(gather_results)

        if api_refs:
            sections.append("\n## Stage 2: API References\n")
            sections.extend(api_refs)

        sections.append("\n## Stage 3: Design Plan (Arrange → Act → Assert)\n")
        sections.append(
            f"1. **Arrange**: Acquire required tools/features from the node. "
            f"Verify preconditions.\n"
            f"2. **Act**: {what_to_validate}\n"
            f"3. **Assert**: Verify the observable signal confirms success.\n"
        )

        if needs_mark_dirty:
            sections.append(
                "**Node Hygiene:** `node.mark_dirty()` IS required — this test "
                "modifies system state (kernel params, drivers, or network config).\n"
            )
        else:
            sections.append(
                "**Node Hygiene:** `node.mark_dirty()` is likely NOT required — "
                "this test appears to be read-only.\n"
            )

        sections.append(
            "---\n\n"
            "**Confirm this design plan before proceeding to implementation.**\n"
            "Once confirmed, use `lisa_scaffold_test_suite` or "
            "`lisa_scaffold_test_case` "
            "to generate the code skeleton, then fill in the logic using the "
            "gathered tools and features above."
        )

        sections.append(
            "\n---\n\n"
            "*This plan follows the `lisa_test_writer.prompt.md` workflow. "
            "Call `lisa_get_test_writer_guidelines` for the full authoring protocol.*"
        )

        # --- Structured response metadata (for agent-to-agent consumption) ---
        existing_tests_meta = []
        if repo_root and found_suites:
            for suite_info in _extract_existing_tests(repo_root, found_suites):
                existing_tests_meta.append(
                    {
                        "file": str(suite_info["rel_path"]),
                        "class": suite_info["class_name"],
                        "methods": [m["name"] for m in suite_info["methods"]],
                    }
                )

        metadata = {
            "file_path": file_path,
            "class_name": class_name,
            "method_name": method_name,
            "area": feature_area,
            "feature": feature,
            "tier": tier,
            "platform": platform,
            "required_features": found_features[:5],
            "required_tools": found_tools[:5],
            "existing_suites": existing_tests_meta,
        }
        sections.append(
            "\n---\n\n"
            "## Structured Metadata\n\n"
            f"```json\n{json.dumps(metadata, indent=2)}\n```"
        )

        return "\n\n".join(sections)


def _to_snake_case(name: str) -> str:
    """Convert PascalCase to snake_case."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _extract_existing_tests(
    repo_root: Path,
    suite_files: list[str],
    subdir: str = "lisa/microsoft/testsuites",
) -> list[dict[str, object]]:
    """Extract test method names, descriptions, and locations from suite files.

    Returns a list of dicts with keys: file, rel_path, class_name, methods.
    Each method entry has: name, line, description.
    """
    results: list[dict[str, object]] = []
    search_dir = repo_root / subdir.replace("/", os.sep)

    for suite_name in suite_files[:5]:
        # Find the actual file path (could be in any subdirectory)
        matches = list(search_dir.rglob(suite_name))
        if not matches:
            continue
        py_file = matches[0]

        try:
            content = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        lines = content.split("\n")
        rel_path = str(py_file.relative_to(repo_root))
        current_class = ""
        methods: list[dict[str, object]] = []

        for i, line in enumerate(lines):
            stripped = line.strip()
            # Track current class
            class_match = re.match(r"class\s+(\w+)\s*\(", stripped)
            if class_match:
                current_class = class_match.group(1)

            # Find test methods (verify_* or test_*)
            method_match = re.match(r"def\s+((?:verify|test)_\w+)\s*\(", stripped)
            if method_match:
                method_name = method_match.group(1)
                # Look for description in preceding @TestCaseMetadata
                desc = ""
                for j in range(max(0, i - 10), i):
                    desc_match = re.search(
                        r'description\s*=\s*["\'](.+?)["\']', lines[j]
                    )
                    if desc_match:
                        desc = desc_match.group(1)
                        break
                methods.append(
                    {
                        "name": method_name,
                        "line": i + 1,
                        "description": desc,
                    }
                )

        if methods:
            results.append(
                {
                    "file": suite_name,
                    "rel_path": rel_path,
                    "class_name": current_class,
                    "methods": methods,
                }
            )

    return results


def _search_repo_symbols(
    repo_root: Optional[Path],
    subdir: str,
    query: str,
) -> list[str]:
    """Search a repo subdirectory for Python files matching query keywords."""
    if not repo_root:
        return []

    search_dir = repo_root / subdir.replace("/", os.sep)
    if not search_dir.exists():
        return []

    keywords = [
        w.lower()
        for w in re.split(r"\W+", query)
        if len(w) > 2
        and w.lower()
        not in {
            "the",
            "and",
            "for",
            "test",
            "with",
            "that",
            "are",
            "this",
            "from",
            "have",
            "has",
            "was",
            "were",
        }
    ]

    if not keywords:
        return []

    scored: list[tuple[int, str]] = []
    for py_file in search_dir.rglob("*.py"):
        if py_file.name.startswith("_"):
            continue
        filename_lower = py_file.stem.lower()
        score = 0
        for kw in keywords:
            if kw in filename_lower:
                score += 10
        try:
            content = py_file.read_text(encoding="utf-8", errors="replace")
            content_lower = content.lower()
            for kw in keywords:
                score += min(content_lower.count(kw), 3)
            # Boost score for files with test methods matching keywords
            for match in re.finditer(r"def\s+((?:verify|test)_\w+)\s*\(", content):
                method_lower = match.group(1).lower()
                for kw in keywords:
                    if kw in method_lower:
                        score += 20  # strong signal: method name matches
        except OSError:
            pass
        if score > 0:
            scored.append((score, py_file.name))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [name for _, name in scored]


def _extract_class_signature(py_file: Path) -> str:
    """Extract class name and public method signatures from a Python file."""
    if not py_file.exists():
        return ""
    try:
        content = py_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

    lines = content.split("\n")
    result_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("class ") and "(" in stripped:
            result_lines.append(stripped)
        elif stripped.startswith("def ") and not stripped.startswith("def _"):
            result_lines.append(f"    {stripped}")

        if len(result_lines) > 15:
            break

    return "\n".join(result_lines) if result_lines else ""
