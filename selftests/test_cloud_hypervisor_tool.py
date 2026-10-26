# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
import shlex
from contextlib import ExitStack
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple, Union, cast
from unittest import TestCase
from unittest.mock import MagicMock, mock_open, patch
from xml.etree import ElementTree

from lisa.executable import ExecutableResult
from lisa.messages import TestStatus
from lisa.microsoft.testsuites.cloud_hypervisor import ch_tests_tool
from lisa.microsoft.testsuites.cloud_hypervisor.ch_tests import CloudHypervisorTestSuite
from lisa.microsoft.testsuites.cloud_hypervisor.ch_tests_tool import (
    CloudHypervisorTests,
)
from lisa.microsoft.testsuites.mshv.cloud_hypervisor_tool import CloudHypervisor
from lisa.util import LisaException, SkippedException


class CloudHypervisorToolTestCase(TestCase):
    def _render_command(self, guest_vm_type: str) -> str:
        tool = CloudHypervisor.__new__(CloudHypervisor)
        with patch.object(tool, "run_async") as run_async:
            tool.start_vm_async(
                kernel="/kernel",
                cpus=2,
                memory_mb=1024,
                disk_path="/disk.img",
                sudo=True,
                guest_vm_type=guest_vm_type,
                igvm_path="/igvm",
                log_file="/vm.log",
            )

        return cast(str, run_async.call_args.args[0])

    def test_confidential_guest_types_disable_nested_virtualization(self) -> None:
        for guest_vm_type in ("CVM", "ConfidentialVM"):
            with self.subTest(guest_vm_type=guest_vm_type):
                command = self._render_command(guest_vm_type)

                self.assertIn("--cpus boot=2,nested=off", command)
                self.assertIn("--platform sev_snp=on", command)

    def test_non_cvm_launch_is_unchanged(self) -> None:
        command = self._render_command("NON-CVM")

        self.assertIn("--cpus boot=2 ", command)
        self.assertNotIn("nested=", command)
        self.assertIn("--kernel /kernel", command)
        self.assertNotIn("--platform sev_snp=on", command)


class CloudHypervisorSelectionTestCase(TestCase):
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.tool = CloudHypervisorTests.__new__(CloudHypervisorTests)
        node = MagicMock()
        node.tools = {CloudHypervisorTests: self.tool}
        node.features.is_supported.return_value = False
        self.tool.node = node
        self.tool._log = MagicMock()
        self.tool.repo_root = PurePosixPath("/cloud-hypervisor")
        self.tool.env_vars = {}
        self.tool.perf_stable_enabled = False
        suite_type = cast(Any, CloudHypervisorTestSuite).__wrapped__
        self.suite = suite_type.__new__(suite_type)
        self.stack.enter_context(
            patch.object(self.suite, "_get_hypervisor_param", return_value="mshv")
        )
        for method in (
            "_configure_environment_if_needed",
            "_ensure_cvm_integration_assets",
            "_setup_disk_for_metrics",
            "_ensure_host_setup",
            "_copy_back_artifacts",
            "_save_kernel_logs",
            "_check_test_panic_from_logs",
        ):
            self._patch(method)
        self.discovery = self._patch("run")
        self.workload = self._patch(
            "_run_with_enhanced_diagnostics",
            side_effect=RuntimeError("workload started"),
        )
        self.publication = self.stack.enter_context(
            patch.object(ch_tests_tool, "send_sub_test_result_message")
        )

    def _patch(self, method: str, **kwargs: Any) -> MagicMock:
        return cast(
            MagicMock,
            self.stack.enter_context(patch.object(self.tool, method, **kwargs)),
        )

    def _set_discovery(
        self,
        mode: str,
        names: List[str],
        exit_code: int = 0,
        is_timeout: bool = False,
    ) -> None:
        if mode == "perf":
            output = "\n".join(
                f'"{name}" (test_timeout = 10s, test_iterations = 5)' for name in names
            )
        else:
            output = json.dumps(
                {
                    "rust-suites": {
                        f"binary-{index}": {"testcases": {name: {}}}
                        for index, name in enumerate(names)
                    }
                }
            )
        self.discovery.reset_mock()
        self.workload.reset_mock()
        self.publication.reset_mock()
        self.discovery.return_value = ExecutableResult(
            _stdout=output,
            _stderr="discovery diagnostic",
            exit_code=exit_code,
            cmd="list",
            _id_="list",
            elapsed=0,
            is_timeout=is_timeout,
        )

    def _set_workload_output(
        self, stdout: str = "", junit: Optional[str] = None
    ) -> None:
        self.workload.side_effect = None
        self.workload.return_value = ExecutableResult(
            _stdout=stdout,
            _stderr="",
            exit_code=0,
            cmd="tests",
            _id_="tests",
            elapsed=0,
        )
        self._patch(
            "_collect_nextest_junit_files",
            return_value=[Path("unused.xml")] if junit is not None else [],
        )
        if junit is not None:
            self.stack.enter_context(
                patch.object(
                    ch_tests_tool.ETree,
                    "parse",
                    return_value=ElementTree.ElementTree(ElementTree.fromstring(junit)),
                )
            )

    def _run_selection(
        self,
        mode: str,
        requested: List[str],
        excluded: Optional[List[str]] = None,
        strict: Optional[Union[str, bool]] = True,
    ) -> None:
        family = "integration" if mode == "cvm" else mode
        case = "performance_metrics" if mode == "perf" else family
        variables: Dict[str, Any] = {
            f"ch_{family}_tests_included": ",".join(requested),
            f"ch_{family}_tests_excluded": ",".join(excluded or []),
        }
        if strict is not None:
            variables["ch_test_selection_strict"] = strict
        if mode == "cvm":
            variables["ch_integration_test_type"] = "integration-cvm"
        getattr(self.suite, f"verify_cloud_hypervisor_{case}_tests")(
            node=self.tool.node,
            log_path=Path("unused"),
            result=MagicMock(),
            variables=variables,
        )

    def test_strict_performance_rejects_non_exact_expansions(self) -> None:
        cases: List[Tuple[List[str], List[str]]] = [
            ([], ["latency"]),
            (["latency"], []),
            (["latency", "missing"], ["latency"]),
            (["latency"], ["latency", "latency_extra"]),
            (["latency", "latency"], ["latency"]),
            (["latency"], ["latency", "latency"]),
            (["latency", ""], ["latency"]),
        ]
        for requested, selected in cases:
            with self.subTest(requested=requested, selected=selected):
                self._set_discovery("perf", selected)
                with self.assertRaisesRegex(LisaException, "Strict Cloud Hypervisor"):
                    self._run_selection("perf", requested)
                self.workload.assert_not_called()

    def test_strict_performance_uses_filtered_discovery(self) -> None:
        self._set_discovery("perf", ["latency", "block_write"])
        with self.assertRaisesRegex(RuntimeError, "workload started"):
            self._run_selection("perf", ["block_write", "latency"], ["unrelated"])

        self.discovery.assert_called_once()
        args = shlex.split(self.discovery.call_args.args[0])
        self.assertIn("--list-tests", args)
        self.assertEqual("block_write,latency", args[args.index("--test-filter") + 1])
        self.assertEqual("unrelated", args[args.index("--test-exclude") + 1])
        self.workload.assert_called_once()
        self.assertNotIn("--timeout", self.workload.call_args.kwargs["cmd_args"])

    def test_strict_performance_rejects_partially_parsed_listing(self) -> None:
        self._set_discovery("perf", ["latency"])
        self.discovery.return_value.stdout += '\n"extra" (unrecognized control format)'
        with self.assertRaisesRegex(LisaException, "discovery could not parse"):
            self._run_selection("perf", ["latency"])
        self.workload.assert_not_called()

    def test_strict_integration_rejects_substring_skip_collision(self) -> None:
        self._set_discovery("integration", ["common::case", "common::case_extra"])
        with self.assertRaisesRegex(LisaException, "Strict Cloud Hypervisor"):
            self._run_selection("integration", ["common::case_extra"])
        self.workload.assert_not_called()

    def test_strict_integration_rejects_missing_and_duplicate_names(self) -> None:
        for mode, name in (
            ("integration", "common::case"),
            ("cvm", "common_cvm::case"),
            ("live_migration", "live_migration::case"),
        ):
            cases: List[Tuple[List[str], List[str]]] = [
                ([], [name]),
                ([name], []),
                ([name, "missing"], [name]),
                ([name, name], [name]),
                ([name], [name, name]),
            ]
            for requested, selected in cases:
                with self.subTest(mode=mode, requested=requested, selected=selected):
                    self._set_discovery(mode, selected)
                    with self.assertRaises(LisaException) as error:
                        self._run_selection(mode, requested)
                    self.assertNotIsInstance(error.exception, SkippedException)
                    self.workload.assert_not_called()

    def test_strict_live_migration_uses_exact_excludes(self) -> None:
        self._set_discovery(
            "live_migration",
            ["live_migration::case", "live_migration::case_extra"],
        )
        with self.assertRaisesRegex(RuntimeError, "workload started"):
            self._run_selection(
                "live_migration",
                ["live_migration::case_extra"],
                ["live_migration::case"],
            )
        self.workload.assert_called_once()
        command = self.workload.call_args.kwargs["cmd_args"]
        self.assertIn("test(=live_migration::case_extra)", command)
        self.assertIn("-test(=live_migration::case)", command)

    def test_strict_exclusion_cannot_remove_a_requested_name(self) -> None:
        for mode, name in (
            ("perf", "latency"),
            ("integration", "common::case"),
            ("cvm", "common_cvm::case"),
            ("live_migration", "live_migration::case"),
        ):
            with self.subTest(mode=mode):
                self._set_discovery(mode, [] if mode == "perf" else [name])
                with self.assertRaisesRegex(LisaException, "Strict Cloud Hypervisor"):
                    self._run_selection(mode, [name], [name])
                self.workload.assert_not_called()

    def test_strict_discovery_failure_stops_all_workloads(self) -> None:
        for mode, name in (
            ("perf", "latency"),
            ("integration", "common::case"),
            ("cvm", "common_cvm::case"),
            ("live_migration", "live_migration::case"),
        ):
            for exit_code, is_timeout in ((1, False), (0, True)):
                with self.subTest(mode=mode, exit_code=exit_code, timeout=is_timeout):
                    self._set_discovery(mode, [name], exit_code, is_timeout)
                    with self.assertRaisesRegex(LisaException, "discovery"):
                        self._run_selection(mode, [name])
                    self.workload.assert_not_called()

    def test_strict_valid_names_reach_workload(self) -> None:
        strict_values: List[Union[str, bool]] = [True, "True"]
        for mode, name in (
            ("perf", "latency"),
            ("integration", "common::case"),
            ("cvm", "common_cvm::case"),
            ("live_migration", "live_migration::case"),
        ):
            for strict in strict_values:
                with self.subTest(mode=mode, strict=strict):
                    self._set_discovery(mode, [name])
                    with self.assertRaisesRegex(RuntimeError, "workload started"):
                        self._run_selection(mode, [name], strict=strict)
                    self.discovery.assert_called_once()
                    self.workload.assert_called_once()

    def test_default_and_false_preserve_legacy_selection(self) -> None:
        strict_values: List[Optional[Union[str, bool]]] = [None, False, "False"]
        for strict in strict_values:
            for mode, requested, listed in (
                ("perf", ["latency"], ["latency", "latency_extra"]),
                (
                    "integration",
                    ["common::case_extra"],
                    ["common::case", "common::case_extra"],
                ),
                ("cvm", ["common_cvm::case", "missing"], ["common_cvm::case"]),
            ):
                with self.subTest(mode=mode, strict=strict):
                    self._set_discovery(mode, listed)
                    with self.assertRaisesRegex(RuntimeError, "workload started"):
                        self._run_selection(mode, requested, strict=strict)
                    self.workload.assert_called_once()
                    if mode == "perf":
                        self.discovery.assert_not_called()

            with self.subTest(mode="live_migration", strict=strict):
                self._set_discovery("live_migration", ["live_migration::case"])
                with self.assertRaises(SkippedException):
                    self._run_selection("live_migration", ["missing"], strict=strict)
                self.workload.assert_not_called()

    def test_strict_publication_omits_only_unrequested_skips(self) -> None:
        for mode, name in (
            ("integration", "common::case"),
            ("live_migration", "live_migration::case"),
        ):
            for strict in (True, False):
                with self.subTest(mode=mode, strict=strict):
                    self._set_discovery(mode, [name])
                    self._set_workload_output(
                        junit=(
                            f'<testsuite><testcase name="{name}"/>'
                            '<testcase name="unrequested"><skipped/></testcase>'
                            "</testsuite>"
                        )
                    )
                    self._run_selection(mode, [name], strict=strict)
                    published = {
                        call.kwargs["test_case_name"]: call.kwargs["test_status"]
                        for call in self.publication.call_args_list
                    }
                    expected = {name: TestStatus.PASSED}
                    if not strict:
                        expected["unrequested"] = TestStatus.SKIPPED
                    self.assertEqual(expected, published)

    def test_strict_publication_preserves_requested_skip(self) -> None:
        self._set_discovery("integration", ["common::case"])
        self._set_workload_output(
            junit='<testsuite><testcase name="common::case"><skipped/></testcase>'
            "</testsuite>"
        )
        self._run_selection("integration", ["common::case"])
        self.publication.assert_called_once()
        self.assertEqual(
            TestStatus.SKIPPED, self.publication.call_args.kwargs["test_status"]
        )

    def test_strict_publication_preserves_exact_name_case(self) -> None:
        for use_junit in (True, False):
            with self.subTest(junit=use_junit):
                self._set_discovery("integration", ["common::Case"])
                self._set_workload_output(
                    stdout="" if use_junit else "test common::Case ... ok",
                    junit=(
                        '<testsuite><testcase name="common::Case"/></testsuite>'
                        if use_junit
                        else None
                    ),
                )
                self._run_selection("integration", ["common::Case"])
                self.publication.assert_called_once()
                self.assertEqual(
                    "common::Case", self.publication.call_args.kwargs["test_case_name"]
                )
                self.assertEqual(
                    TestStatus.PASSED, self.publication.call_args.kwargs["test_status"]
                )

    def test_strict_publication_rejects_unexpected_executed_children(self) -> None:
        for use_junit in (True, False):
            with self.subTest(junit=use_junit):
                self._set_discovery("integration", ["common::case"])
                self._set_workload_output(
                    stdout=(
                        ""
                        if use_junit
                        else "test common::case ... ok\ntest unrequested ... ok"
                    ),
                    junit=(
                        '<testsuite><testcase name="common::case"/>'
                        '<testcase name="unrequested"/></testsuite>'
                        if use_junit
                        else None
                    ),
                )
                with self.assertRaisesRegex(LisaException, "unexpected"):
                    self._run_selection("integration", ["common::case"])
                self.publication.assert_not_called()

    def test_strict_metrics_does_not_publish_extra_or_unrecognized_results(
        self,
    ) -> None:
        reports = [
            [
                {"name": "latency", "status": "PASSED"},
                {"name": "unrequested", "status": "PASSED"},
            ],
            [{"name": "latency", "status": "SKIPPED"}],
            [{"name": "latency"}],
            [
                {"name": "latency", "status": "PASSED"},
                {"name": "latency", "status": "PASSED"},
            ],
            [],
        ]
        for report in reports:
            with self.subTest(report=report):
                self._set_discovery("perf", ["latency"])
                self._set_workload_output()
                with patch(
                    "builtins.open",
                    mock_open(read_data=json.dumps({"results": report})),
                ), self.assertRaisesRegex(
                    (LisaException, AssertionError), "Strict Cloud Hypervisor"
                ):
                    self._run_selection("perf", ["latency"])
                self.publication.assert_not_called()

    def test_strict_metrics_publishes_expected_results(self) -> None:
        self._set_discovery("perf", ["latency", "block_write"])
        self._set_workload_output()
        report = {
            "results": [
                {"name": "latency", "status": "PASSED"},
                {"name": "block_write", "status": "PASSED"},
            ]
        }
        with patch("builtins.open", mock_open(read_data=json.dumps(report))):
            self._run_selection("perf", ["block_write", "latency"])
        self.assertEqual(
            {"latency", "block_write"},
            {call.kwargs["test_case_name"] for call in self.publication.call_args_list},
        )
        self.assertEqual(2, self.publication.call_count)
        self.assertTrue(
            all(
                call.kwargs["test_status"] == TestStatus.PASSED
                for call in self.publication.call_args_list
            )
        )
