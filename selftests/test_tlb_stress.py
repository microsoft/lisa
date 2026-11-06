# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from unittest import TestCase
from unittest.mock import MagicMock, patch

from lisa.microsoft.testsuites.stress.tlb_stress import (
    PerformanceMetrics,
    TlbStress,
)
from lisa.util import LisaException
from lisa.util.process import ExecutableResult


class TlbStressTestCase(TestCase):
    def test_finish_capture_uses_perf_duration_and_ipi_sampling_interval(self) -> None:
        tool = object.__new__(TlbStress)
        tool._get_proc_interrupts = MagicMock(
            side_effect=[
                {"resched": 100, "call_function": 200},
                {"resched": 145, "call_function": 260},
            ]
        )
        result = ExecutableResult(
            "1000 dTLB-load-misses",
            "45.0 seconds time elapsed",
            0,
            "perf stat",
            "test",
            100.0,
        )

        with patch(
            "lisa.microsoft.testsuites.stress.tlb_stress.time.monotonic",
            return_value=70.0,
        ):
            metrics = tool._finish_performance_capture(
                result,
                "dTLB-load-misses",
                45,
                {"resched": 100, "call_function": 200},
                None,
                10.0,
            )

        self.assertEqual(metrics.measurement_duration, 45.0)
        self.assertEqual(metrics.ipi_measurement_duration, 60.0)
        self.assertAlmostEqual(metrics.dtlb_load_misses_per_sec, 1000 / 45)

    def test_finish_capture_rejects_short_perf_duration(self) -> None:
        tool = object.__new__(TlbStress)
        result = ExecutableResult(
            "1000 dTLB-load-misses",
            "44.0 seconds time elapsed",
            0,
            "perf stat",
            "test",
            100.0,
        )

        with self.assertRaisesRegex(LisaException, "duration: 44.0"):
            tool._finish_performance_capture(
                result,
                "dTLB-load-misses",
                45,
                {"resched": 100},
                None,
                10.0,
            )

    def test_ipi_analysis_uses_interrupt_sampling_intervals(self) -> None:
        tool = object.__new__(TlbStress)
        tool._log = MagicMock()
        baseline = PerformanceMetrics(
            measurement_duration=100,
            ipi_measurement_duration=10,
            perf_event_rates={"dTLB-load-misses": 1},
            ipi_deltas={"resched": 100},
        )
        stress = PerformanceMetrics(
            measurement_duration=100,
            ipi_measurement_duration=20,
            perf_event_rates={"dTLB-load-misses": 1},
            ipi_deltas={"resched": 200},
        )

        with patch.object(tool, "detect_environment_type", return_value=False):
            with patch.object(tool, "_check_kernel_health_issues", return_value=[]):
                analysis = tool.analyze_performance_degradation(baseline, stress)

        self.assertEqual(analysis["metrics"]["ipi_increase_percent"], 0)
