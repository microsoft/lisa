# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import hashlib
import json
import runpy
import stat
import subprocess
import xml.etree.ElementTree as ETree  # noqa: N817
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any, Dict, Iterator
from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.microsoft.testsuites.cloud_hypervisor.ch_guest_identity import (
    WORKLOAD_PROVENANCE_PROBE,
    create_guest_identity_report,
    extract_console_identity,
    snapshot_guest_sources,
)


def _console(*lines: str) -> str:
    return (
        "==== Start child stdout ====\n"
        + "\n".join(lines)
        + "\n==== End child stdout ====\n"
    )


class ConsoleIdentityTestCase(TestCase):
    def test_ignores_host_and_firmware_text_outside_child_output(self) -> None:
        content = (
            "Linux version 6.99-host (host-builder)\n"
            "Booting from ubuntu\nBoot Failed: ubuntu\n"
            "Welcome to Microsoft Azure Linux 3.0!\n"
            + _console(
                "[    0.000000] Linux version 6.12-guest (guest-builder)",
                "\x1b[1mWelcome to Ubuntu 22.04.5 LTS!\x1b[0m",
            )
            + "Linux version 6.99-host (host-builder)\n"
        )
        blocks = extract_console_identity(content.splitlines())
        self.assertEqual(1, len(blocks))
        self.assertEqual("complete", blocks[0]["framing"])
        self.assertEqual(
            ["6.12-guest", "Ubuntu 22.04.5 LTS"],
            [item["value"] for item in blocks[0]["observations"]],
        )
        self.assertEqual(6, blocks[0]["observations"][0]["line"])

    def test_keeps_multiple_kernel_versions_without_choosing_one(self) -> None:
        blocks = extract_console_identity(
            _console(
                "Linux version 6.10-old (builder)",
                "Linux version 6.12-new (builder)",
                'PRETTY_NAME="Ubuntu 24.04.1 LTS"',
                'ID="$(not-a-command)"',
            ).splitlines()
        )
        self.assertEqual(4, len(blocks[0]["observations"]))
        self.assertEqual('"$(not-a-command)"', blocks[0]["observations"][-1]["value"])
        self.assertEqual("os_release_style_line", blocks[0]["observations"][-1]["kind"])

    def test_records_incomplete_and_ambiguous_framing(self) -> None:
        for ending, expected in (
            ("", "incomplete"),
            ("==== End child stderr ====", "ambiguous"),
            ("==== Start child stderr ====", "ambiguous"),
        ):
            with self.subTest(ending=ending):
                blocks = extract_console_identity(
                    (
                        "==== Start child stdout ====\n"
                        "Linux version 6.12-guest (builder)\n" + ending
                    ).splitlines()
                )
                self.assertEqual(expected, blocks[0]["framing"])

    def test_empty_child_output_is_not_identity_evidence(self) -> None:
        blocks = extract_console_identity(_console("").splitlines())
        self.assertEqual([], blocks[0]["observations"])


class GuestIdentityReportTestCase(TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.name = "ch_integration_mshv"
        self.log = self.root / f"{self.name}.log"
        self.junit = self.root / "junit" / "common.xml"
        self.junit.parent.mkdir()
        self.provenance: Dict[str, Any] = {
            "status": "collected",
            "files": [{"path": "/root/workloads/ubuntu.qcow2"}],
        }

    def _report(self) -> Dict[str, Any]:
        return create_guest_identity_report(
            self.root, self.name, True, {}, self.provenance
        )

    def test_junit_includes_retry_output_and_cases_without_output(self) -> None:
        root = ETree.Element("testsuites")
        suite = ETree.SubElement(root, "testsuite")
        case = ETree.SubElement(
            suite, "testcase", name="common::test_net", classname="integration"
        )
        retry = ETree.SubElement(case, "rerunFailure")
        ETree.SubElement(retry, "system-err").text = _console(
            "Welcome to Ubuntu 22.04.5 LTS!"
        )
        ETree.SubElement(case, "system-out").text = _console(
            "Linux version 6.12-new (builder)"
        )
        ETree.SubElement(suite, "testcase", name="common::test_pass")
        ETree.ElementTree(root).write(self.junit, encoding="utf-8")
        report = self._report()
        source = report["console_sources"][0]
        self.assertEqual("junit/common.xml", source["path"])
        reported_case = source["cases"][0]
        self.assertEqual("common::test_net", reported_case["subtest"])
        self.assertEqual(2, len(reported_case["outputs"]))
        self.assertEqual("system-err", reported_case["outputs"][0]["stream"])
        self.assertEqual(1, reported_case["outputs"][1]["output_index"])
        self.assertEqual([], source["cases"][1]["outputs"])
        self.assertEqual("observations_only", report["console_evidence_status"])
        self.assertIsNone(report["runtime_identity"]["guest_id"])
        self.assertIsNone(report["runtime_identity"]["kernel_version"])
        self.assertIsNone(report["runtime_identity"]["distro"])

    def test_aggregate_is_unattributed_and_never_reads_host_serial(self) -> None:
        self.log.write_text(
            _console("Welcome to Ubuntu 22.04.5 LTS!"), encoding="utf-8"
        )
        for filename in ("serial_console.log", "node.log", "ch_other.log"):
            (self.root / filename).write_text(
                _console("Linux version 6.99-host (builder)"), encoding="utf-8"
            )
        report = self._report()
        self.assertEqual(1, len(report["console_sources"]))
        source = report["console_sources"][0]
        self.assertEqual("harness_unattributed", source["scope"])
        self.assertIsNone(source["subtest"])
        self.assertNotIn("6.99-host", json.dumps(report))

    def test_old_sources_are_not_misattributed_to_current_attempt(self) -> None:
        self.log.write_text(
            _console("Linux version 6.10-old (builder)"), encoding="utf-8"
        )
        before = snapshot_guest_sources(self.root, self.name, True)
        attempt = self.root / f"{self.name}.attempt2.log"
        attempt.write_text(
            _console("Linux version 6.12-new (builder)"), encoding="utf-8"
        )
        report = create_guest_identity_report(
            self.root, self.name, True, before, self.provenance
        )
        self.assertNotIn("6.10-old", json.dumps(report))
        self.assertIn("6.12-new", json.dumps(report))
        self.assertIn("unchanged_since_start_not_used", json.dumps(report))

    def test_overwritten_junit_is_current_evidence(self) -> None:
        self.junit.write_text("<testsuites/>", encoding="utf-8")
        before = snapshot_guest_sources(self.root, self.name, True)
        self.junit.write_text(
            "<testsuites><testcase name='new'/></testsuites>", encoding="utf-8"
        )
        report = create_guest_identity_report(
            self.root, self.name, True, before, self.provenance
        )
        self.assertEqual("new", report["console_sources"][0]["cases"][0]["subtest"])

    def test_missing_output_does_not_guess_distro_from_image_name(self) -> None:
        report = self._report()
        self.assertEqual("unavailable", report["console_evidence_status"])
        self.assertEqual("unavailable", report["runtime_identity"]["status"])
        self.assertIsNone(report["runtime_identity"]["distro"])
        self.assertEqual([], report["console_sources"])

    def test_malformed_junit_does_not_discard_valid_aggregate(self) -> None:
        self.junit.write_text("<testsuites", encoding="utf-8")
        self.log.write_text(
            _console("Linux version 6.12-guest (builder)"), encoding="utf-8"
        )
        report = self._report()
        self.assertEqual(1, len(report["errors"]))
        self.assertEqual("observations_only", report["console_evidence_status"])

    def test_invalid_encoding_is_reported_not_silently_replaced(self) -> None:
        self.log.write_bytes(b"\xff\xfe")
        report = self._report()
        self.assertEqual("unavailable", report["console_evidence_status"])
        self.assertEqual(1, len(report["errors"]))

    def test_missing_baseline_does_not_use_potentially_stale_logs(self) -> None:
        self.log.write_text(_console("Linux version 6.10-old"), encoding="utf-8")
        report = create_guest_identity_report(
            self.root, self.name, True, None, self.provenance
        )
        self.assertEqual([], report["console_sources"])
        self.assertEqual(1, len(report["errors"]))

    def test_metrics_does_not_read_unrelated_junit(self) -> None:
        self.junit.write_text("<testsuites/>", encoding="utf-8")
        self.assertEqual({}, snapshot_guest_sources(self.root, self.name, False))


class WorkloadProvenanceProbeTestCase(TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.workloads = self.root / "workloads"
        self.workloads.mkdir()
        self.output = self.root / "provenance.json"
        self.script = self.root / "probe.py"
        self.script.write_text(WORKLOAD_PROVENANCE_PROBE, encoding="utf-8")
        self.git = MagicMock(
            return_value=subprocess.CompletedProcess(["git"], 0, "a" * 40, "")
        )

    def _probe(self) -> Dict[str, Any]:
        original_iterdir = Path.iterdir

        def iterdir(path: Path) -> Iterator[Path]:
            # Never inspect the machine's real workloads directory in a selftest.
            self.assertIn(
                path.as_posix(), ("/root/workloads", "/root/workloads/igvm_files")
            )
            relative = path.relative_to(Path("/root/workloads"))
            return original_iterdir(self.workloads / relative)

        with patch.object(Path, "iterdir", iterdir), patch(
            "subprocess.run", self.git
        ), patch("sys.argv", ["probe", str(self.output)]):
            runpy.run_path(str(self.script), run_name="__main__")
        report: Dict[str, Any] = json.loads(self.output.read_text(encoding="utf-8"))
        return report

    def test_hashes_kernel_but_not_disks_and_ignores_unrelated_files(self) -> None:
        (self.workloads / "vmlinux-x86_64").write_bytes(b"custom kernel")
        (self.workloads / "jammy.qcow2").write_bytes(b"disk")
        (self.workloads / "credentials.toml").write_text(
            "token=do-not-read", encoding="utf-8"
        )
        report = self._probe()
        self.assertEqual("collected", report["status"])
        self.assertEqual("available_inputs_not_confirmed_per_guest", report["scope"])
        files = {Path(entry["path"]).name: entry for entry in report["files"]}
        self.assertEqual({"jammy.qcow2", "vmlinux-x86_64"}, set(files))
        self.assertEqual(
            hashlib.sha256(b"custom kernel").hexdigest(),
            files["vmlinux-x86_64"]["sha256"],
        )
        self.assertEqual(
            "not_collected_for_disk_images", files["jammy.qcow2"]["sha256_status"]
        )
        self.assertNotIn("sha256", files["jammy.qcow2"])
        self.assertNotIn("token", json.dumps(report))

    def test_collects_cvm_inputs_from_known_subdirectory(self) -> None:
        cvm = self.workloads / "igvm_files"
        cvm.mkdir()
        (cvm / "guest.igvm").write_bytes(b"igvm")
        (cvm / "guest.vhd").write_bytes(b"disk")
        report = self._probe()
        self.assertEqual(2, len(report["files"]))

    def test_does_not_open_devices_or_symlinks(self) -> None:
        kernel = self.workloads / "vmlinux-x86_64"
        kernel.touch()
        for mode in (stat.S_IFLNK, stat.S_IFBLK, stat.S_IFIFO):
            with self.subTest(mode=mode), patch.object(
                Path, "lstat", return_value=SimpleNamespace(st_mode=mode)
            ):
                report = self._probe()
            self.assertEqual(
                "not_a_regular_file_not_read", report["files"][0]["status"]
            )
            self.assertNotIn("sha256", report["files"][0])

    def test_exact_hash_size_limit_is_enforced(self) -> None:
        kernel = self.workloads / "vmlinux-x86_64"
        kernel.write_bytes(b"kernel")
        for size, expected in (
            (256 * 1024 * 1024, "unavailable"),
            (256 * 1024 * 1024 + 1, "available"),
        ):
            with self.subTest(size=size), patch.object(
                Path,
                "lstat",
                return_value=SimpleNamespace(
                    st_mode=stat.S_IFREG,
                    st_size=size,
                    st_mtime_ns=1,
                    st_ino=1,
                ),
            ):
                report = self._probe()
                entry = report["files"][0]
                self.assertEqual(expected, entry["status"])
                self.assertNotIn("sha256", entry)
                if size > 256 * 1024 * 1024:
                    self.assertEqual("exceeds_256_MiB_limit", entry["sha256_status"])
                else:
                    self.assertIn("changed during", entry["error"])

    def test_git_failure_is_explicit_and_does_not_hide_file_inventory(self) -> None:
        (self.workloads / "vmlinux-x86_64").write_bytes(b"kernel")
        self.git.return_value = subprocess.CompletedProcess(
            ["git"], 1, "git stdout", "git stderr"
        )
        report = self._probe()
        self.assertEqual("partial", report["status"])
        self.assertEqual(1, len(report["files"]))
        self.assertIn("git stdout", report["errors"][0])
        self.assertIn("git stderr", report["errors"][0])

    def test_missing_workloads_is_explicit(self) -> None:
        self.workloads.rmdir()
        report = self._probe()
        self.assertEqual("partial", report["status"])
        self.assertEqual([], report["files"])
        self.assertEqual(1, len(report["errors"]))
