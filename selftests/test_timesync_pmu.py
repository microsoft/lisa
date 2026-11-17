# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from inspect import unwrap
from typing import Dict
from unittest import TestCase
from unittest.mock import Mock, patch

from lisa import LisaException, Logger, SkippedException, TestSuiteMetadata
from lisa.microsoft.testsuites.core.timesync import TimeSync, _run_pmu_diagnostic
from lisa.operating_system import CpuArchitecture
from lisa.tools import Cat, Lscpu
from lisa.util.process import ExecutableResult


def _result(stdout: str = "", stderr: str = "", exit_code: int = 0) -> ExecutableResult:
    return ExecutableResult(stdout, stderr, exit_code, "pmu probe", "1", 0.1)


class PmuDiagnosticTestCase(TestCase):
    def setUp(self) -> None:
        self.suite = unwrap(TimeSync)(
            TestSuiteMetadata("time", "functional", "PMU selftest")
        )
        self.node = Mock()
        self.log = Mock(spec=Logger)
        self.lscpu = Mock()
        self.lscpu.get_architecture.return_value = CpuArchitecture.ARM64
        self.cat = Mock()
        self.cat.run.return_value = _result(
            "quiet initcall_blacklist=arm_pmu_acpi_init"
        )
        self.node.tools = {Cat: self.cat, Lscpu: self.lscpu}
        self.results: Dict[str, ExecutableResult] = {}
        self.node.execute.side_effect = self._execute
        config_patch = patch("lisa.microsoft.testsuites.core.timesync.KernelConfig")
        self.config_type = config_patch.start()
        self.addCleanup(config_patch.stop)
        self.config = self.config_type.return_value
        self.config.exists = True
        self.config.config_path = "/boot/config-test"

    def _execute(self, command: str, **kwargs: object) -> ExecutableResult:
        if command in self.results:
            return self.results[command]
        if command.startswith("cat /boot/config"):
            return _result(
                "CONFIG_ARM_PMUV3=y\n# CONFIG_ARM_SPE_PMU is not set\n"
                "CONFIG_UNRELATED=y"
            )
        if command == "dmesg --color=never":
            return _result("unrelated boot message\nhw perfevents: PMU enabled")
        if command == "command -v perf":
            return _result("/usr/bin/perf")
        if command == "perf --version":
            return _result("perf version 6.12")
        return _result("diagnostic output")

    def _run_case(self) -> None:
        self.suite.verify_pmu_disabled_for_arm64(self.node, self.log)

    def _messages(self) -> str:
        return "\n".join(
            str(call.args[0])
            for call in self.log.info.call_args_list + self.log.warning.call_args_list
        )

    def test_non_arm64_skips_before_diagnostics(self) -> None:
        self.lscpu.get_architecture.return_value = CpuArchitecture.X64
        with self.assertRaises(SkippedException):
            self._run_case()
        self.cat.run.assert_not_called()
        self.node.execute.assert_not_called()
        self.config_type.assert_not_called()

    def test_missing_legacy_token_collects_before_failure(self) -> None:
        self.cat.run.return_value = _result("quiet")
        with self.assertRaisesRegex(LisaException, "Legacy PMU command-line"):
            self._run_case()
        commands = [call.args[0] for call in self.node.execute.call_args_list]
        self.assertTrue(any("perf stat" in command for command in commands))
        self.assertTrue(any("perf record" in command for command in commands))
        self.assertIn("not a functional CPU PMU verdict", self._messages())

    def test_legacy_token_passes_without_functional_verdict(self) -> None:
        self._run_case()
        self.cat.run.assert_called_once_with("/proc/cmdline", force_run=True)
        self.assertIn("legacy gate", self._messages())
        self.assertIn("count_cycles", self._messages())
        self.assertIn("sample_cycles", self._messages())

    def test_cpu_driver_token_alone_keeps_legacy_failure(self) -> None:
        self.cat.run.return_value = _result("initcall_blacklist=armv8_pmu_driver_init")
        with self.assertRaisesRegex(LisaException, "Legacy PMU command-line"):
            self._run_case()

    def test_cmdline_read_error_is_not_a_missing_token(self) -> None:
        self.cat.run.return_value = _result("", "read failed", 1)
        with self.assertRaisesRegex(AssertionError, "Unable to read /proc/cmdline"):
            self._run_case()
        self.node.execute.assert_not_called()

    def test_missing_perf_is_explicit_and_never_installed(self) -> None:
        self.results["command -v perf"] = _result("", "", 1)
        self._run_case()
        commands = [call.args[0] for call in self.node.execute.call_args_list]
        self.assertNotIn("perf --version", commands)
        self.assertFalse(any("perf stat" in command for command in commands))
        self.assertIn("perf is not installed or discoverable", self._messages())

    def test_unusable_perf_wrapper_skips_functional_probes(self) -> None:
        self.results["perf --version"] = _result("", "matching tools missing", 127)
        self._run_case()
        commands = [call.args[0] for call in self.node.execute.call_args_list]
        self.assertFalse(any("perf stat" in command for command in commands))
        self.assertIn("installed perf is not usable", self._messages())

    def test_permission_error_is_logged_not_treated_as_disabled(self) -> None:
        self.node.execute.side_effect = lambda command, **kwargs: (
            _result("", "Permission denied", 255)
            if command.startswith("perf stat") and "-e cycles " in command
            else self._execute(command, **kwargs)
        )
        self._run_case()
        self.assertIn("Permission denied", self._messages())
        self.assertIn("not proof that the CPU PMU is disabled", self._messages())
        self.assertIn("count_instructions", self._messages())
        self.assertIn("sample_cycles", self._messages())

    def test_missing_config_does_not_prevent_other_probes(self) -> None:
        self.config.exists = False
        self._run_case()
        self.assertIn("kernel configuration is unavailable", self._messages())
        self.assertIn("count_cycles", self._messages())

    def test_gzip_config_reuses_discovery_and_filters_output(self) -> None:
        self.config.config_path = "/proc/config.gz"
        self.results["zcat /proc/config.gz"] = _result(
            "CONFIG_ARM_PMUV3=y\nCONFIG_UNRELATED=y"
        )
        self._run_case()
        self.config_type.assert_called_once_with(self.node)
        self.config.initialize.assert_called_once_with()
        self.assertIn("CONFIG_ARM_PMUV3=y", self._messages())
        self.assertNotIn("CONFIG_UNRELATED", self._messages())

    def test_probes_are_bounded_and_do_not_change_configuration(self) -> None:
        self._run_case()
        for call in self.node.execute.call_args_list:
            self.assertEqual(call.kwargs["timeout"], 15)
            self.assertEqual(call.kwargs["update_envs"], {"LC_ALL": "C"})
            self.assertFalse(
                any(
                    forbidden in call.args[0]
                    for forbidden in [
                        "sysctl -w",
                        "grubby",
                        "update-grub",
                        "reboot",
                        "dnf ",
                        "apt ",
                    ]
                )
            )
        commands = [call.args[0] for call in self.node.execute.call_args_list]
        sampling = next(command for command in commands if "perf record" in command)
        self.assertIn("--no-buildid --no-buildid-cache -o /dev/null", sampling)

    def test_failed_probe_preserves_unfiltered_error_output(self) -> None:
        self.results["probe"] = _result("unfiltered failure", "stderr detail", 2)
        result = _run_pmu_diagnostic(
            self.node, self.log, "test", "probe", filter_pattern="will not match"
        )
        self.assertEqual(result.exit_code, 2)
        self.assertIn("command:\nprobe", self._messages())
        self.assertIn("unfiltered failure", self._messages())
        self.assertIn("stderr detail", self._messages())

    def test_timed_out_probe_is_explicit(self) -> None:
        result = _result("", "probe timed out", -15)
        result.is_timeout = True
        self.results["probe"] = result
        _run_pmu_diagnostic(self.node, self.log, "test", "probe")
        self.assertIn("timed_out=True", self._messages())
        self.assertIn("probe timed out", self._messages())
        self.assertIn("not proof that the CPU PMU is disabled", self._messages())

    def test_no_matching_boot_messages_is_not_a_pmu_verdict(self) -> None:
        self.results["dmesg --color=never"] = _result("unrelated boot message")
        self._run_case()
        self.assertIn("<no matching lines>", self._messages())
        self.assertIn("not a functional CPU PMU verdict", self._messages())
