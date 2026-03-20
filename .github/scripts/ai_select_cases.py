# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
AI-powered test case selector for LISA PRs.

This script:
1. Reads the PR diff (changed files + patch) from environment variables
   set by the GitHub Actions workflow.
2. Enumerates all LISA test cases under microsoft/testsuites.
3. Calls the GitHub Models API (GPT-4o) to decide which test cases
   are relevant to the code changes.
4. Outputs a LISA runbook YAML fragment with the selected test cases.
"""

import ast
import json
import os
import re
import sys
from pathlib import Path
from typing import Callable, Dict, List, Set, Tuple
from urllib.error import HTTPError

FRAMEWORK_CHANGE_PATTERNS = (
    re.compile(r"^lisa/advanced_tools/.+\.py$"),
    re.compile(r"^lisa/base_tools/.+\.py$"),
    re.compile(r"^lisa/features/.+\.py$"),
    re.compile(r"^lisa/parameter_parser/.+\.py$"),
    re.compile(r"^lisa/runners/.+\.py$"),
    re.compile(r"^lisa/sut_orchestrator/.+\.py$"),
    re.compile(r"^lisa/tools/.+\.py$"),
    re.compile(r"^lisa/util/.+\.py$"),
    re.compile(r"^lisa/[^/]+\.py$"),
)
TESTSUITE_CHANGE_PATTERNS = (re.compile(r"^lisa/microsoft/testsuites/.+\.py$"),)
RELEVANT_CHANGE_PATTERNS = [
    *FRAMEWORK_CHANGE_PATTERNS,
    *TESTSUITE_CHANGE_PATTERNS,
]
DEFAULT_MARKETPLACE_IMAGE = (
    "canonical 0001-com-ubuntu-server-jammy 22_04-lts-gen2 latest"
)
MAX_PROMPT_DIFF_CHARS = 4000
MAX_PROMPT_CANDIDATE_CASES = 120
MAX_PROMPT_FALLBACK_CASES = 60
MAX_SUMMARY_FEATURES = 4
MAX_SUMMARY_TOOLS = 5
LOGIC_TOKEN_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "any",
        "arg",
        "args",
        "azure",
        "capability",
        "capabilities",
        "class",
        "cls",
        "count",
        "create",
        "default",
        "def",
        "disk",
        "feature",
        "features",
        "for",
        "from",
        "get",
        "if",
        "in",
        "int",
        "kwargs",
        "none",
        "node",
        "optional",
        "or",
        "raw",
        "raw_capabilities",
        "resource",
        "return",
        "schema",
        "self",
        "setting",
        "settings",
        "size",
        "the",
        "to",
        "true",
        "type",
        "vm",
    }
)

MARKETPLACE_IMAGES: Dict[str, Dict[str, str]] = {
    "ubuntu": {
        "default": "canonical 0001-com-ubuntu-server-jammy 22_04-lts-gen2 latest",
        "arm64": "canonical 0001-com-ubuntu-server-jammy 22_04-lts-arm64 latest",
        "gen1": "canonical ubuntu-24_04-lts server-gen1 latest",
        "gen2": "canonical 0001-com-ubuntu-server-jammy 22_04-lts-gen2 latest",
    },
    "debian": {
        "default": "debian debian-12 12 latest",
        "arm64": "debian debian-12 12-arm64 latest",
        "gen2": "debian debian-12 12-gen2 latest",
    },
    "azurelinux": {
        "default": "microsoftcblmariner azure-linux-3 azure-linux-3 latest",
        "arm64": "microsoftcblmariner azure-linux-3 azure-linux-3-arm64 latest",
        "gen2": "microsoftcblmariner azure-linux-3 azure-linux-3-gen2 latest",
    },
    "oracle": {
        "default": "oracle oracle-linux ol94-lvm-gen2 latest",
        "arm64": "oracle oracle-linux ol94-arm64-lvm-gen2 latest",
        "gen2": "oracle oracle-linux ol94-lvm-gen2 latest",
    },
    "rhel": {
        "default": "redhat rhel 9_5 latest",
        "arm64": "redhat rhel-arm64 9_5-arm64 latest",
        "gen2": "redhat rhel 95_gen2 latest",
    },
    "suse": {
        "default": "suse sles-15-sp6 gen2 latest",
        "arm64": "suse sles-15-sp6-arm64 gen2 latest",
        "gen1": "suse sles-15-sp6 gen1 latest",
        "gen2": "suse sles-15-sp6 gen2 latest",
    },
}


def has_relevant_code_changes(changed_files: str) -> bool:
    """Return True if changed files include framework or testsuite Python code."""
    for changed_file in changed_files.splitlines():
        normalized = changed_file.strip()
        if not normalized:
            continue
        if any(pattern.match(normalized) for pattern in RELEVANT_CHANGE_PATTERNS):
            return True
    return False


def get_change_scope(changed_files: str) -> Tuple[bool, bool]:
    """Return whether framework code or testsuite code changed."""
    has_framework_changes = False
    has_testsuite_changes = False

    for changed_file in changed_files.splitlines():
        normalized = changed_file.strip()
        if not normalized:
            continue
        if any(pattern.match(normalized) for pattern in FRAMEWORK_CHANGE_PATTERNS):
            has_framework_changes = True
        if any(pattern.match(normalized) for pattern in TESTSUITE_CHANGE_PATTERNS):
            has_testsuite_changes = True

    return has_framework_changes, has_testsuite_changes


def find_repo_root() -> Path:
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent.parent


def _split_top_level_items(raw_text: str) -> List[str]:
    items: List[str] = []
    current: List[str] = []
    depth = 0

    for char in raw_text:
        if char == "," and depth == 0:
            item = "".join(current).strip()
            if item:
                items.append(item)
            current = []
            continue

        current.append(char)
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)

    trailing = "".join(current).strip()
    if trailing:
        items.append(trailing)

    return items


def _normalize_feature_name(name: str) -> str:
    return name.removesuffix("Settings")


def _identity_name(name: str) -> str:
    return name


def _normalize_repo_path(path: str) -> str:
    return path.strip().replace("\\", "/")


def _extract_changed_new_lines(diff: str) -> Dict[str, Set[int]]:
    changed_lines_by_file: Dict[str, Set[int]] = {}
    current_path = ""
    current_line = 0
    in_hunk = False

    for line in diff.splitlines():
        if line.startswith("+++ "):
            current_path = line[4:].strip()
            if current_path.startswith("b/"):
                current_path = current_path[2:]
            if current_path == "/dev/null":
                current_path = ""
            current_path = _normalize_repo_path(current_path)
            in_hunk = False
            continue

        if line.startswith("@@ "):
            match = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if not match or not current_path:
                in_hunk = False
                continue
            current_line = int(match.group(1))
            in_hunk = True
            continue

        if not in_hunk or not current_path:
            continue

        if line.startswith("+") and not line.startswith("+++"):
            changed_lines_by_file.setdefault(current_path, set()).add(current_line)
            current_line += 1
            continue

        if line.startswith("-") and not line.startswith("---"):
            continue

        if not line.startswith("\\"):
            current_line += 1

    return changed_lines_by_file


def _extract_changed_named_classes(
    repo_root: Path,
    changed_files: str,
    diff: str,
    known_names: Set[str],
    file_pattern: str,
    normalizer: Callable[[str], str],
) -> Tuple[str, ...]:
    changed_lines_by_file = _extract_changed_new_lines(diff)
    matched_names: Set[str] = set()

    for raw_path in changed_files.splitlines():
        changed_path = _normalize_repo_path(raw_path)
        if not changed_path or not re.search(file_pattern, changed_path):
            continue

        file_path = repo_root / Path(changed_path)
        if not file_path.exists():
            continue

        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue

        changed_lines = changed_lines_by_file.get(changed_path, set())
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            normalized_name = normalizer(node.name)
            if normalized_name not in known_names:
                continue
            end_lineno = getattr(node, "end_lineno", node.lineno)
            if any(node.lineno <= line_no <= end_lineno for line_no in changed_lines):
                matched_names.add(normalized_name)

    return tuple(sorted(matched_names))


def _extract_class_name_from_subscript(node: ast.Subscript) -> str:
    slice_node = node.slice
    if isinstance(slice_node, ast.Name):
        return slice_node.id
    if isinstance(slice_node, ast.Attribute):
        return slice_node.attr
    return ""


def _is_tools_attribute(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "tools"


def _decorator_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _extract_tool_imports(tree: ast.AST) -> Dict[str, str]:
    tool_aliases: Dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if ".tools" not in node.module and not node.module.endswith("tools"):
                continue
            for alias in node.names:
                local_name = alias.asname or alias.name
                tool_aliases[local_name] = alias.name

    return tool_aliases


def _collect_function_details(
    function_node: ast.AST,
    tool_aliases: Dict[str, str],
) -> Tuple[Set[str], Set[str], Set[str]]:
    tools_used: Set[str] = set()
    self_calls: Set[str] = set()
    plain_calls: Set[str] = set()

    for node in ast.walk(function_node):
        if isinstance(node, ast.Subscript) and _is_tools_attribute(node.value):
            tool_name = _extract_class_name_from_subscript(node)
            if tool_name:
                tools_used.add(tool_aliases.get(tool_name, tool_name))

        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                plain_calls.add(node.func.id)
            elif (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
            ):
                self_calls.add(node.func.attr)

    return tools_used, self_calls, plain_calls


def _resolve_function_tools(
    key: Tuple[str, str],
    direct_tools: Dict[Tuple[str, str], Set[str]],
    self_calls: Dict[Tuple[str, str], Set[str]],
    plain_calls: Dict[Tuple[str, str], Set[str]],
    cache: Dict[Tuple[str, str], Set[str]],
    visiting: Set[Tuple[str, str]],
) -> Set[str]:
    if key in cache:
        return cache[key]
    if key in visiting:
        return set()

    visiting.add(key)
    scope, _ = key
    resolved_tools = set(direct_tools.get(key, set()))

    for called_name in self_calls.get(key, set()):
        resolved_tools.update(
            _resolve_function_tools(
                (scope, called_name),
                direct_tools,
                self_calls,
                plain_calls,
                cache,
                visiting,
            )
        )

    for called_name in plain_calls.get(key, set()):
        if (scope, called_name) in direct_tools:
            resolved_tools.update(
                _resolve_function_tools(
                    (scope, called_name),
                    direct_tools,
                    self_calls,
                    plain_calls,
                    cache,
                    visiting,
                )
            )
        elif ("", called_name) in direct_tools:
            resolved_tools.update(
                _resolve_function_tools(
                    ("", called_name),
                    direct_tools,
                    self_calls,
                    plain_calls,
                    cache,
                    visiting,
                )
            )

    visiting.remove(key)
    cache[key] = resolved_tools
    return resolved_tools


def _extract_case_tools_by_line(lines: List[str]) -> Dict[int, Tuple[str, ...]]:
    source = "\n".join(lines)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}

    tool_aliases = _extract_tool_imports(tree)
    direct_tools: Dict[Tuple[str, str], Set[str]] = {}
    self_calls: Dict[Tuple[str, str], Set[str]] = {}
    plain_calls: Dict[Tuple[str, str], Set[str]] = {}
    case_lines: Dict[int, Tuple[str, str]] = {}

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            key = ("", node.name)
            tools_used, method_calls, name_calls = _collect_function_details(
                node, tool_aliases
            )
            direct_tools[key] = tools_used
            self_calls[key] = method_calls
            plain_calls[key] = name_calls
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                key = (node.name, child.name)
                tools_used, method_calls, name_calls = _collect_function_details(
                    child, tool_aliases
                )
                direct_tools[key] = tools_used
                self_calls[key] = method_calls
                plain_calls[key] = name_calls
                if any(
                    _decorator_name(decorator) == "TestCaseMetadata"
                    for decorator in child.decorator_list
                ):
                    case_lines[child.lineno] = key

    cache: Dict[Tuple[str, str], Set[str]] = {}
    case_tools: Dict[int, Tuple[str, ...]] = {}
    for line_no, key in case_lines.items():
        resolved = _resolve_function_tools(
            key,
            direct_tools,
            self_calls,
            plain_calls,
            cache,
            set(),
        )
        case_tools[line_no] = tuple(sorted(resolved))

    return case_tools


def _extract_supported_features(metadata_block: str) -> Tuple[str, ...]:
    match = re.search(r"supported_features\s*=\s*\[(.*?)\]", metadata_block, re.S)
    if not match:
        return ()

    features: List[str] = []
    for item in _split_top_level_items(match.group(1)):
        feature_match = re.match(r"\s*([A-Z][A-Za-z0-9_]*)", item)
        if not feature_match:
            continue
        feature_name = _normalize_feature_name(feature_match.group(1))
        if feature_name not in features:
            features.append(feature_name)

    return tuple(features)


def extract_changed_feature_names(
    repo_root: Path, changed_files: str, diff: str, known_features: Set[str]
) -> Tuple[str, ...]:
    matched_features = _extract_changed_named_classes(
        repo_root,
        changed_files,
        diff,
        known_features,
        r"(^|/)(features\.py|features/.+\.py)$",
        _normalize_feature_name,
    )
    if matched_features:
        return matched_features

    combined = f"{changed_files}\n{diff}"
    regex_matched_features = [
        feature
        for feature in sorted(known_features)
        if re.search(rf"\b{re.escape(feature)}(?:Settings)?\b", combined)
    ]
    return tuple(regex_matched_features)


def extract_changed_tool_names(
    repo_root: Path, changed_files: str, diff: str, known_tools: Set[str]
) -> Tuple[str, ...]:
    matched_tools = _extract_changed_named_classes(
        repo_root,
        changed_files,
        diff,
        known_tools,
        r"(^|/)tools?(\.py|/.+\.py)$",
        _identity_name,
    )
    if matched_tools:
        return matched_tools

    changed_tools: Set[str] = set()
    for raw_path in changed_files.splitlines():
        changed_path = _normalize_repo_path(raw_path)
        if not changed_path or not re.search(
            r"(^|/)tools?(\.py|/.+\.py)$", changed_path
        ):
            continue

        file_path = repo_root / Path(changed_path)
        if not file_path.exists():
            continue

        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue

        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name in known_tools:
                changed_tools.add(node.name)

    return tuple(sorted(changed_tools))


def list_test_cases(
    repo_root: Path,
    base_dir: Path,
) -> List[Tuple[str, str, str, int, Tuple[str, ...], Tuple[str, ...]]]:
    """Return case metadata including supported features and used tools."""
    results: List[Tuple[str, str, str, int, Tuple[str, ...], Tuple[str, ...]]] = []
    for f in sorted(base_dir.rglob("*.py")):
        lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        case_tools_by_line = _extract_case_tools_by_line(lines)
        area = ""
        in_suite_meta = False
        in_case_meta = False
        priority = 99
        case_metadata_lines: List[str] = []
        for line_no, line in enumerate(lines, start=1):
            if "@TestSuiteMetadata" in line:
                in_suite_meta = True
            if in_suite_meta:
                m = re.search(r'area\s*=\s*(["\'])(.*?)\1', line)
                if m:
                    area = m.group(2)
                if line.strip().startswith("class "):
                    in_suite_meta = False
            if "@TestCaseMetadata" in line:
                in_case_meta = True
                priority = 99
                case_metadata_lines = [line]
                continue
            if in_case_meta:
                case_metadata_lines.append(line)
                priority_match = re.search(r"priority\s*=\s*(\d+)", line)
                if priority_match:
                    priority = int(priority_match.group(1))
                m = re.match(r"\s+def (\w+)\(", line)
                if m:
                    rel = str(f.relative_to(repo_root)).replace("\\", "/")
                    metadata_block = "\n".join(case_metadata_lines)
                    results.append(
                        (
                            rel,
                            area,
                            m.group(1),
                            priority,
                            _extract_supported_features(metadata_block),
                            case_tools_by_line.get(line_no, ()),
                        )
                    )
                    in_case_meta = False
    return results


def find_testsuites_dir(repo_root: Path) -> Path:
    testsuites_dir = repo_root / "lisa" / "microsoft" / "testsuites"
    if not testsuites_dir.exists():
        print(f"ERROR: testsuites directory not found at {testsuites_dir}")
        sys.exit(1)
    return testsuites_dir


def _testsuite_suite_key(path: str) -> str:
    normalized_path = path.replace("\\", "/")
    marker = "microsoft/testsuites/"
    if marker not in normalized_path:
        return ""

    relative = normalized_path.split(marker, 1)[1]
    first_segment, _, _ = relative.partition("/")
    return first_segment


def get_testsuite_related_cases(
    all_cases: List[Tuple[str, str, str, int, Tuple[str, ...], Tuple[str, ...]]],
    changed_files: str,
) -> List[str]:
    changed_testsuite_files = {
        path.strip().replace("\\", "/")
        for path in changed_files.splitlines()
        if path.strip()
        and any(
            pattern.match(path.strip().replace("\\", "/"))
            for pattern in TESTSUITE_CHANGE_PATTERNS
        )
    }
    if not changed_testsuite_files:
        return []

    exact_match_cases: List[str] = []
    suite_match_cases: List[str] = []
    changed_suite_keys = {
        suite_key
        for suite_key in (
            _testsuite_suite_key(path) for path in changed_testsuite_files
        )
        if suite_key
    }

    for rel_path, _, case_name, _, _, _ in all_cases:
        normalized_path = rel_path.replace("\\", "/")
        if normalized_path in changed_testsuite_files:
            exact_match_cases.append(case_name)
            continue
        if _testsuite_suite_key(normalized_path) in changed_suite_keys:
            suite_match_cases.append(case_name)

    return exact_match_cases or suite_match_cases


def get_feature_related_cases(
    all_cases: List[Tuple[str, str, str, int, Tuple[str, ...], Tuple[str, ...]]],
    changed_features: Tuple[str, ...],
) -> List[str]:
    if not changed_features:
        return []

    changed_feature_names = {feature.lower() for feature in changed_features}
    related_cases: List[str] = []
    for _, _, case_name, _, supported_features, _ in all_cases:
        if any(
            supported_feature.lower() in changed_feature_names
            for supported_feature in supported_features
        ):
            related_cases.append(case_name)

    return related_cases


def get_tool_related_cases(
    all_cases: List[Tuple[str, str, str, int, Tuple[str, ...], Tuple[str, ...]]],
    changed_tools: Tuple[str, ...],
) -> List[str]:
    if not changed_tools:
        return []

    changed_tool_names = {tool.lower() for tool in changed_tools}
    related_cases: List[str] = []
    for _, _, case_name, _, _, used_tools in all_cases:
        if any(used_tool.lower() in changed_tool_names for used_tool in used_tools):
            related_cases.append(case_name)

    return related_cases


def call_github_models(prompt: str, token: str) -> str:
    """Call GitHub Models API (OpenAI-compatible) and return the response text."""
    import urllib.request

    url = "https://models.github.ai/inference/chat/completions"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "openai/gpt-4o",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a test selection expert for the LISA Linux VM "
                    "test framework. Given a PR diff and a list of available "
                    "test cases, select the test cases that should be run to "
                    "validate the changes. Consider:\n"
                    "- Which test areas are affected by the changed files\n"
                    "- Which test cases directly test the changed functionality\n"
                    "- Select only cases impacted by the modified code\n"
                    "- Use smoke_test only when no impacted case can be found\n"
                    "- Include related integration tests\n"
                    "- Be conservative: include cases that MIGHT be affected\n"
                    "Return ONLY a JSON array of test case names, no explanation."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    return result["choices"][0]["message"]["content"]


def generate_runbook(case_names: List[str]) -> str:
    """Generate a LISA runbook YAML fragment for the selected test cases."""
    if not case_names:
        return "# No test cases selected by AI\ntestcase: []\n"

    # Join names with | for regex OR pattern in LISA criteria
    name_pattern = "|".join(case_names)
    lines = [
        "# Auto-generated by AI test selector",
        f"# Selected {len(case_names)} test cases",
        "testcase:",
        "  - criteria:",
        f'      name: "{name_pattern}"',
    ]
    return "\n".join(lines) + "\n"


def build_prompt(
    changed_files: str,
    diff: str,
    case_summary: str,
    candidate_case_count: int,
    has_framework_changes: bool,
    has_testsuite_changes: bool,
    testsuite_related_cases: List[str],
    changed_features: Tuple[str, ...],
    feature_related_cases: List[str],
    changed_tools: Tuple[str, ...],
    tool_related_cases: List[str],
) -> str:
    """Build the prompt for the AI model."""
    selection_guidance = (
        "Select the test cases that should run for this PR. "
        "Only select cases that are impacted by the modified code paths. "
        "IMPORTANT: Avoid selecting cases whose names start with stress_ "
        "unless the PR directly modifies stress test code or core functionality "
        "that stress tests specifically validate. Prefer lighter functional tests "
        "over stress tests. Use smoke_test only when no impacted case can be "
        "identified from the code changes. "
    )

    if has_framework_changes and not has_testsuite_changes:
        selection_guidance += (
            "This PR changes framework code only. Select the minimum validating set "
            "of test cases needed to prove the framework update works. If multiple "
            "cases validate the same changed code path with only minor scenario "
            "variations, keep one representative case and use the remaining slots for "
            "different behaviors. Do not select broad regression coverage unless the "
            "diff clearly changes behavior used by all test areas. Prefer a few "
            "representative integration cases that cover different code paths. Do not "
            "force a fixed case count when extra cases cover different changed "
            "behaviors. "
        )
    else:
        selection_guidance += (
            "Prefer the smallest set of direct, representative validation cases over "
            "broad coverage. "
        )

    testsuite_guidance = ""
    if testsuite_related_cases:
        testsuite_guidance = (
            "\nChanged testsuite files map to these cases. Prefer them first, and "
            "only include extra cases when shared helpers or common code paths make "
            "them necessary."
        )

    testsuite_case_summary = ""
    if testsuite_related_cases:
        testsuite_case_summary = (
            "## Cases From Changed Testsuite Area\n"
            f"{', '.join(testsuite_related_cases)}\n\n"
        )

    feature_guidance = ""
    if changed_features:
        feature_guidance = (
            "\nChanged framework features detected from the diff: "
            f"{', '.join(changed_features)}. "
            "Strongly prefer cases whose declared supported_features include those "
            "same features. Exclude smoke_test unless there are no targeted matches."
        )

    feature_case_summary = ""
    if feature_related_cases:
        feature_case_summary = (
            "## Cases With Matching supported_features\n"
            f"{', '.join(feature_related_cases)}\n\n"
        )

    tool_guidance = ""
    if changed_tools:
        tool_guidance = (
            "\nChanged tool classes detected from the diff: "
            f"{', '.join(changed_tools)}. "
            "Prefer cases that actually use those tools. If many cases use the same "
            "tool, choose the smallest set whose steps are most likely to execute the "
            "modified code paths in the diff."
        )

    tool_case_summary = ""
    if tool_related_cases:
        tool_case_summary = (
            f"## Cases Using Changed Tools\n{', '.join(tool_related_cases)}\n\n"
        )

    return (
        "## PR Changed Files\n"
        f"{changed_files}\n\n"
        "## Candidate Case Count\n"
        f"{candidate_case_count}\n\n"
        "## PR Diff (truncated to key changes)\n"
        f"{diff[:MAX_PROMPT_DIFF_CHARS]}\n\n"
        f"{testsuite_case_summary}"
        f"{feature_case_summary}"
        f"{tool_case_summary}"
        "## Available Test Cases\n"
        f"{case_summary}\n\n"
        f"{selection_guidance}\n"
        f"{testsuite_guidance}\n"
        f"{feature_guidance}\n"
        f"{tool_guidance}\n"
        "Return a JSON array of case names only, e.g. "
        '["smoke_test", "verify_cpu_count"].'
    )


def build_case_summary(
    all_cases: List[Tuple[str, str, str, int, Tuple[str, ...], Tuple[str, ...]]],
    candidate_case_names: List[str],
) -> str:
    candidate_set = set(candidate_case_names)
    lines: List[str] = []

    for _, area, name, priority, supported_features, used_tools in all_cases:
        if name not in candidate_set:
            continue

        summary = f"[{area}] {name} p{priority}"
        if supported_features:
            feature_text = ",".join(supported_features[:MAX_SUMMARY_FEATURES])
            if len(supported_features) > MAX_SUMMARY_FEATURES:
                feature_text += ",..."
            summary += f" features={feature_text}"
        if used_tools:
            tool_text = ",".join(used_tools[:MAX_SUMMARY_TOOLS])
            if len(used_tools) > MAX_SUMMARY_TOOLS:
                tool_text += ",..."
            summary += f" tools={tool_text}"
        lines.append(summary)

    return "\n".join(lines)


def _is_smoke_case(case_name: str) -> bool:
    return case_name == "smoke_test" or case_name.startswith("smoke_")


def _is_stress_case(case_name: str) -> bool:
    return case_name.startswith("stress_")


def _is_perf_case(case_name: str) -> bool:
    return case_name.startswith("perf_")


def _is_verify_case(case_name: str) -> bool:
    return case_name.startswith("verify_")


def _tokenize_logic_text(text: str) -> Set[str]:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    tokens = {
        token.lower()
        for token in re.split(r"[^A-Za-z0-9]+", normalized)
        if token and len(token) > 2
    }
    return {token for token in tokens if token not in LOGIC_TOKEN_STOP_WORDS}


def _case_logic_text(
    case_entry: Tuple[str, str, str, int, Tuple[str, ...], Tuple[str, ...]]
) -> str:
    rel_path, area, name, _, supported_features, used_tools = case_entry
    return " ".join(
        [
            rel_path,
            area,
            name,
            " ".join(supported_features),
            " ".join(used_tools),
        ]
    )


def rank_logic_related_cases(
    candidate_names: List[str],
    all_cases: List[Tuple[str, str, str, int, Tuple[str, ...], Tuple[str, ...]]],
    changed_files: str,
    diff: str,
    changed_features: Tuple[str, ...],
    changed_tools: Tuple[str, ...],
) -> List[str]:
    if not candidate_names:
        return candidate_names

    change_tokens = _tokenize_logic_text(
        " ".join(
            [changed_files, diff, " ".join(changed_features), " ".join(changed_tools)]
        )
    )
    if not change_tokens:
        return candidate_names

    case_map = {case_entry[2]: case_entry for case_entry in all_cases}
    scored_candidates: List[Tuple[int, str]] = []
    for case_name in candidate_names:
        case_entry = case_map.get(case_name)
        if not case_entry:
            continue
        case_tokens = _tokenize_logic_text(_case_logic_text(case_entry))
        score = len(change_tokens.intersection(case_tokens))
        scored_candidates.append((score, case_name))

    positive_cases = [case_name for score, case_name in scored_candidates if score > 0]
    if positive_cases:
        print(f"Keeping logic-related candidate cases: {positive_cases}")
        return positive_cases

    return candidate_names


def select_candidate_cases(
    all_cases: List[Tuple[str, str, str, int, Tuple[str, ...], Tuple[str, ...]]],
    testsuite_related_cases: List[str],
    feature_related_cases: List[str],
    tool_related_cases: List[str],
    changed_files: str,
    diff: str,
    changed_features: Tuple[str, ...],
    changed_tools: Tuple[str, ...],
    has_framework_changes: bool,
    has_testsuite_changes: bool,
    max_cases: int,
) -> List[str]:
    candidate_names: List[str] = []
    seen: Set[str] = set()

    def _add(case_name: str) -> None:
        if _is_smoke_case(case_name):
            return
        if case_name not in seen:
            seen.add(case_name)
            candidate_names.append(case_name)

    for case_name in testsuite_related_cases:
        _add(case_name)
    for case_name in feature_related_cases:
        _add(case_name)
    for case_name in tool_related_cases:
        _add(case_name)

    candidate_names = rank_logic_related_cases(
        candidate_names,
        all_cases,
        changed_files,
        diff,
        changed_features,
        changed_tools,
    )

    if len(candidate_names) > max_cases:
        return candidate_names[:max_cases]

    return candidate_names


def parse_ai_response(response: str) -> List[str]:
    """Parse the AI response into a list of test case names."""
    cleaned = response.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```\w*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
        cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        print(f"WARNING: Could not parse AI response as JSON: {cleaned}")
        print("Falling back to empty selection.")
        return []


def filter_stress_tests(validated: List[str], changed_files: str) -> List[str]:
    """Remove cases named with a stress_ prefix unless stress files changed."""
    stress_tests = [case_name for case_name in validated if _is_stress_case(case_name)]
    if not stress_tests:
        return validated
    stress_files_changed = any(
        "stress" in f.lower() for f in changed_files.splitlines() if f.strip()
    )
    if not stress_files_changed:
        print(f"Removing stress tests (no stress files changed): {stress_tests}")
        return [case_name for case_name in validated if not _is_stress_case(case_name)]
    return validated


def apply_smoke_fallback(
    validated: List[str],
    all_cases: List[Tuple[str, str, str, int, Tuple[str, ...], Tuple[str, ...]]],
) -> List[str]:
    non_smoke_cases = [
        case_name for case_name in validated if not _is_smoke_case(case_name)
    ]
    if non_smoke_cases:
        removed_smoke = [
            case_name for case_name in validated if _is_smoke_case(case_name)
        ]
        if removed_smoke:
            print(f"Removing smoke cases from normal selection: {removed_smoke}")
        return non_smoke_cases

    valid_names = {name for _, _, name, _, _, _ in all_cases}
    if "smoke_test" in valid_names:
        print("No targeted cases remained. Falling back to smoke_test.")
        return ["smoke_test"]

    return []


def _has_perf_change_signal(changed_files: str, diff: str) -> bool:
    combined = f"{changed_files}\n{diff}".lower()
    return bool(re.search(r"perf|performance|benchmark|io_uring", combined))


def prefer_verify_cases(validated: List[str]) -> List[str]:
    if not any(_is_verify_case(case_name) for case_name in validated):
        return validated

    non_perf_or_stress_cases = [
        case_name
        for case_name in validated
        if not _is_perf_case(case_name) and not _is_stress_case(case_name)
    ]
    if len(non_perf_or_stress_cases) == len(validated):
        return validated
    if not non_perf_or_stress_cases:
        return validated

    removed_cases = [
        case_name
        for case_name in validated
        if _is_perf_case(case_name) or _is_stress_case(case_name)
    ]
    print(
        "Removing perf_/stress_ cases because verify* cases already cover the "
        f"impacted logic: {removed_cases}"
    )
    return non_perf_or_stress_cases


def prefer_lightweight_cases(
    validated: List[str],
    all_cases: List[Tuple[str, str, str, int, Tuple[str, ...], Tuple[str, ...]]],
    changed_files: str,
    diff: str,
    has_framework_changes: bool,
    has_testsuite_changes: bool,
) -> List[str]:
    if not has_framework_changes or has_testsuite_changes:
        return validated

    priority_map = {name: priority for _, _, name, priority, _, _ in all_cases}

    if not _has_perf_change_signal(changed_files, diff):
        non_perf_cases = [
            name for name in validated if not _is_perf_case(name)
        ]
        if non_perf_cases and len(non_perf_cases) < len(validated):
            removed_perf = [name for name in validated if _is_perf_case(name)]
            print(f"Removing perf cases without perf change signal: {removed_perf}")
            validated = non_perf_cases

    preferred_cases = [name for name in validated if priority_map.get(name, 99) < 3]
    if preferred_cases and len(preferred_cases) < len(validated):
        removed_high_priority = [
            name for name in validated if priority_map.get(name, 99) >= 3
        ]
        print(
            "Removing higher-priority cases when lower-priority alternatives exist: "
            f"{removed_high_priority}"
        )
        return preferred_cases

    return validated


def align_with_feature_requirements(
    validated: List[str],
    all_cases: List[Tuple[str, str, str, int, Tuple[str, ...], Tuple[str, ...]]],
    changed_features: Tuple[str, ...],
    has_framework_changes: bool,
    has_testsuite_changes: bool,
) -> List[str]:
    if not changed_features or not has_framework_changes or has_testsuite_changes:
        return validated

    feature_related_cases = set(get_feature_related_cases(all_cases, changed_features))
    if not feature_related_cases:
        return validated

    aligned_cases = [
        case_name for case_name in validated if case_name in feature_related_cases
    ]
    if aligned_cases:
        removed_cases = [
            case_name for case_name in validated if case_name not in aligned_cases
        ]
        if removed_cases:
            print(
                "Removing cases unrelated to changed supported_features: "
                f"{removed_cases}"
            )
        return aligned_cases

    print(
        "AI selected no cases matching changed supported_features. "
        "Falling back to metadata-matched cases."
    )
    return [
        case_name
        for _, _, case_name, _, _, _ in all_cases
        if case_name in feature_related_cases
    ]


def align_with_testsuite_changes(
    validated: List[str],
    testsuite_related_cases: List[str],
    has_testsuite_changes: bool,
) -> List[str]:
    if not has_testsuite_changes or not testsuite_related_cases:
        return validated

    related_case_set = set(testsuite_related_cases)
    aligned_cases = [
        case_name for case_name in validated if case_name in related_case_set
    ]
    if aligned_cases:
        removed_cases = [
            case_name for case_name in validated if case_name not in aligned_cases
        ]
        if removed_cases:
            print(
                "Removing cases unrelated to changed testsuite files: "
                f"{removed_cases}"
            )
        return aligned_cases

    print(
        "AI selected no cases from the changed testsuite area. Falling back to "
        "testsuite-related cases."
    )
    return testsuite_related_cases


def align_with_tool_usage(
    validated: List[str],
    all_cases: List[Tuple[str, str, str, int, Tuple[str, ...], Tuple[str, ...]]],
    changed_tools: Tuple[str, ...],
    has_framework_changes: bool,
    has_testsuite_changes: bool,
) -> List[str]:
    if not changed_tools or not has_framework_changes or has_testsuite_changes:
        return validated

    tool_related_cases = set(get_tool_related_cases(all_cases, changed_tools))
    if not tool_related_cases:
        return validated

    aligned_cases = [
        case_name for case_name in validated if case_name in tool_related_cases
    ]
    if aligned_cases:
        removed_cases = [
            case_name for case_name in validated if case_name not in aligned_cases
        ]
        if removed_cases:
            print(f"Removing cases unrelated to changed tool usage: {removed_cases}")
        return aligned_cases

    print(
        "AI selected no cases using changed tools. Falling back to tool-related cases."
    )
    return [
        case_name
        for _, _, case_name, _, _, _ in all_cases
        if case_name in tool_related_cases
    ]


def _add_representative_case(
    name: str,
    validated: List[str],
    selected: List[str],
    seen: Set[str],
    covered_areas: Set[str],
    area_map: Dict[str, str],
) -> None:
    if name in seen or name not in validated:
        return

    selected.append(name)
    seen.add(name)

    area = area_map.get(name, "")
    if area:
        covered_areas.add(area)


def _prefer_named_cases(
    preferred_names: Tuple[str, ...],
    validated: List[str],
    selected: List[str],
    seen: Set[str],
    covered_areas: Set[str],
    area_map: Dict[str, str],
) -> None:
    for preferred_name in preferred_names:
        _add_representative_case(
            preferred_name,
            validated,
            selected,
            seen,
            covered_areas,
            area_map,
        )


def _cover_remaining_areas(
    validated: List[str],
    selected: List[str],
    seen: Set[str],
    covered_areas: Set[str],
    area_map: Dict[str, str],
    limit: int,
) -> None:
    for name in validated:
        if len(selected) >= limit:
            return
        area = area_map.get(name, "")
        if area and area not in covered_areas:
            _add_representative_case(
                name,
                validated,
                selected,
                seen,
                covered_areas,
                area_map,
            )


def _fill_remaining_cases(
    validated: List[str],
    selected: List[str],
    seen: Set[str],
    covered_areas: Set[str],
    area_map: Dict[str, str],
    limit: int,
) -> None:
    for name in validated:
        if len(selected) >= limit:
            return
        _add_representative_case(
            name,
            validated,
            selected,
            seen,
            covered_areas,
            area_map,
        )


def minimize_framework_only_cases(
    validated: List[str],
    all_cases: List[Tuple[str, str, str, int, Tuple[str, ...], Tuple[str, ...]]],
    has_framework_changes: bool,
    has_testsuite_changes: bool,
) -> List[str]:
    """Reduce framework-only selections to a deduplicated representative set."""
    if not has_framework_changes or has_testsuite_changes:
        return validated

    area_map: Dict[str, str] = {name: area for _, area, name, _, _, _ in all_cases}
    framework_only_case_limit = len(validated)
    selected: List[str] = []
    seen: Set[str] = set()
    covered_areas: Set[str] = set()

    _cover_remaining_areas(
        validated,
        selected,
        seen,
        covered_areas,
        area_map,
        framework_only_case_limit,
    )
    _fill_remaining_cases(
        validated,
        selected,
        seen,
        covered_areas,
        area_map,
        framework_only_case_limit,
    )

    if len(selected) < len(validated):
        print(
            "Reducing framework-only case selection from "
            f"{len(validated)} to {len(selected)} representative cases"
        )

    return selected


def select_marketplace_image(changed_files: str, diff: str) -> str:
    """Choose a minimal marketplace image based on code-change signals."""
    combined = f"{changed_files}\n{diff}".lower()

    distro = "ubuntu"
    if re.search(r"suse|sles|opensuse", combined):
        distro = "suse"
    elif re.search(r"redhat|rhel", combined):
        distro = "rhel"
    elif re.search(r"oracle|oracle-linux|\bol8\b|\bol9\b|\bol94\b", combined):
        distro = "oracle"
    elif re.search(r"azure-linux|cblmariner|mariner", combined):
        distro = "azurelinux"
    elif re.search(r"debian", combined):
        distro = "debian"
    elif re.search(r"ubuntu|jammy|noble|22\.04|24\.04", combined):
        distro = "ubuntu"

    arch = "arm64" if re.search(r"arm64|aarch64|\barm\b", combined) else "default"
    generation = ""
    if re.search(r"gen1|generation 1", combined):
        generation = "gen1"
    elif re.search(r"gen2|generation 2", combined):
        generation = "gen2"

    images = MARKETPLACE_IMAGES[distro]
    if arch in images:
        return images[arch]
    if generation and generation in images:
        return images[generation]
    return images.get("default", DEFAULT_MARKETPLACE_IMAGE)


def write_outputs(
    validated: List[str],
    all_cases: List[Tuple[str, str, str, int, Tuple[str, ...], Tuple[str, ...]]],
    marketplace_image: str,
    output_file: str,
) -> None:
    """Write runbook, GitHub Actions outputs, and step summary."""
    runbook = generate_runbook(validated)
    output_path = Path(output_file)
    output_path.write_text(runbook, encoding="utf-8")
    print(f"Runbook written to {output_path}")

    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"case_count={len(validated)}\n")
            f.write(f"case_names={','.join(validated)}\n")
            f.write(f"marketplace_image={marketplace_image}\n")

    github_summary = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if github_summary:
        with open(github_summary, "a", encoding="utf-8") as f:
            f.write("## AI Test Case Selection\n\n")
            f.write(f"**Selected {len(validated)} test cases** ")
            f.write(f"from {len(all_cases)} available\n\n")
            f.write(f"**Marketplace image:** `{marketplace_image}`\n\n")
            if validated:
                f.write("| # | Test Case | Area |\n")
                f.write("|---|-----------|------|\n")
                area_map = {name: area for _, area, name, _, _, _ in all_cases}
                for i, name in enumerate(validated, 1):
                    f.write(f"| {i} | `{name}` | {area_map.get(name, '')} |\n")
            else:
                f.write("No test cases selected.\n")


def main() -> None:
    diff = os.environ.get("PR_DIFF", "")
    changed_files = os.environ.get("PR_CHANGED_FILES", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    output_file = os.environ.get("RUNBOOK_OUTPUT", "ai_selected_cases.yml")

    if not token:
        print("ERROR: GITHUB_TOKEN is required for GitHub Models API", file=sys.stderr)
        sys.exit(1)
    if not diff and not changed_files:
        print("ERROR: PR_DIFF or PR_CHANGED_FILES must be set", file=sys.stderr)
        sys.exit(1)

    if not has_relevant_code_changes(changed_files):
        print(
            "No framework or testsuite Python changes detected. "
            "Skipping test selection."
        )
        write_outputs([], [], DEFAULT_MARKETPLACE_IMAGE, output_file)
        return

    has_framework_changes, has_testsuite_changes = get_change_scope(changed_files)

    repo_root = find_repo_root()
    testsuites_dir = find_testsuites_dir(repo_root)
    all_cases = list_test_cases(repo_root, testsuites_dir)
    print(f"Found {len(all_cases)} test cases")

    known_features = {
        feature_name
        for _, _, _, _, supported_features, _ in all_cases
        for feature_name in supported_features
    }
    known_tools = {
        tool_name for _, _, _, _, _, used_tools in all_cases for tool_name in used_tools
    }
    changed_features = extract_changed_feature_names(
        repo_root,
        changed_files,
        diff,
        known_features,
    )
    changed_tools = extract_changed_tool_names(
        repo_root,
        changed_files,
        diff,
        known_tools,
    )
    testsuite_related_cases = get_testsuite_related_cases(all_cases, changed_files)
    feature_related_cases = get_feature_related_cases(all_cases, changed_features)
    tool_related_cases = get_tool_related_cases(all_cases, changed_tools)
    if testsuite_related_cases:
        print("Cases from changed testsuite area: " f"{testsuite_related_cases}")
    if changed_features:
        print(f"Detected changed framework features: {list(changed_features)}")
        print("Cases with matching supported_features: " f"{feature_related_cases}")
    if changed_tools:
        print(f"Detected changed tool classes: {list(changed_tools)}")
        print(f"Cases using changed tools: {tool_related_cases}")

    candidate_case_names = select_candidate_cases(
        all_cases,
        testsuite_related_cases,
        feature_related_cases,
        tool_related_cases,
        changed_files,
        diff,
        changed_features,
        changed_tools,
        has_framework_changes,
        has_testsuite_changes,
        MAX_PROMPT_CANDIDATE_CASES,
    )

    if not candidate_case_names:
        print(
            "No impacted test cases were derived from the changed framework or "
            "testsuite code. Falling back to smoke_test."
        )
        validated = apply_smoke_fallback([], all_cases)
        marketplace_image = select_marketplace_image(changed_files, diff)
        print(f"Selected {len(validated)} valid test cases: {validated}")
        print(f"Selected marketplace image: {marketplace_image}")
        write_outputs(validated, all_cases, marketplace_image, output_file)
        return

    case_summary = build_case_summary(all_cases, candidate_case_names)
    prompt = build_prompt(
        changed_files,
        diff,
        case_summary,
        len(candidate_case_names),
        has_framework_changes,
        has_testsuite_changes,
        testsuite_related_cases,
        changed_features,
        feature_related_cases,
        changed_tools,
        tool_related_cases,
    )

    print("Calling GitHub Models API for test case selection...")
    try:
        response = call_github_models(prompt, token)
    except HTTPError as error:
        if error.code != 413:
            raise

        print(
            "Prompt payload too large. Retrying with a smaller candidate set and "
            "shorter diff excerpt."
        )
        fallback_candidates = select_candidate_cases(
            all_cases,
            testsuite_related_cases,
            feature_related_cases,
            tool_related_cases,
            changed_files,
            diff,
            changed_features,
            changed_tools,
            has_framework_changes,
            has_testsuite_changes,
            MAX_PROMPT_FALLBACK_CASES,
        )
        prompt = build_prompt(
            changed_files,
            diff[: MAX_PROMPT_DIFF_CHARS // 2],
            build_case_summary(all_cases, fallback_candidates),
            len(fallback_candidates),
            has_framework_changes,
            has_testsuite_changes,
            testsuite_related_cases[:MAX_PROMPT_FALLBACK_CASES],
            changed_features,
            feature_related_cases[:MAX_PROMPT_FALLBACK_CASES],
            changed_tools,
            tool_related_cases[:MAX_PROMPT_FALLBACK_CASES],
        )
        response = call_github_models(prompt, token)
    print(f"AI response: {response}")

    selected_cases = parse_ai_response(response)

    candidate_name_set = set(candidate_case_names)

    validated = [c for c in selected_cases if c in candidate_name_set]
    invalid = [c for c in selected_cases if c not in candidate_name_set]
    if invalid:
        print(
            "WARNING: AI selected "
            f"{len(invalid)} cases outside the candidate set: {invalid}"
        )

    validated = align_with_testsuite_changes(
        validated,
        testsuite_related_cases,
        has_testsuite_changes,
    )
    validated = align_with_feature_requirements(
        validated,
        all_cases,
        changed_features,
        has_framework_changes,
        has_testsuite_changes,
    )
    validated = align_with_tool_usage(
        validated,
        all_cases,
        changed_tools,
        has_framework_changes,
        has_testsuite_changes,
    )
    validated = prefer_verify_cases(validated)
    validated = filter_stress_tests(validated, changed_files)
    validated = prefer_lightweight_cases(
        validated,
        all_cases,
        changed_files,
        diff,
        has_framework_changes,
        has_testsuite_changes,
    )
    validated = minimize_framework_only_cases(
        validated,
        all_cases,
        has_framework_changes,
        has_testsuite_changes,
    )
    validated = apply_smoke_fallback(validated, all_cases)
    marketplace_image = select_marketplace_image(changed_files, diff)
    print(f"Selected {len(validated)} valid test cases: {validated}")
    print(f"Selected marketplace image: {marketplace_image}")

    write_outputs(validated, all_cases, marketplace_image, output_file)


if __name__ == "__main__":
    main()
