# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Runbook tools — generate, validate, and fix LISA YAML runbooks."""

from __future__ import annotations

from typing import Optional

from mcp.server.fastmcp import FastMCP

from lisa_mcp.tools._repo import load_docs_for_tool


def register_runbook_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def lisa_generate_runbook(
        platform: str = "azure",
        area: Optional[str] = None,
        priority: Optional[int] = None,
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
            platform: Target platform — "azure", "hyperv", "local", "remote"
            area: Test area filter (e.g. "provisioning", "network")
            priority: Max priority level (0-3) to include
            tags: Comma-separated test tags to filter on
            vm_size: Azure VM size (e.g. "Standard_DS2_v2")
            location: Azure region (e.g. "westus2")
            image: Marketplace image string (e.g. "canonical 0001-com-ubuntu-server-jammy 22_04-lts-gen2 latest")
            concurrency: Number of parallel test environments
            keep_environment: "no", "always", or "failed"
            test_names: Comma-separated test method names to run
        """
        sections = []

        # Header
        sections.append(f"name: generated-runbook")
        sections.append(f"concurrency: {concurrency}")

        # Extension — point to test suites
        sections.append("")
        sections.append("extension:")
        sections.append('  - "../../lisa/microsoft/testsuites"')

        # Platform
        sections.append("")
        sections.append("platform:")
        sections.append(f"  - type: {platform}")
        sections.append(f'    admin_username: "$(admin_username)"')
        sections.append(f'    admin_private_key_file: "$(admin_private_key_file)"')
        sections.append(f"    keep_environment: {keep_environment}")

        if platform == "azure":
            sections.append(f'    azure:')
            sections.append(f'      subscription_id: "$(subscription_id)"')
            if location:
                sections.append(f'      deploy_location: "{location}"')
            if vm_size:
                sections.append(f"      requirement:")
                sections.append(f"        azure:")
                sections.append(f'          vm_size: "{vm_size}"')
            if image:
                parts = image.split()
                if len(parts) == 4:
                    sections.append(f"      marketplace:")
                    sections.append(f'        publisher: "{parts[0]}"')
                    sections.append(f'        offer: "{parts[1]}"')
                    sections.append(f'        sku: "{parts[2]}"')
                    sections.append(f'        version: "{parts[3]}"')

        elif platform == "remote":
            sections.append("    # Configure remote node connection")
            sections.append("    # nodes:")
            sections.append("    #   - type: remote")
            sections.append('    #     address: "$(remote_address)"')
            sections.append("    #     port: 22")

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
        if platform == "azure":
            sections.append("  - name: subscription_id")
            sections.append('    value: ""')
            sections.append("    is_secret: true")

        # Test cases
        sections.append("")
        sections.append("testcase:")
        sections.append("  - criteria:")
        if area:
            sections.append(f"      area: {area}")
        if priority is not None:
            sections.append(f"      priority: [0, {priority}]")
        if tags:
            tag_list = [t.strip() for t in tags.split(",")]
            sections.append(f"      tags: [{', '.join(tag_list)}]")

        if test_names:
            names = [n.strip() for n in test_names.split(",")]
            for name in names:
                sections.append(f"  - criteria:")
                sections.append(f"      name: {name}")

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
            return "**Error:** Runbook must be a YAML mapping (dictionary) at top level."

        # Check platform
        if "platform" not in doc:
            errors.append("Missing `platform` section — LISA needs at least one platform configured.")
        elif isinstance(doc["platform"], list):
            for i, p in enumerate(doc["platform"]):
                if not isinstance(p, dict):
                    errors.append(f"platform[{i}] must be a mapping.")
                    continue
                if "type" not in p:
                    errors.append(f"platform[{i}] missing `type` field.")
                else:
                    known = {"azure", "hyperv", "local", "remote", "mock",
                             "libvirt", "baremetal", "aws", "ready"}
                    if p["type"] not in known:
                        warnings.append(
                            f"platform[{i}].type = '{p['type']}' — "
                            f"not a known built-in type ({', '.join(sorted(known))}). "
                            "This is fine if you have a custom platform extension."
                        )

        # Check testcase
        if "testcase" not in doc and "testcase_raw" not in doc:
            errors.append(
                "Missing `testcase` section — no tests will be selected. "
                "Add at least one testcase criteria block."
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
            result_parts.append("**Warnings:**\n" + "\n".join(f"- {w}" for w in warnings))
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

        fixes = []

        try:
            doc = yaml.safe_load(runbook_content)
        except yaml.YAMLError as e:
            return (
                f"**YAML syntax error — cannot auto-fix:**\n\n```\n{e}\n```\n\n"
                "Fix the YAML syntax first, then re-run this tool."
            )

        if not isinstance(doc, dict):
            return "Runbook must be a YAML mapping at the top level."

        modified = dict(doc)

        # Fix: missing platform
        if "platform" not in modified:
            modified["platform"] = [{"type": "azure"}]
            fixes.append("Added default `platform` section with `type: azure`.")

        # Fix: platform as dict instead of list
        if isinstance(modified.get("platform"), dict):
            modified["platform"] = [modified["platform"]]
            fixes.append("Wrapped `platform` in a list (LISA expects a list of platforms).")

        # Fix: missing notifier
        if "notifier" not in modified:
            modified["notifier"] = [{"type": "console"}, {"type": "html"}]
            fixes.append("Added `notifier` section with console and html output.")

        # Fix: missing testcase
        if "testcase" not in modified and "testcase_raw" not in modified:
            modified["testcase"] = [{"criteria": {}}]
            fixes.append(
                "Added empty `testcase` criteria block. "
                "Specify `area`, `priority`, or `name` to filter tests."
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
        corrected_yaml = yaml.dump(
            modified, default_flow_style=False, sort_keys=False
        )

        if fixes:
            fix_list = "\n".join(f"- {f}" for f in fixes)
            return (
                f"**Fixes applied ({len(fixes)}):**\n{fix_list}\n\n"
                f"**Corrected runbook:**\n\n```yaml\n{corrected_yaml}```"
            )
        else:
            return (
                "No structural issues found. The runbook looks correct.\n\n"
                f"```yaml\n{corrected_yaml}```"
            )
