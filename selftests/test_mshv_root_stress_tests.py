# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
import sys
from pathlib import Path, PurePath
from types import SimpleNamespace
from typing import Any, List, cast
from unittest import TestCase
from unittest.mock import MagicMock, patch

# The mshv test suite modules import their siblings via the top-level
# ``microsoft`` namespace (e.g. ``from microsoft.testsuites.mshv...``), which
# only resolves when the worktree's ``lisa`` package directory is on sys.path.
# Insert it (ahead of any installed copy) so the suite under test is imported
# from this worktree.
_LISA_PKG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "lisa"))
if _LISA_PKG_DIR not in sys.path:
    sys.path.insert(0, _LISA_PKG_DIR)

from microsoft.testsuites.mshv import (  # noqa: E402
    mshv_root_stress_tests as mshv_module,
)
from microsoft.testsuites.mshv.mshv_root_stress_tests import (  # noqa: E402
    MshvHostStressTestSuite,
)

from lisa.messages import TestStatus  # noqa: E402
from lisa.util import LisaException, SkippedException  # noqa: E402

# A single log line carrying the exact unsupported VmCreate + EINVAL signature.
_UNSUPPORTED_LINE = (
    "cloud-hypervisor: Error booting VM: VmBoot(VmCreate(Kernel returned "
    "errno: Invalid argument (os error 22)))"
)
_UNSUPPORTED_OUTPUT = (
    f"{_UNSUPPORTED_LINE}\nthread 'vmm' panicked at vmm/src/vm.rs:1445"
)


class MshvHostStressTestSuiteTestCase(TestCase):
    _suite_type = cast(Any, MshvHostStressTestSuite).__wrapped__

    def _new_suite(self) -> Any:
        return self._suite_type.__new__(self._suite_type)

    def _make_result(
        self, stdout: str = "", stderr: str = "", exit_code: int = 1
    ) -> SimpleNamespace:
        return SimpleNamespace(stdout=stdout, stderr=stderr, exit_code=exit_code)

    def _make_node(self) -> MagicMock:
        node = MagicMock()
        node.get_working_path.return_value = PurePath("/home/user")
        node.working_path = PurePath("/home/user")
        node.tools = {
            mshv_module.Ls: MagicMock(),
            mshv_module.Cp: MagicMock(),
            mshv_module.Rm: MagicMock(),
            mshv_module.Free: MagicMock(),
            mshv_module.Lscpu: MagicMock(),
            mshv_module.Uname: MagicMock(),
            mshv_module.CloudHypervisor: MagicMock(),
        }
        node.tools[mshv_module.Ls].path_exists.return_value = True
        node.tools[
            mshv_module.Uname
        ].get_linux_information.return_value = SimpleNamespace(
            kernel_version_raw="6.6.0-mshv"
        )
        return node

    def _run_iterations(
        self,
        suite: Any,
        node: MagicMock,
        *,
        times: int = 1,
        cpus_per_vm: int = 1,
        thread_count: int = 1,
        guest_vm_type: str = "NON-CVM",
        config_id: int = 0,
    ) -> None:
        suite._get_disk_img_copy_path = MagicMock(
            return_value=PurePath("/mnt/resource")
        )
        node.tools[mshv_module.Lscpu].get_thread_count.return_value = thread_count
        suite._mshv_stress_vm_create(
            times=times,
            cpus_per_vm=cpus_per_vm,
            mem_per_vm_mb=1024,
            log=MagicMock(),
            node=node,
            log_path=Path("."),
            guest_vm_type=guest_vm_type,
            config_id=config_id,
        )

    # ------------------------------------------------------------------
    # (1) batching + timing: launch the whole batch, one shared grace,
    #     original total keep-running duration preserved.
    # ------------------------------------------------------------------
    def test_batch_launches_before_grace_and_preserves_duration(self) -> None:
        suite = self._new_suite()
        node = self._make_node()

        procs = [MagicMock(name=f"p{i}") for i in range(3)]
        for p in procs:
            p.is_running.return_value = True

        events: List[Any] = []
        proc_iter = iter(procs)

        def start_side(**kwargs: Any) -> MagicMock:
            events.append(("start", kwargs["log_file"]))
            return next(proc_iter)

        node.tools[mshv_module.CloudHypervisor].start_vm_async.side_effect = start_side

        def sleep_side(duration: float) -> None:
            events.append(("sleep", duration))

        with patch.object(mshv_module.time, "sleep", sleep_side):
            self._run_iterations(suite, node, thread_count=3, cpus_per_vm=1)

        starts = [e for e in events if e[0] == "start"]
        sleeps = [e[1] for e in events if e[0] == "sleep"]
        first_sleep_idx = next(idx for idx, e in enumerate(events) if e[0] == "sleep")

        # The whole batch is launched before any wait (no per-VM blocking).
        self.assertEqual(len(starts), 3)
        self.assertTrue(all(events[i][0] == "start" for i in range(first_sleep_idx)))
        # Total keep-running duration for NON-CVM stays at the original 10s
        # (grace + remainder), not vm_count * 10s.
        self.assertEqual(sleeps, [5, 5])
        self.assertEqual(sum(sleeps), 10)
        for p in procs:
            # Killed by the main stop loop (the finally net may re-kill mocks
            # whose is_running() stays True; real processes report not-running).
            self.assertTrue(p.kill.called)

    # ------------------------------------------------------------------
    # (2) CVM gating + same-line matching
    # ------------------------------------------------------------------
    def test_matches_unsupported_requires_same_line(self) -> None:
        suite = self._new_suite()
        self.assertTrue(suite._matches_unsupported_vm_create(_UNSUPPORTED_LINE))
        self.assertTrue(suite._matches_unsupported_vm_create(_UNSUPPORTED_OUTPUT))
        self.assertTrue(
            suite._matches_unsupported_vm_create(
                "boot error: VmCreate(Kernel returned errno: EINVAL)"
            )
        )
        # Near miss: VmCreate and the EINVAL indicator on different lines.
        self.assertFalse(
            suite._matches_unsupported_vm_create(
                "VmCreate failed to build the VM\nlater: open: os error 22"
            )
        )
        # VmCreate with a non-EINVAL error.
        self.assertFalse(
            suite._matches_unsupported_vm_create("VmCreate(KvmError(os error 12))")
        )
        self.assertFalse(suite._matches_unsupported_vm_create(""))

    def test_cvm_early_exit_with_signature_is_skipped(self) -> None:
        suite = self._new_suite()
        node = self._make_node()
        proc = MagicMock()
        proc.is_running.return_value = False
        proc.wait_result.return_value = self._make_result(stderr=_UNSUPPORTED_OUTPUT)

        with self.assertRaises(SkippedException) as ctx:
            suite._check_early_exits(
                [proc],
                [PurePath("/mnt/resource/CH_VM0_iter0.log")],
                node,
                Path("."),
                MagicMock(),
                "CVM",
                "startup",
            )
        message = str(ctx.exception)
        self.assertIn("VmCreate", message)
        self.assertIn("6.6.0-mshv", message)

    def test_non_cvm_early_exit_with_signature_fails(self) -> None:
        suite = self._new_suite()
        node = self._make_node()
        proc = MagicMock()
        proc.is_running.return_value = False
        proc.wait_result.return_value = self._make_result(stderr=_UNSUPPORTED_OUTPUT)

        with self.assertRaises(LisaException) as ctx:
            suite._check_early_exits(
                [proc],
                [PurePath("/mnt/resource/CH_VM0_iter0.log")],
                node,
                Path("."),
                MagicMock(),
                "NON-CVM",
                "startup",
            )
        # Standard VMs never treat the signature as unsupported.
        self.assertNotIsInstance(ctx.exception, SkippedException)

    def test_cvm_hard_failure_dominates_unsupported(self) -> None:
        suite = self._new_suite()
        node = self._make_node()
        unsupported = MagicMock()
        unsupported.is_running.return_value = False
        unsupported.wait_result.return_value = self._make_result(
            stderr=_UNSUPPORTED_OUTPUT
        )
        hard_fail = MagicMock()
        hard_fail.is_running.return_value = False
        hard_fail.wait_result.return_value = self._make_result(
            stderr="thread 'vmm' panicked: GuestMemory error", exit_code=101
        )

        with self.assertRaises(LisaException) as ctx:
            suite._check_early_exits(
                [unsupported, hard_fail],
                [
                    PurePath("/mnt/resource/CH_VM0_iter0.log"),
                    PurePath("/mnt/resource/CH_VM1_iter0.log"),
                ],
                node,
                Path("."),
                MagicMock(),
                "CVM",
                "startup",
            )
        self.assertNotIsInstance(ctx.exception, SkippedException)

    # ------------------------------------------------------------------
    # (3) post-start race: a VM that exits after the startup grace must be
    #     captured at the pre-stop check, but counted (not raised) so later
    #     iterations still run.
    # ------------------------------------------------------------------
    def test_post_start_exit_classified_at_pre_stop(self) -> None:
        suite = self._new_suite()
        node = self._make_node()
        proc = MagicMock()
        # Running at startup, exited by the pre-stop check.
        proc.is_running.side_effect = [True, False]
        proc.wait_result.return_value = self._make_result(
            stderr="thread 'vmm' panicked: late crash", exit_code=134
        )
        log_files = [PurePath("/mnt/resource/CH_VM0_iter0.log")]

        # First pass sees it running -> nothing counted, nothing raised.
        self.assertEqual(
            suite._check_early_exits(
                [proc], log_files, node, Path("."), MagicMock(), "NON-CVM", "startup"
            ),
            0,
        )
        # Second pass sees the late exit and counts it as a deferred failure
        # instead of raising, so the caller can keep running.
        self.assertEqual(
            suite._check_early_exits(
                [proc], log_files, node, Path("."), MagicMock(), "NON-CVM", "pre-stop"
            ),
            1,
        )

    def test_pre_stop_crash_defers_failure_until_all_iterations_run(self) -> None:
        # A VM that crashes after its keep-running period in iteration 1 must
        # not stop the run: later iterations still execute and the config fails
        # only after every iteration has completed.
        suite = self._new_suite()
        node = self._make_node()

        # proc0 is running at startup, then found dead at pre-stop in iter 1.
        proc0 = MagicMock(name="p0")
        calls = {"n": 0}

        def proc0_running() -> bool:
            calls["n"] += 1
            # Only the startup check (first call) sees it running.
            return calls["n"] == 1

        proc0.is_running.side_effect = proc0_running
        proc0.wait_result.return_value = self._make_result(
            stderr="thread 'vmm' panicked: late crash", exit_code=134
        )
        # proc1 (iteration 2) stays healthy for the whole iteration.
        proc1 = MagicMock(name="p1")
        proc1.is_running.return_value = True
        node.tools[mshv_module.CloudHypervisor].start_vm_async.side_effect = [
            proc0,
            proc1,
        ]

        with patch.object(mshv_module.time, "sleep", lambda _d: None):
            with self.assertRaises(AssertionError) as ctx:
                self._run_iterations(suite, node, times=2, thread_count=1)

        # Both iterations ran -- iteration 2 started despite the iter-1 crash.
        self.assertEqual(
            node.tools[mshv_module.CloudHypervisor].start_vm_async.call_count, 2
        )
        # The already-exited VM is never signalled; the healthy one is torn down.
        proc0.kill.assert_not_called()
        self.assertTrue(proc1.kill.called)
        # Failure is reported only after completing all iterations.
        self.assertIn(
            "exited unexpectedly after the keep-running period",
            str(ctx.exception),
        )

    # ------------------------------------------------------------------
    # (5) iteration-unique log names
    # ------------------------------------------------------------------
    def test_unique_log_names_across_iterations(self) -> None:
        suite = self._new_suite()
        node = self._make_node()
        procs = [MagicMock(name=f"p{i}") for i in range(2)]
        for p in procs:
            p.is_running.return_value = True
        node.tools[mshv_module.CloudHypervisor].start_vm_async.side_effect = procs

        with patch.object(mshv_module.time, "sleep", lambda _d: None):
            self._run_iterations(suite, node, times=2, thread_count=1)

        log_files = [
            call.kwargs["log_file"]
            for call in node.tools[
                mshv_module.CloudHypervisor
            ].start_vm_async.call_args_list
        ]
        self.assertEqual(len(log_files), 2)
        self.assertEqual(len(set(log_files)), 2)
        self.assertTrue(any("CH_VM0_cfg0_iter0" in f for f in log_files))
        self.assertTrue(any("CH_VM0_cfg0_iter1" in f for f in log_files))

        removed = [
            call.args[0]
            for call in node.tools[mshv_module.Rm].remove_file.call_args_list
        ]
        self.assertTrue(any("CH_VM0_cfg0_iter0" in r for r in removed))
        self.assertTrue(any("CH_VM0_cfg0_iter1" in r for r in removed))

    def test_unique_log_names_across_configs(self) -> None:
        # Two configs that would otherwise produce identical per-iteration log
        # names must still get distinct artifact names via the config
        # discriminator, so a later config cannot overwrite earlier evidence.
        suite = self._new_suite()
        node = self._make_node()
        procs = [MagicMock(name=f"p{i}") for i in range(2)]
        for p in procs:
            p.is_running.return_value = True
        node.tools[mshv_module.CloudHypervisor].start_vm_async.side_effect = procs

        with patch.object(mshv_module.time, "sleep", lambda _d: None):
            self._run_iterations(suite, node, times=1, thread_count=1, config_id=0)
            self._run_iterations(suite, node, times=1, thread_count=1, config_id=1)

        log_files = [
            call.kwargs["log_file"]
            for call in node.tools[
                mshv_module.CloudHypervisor
            ].start_vm_async.call_args_list
        ]
        self.assertEqual(len(log_files), 2)
        self.assertEqual(len(set(log_files)), 2)
        self.assertTrue(any("CH_VM0_cfg0_iter0" in f for f in log_files))
        self.assertTrue(any("CH_VM0_cfg1_iter0" in f for f in log_files))

    # ------------------------------------------------------------------
    # (4) root-owned CH logs are staged/made readable before copy_back;
    #     preservation failures surface as warnings.
    # ------------------------------------------------------------------
    def test_preserve_root_owned_log_stages_before_copy_back(self) -> None:
        suite = self._new_suite()
        node = self._make_node()
        log = MagicMock()

        suite._preserve_vm_log(
            node, PurePath("/mnt/resource/CH_VM0_iter0.log"), Path("artifacts"), log
        )

        commands = [call.args[0] for call in node.execute.call_args_list]
        self.assertTrue(any(cmd.startswith("cp -f ") for cmd in commands))
        self.assertTrue(any(cmd.startswith("chmod a+r ") for cmd in commands))
        for call in node.execute.call_args_list:
            self.assertTrue(call.kwargs.get("sudo"))
            # Staging must assert success so a failed cp/chmod cannot be
            # mistaken for preserved evidence.
            self.assertEqual(call.kwargs.get("expected_exit_code"), 0)
        # copy_back reads the staged, user-readable copy (never the root file)
        # and the staged name is distinct from the original log name.
        node.shell.copy_back.assert_called_once()
        staged_arg = node.shell.copy_back.call_args.args[0]
        self.assertEqual(
            PurePath(staged_arg), PurePath("/home/user/.staged_CH_VM0_iter0.log")
        )

    def test_preserve_root_owned_log_warns_on_failure(self) -> None:
        suite = self._new_suite()
        node = self._make_node()
        node.shell.copy_back.side_effect = OSError("permission denied")
        log = MagicMock()

        suite._preserve_vm_log(
            node, PurePath("/mnt/resource/CH_VM0_iter0.log"), Path("."), log
        )

        log.warning.assert_called_once()

    def test_preserve_retains_original_when_staging_under_working_path(self) -> None:
        # When the disk-image copy path falls back to node.working_path, the
        # remote log already lives under working_path. Staging must use a
        # distinct name so a copy_back failure never removes the original log
        # (its only remaining evidence) as if it were the staged copy.
        suite = self._new_suite()
        node = self._make_node()
        node.working_path = PurePath("/home/user")
        remote_log_path = PurePath("/home/user/CH_VM0_cfg0_iter0.log")
        node.shell.copy_back.side_effect = OSError("transport closed")
        log = MagicMock()

        suite._preserve_vm_log(node, remote_log_path, Path("."), log)

        removed = [
            call.args[0]
            for call in node.tools[mshv_module.Rm].remove_file.call_args_list
        ]
        # The staged copy is cleaned up, but the original log is never removed.
        staged = str(node.working_path / ".staged_CH_VM0_cfg0_iter0.log")
        self.assertIn(staged, removed)
        self.assertNotIn(str(remote_log_path), removed)
        log.warning.assert_called_once()

    # ------------------------------------------------------------------
    # (6) parent subtest reporting semantics
    # ------------------------------------------------------------------
    def _run_parent(self, side_effects: List[Any]) -> MagicMock:
        suite = self._new_suite()
        suite._mshv_stress_vm_create = MagicMock(side_effect=side_effects)
        self._worker_mock = suite._mshv_stress_vm_create

        configs = [{"iterations": i + 1} for i in range(len(side_effects))]
        node = MagicMock()
        ssh = MagicMock()
        ch = MagicMock()
        node.tools = {mshv_module.Ssh: ssh, mshv_module.CloudHypervisor: ch}

        send_mock = MagicMock()
        with patch.object(mshv_module, "send_sub_test_result_message", send_mock):
            self._parent_error: Any = None
            try:
                suite.stress_mshv_vm_create(
                    log=MagicMock(),
                    node=node,
                    variables={MshvHostStressTestSuite.CONFIG_VARIABLE: configs},
                    log_path=Path("."),
                    result=MagicMock(),
                )
            except BaseException as e:  # noqa: B036
                self._parent_error = e
        ch.save_dmesg_logs.assert_called_once()
        return send_mock

    def test_parent_mixed_pass_skip_fail_reports_and_fails(self) -> None:
        send_mock = self._run_parent(
            [None, SkippedException("unsupported"), LisaException("boom")]
        )
        statuses = [call.kwargs["test_status"] for call in send_mock.call_args_list]
        self.assertEqual(
            statuses, [TestStatus.PASSED, TestStatus.SKIPPED, TestStatus.FAILED]
        )
        self.assertIsInstance(self._parent_error, AssertionError)

    def test_parent_pass_and_skip_without_failures_passes(self) -> None:
        send_mock = self._run_parent([None, SkippedException("unsupported")])
        statuses = [call.kwargs["test_status"] for call in send_mock.call_args_list]
        self.assertEqual(statuses, [TestStatus.PASSED, TestStatus.SKIPPED])
        self.assertIsNone(self._parent_error)

    def test_parent_all_skipped_skips_parent(self) -> None:
        send_mock = self._run_parent(
            [SkippedException("unsupported"), SkippedException("unsupported")]
        )
        statuses = [call.kwargs["test_status"] for call in send_mock.call_args_list]
        self.assertEqual(statuses, [TestStatus.SKIPPED, TestStatus.SKIPPED])
        self.assertIsInstance(self._parent_error, SkippedException)

    def test_parent_passes_distinct_config_ids(self) -> None:
        # The parent must hand each config a distinct discriminator so the
        # worker can build collision-free artifact names across configs.
        self._run_parent([None, None, None])
        config_ids = [
            call.kwargs["config_id"] for call in self._worker_mock.call_args_list
        ]
        self.assertEqual(config_ids, [0, 1, 2])

    # ------------------------------------------------------------------
    # (6) reliable partial cleanup when a later VM fails
    # ------------------------------------------------------------------
    def test_partial_cleanup_on_later_vm_failure(self) -> None:
        suite = self._new_suite()
        node = self._make_node()

        procs = [MagicMock(name=f"p{i}") for i in range(3)]
        procs[0].is_running.return_value = True
        procs[1].is_running.return_value = True
        # The third VM exits early with a non-signature failure (NON-CVM).
        procs[2].is_running.return_value = False
        procs[2].wait_result.return_value = self._make_result(
            stderr="thread 'vmm' panicked: boom", exit_code=101
        )
        node.tools[mshv_module.CloudHypervisor].start_vm_async.side_effect = procs

        with patch.object(mshv_module.time, "sleep", lambda _d: None):
            with self.assertRaises(LisaException):
                self._run_iterations(suite, node, thread_count=3, cpus_per_vm=1)

        # Already-running VMs are torn down; the exited one is not re-killed.
        procs[0].kill.assert_called_once()
        procs[1].kill.assert_called_once()
        procs[2].kill.assert_not_called()

        removed = [
            call.args[0]
            for call in node.tools[mshv_module.Rm].remove_file.call_args_list
        ]
        for i in range(3):
            disk = str(PurePath("/mnt/resource") / f"VM{i}_{suite.DISK_IMG_NAME}")
            log_file = str(PurePath("/mnt/resource") / f"CH_VM{i}_cfg0_iter0.log")
            self.assertIn(disk, removed)
            self.assertIn(log_file, removed)
        # Evidence for the failing VM is preserved (staged + copied back).
        self.assertGreaterEqual(node.shell.copy_back.call_count, 1)
