# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Build OS-compatible PR validation groups from reviewed images and real metadata."""

import ast
import importlib
import json
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple, Type, TypedDict

from validation_report import ValidationRecommendation

from lisa.operating_system import OperatingSystem
from lisa.testselector import _is_os_compatible, _is_platform_compatible
from lisa.testsuite import TestCaseMetadata, get_cases_metadata
from lisa.util.os_resolver import infer_target_os, resolve_os_class


class ValidationGroup(TypedDict):
    marketplace_image: str
    cases: List[str]
    required_cases: List[str]
    reasons: Dict[str, str]


class RecommendationFields(TypedDict, total=False):
    recommendations: List["ValidationRecommendation"]


class ValidationPlan(RecommendationFields):
    status: str
    reason: str
    groups: List[ValidationGroup]


NON_AZURE_SUITES = {
    "cloud_hypervisor": "Cloud Hypervisor host",
    "hyperv": "Hyper-V host",
    "kvm": "KVM host",
    "libvirt": "libvirt host",
    "mshv": "MSHV host",
    "rust_vmm_mshv": "MSHV host",
    "openvmm": "OpenVMM host/platform",
}


def manual_requirements(path: str, case: TestCaseMetadata) -> Tuple[str, str]:
    parts = path.split("/")
    platform = NON_AZURE_SUITES.get(parts[-2], "")
    if platform:
        if parts[-2] == "openvmm":
            if case.suite.name == "OpenVmmUpstreamTestSuite":
                return (
                    platform,
                    "Prepared Azure Linux/CBLMariner x86_64 host; accessible "
                    "/dev/mshv; Intel CPU for linux-intel-mshv; Docker and upstream "
                    "OpenVMM guest prerequisites. Ordinary Azure VM is insufficient.",
                )
            return (
                platform,
                "Prepared L1 host and OpenVMM orchestrator with OpenVmmGuestNode; "
                "platform StartStop support for restart/stop-start cases.",
            )
        return platform, f"Prepared {platform}; satisfy the case's real requirements."
    if not _is_platform_compatible(case, ["azure"]):
        return (
            "Non-Azure platform",
            "Use a platform supported by the registered case requirement.",
        )
    return "", ""


def manual_plan(
    case_files: Dict[str, str],
    metadata: Dict[str, TestCaseMetadata],
    required_cases: List[str],
    reasons: Dict[str, str],
) -> ValidationPlan:
    recommendations: List[ValidationRecommendation] = []
    for name, path in case_files.items():
        platform, requirements = manual_requirements(path, metadata[name])
        recommendations.append(
            {
                "case": metadata[name].full_name,
                "platform": platform or "Azure",
                "requirements": requirements
                or "Azure-compatible case deferred with this mixed-platform plan; "
                "validate separately using reviewed images and real requirements.",
                "reason": reasons.get(name, "AI-ranked related case"),
                "required": name in required_cases,
                "execution_status": "not_executed",
            }
        )
    return {
        "status": "manual_required",
        "reason": "Selected cases require a platform/host outside this Azure pipeline. "
        "Dedicated-platform validation is required; no guest tests were executed.",
        "groups": [],
        "recommendations": recommendations,
    }


def reviewed_images(repo_root: Path) -> List[str]:
    source = (repo_root / ".github" / "copilot-instructions.md").read_text(
        encoding="utf-8"
    )
    section = source.split("### Available Azure Marketplace Images", 1)[1]
    images = re.findall(r"^- `([^`\n]+ latest)`$", section, re.MULTILINE)
    if not images:
        raise ValueError("No reviewed Marketplace images found.")
    # The reviewed list is ordered from older to newer releases within each OS.
    # Prefer Gen2 and later entries; retain a conventional Ubuntu baseline.
    default = "canonical 0001-com-ubuntu-server-jammy 22_04-lts-gen2 latest"
    ordered = [
        image
        for _, image in sorted(
            enumerate(dict.fromkeys(images)),
            key=lambda item: (item[1] == default, "gen2" in item[1], item[0]),
            reverse=True,
        )
    ]
    return ordered


def load_metadata(
    repo_root: Path, case_files: Dict[str, str]
) -> Dict[str, TestCaseMetadata]:
    for path in sorted(set(case_files.values())):
        module = importlib.import_module(path.removesuffix(".py").replace("/", "."))
        if Path(module.__file__ or "").resolve() != (repo_root / path).resolve():
            raise ValueError(
                f"Imported testsuite does not match the repository: {path}"
            )
    registered = get_cases_metadata()
    result: Dict[str, TestCaseMetadata] = {}
    for name, path in case_files.items():
        module_name = path.removesuffix(".py").replace("/", ".")
        matches = [
            case
            for case in registered.values()
            if case.name == name
            and case.suite.name == case.full_name.rsplit(".", 1)[0]
            and getattr(case.suite.test_class, "__module__", "") == module_name
        ]
        if len(matches) != 1:
            raise ValueError(f"Case {name!r} in {path} is missing or ambiguous.")
        result[name] = matches[0]
    return result


def _os_names(node: ast.AST) -> Set[str]:
    result: Set[str] = set()
    for item in ast.walk(node):
        if not isinstance(item, (ast.Name, ast.Attribute)):
            continue
        name = item.id if isinstance(item, ast.Name) else item.attr
        os_class = resolve_os_class(name)
        if os_class and os_class.__name__ not in (
            "OperatingSystem",
            "Posix",
            "Linux",
            "RPMDistro",
        ):
            result.add(os_class.__name__)
    return result


def changed_os_context(
    repo_root: Path, changed_lines: Dict[str, Set[int]]
) -> Tuple[Set[str], str]:
    """Inspect changed statements and enclosing OS branches, not unrelated context."""
    names: Set[str] = set()
    contexts: List[str] = []
    for path, line_numbers in changed_lines.items():
        file_path = repo_root / path
        if not line_numbers or not file_path.is_file() or file_path.suffix != ".py":
            continue
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        nodes = list(ast.walk(tree))
        for line in sorted(line_numbers):
            enclosing = [
                node
                for node in nodes
                if isinstance(node, ast.stmt)
                and node.lineno <= line <= getattr(node, "end_lineno", node.lineno)
            ]
            for node in enclosing:
                if (
                    isinstance(node, ast.ClassDef)
                    and path == "lisa/operating_system.py"
                ):
                    names.update(_os_names(ast.Name(id=node.name, ctx=ast.Load())))
                elif isinstance(node, ast.If):
                    negative = any(
                        isinstance(item, ast.UnaryOp)
                        and isinstance(item.op, ast.Not)
                        and _os_names(item.operand)
                        for item in ast.walk(node.test)
                    )
                    positive_branch = any(
                        item.lineno <= line <= item.end_lineno
                        for item in [node.test, *node.body]
                        if isinstance(item, (ast.expr, ast.stmt))
                        and item.end_lineno is not None
                    )
                    if positive_branch and not negative:
                        names.update(_os_names(node.test))
                    elif _os_names(node.test) and not (
                        len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If)
                    ):
                        contexts.append("UNRESOLVED_OS_BRANCH")
                    if negative:
                        contexts.append("UNRESOLVED_OS_BRANCH")
                    contexts.append(ast.get_source_segment(source, node.test) or "")
            statements = [
                node
                for node in enclosing
                if not isinstance(
                    node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.If)
                )
            ]
            if statements:
                smallest = min(
                    statements,
                    key=lambda node: getattr(node, "end_lineno", 0) - node.lineno,
                )
                names.update(_os_names(smallest))
                contexts.append(ast.get_source_segment(source, smallest) or "")
    return names, "\n".join(contexts)


def _image_os(image: str) -> Type[OperatingSystem]:
    os_class = infer_target_os({"marketplace_image": image})
    if image.split()[1].startswith("sles-"):
        os_class = resolve_os_class("SLES")
    if os_class is None:
        raise ValueError(f"Cannot resolve OS for reviewed image {image!r}.")
    return os_class


def _compatible(case: TestCaseMetadata, image: str) -> bool:
    os_class = _image_os(image)
    return _is_os_compatible(case, os_class) and _is_platform_compatible(
        case, ["azure"]
    )


def _matches_os(image: str, name: str) -> bool:
    os_class = _image_os(image)
    required_os = resolve_os_class(name)
    if name == "Suse":
        return bool(required_os and issubclass(os_class, required_os))
    return os_class is required_os


def _image_candidates(
    catalog: List[str], context: str, explicit_images: List[str]
) -> List[str]:
    if explicit_images:
        if any(image not in catalog for image in explicit_images):
            raise ValueError("Explicit images must come from the reviewed image list.")
        return list(dict.fromkeys(explicit_images))
    if "UNRESOLVED_OS_BRANCH" in context:
        raise ValueError("Negative/else OS branch needs explicit validationImages.")
    if re.search(r"\bversion\b.*(?:[<>]=?|==)|parse_version\s*\(", context):
        raise ValueError(
            "Version-specific change needs explicit validationImages from the reviewed "
            "list; automatic selection cannot prove version-branch coverage."
        )
    arm = bool(re.search(r"\b(?:arm64|aarch64)\b", context, re.IGNORECASE))
    gen1 = bool(re.search(r"\bgen1\b", context, re.IGNORECASE))
    gen2 = bool(re.search(r"\bgen2\b", context, re.IGNORECASE))
    if gen1 and gen2:
        raise ValueError("Both image generations changed; specify validationImages.")
    if arm and re.search(r"\b(?:x64|x86_64)\b", context, re.IGNORECASE):
        raise ValueError("Both architectures changed; specify validationImages.")
    result = [
        image
        for image in catalog
        if bool(re.search(r"arm64|aarch64", image)) == arm
        and (not gen1 or "gen1" in image)
        and (not gen2 or "gen2" in image)
    ]
    if not result:
        raise ValueError(
            "No reviewed image matches the changed architecture/generation."
        )
    return result


def build_validation_plan(
    repo_root: Path,
    case_files: Dict[str, str],
    required_cases: List[str],
    reasons: Dict[str, str],
    changed_lines: Dict[str, Set[int]],
    explicit_images: List[str],
) -> ValidationPlan:
    if not case_files:
        return {
            "status": "not_required",
            "reason": "No guest validation required.",
            "groups": [],
        }
    metadata = load_metadata(repo_root, case_files)
    if any(
        manual_requirements(path, metadata[name])[0]
        for name, path in case_files.items()
    ):
        return manual_plan(case_files, metadata, required_cases, reasons)
    return _azure_validation_plan(
        repo_root,
        case_files,
        required_cases,
        reasons,
        changed_lines,
        explicit_images,
        metadata,
    )


def _azure_validation_plan(
    repo_root: Path,
    case_files: Dict[str, str],
    required_cases: List[str],
    reasons: Dict[str, str],
    changed_lines: Dict[str, Set[int]],
    explicit_images: List[str],
    metadata: Dict[str, TestCaseMetadata],
) -> ValidationPlan:
    os_names, context = changed_os_context(repo_root, changed_lines)
    catalog = reviewed_images(repo_root)
    candidates = _image_candidates(catalog, context, explicit_images)
    for os_name in sorted(os_names):
        if not any(_matches_os(image, os_name) for image in candidates):
            raise ValueError(
                f"No reviewed image covers affected OS {os_name}. "
                "Extend the reviewed catalog or specify compatible validationImages."
            )
    targets = sorted(os_names) or [""]
    groups: Dict[str, ValidationGroup] = {}
    covered: Set[str] = set()
    for target in targets:
        images = [
            image for image in candidates if not target or _matches_os(image, target)
        ]
        if explicit_images:
            images_to_run = images
        else:
            images_to_run = []
            remaining = set(case_files)
            for image in images:
                matching = {
                    name for name in remaining if _compatible(metadata[name], image)
                }
                if matching:
                    images_to_run.append(image)
                    remaining.difference_update(matching)
        if target and not images_to_run:
            raise ValueError(f"No selected case can validate affected OS {target}.")
        for image in images_to_run:
            names = [name for name in case_files if _compatible(metadata[name], image)]
            if not names:
                raise ValueError(
                    f"No selected case can validate target {target or image}."
                )
            group = groups.setdefault(
                image,
                {
                    "marketplace_image": image,
                    "cases": [],
                    "required_cases": [],
                    "reasons": {},
                },
            )
            for name in names:
                full_name = metadata[name].full_name
                if full_name not in group["cases"]:
                    group["cases"].append(full_name)
                    group["reasons"][full_name] = reasons.get(
                        name, "AI-ranked related case"
                    )
                    if name in required_cases:
                        group["required_cases"].append(full_name)
            covered.update(names)
    missing = set(case_files).difference(covered)
    if missing:
        raise ValueError(
            f"No compatible reviewed image for selected cases: {sorted(missing)}"
        )
    return {
        "status": "selected",
        "reason": "Targeted validation; not a coverage proof.",
        "groups": list(groups.values()),
    }


def parse_explicit_images(value: str) -> List[str]:
    result = json.loads(value)
    if not isinstance(result, list) or not all(
        isinstance(item, str) for item in result
    ):
        raise ValueError(
            "validationImages must be a JSON array of reviewed image strings."
        )
    return result
