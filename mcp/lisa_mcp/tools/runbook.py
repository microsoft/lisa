# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Runbook tools — generate, validate, and fix LISA YAML runbooks."""

from __future__ import annotations

import copy
import json
from typing import Optional

from mcp.server.mcpserver import MCPServer

# Platform types LISA actually registers. `local` and `remote` are node types
# under environment.environments[].nodes[], not platforms — those runbooks use
# the `ready` platform (lisa/microsoft/runbook/local.yml).
_KNOWN_PLATFORMS = {
    "aws",
    "azure",
    "baremetal",
    "cloud-hypervisor",
    "hyperv",
    "mock",
    "qemu",
    "ready",
}
_NODE_TYPE_PLATFORMS = {"local", "remote"}
_KEEP_ENVIRONMENT_VALUES = {"no", "always", "failed"}
# lisa/schema.py validates Criteria.priority with Range(min=0, max=4). A test
# may *declare* any int — suites here use 5 — but a runbook cannot filter on
# anything above 4, so those have to be selected by name, area, or tags.
_MAX_CRITERIA_PRIORITY = 4


def _q(value: object) -> str:
    """Render *value* as a YAML double-quoted scalar.

    JSON string syntax is a valid YAML double-quoted scalar, so this keeps a
    caller-supplied `area` or tag containing `:` or a newline from rewriting
    the surrounding document structure.
    """
    return json.dumps(str(value))


def register_runbook_tools(mcp: MCPServer) -> None:  # noqa: C901
    @mcp.tool()
    def lisa_generate_runbook(
        platform: str = "azure",
        area: Optional[str] = None,
        max_priority: Optional[int] = None,
        tags: Optional[str] = None,
        vm_size: Optional[str] = None,
        location: Optional[str] = None,
        image: Optional[str] = None,
        concurrency: int = 1,
        keep_environment: str = "no",
        test_names: Optional[str] = None,
    ) -> str:
        """Generate a valid LISA YAML runbook from parameters.

        Args:
            platform: Where to run — "azure", "hyperv", "aws", "baremetal",
                "ready", or the node-type shorthands "local" / "remote",
                which emit a `ready` platform with a matching node entry
            area: Test area filter (e.g. "provisioning", "network")
            max_priority: Highest priority level to include; emits the
                inclusive range `priority: [0, max_priority]`. LISA caps
                runbook criteria at 4. Suites declared with priority 5 exist
                but can only be selected by name, area, or tags.
            tags: Comma-separated test tags to filter on
            vm_size: Azure VM size (e.g. "Standard_DS2_v2")
            location: Azure region (e.g. "westus2")
            image: Marketplace image string (e.g. "canonical 0001-com-ubuntu-server-jammy 22_04-lts-gen2 latest")  # noqa: E501
            concurrency: Number of parallel test environments
            keep_environment: "no", "always", or "failed"
            test_names: Comma-separated test method names to run
        """
        sections = []

        # Reject bad enum/numeric input rather than emitting a runbook that
        # only fails once LISA tries to load it.
        if platform not in _KNOWN_PLATFORMS | _NODE_TYPE_PLATFORMS:
            return (
                f"**Error:** Unknown platform `{platform}`. Choose one of "
                f"{', '.join(sorted(_KNOWN_PLATFORMS))}, or the node-type "
                f"shorthands {', '.join(sorted(_NODE_TYPE_PLATFORMS))}."
            )
        if keep_environment not in _KEEP_ENVIRONMENT_VALUES:
            return (
                f"**Error:** `keep_environment` must be one of "
                f"{', '.join(sorted(_KEEP_ENVIRONMENT_VALUES))}, "
                f"got `{keep_environment}`."
            )
        if concurrency < 1:
            return f"**Error:** `concurrency` must be at least 1, got {concurrency}."
        if max_priority is not None and not 0 <= max_priority <= _MAX_CRITERIA_PRIORITY:
            return (
                f"**Error:** `max_priority` must be between 0 and "
                f"{_MAX_CRITERIA_PRIORITY}, got {max_priority}. LISA validates "
                "`testcase[].criteria.priority` with that range, so a higher "
                "value produces a runbook it refuses to load. Suites declared "
                "with priority 5 have to be selected by `name`, `area`, or "
                "`tags` instead."
            )
        if image and len(image.split()) != 4:
            return (
                "**Error:** `image` must be four space-separated fields "
                '(publisher offer sku version), e.g. "canonical '
                'ubuntu-24_04-lts server latest".'
            )

        # "local" and "remote" are node types, not platforms — LISA runs them
        # on the `ready` platform with the nodes declared up front.
        node_type = platform if platform in _NODE_TYPE_PLATFORMS else ""
        platform_type = "ready" if node_type else platform

        if platform_type == "ready" and not node_type:
            # ReadyPlatform._prepare_environment only succeeds when the
            # environment already has nodes, so a bare `ready` runbook cannot
            # run. Which machine to use is the caller's to state.
            return (
                "**Error:** the `ready` platform provisions nothing, so the "
                "runbook has to name the machines it runs on. Ask for "
                "`local` (this machine) or `remote` (a host reached over "
                "SSH) \u2014 both generate a `ready` platform with the matching "
                "`environment.environments[].nodes[]` entry."
            )

        # Header
        sections.append("name: generated-runbook")
        sections.append(f"concurrency: {int(concurrency)}")

        # Load the built-in suites by flag rather than by relative path: an
        # `extension:` entry resolves against wherever the caller saves this
        # file, and the tool does not control that.
        sections.append("import_builtin_tests: true")
        sections.append("")
        sections.append("# For your own suites, add paths relative to this file:")
        sections.append("# extension:")
        sections.append('#   - "path/to/your/testsuites"')

        if node_type:
            sections.append("")
            sections.append("environment:")
            sections.append("  environments:")
            sections.append("    - nodes:")
            sections.append(f"        - type: {node_type}")
            if node_type == "remote":
                sections.append('          address: "$(remote_address)"')
                sections.append("          port: 22")
                sections.append('          username: "$(admin_username)"')
                sections.append(
                    '          private_key_file: "$(admin_private_key_file)"'
                )

        # Platform
        sections.append("")
        sections.append("platform:")
        sections.append(f"  - type: {platform_type}")
        sections.append('    admin_username: "$(admin_username)"')
        sections.append('    admin_private_key_file: "$(admin_private_key_file)"')
        sections.append(f"    keep_environment: {_q(keep_environment)}")

        if platform_type == "azure":
            sections.append("    azure:")
            sections.append('      subscription_id: "$(subscription_id)"')
            sections.append('      resource_group_name: "$(resource_group_name)"')

            # location/vm_size/marketplace are node requirements, not platform
            # settings — see lisa/microsoft/runbook/azure.yml.
            requirement_lines = []
            if location:
                requirement_lines.append(f"        location: {_q(location)}")
            if vm_size:
                requirement_lines.append(f"        vm_size: {_q(vm_size)}")
            if image:
                parts = image.split()
                requirement_lines.append("        marketplace:")
                requirement_lines.append(f"          publisher: {_q(parts[0])}")
                requirement_lines.append(f"          offer: {_q(parts[1])}")
                requirement_lines.append(f"          sku: {_q(parts[2])}")
                requirement_lines.append(f"          version: {_q(parts[3])}")
            if requirement_lines:
                sections.append("    requirement:")
                sections.append("      azure:")
                sections.extend(requirement_lines)

        # Notifier
        sections.append("")
        sections.append("notifier:")
        sections.append("  - type: console")
        sections.append("  - type: html")

        # Variable section
        sections.append("")
        sections.append("variable:")
        sections.append("  - name: admin_username")
        sections.append('    value: ""')
        sections.append("  - name: admin_private_key_file")
        sections.append('    value: ""')
        if node_type == "remote":
            sections.append("  - name: remote_address")
            sections.append('    value: ""')
        if platform_type == "azure":
            sections.append("  - name: subscription_id")
            sections.append('    value: ""')
            sections.append("    is_secret: true")
            sections.append("  - name: resource_group_name")
            sections.append('    value: ""')

        # Test cases
        sections.append("")
        sections.append("testcase:")

        # Build the filters first: a `- criteria:` with nothing under it
        # parses as `criteria: null`, which selects every test in the repo.
        # Emit the block only when there is something to filter on.
        criteria_lines = []
        if area:
            criteria_lines.append(f"      area: {_q(area)}")
        if max_priority is not None:
            criteria_lines.append(f"      priority: [0, {int(max_priority)}]")
        if tags:
            tag_list = [_q(t.strip()) for t in tags.split(",") if t.strip()]
            if tag_list:
                criteria_lines.append(f"      tags: [{', '.join(tag_list)}]")

        if criteria_lines:
            sections.append("  - criteria:")
            sections.extend(criteria_lines)

        if test_names:
            names = [n.strip() for n in test_names.split(",") if n.strip()]
            for name in names:
                sections.append("  - criteria:")
                sections.append(f"      name: {_q(name)}")

        if not criteria_lines and not test_names:
            sections.append("  # No filters were given, so every test would run.")
            sections.append("  # Narrow this down before using the runbook:")
            sections.append("  - criteria:")
            sections.append("      area: <area>   # e.g. provisioning, network")

        runbook_yaml = "\n".join(sections) + "\n"

        return (
            "Generated LISA runbook:\n\n"
            f"```yaml\n{runbook_yaml}```\n\n"
            "**Usage:**\n"
            "```bash\n"
            "lisa -r <runbook_path>.yml "
            '-v "admin_username:<user>" '
            '-v "admin_private_key_file:~/.ssh/id_rsa"\n'
            "```"
        )

    @mcp.tool()
    def lisa_validate_runbook(runbook_content: str) -> str:
        """Validate a LISA runbook YAML for structural correctness.
        Checks required fields, known platform types, and common mistakes.

        Args:
            runbook_content: The YAML content of the runbook to validate
        """
        import yaml

        errors = []
        warnings = []

        try:
            doc = yaml.safe_load(runbook_content)
        except yaml.YAMLError as e:
            return f"**YAML parse error:** {e}"

        if not isinstance(doc, dict):
            return (
                "**Error:** Runbook must be a YAML mapping (dictionary) at top level."
            )

        # Check platform
        if "platform" not in doc:
            errors.append(
                "Missing `platform` section — "
                "LISA needs at least one platform configured."
            )
        elif not isinstance(doc["platform"], list):
            errors.append(
                f"`platform` must be a list of platform mappings, got "
                f"{type(doc['platform']).__name__}. Write it as:\n"
                "  platform:\n"
                "    - type: azure"
            )
        elif not doc["platform"]:
            errors.append(
                "`platform` is an empty list — LISA needs at least one "
                "platform entry with a `type` field."
            )
        else:
            for i, p in enumerate(doc["platform"]):
                if not isinstance(p, dict):
                    errors.append(f"platform[{i}] must be a mapping.")
                    continue
                if "type" not in p:
                    errors.append(f"platform[{i}] missing `type` field.")
                elif p["type"] in _NODE_TYPE_PLATFORMS:
                    errors.append(
                        f"platform[{i}].type = '{p['type']}' is a *node* type, "
                        "not a platform. Use the `ready` platform and declare "
                        "the node under `environment`:\n"
                        "  environment:\n"
                        "    environments:\n"
                        "      - nodes:\n"
                        f"          - type: {p['type']}\n"
                        "  platform:\n"
                        "    - type: ready"
                    )
                elif p["type"] not in _KNOWN_PLATFORMS:
                    warnings.append(
                        f"platform[{i}].type = '{p['type']}' — "
                        f"not a known built-in type "
                        f"({', '.join(sorted(_KNOWN_PLATFORMS))}). "
                        "This is fine if you have a custom platform extension."
                    )

        # Check testcase
        if "testcase" not in doc and "testcase_raw" not in doc:
            errors.append(
                "Missing `testcase` section — no tests will be selected. "
                "Add at least one testcase criteria block."
            )
        elif "testcase" in doc and not isinstance(doc["testcase"], list):
            errors.append(
                f"`testcase` must be a list of selection blocks, got "
                f"{type(doc['testcase']).__name__}. Write it as:\n"
                "  testcase:\n"
                "    - criteria:\n"
                "        area: provisioning"
            )
        elif isinstance(doc.get("testcase"), list):
            for i, entry in enumerate(doc["testcase"]):
                if not isinstance(entry, dict):
                    errors.append(
                        f"testcase[{i}] must be a mapping, got "
                        f"{type(entry).__name__} ({entry!r}). A bare test name "
                        "selects nothing; write it as:\n"
                        "  testcase:\n"
                        "    - criteria:\n"
                        "        name: smoke_test"
                    )
                    continue
                criteria = entry.get("criteria")
                # LISA runs all([]) over the predicates built from criteria,
                # so an absent or empty block matches every test.
                if not criteria:
                    warnings.append(
                        f"testcase[{i}] has no criteria — this selects *every* "
                        "test in the repo and provisions an environment for "
                        "each. Add `area`, `name`, `priority`, or `tags` "
                        "unless you really mean to run everything."
                    )
                    continue
                if not isinstance(criteria, dict):
                    errors.append(
                        f"testcase[{i}].criteria must be a mapping, got "
                        f"{type(criteria).__name__}."
                    )
                    continue
                priority = criteria.get("priority")
                levels = priority if isinstance(priority, list) else [priority]
                for level in levels:
                    if (
                        isinstance(level, int)
                        and not isinstance(level, bool)
                        and not 0 <= level <= _MAX_CRITERIA_PRIORITY
                    ):
                        errors.append(
                            f"testcase[{i}].criteria.priority contains {level}; "
                            f"LISA validates this field with the range 0–"
                            f"{_MAX_CRITERIA_PRIORITY} and will refuse to load "
                            "the runbook. Select higher-priority suites by "
                            "`name`, `area`, or `tags`."
                        )

        # Check extension
        if "extension" not in doc:
            warnings.append(
                "No `extension` section — LISA won't load test suites unless "
                "they're on the Python path. Usually you need:\n"
                "  extension:\n"
                '    - "path/to/testsuites"'
            )

        # Check notifier
        if "notifier" not in doc:
            warnings.append(
                "No `notifier` section — consider adding console and html notifiers "
                "for visibility."
            )

        # Check variables with secrets
        if "variable" in doc and isinstance(doc["variable"], list):
            for v in doc["variable"]:
                if isinstance(v, dict):
                    if v.get("is_secret") and v.get("value"):
                        val = str(v.get("value", ""))
                        if val and val not in ("", '""', "''"):
                            errors.append(
                                f"Variable `{v.get('name', '?')}` is marked is_secret "
                                "but has a hardcoded value. Use CLI `-v` overrides or "
                                "environment variables for secrets."
                            )

        # Build result
        result_parts = []
        if errors:
            result_parts.append("**Errors:**\n" + "\n".join(f"- {e}" for e in errors))
        if warnings:
            result_parts.append(
                "**Warnings:**\n" + "\n".join(f"- {w}" for w in warnings)
            )
        if not errors and not warnings:
            result_parts.append("Runbook structure looks valid. No issues found.")

        return "\n\n".join(result_parts)

    @mcp.tool()
    def lisa_fix_runbook(runbook_content: str) -> str:
        """Validate a LISA runbook YAML, fix common issues, and return the
        corrected version with explanations of what was changed.

        Args:
            runbook_content: The YAML content of the runbook to fix
        """
        import yaml

        fixes: list[str] = []
        unfixable: list[str] = []

        try:
            doc = yaml.safe_load(runbook_content)
        except yaml.YAMLError as e:
            return (
                f"**YAML syntax error — cannot auto-fix:**\n\n```\n{e}\n```\n\n"
                "Fix the YAML syntax first, then re-run this tool."
            )

        if not isinstance(doc, dict):
            return "Runbook must be a YAML mapping at the top level."

        modified = copy.deepcopy(doc)

        # Deliberately not auto-adding a missing `platform`: defaulting to
        # azure would turn an incomplete runbook into one that provisions
        # billable cloud resources without the author ever asking for it.
        if "platform" not in modified:
            unfixable.append(
                "Missing `platform` — not auto-filled, because guessing a "
                "cloud platform here could provision billable resources. "
                "Add the platform you actually intend to run on, e.g.:\n"
                "  platform:\n"
                "    - type: azure     # or hyperv, aws, baremetal, ready\n"
                "To run on a machine you already have, use the `ready` "
                "platform and declare the node instead:\n"
                "  environment:\n"
                "    environments:\n"
                "      - nodes:\n"
                "          - type: local   # or remote\n"
                "  platform:\n"
                "    - type: ready"
            )

        # Fix: platform as dict instead of list
        if isinstance(modified.get("platform"), dict):
            modified["platform"] = [modified["platform"]]
            fixes.append(
                "Wrapped `platform` in a list (LISA expects a list of platforms)."
            )

        # Fix: missing notifier
        if "notifier" not in modified:
            modified["notifier"] = [{"type": "console"}, {"type": "html"}]
            fixes.append("Added `notifier` section with console and html output.")

        # Deliberately not auto-adding `testcase` either: an empty criteria
        # mapping contributes no predicates, and _match_cases does all([])
        # over them — every test in the repo matches and runs.
        if "testcase" not in modified and "testcase_raw" not in modified:
            unfixable.append(
                "Missing `testcase` — not auto-filled, because an empty "
                "criteria block selects *every* test in the repo and would "
                "provision an environment for each. Add the selection you "
                "actually want, e.g.:\n"
                "  testcase:\n"
                "    - criteria:\n"
                "        area: provisioning   # or name / priority / tags"
            )

        # Fix: testcase as dict instead of list
        if isinstance(modified.get("testcase"), dict):
            modified["testcase"] = [modified["testcase"]]
            fixes.append("Wrapped `testcase` in a list.")

        # Fix: keep_environment as bool True (should be string)
        if isinstance(modified.get("platform"), list):
            for i, p in enumerate(modified["platform"]):
                if isinstance(p, dict):
                    ke = p.get("keep_environment")
                    if ke is True:
                        p["keep_environment"] = "always"
                        fixes.append(
                            f"platform[{i}]: Changed `keep_environment: true` to "
                            '`keep_environment: "always"`.'
                        )
                    elif ke is False:
                        p["keep_environment"] = "no"
                        fixes.append(
                            f"platform[{i}]: Changed `keep_environment: false` to "
                            '`keep_environment: "no"`.'
                        )

        # Dump corrected YAML
        corrected_yaml = yaml.dump(modified, default_flow_style=False, sort_keys=False)

        sections = []
        if fixes:
            fix_list = "\n".join(f"- {f}" for f in fixes)
            sections.append(f"**Fixes applied ({len(fixes)}):**\n{fix_list}")
        if unfixable:
            todo_list = "\n".join(f"- {u}" for u in unfixable)
            sections.append(f"**Needs your input ({len(unfixable)}):**\n{todo_list}")
        if not sections:
            sections.append("No structural issues found. The runbook looks correct.")

        sections.append(f"**Runbook:**\n\n```yaml\n{corrected_yaml}```")
        return "\n\n".join(sections)
