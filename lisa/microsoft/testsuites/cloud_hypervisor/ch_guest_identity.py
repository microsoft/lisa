# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
import xml.etree.ElementTree as ETree  # noqa: N817
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from lisa.util import filter_ansi_escape

SourceSnapshot = Dict[Path, Tuple[int, int]]

WORKLOAD_PROVENANCE_PROBE = r"""
import hashlib
import json
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

MAX_HASH_BYTES = 256 * 1024 * 1024
root = Path("/root/workloads")
report = {
    "collected_at_utc": datetime.now(timezone.utc).isoformat(),
    "capture_phase": "after_harness",
    "scope": "available_inputs_not_confirmed_per_guest",
    "files": [],
    "errors": [],
}
try:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
        timeout=10, check=False,
    )
    if revision.returncode:
        report["errors"].append(
            f"git rev-parse failed: {revision.stdout}\n{revision.stderr}"
        )
    else:
        report["ch_revision"] = revision.stdout.strip()
except (OSError, subprocess.TimeoutExpired) as error:
    report["errors"].append(f"Cannot read CH revision: {error}")

for directory in (root, root / "igvm_files"):
    try:
        entries = sorted(directory.iterdir())
    except FileNotFoundError as error:
        if directory == root:
            report["errors"].append(str(error))
        continue
    except OSError as error:
        report["errors"].append(str(error))
        continue
    for path in entries:
        if path.suffix.lower() in (".raw", ".qcow2", ".img", ".vhd", ".vhdx"):
            kind = "disk_image"
        elif path.name.startswith(("vmlinux", "bzImage", "Image")):
            kind = "kernel"
        elif path.suffix.lower() in (".igvm", ".bin", ".elf", ".fd"):
            kind = "kernel_or_firmware"
        elif path.name == "hypervisor-fw":
            kind = "firmware"
        else:
            continue
        entry = {"path": str(path), "kind": kind}
        report["files"].append(entry)
        try:
            before = path.lstat()
            if not stat.S_ISREG(before.st_mode):
                entry["status"] = "not_a_regular_file_not_read"
                continue
            entry.update(
                status="available", size_bytes=before.st_size,
                mtime_ns=before.st_mtime_ns,
            )
            if kind == "disk_image":
                entry["sha256_status"] = "not_collected_for_disk_images"
            elif before.st_size > MAX_HASH_BYTES:
                entry["sha256_status"] = "exceeds_256_MiB_limit"
            else:
                digest = hashlib.sha256()
                size = 0
                with path.open("rb") as stream:
                    while True:
                        data = stream.read(1024 * 1024)
                        if not data:
                            break
                        size += len(data)
                        if size > MAX_HASH_BYTES:
                            raise OSError("File grew beyond the 256 MiB hash limit")
                        digest.update(data)
                after = path.lstat()
                if (
                    (before.st_ino, before.st_size, before.st_mtime_ns)
                    != (after.st_ino, after.st_size, after.st_mtime_ns)
                    or size != before.st_size
                ):
                    raise OSError("File changed during provenance collection")
                entry.update(sha256=digest.hexdigest(), sha256_status="collected")
        except OSError as error:
            entry.update(status="unavailable", error=str(error))
            report["errors"].append(f"{path}: {error}")

report["status"] = (
    "partial" if report["errors"] else "collected" if report["files"] else "empty"
)
output = Path(sys.argv[1])
output.write_text(json.dumps(report, indent=2), encoding="utf-8")
output.chmod(0o644)
"""

_CHILD_MARKER = re.compile(r"^==== (Start|End) child (stdout|stderr) ====$")
_KERNEL_BANNER = re.compile(
    r"^(?:<\d+>)?(?:\[\s*\d+(?:\.\d+)?\]\s*)?Linux version (\S+)(?:\s|$)"
)
_DISTRO_BANNER = re.compile(r"^Welcome to (.+)!$")
_OS_RELEASE_LINE = re.compile(
    r"^(PRETTY_NAME|NAME|ID|ID_LIKE|VERSION|VERSION_ID)=(.*)$"
)


def extract_console_identity(lines: Iterable[str]) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for number, raw in enumerate(lines, 1):
        line = filter_ansi_escape(raw).strip()
        marker = _CHILD_MARKER.fullmatch(line)
        if marker:
            action, stream = marker.groups()
            if action == "Start":
                framing = "incomplete"
                if current is not None:
                    current["framing"] = "ambiguous"
                    framing = "ambiguous"
                current = {
                    "child_stream": stream,
                    "start_line": number,
                    "framing": framing,
                    "observations": [],
                }
                blocks.append(current)
            elif current is not None:
                if current["child_stream"] != stream:
                    current["framing"] = "ambiguous"
                elif current["framing"] != "ambiguous":
                    current["framing"] = "complete"
                current["end_line"] = number
                current = None
            continue
        if current is None:
            continue
        observation: Dict[str, Any] = {"line": number, "text": line}
        kernel = _KERNEL_BANNER.match(line)
        distro = _DISTRO_BANNER.fullmatch(line)
        os_release = _OS_RELEASE_LINE.fullmatch(line)
        if kernel:
            observation.update(kind="kernel_banner", value=kernel.group(1))
        elif distro:
            observation.update(kind="distro_banner", value=distro.group(1))
        elif os_release:
            observation.update(
                kind="os_release_style_line",
                key=os_release.group(1),
                value=os_release.group(2),
            )
        else:
            continue
        current["observations"].append(observation)
    return blocks


def snapshot_guest_sources(
    log_path: Path, test_name: str, nextest: bool
) -> SourceSnapshot:
    pattern = re.compile(rf"{re.escape(test_name)}(?:\.attempt\d+)?\.log")
    paths = [
        path
        for path in log_path.glob(f"{test_name}*.log")
        if pattern.fullmatch(path.name)
    ]
    if nextest:
        paths.extend((log_path / "junit").glob("*.xml"))
    snapshot: SourceSnapshot = {}
    for path in sorted(paths):
        info = path.stat()
        snapshot[path] = (info.st_mtime_ns, info.st_size)
    return snapshot


def create_guest_identity_report(
    log_path: Path,
    test_name: str,
    nextest: bool,
    previous_sources: Optional[SourceSnapshot],
    provenance: Dict[str, Any],
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "schema_version": 1,
        "test_name": test_name,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_identity": {
            "status": "unavailable",
            "reason": "LISA does not query the CH harness's guests for identity.",
            "kernel_version": None,
            "distro": None,
            "guest_id": None,
            "boot_id": None,
        },
        "configured_provenance": provenance,
        "console_evidence_status": "unavailable",
        "console_sources": [],
        "errors": [],
    }
    if previous_sources is None:
        report["errors"].append("Before-run log snapshot unavailable; ignoring logs.")
        return report
    try:
        sources = snapshot_guest_sources(log_path, test_name, nextest)
    except OSError as error:
        report["errors"].append(f"Cannot enumerate CH output: {error}")
        return report

    has_observations = False
    has_current_source = False
    for path, signature in sources.items():
        source: Dict[str, Any] = {"path": path.relative_to(log_path).as_posix()}
        report["console_sources"].append(source)
        if previous_sources.get(path) == signature:
            source["status"] = "unchanged_since_start_not_used"
            continue
        try:
            outputs: List[Dict[str, Any]] = []
            if path.suffix == ".xml":
                root = ETree.parse(path).getroot()
                cases = []
                for case_index, case in enumerate(root.iter("testcase")):
                    case_outputs = []
                    for output_index, element in enumerate(
                        item
                        for item in case.iter()
                        if item.tag in ("system-out", "system-err")
                    ):
                        output: Dict[str, Any] = {
                            "stream": element.tag,
                            "output_index": output_index,
                            "line_basis": "output_element_text",
                            "blocks": extract_console_identity(
                                (element.text or "").splitlines()
                            ),
                        }
                        case_outputs.append(output)
                        outputs.append(output)
                    cases.append(
                        {
                            "testcase_index": case_index,
                            "subtest": case.get("name"),
                            "classname": case.get("classname"),
                            "outputs": case_outputs,
                        }
                    )
                source.update(scope="subtest_not_individual_guest", cases=cases)
            else:
                with path.open(encoding="utf-8") as stream:
                    output = {
                        "line_basis": "file",
                        "blocks": extract_console_identity(stream),
                    }
                outputs.append(output)
                source.update(
                    scope="harness_unattributed",
                    subtest=None,
                    outputs=outputs,
                )
            source["status"] = "read"
            has_current_source = True
            has_observations = has_observations or any(
                block["observations"]
                for output in outputs
                for block in output["blocks"]
            )
        except (OSError, UnicodeError, ETree.ParseError) as error:
            source.update(status="unavailable", error=str(error))
            report["errors"].append(f"Cannot read {source['path']}: {error}")
    if has_current_source:
        report["console_evidence_status"] = (
            "observations_only" if has_observations else "no_identity_markers"
        )
    return report
