# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Resolve reviewed images, execute validation groups, and enforce JUnit coverage."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree

from validation_plan import reviewed_images


def azure_json(arguments: List[str]) -> Any:
    result = subprocess.run(
        ["az", *arguments, "--output", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Azure CLI failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def resolve_image(image: str, location: str) -> str:
    parts = image.split()
    if len(parts) != 4:
        raise ValueError(f"Invalid Marketplace image: {image!r}")
    resolved = azure_json(
        ["vm", "image", "show", "--location", location, "--urn", ":".join(parts)]
    )
    version = resolved.get("name", "")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"Image did not resolve to a concrete version: {image!r}")
    return " ".join(parts[:3] + [version])


def case_pattern(full_names: List[str]) -> str:
    # LISA Criteria.name matches method names, not suite-qualified names.
    # The selector rejects ambiguous method names before producing a plan.
    return (
        "^(?:"
        + "|".join(re.escape(name.rsplit(".", 1)[1]) for name in full_names)
        + ")$"
    )


def read_outcomes(directory: Path, expected: List[str]) -> Dict[str, Dict[str, str]]:
    files = list(directory.rglob("lisa.junit.xml"))
    if not files:
        raise ValueError(f"No JUnit results found under {directory}.")
    cases = [
        case for path in files for case in ElementTree.parse(path).iter("testcase")
    ]
    outcomes: Dict[str, Dict[str, str]] = {}
    for name in expected:
        suite, method = name.rsplit(".", 1)
        matches = [
            case
            for case in cases
            if case.get("classname") == name
            or (
                case.get("classname") == suite
                and re.sub(r" \([^()]*\)$", "", case.get("name", "")) == method
            )
        ]
        if not matches:
            outcomes[name] = {"status": "missing", "signature": ""}
            continue
        signatures = set()
        statuses = set()
        for case in matches:
            failure = case.find("failure")
            error = case.find("error")
            if case.find("skipped") is not None:
                statuses.add("skipped")
            elif failure is not None or error is not None:
                element = failure if failure is not None else error
                assert element is not None
                status = "failed" if failure is not None else "error"
                statuses.add(status)
                # Ignore checkout paths/traceback line numbers, not semantic values.
                text = element.get("message", "") + "\n" + (element.text or "")
                text = re.sub(
                    r'File "[^"]+", line \d+', 'File "<source>", line N', text
                )
                text = re.sub(r"\s+", " ", text).strip()
                if not text:
                    raise ValueError(f"Failure has no diagnostic signature: {name}")
                signatures.add(hashlib.sha256(text.encode("utf-8")).hexdigest())
            else:
                statuses.add("passed")
        if len(statuses) != 1 or len(signatures) > 1:
            outcomes[name] = {"status": "inconsistent", "signature": ""}
        else:
            outcomes[name] = {
                "status": statuses.pop(),
                "signature": next(iter(signatures), ""),
            }
    for case in cases:
        if case.find("failure") is not None or case.find("error") is not None:
            if not any(
                case.get("classname") == name
                or (
                    case.get("classname") == name.rsplit(".", 1)[0]
                    and re.sub(r" \([^()]*\)$", "", case.get("name", ""))
                    == name.rsplit(".", 1)[1]
                )
                for name in expected
            ):
                raise ValueError("JUnit contains an unexpected failed case.")
    return outcomes


def compare_outcomes(head: Dict[str, str], base: Dict[str, str]) -> str:
    if head["status"] not in ("failed", "error"):
        return "inconclusive"
    if base["status"] == "passed":
        return "suspected_regression"
    if (
        base["status"] == head["status"]
        and head["signature"]
        and base["signature"] == head["signature"]
    ):
        return "same_failure"
    if base["status"] in ("failed", "error"):
        return "different_failure"
    return "inconclusive"


def deployment_sizes(directory: Path) -> List[str]:
    shapes = set()
    for path in directory.rglob("arm_template_parameters.json"):
        parameters = json.loads(path.read_text(encoding="utf-8"))
        nodes = parameters.get("nodes", {}).get("value", [])
        shape = tuple(sorted(node["vm_size"] for node in nodes))
        if shape:
            shapes.add(shape)
    if len(shapes) != 1:
        raise ValueError("Cannot identify one comparable deployed VM topology.")
    sizes = list(shapes.pop())
    if len(set(sizes)) != 1:
        raise ValueError("Baseline cannot pin a heterogeneous VM topology.")
    return sizes


def deployment_signature(directory: Path) -> str:
    signatures = set()
    keys = (
        "vm_size",
        "osdisk_size_in_gb",
        "maximize_capability",
        "marketplace",
        "security_profile",
        "disk_controller_type",
        "data_disk_count",
        "data_disk_type",
        "data_disk_size",
        "nic_count",
        "network_data_path",
    )
    for path in directory.rglob("arm_template_parameters.json"):
        parameters = json.loads(path.read_text(encoding="utf-8"))
        nodes = parameters.get("nodes", {}).get("value", [])
        configuration = sorted(
            json.dumps({key: node.get(key) for key in keys}, sort_keys=True)
            for node in nodes
        )
        signatures.add(
            hashlib.sha256(json.dumps(configuration).encode("utf-8")).hexdigest()
        )
    if len(signatures) != 1:
        raise ValueError("Cannot identify one comparable deployment configuration.")
    return signatures.pop()


def prepare_baseline(repo_root: Path, base_sha: str, directory: Path) -> Path:
    source = directory / "source"
    environment = directory / "venv"
    directory.mkdir(parents=True)
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(source), base_sha],
        cwd=repo_root,
        check=True,
    )
    try:
        subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        subprocess.run(
            [str(python), "-m", "pip", "install", "-e", ".[azure]"],
            cwd=source,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(source)],
            cwd=repo_root,
            check=True,
        )
        raise
    return scripts / ("lisa.exe" if os.name == "nt" else "lisa")


def execute_group(
    executable: str,
    source: Path,
    directory: Path,
    runbook: str,
    location: str,
    image: str,
    names: List[str],
    subscription: str,
    vm_size: Optional[str] = None,
) -> Dict[str, Dict[str, str]]:
    if directory.exists():
        raise ValueError(f"Refusing to reuse stale results directory: {directory}")
    directory.mkdir(parents=True)
    token = azure_json(
        ["account", "get-access-token", "--resource", "https://management.azure.com/"]
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(source)
    environment["S_LISA_azure_arm_access_token"] = token["accessToken"]
    # Never reuse an environment left behind by the head execution.
    command = [
        executable,
        "--log_path",
        str(directory),
        "-r",
        runbook,
        "-v",
        f"subscription_id:{subscription}",
        "-v",
        f"location:{location}",
        "-v",
        f"marketplace_image:{image}",
        "-v",
        f"test_case_name:{case_pattern(names)}",
        "-v",
        "enable_tests:False",
        "-v",
        "auth_type:token",
        "-v",
        "deploy:True",
        "-v",
        "resource_group_name:",
        "-v",
        "keep_environment:no",
        "-v",
        "wait_delete:True",
        "-v",
        "concurrency:1",
    ]
    if vm_size:
        command.extend(["-v", f"vm_size:{vm_size}"])
    print(f"Running {directory.name}: {image}; cases={names}", flush=True)
    completed = subprocess.run(command, cwd=source, env=environment, check=False)
    outcomes = read_outcomes(directory, names)
    if completed.returncode and all(
        outcome["status"] == "passed" for outcome in outcomes.values()
    ):
        raise RuntimeError(
            f"LISA exited with {completed.returncode} despite PASS JUnit."
        )
    return outcomes


def validate_groups(groups: List[Dict[str, Any]], repo_root: Path) -> None:
    catalog = reviewed_images(repo_root)
    for group in groups:
        if group["marketplace_image"] not in catalog:
            raise ValueError("Validation image is not in the reviewed catalog.")
        if not group["cases"] or any(
            not isinstance(name, str) or not re.fullmatch(r"\w+\.\w+", name)
            for name in group["cases"]
        ):
            raise ValueError("Invalid or empty validation case list.")
        if not set(group["required_cases"]).issubset(group["cases"]):
            raise ValueError("Required cases are missing from the execution group.")


def compare_group(
    result: Dict[str, Any],
    names: List[str],
    repo_root: Path,
    runbook: str,
    subscription: str,
    index: int,
    baseline_directory: Path,
) -> None:
    directory = (
        Path("runtime") / "pr-validation" / "head" / f"group-{index}"
    ).resolve()
    head = execute_group(
        "lisa",
        repo_root,
        directory,
        runbook,
        result["location"],
        result["image"],
        names,
        subscription,
    )
    result["cases"] = {
        name: {
            "head": outcome,
            "comparison": (
                "not_required" if outcome["status"] == "passed" else "inconclusive"
            ),
        }
        for name, outcome in head.items()
    }
    failed = [
        name
        for name, outcome in head.items()
        if outcome["status"] in ("failed", "error")
    ]
    if failed and result["base_sha"]:
        sizes = deployment_sizes(directory)
        result["vm_sizes"] = sizes
        result["configuration_signature"] = deployment_signature(directory)
        scripts = (
            baseline_directory / "venv" / ("Scripts" if os.name == "nt" else "bin")
        )
        executable = scripts / ("lisa.exe" if os.name == "nt" else "lisa")
        if not executable.exists():
            executable = prepare_baseline(
                repo_root, result["base_sha"], baseline_directory
            )
        base_directory = (
            Path("runtime") / "pr-validation" / "base" / f"group-{index}"
        ).resolve()
        base = execute_group(
            str(executable),
            baseline_directory / "source",
            base_directory,
            runbook,
            result["location"],
            result["image"],
            failed,
            subscription,
            sizes[0],
        )
        if deployment_sizes(base_directory) != sizes:
            raise ValueError("Base/head deployed VM topologies differ.")
        if deployment_signature(base_directory) != result["configuration_signature"]:
            raise ValueError("Base/head deployment configurations differ.")
        for name in failed:
            result["cases"][name].update(
                base=base[name], comparison=compare_outcomes(head[name], base[name])
            )
    acceptable = all(
        outcome["status"] == "passed"
        or result["cases"][name]["comparison"] == "same_failure"
        for name, outcome in head.items()
    )
    if not acceptable:
        raise RuntimeError("New failure or incomplete baseline comparison.")
    result["status"] = "same_failure" if failed else "passed"


def cleanup_baseline(repo_root: Path, directory: Path) -> None:
    source = directory / "source"
    if source.exists():
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(source)],
            cwd=repo_root,
            check=True,
        )
    environment = directory / "venv"
    if environment.exists():
        shutil.rmtree(environment)


def run_plan(
    plan_path: Path, runbook: str, location: str, base_sha: Optional[str] = None
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan["status"] == "manual_required":
        raise ValueError(
            "manual_required: recommendations are NOT EXECUTED. "
            "Use a prepared dedicated platform/host; Azure execution is prohibited."
        )
    if plan["status"] == "not_required" and not plan["groups"]:
        print(plan["reason"])
        return
    if plan["status"] != "selected" or not plan["groups"]:
        raise ValueError("Invalid or empty validation plan.")
    groups = plan["groups"]
    validate_groups(groups, repo_root)
    # Resolve every target before deploying any guests. Never replace an unavailable
    # target with a different distro or leave "latest" unresolved in the run record.
    images = [resolve_image(group["marketplace_image"], location) for group in groups]
    account = azure_json(["account", "show"])
    head_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True
    ).strip()
    if base_sha:
        if not re.fullmatch(r"[0-9a-f]{40}", base_sha):
            raise ValueError("Baseline must be a fixed full commit SHA.")
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", base_sha, head_sha],
            cwd=repo_root,
            check=True,
        )
    runbook_path = Path(runbook)
    if runbook_path.is_absolute():
        runbook_path = runbook_path.resolve().relative_to(repo_root)
    if ".." in runbook_path.parts:
        raise ValueError("Runbook must be inside the checked-out repository.")
    runbook = str(runbook_path)
    baseline_directory = (Path("runtime") / "pr-validation" / "baseline").resolve()
    if baseline_directory.exists():
        raise ValueError(
            f"Refusing to reuse stale baseline directory: {baseline_directory}"
        )
    results: List[Dict[str, Any]] = []
    report_path = plan_path.with_name("pr_validation_results.json")
    for index, (group, image) in enumerate(zip(groups, images)):
        # LISA resolves relative log paths under its own runtime root.
        result: Dict[str, Any] = {
            "image": image,
            "location": location,
            "status": "running",
            "details": "",
            "head_sha": head_sha,
            "base_sha": base_sha,
            "cases": {},
        }
        results.append(result)
        report_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        try:
            compare_group(
                result,
                group["cases"],
                repo_root,
                runbook,
                account["id"],
                index,
                baseline_directory,
            )
        except (
            ValueError,
            RuntimeError,
            OSError,
            ElementTree.ParseError,
            subprocess.CalledProcessError,
        ) as error:
            result.update(status="failed", details=str(error))
            print(f"Validation group {index} failed: {error}", flush=True)
        report_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    cleanup_baseline(repo_root, baseline_directory)
    if any(result["status"] not in ("passed", "same_failure") for result in results):
        raise RuntimeError(f"Validation incomplete or failed; see {report_path}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", default="ai_selected_cases.json", type=Path)
    parser.add_argument("--runbook", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument(
        "--base-sha", help="Fixed target commit for failure-only reruns"
    )
    args = parser.parse_args()
    run_plan(args.plan, args.runbook, args.location, args.base_sha)
