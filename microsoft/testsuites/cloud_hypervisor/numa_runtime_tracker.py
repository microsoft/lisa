# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
NUMA Runtime Test Result Tracker

TEMPORARY: For real-time variance tracking during test execution.
Remove this file after Phase 3 validation is complete.

Tracks test iterations and generates summary statistics at test completion.
"""

import json
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class IterationResult:
    """Single test iteration result."""

    iteration: int
    value: float  # throughput, IOPS, latency, etc.
    unit: str
    timestamp: str
    duration_sec: float


@dataclass
class TestSummary:
    """Statistical summary of all test iterations."""

    test_name: str
    total_iterations: int
    mean: float
    std_dev: float
    cv_percent: float
    min_value: float
    max_value: float
    median: float
    p95: float
    p99: float
    unit: str
    total_duration_sec: float
    numa_enabled: bool
    numa_policy: Optional[str] = None
    cross_numa_access: Optional[bool] = None
    irq_locality_enabled: Optional[bool] = None
    variance_risk_factors: Optional[List[str]] = None


class NumaRuntimeTracker:
    """
    Track test iterations and generate summary statistics.

    TEMPORARY: Remove after validation complete.

    Usage:
        tracker = NumaRuntimeTracker(test_name="block_fio_random_read")

        # During test execution (each iteration)
        tracker.add_iteration(value=1234.5, unit="IOPS", duration_sec=60.0)

        # At test completion
        summary = tracker.get_summary(numa_config={...})
        tracker.print_summary()
        tracker.save_summary(output_dir)
    """

    def __init__(self, test_name: str):
        self.test_name = test_name
        self.iterations: List[IterationResult] = []
        self.numa_config: Dict = {}

    def add_iteration(self, value: float, unit: str, duration_sec: float = 0.0) -> None:
        """Add a test iteration result."""
        iteration = IterationResult(
            iteration=len(self.iterations) + 1,
            value=value,
            unit=unit,
            timestamp=datetime.now().isoformat(),
            duration_sec=duration_sec,
        )
        self.iterations.append(iteration)

    def get_summary(self, numa_config: Optional[Dict] = None) -> TestSummary:
        """
        Generate statistical summary of all iterations.

        Args:
            numa_config: Optional NUMA metadata from ch_tests_tool
        """
        if numa_config:
            self.numa_config = numa_config

        if not self.iterations:
            raise ValueError(f"No iterations recorded for {self.test_name}")

        values = [it.value for it in self.iterations]
        durations = [it.duration_sec for it in self.iterations]

        mean_val = statistics.mean(values)
        std_dev = statistics.stdev(values) if len(values) > 1 else 0.0
        cv_percent = (std_dev / mean_val * 100) if mean_val > 0 else 0.0

        sorted_values = sorted(values)
        n = len(sorted_values)
        p95_idx = int(n * 0.95)
        p99_idx = int(n * 0.99)

        summary = TestSummary(
            test_name=self.test_name,
            total_iterations=len(self.iterations),
            mean=mean_val,
            std_dev=std_dev,
            cv_percent=cv_percent,
            min_value=min(values),
            max_value=max(values),
            median=statistics.median(values),
            p95=sorted_values[p95_idx] if p95_idx < n else sorted_values[-1],
            p99=sorted_values[p99_idx] if p99_idx < n else sorted_values[-1],
            unit=self.iterations[0].unit,
            total_duration_sec=sum(durations),
            numa_enabled=self.numa_config.get("numa_enabled", False),
            numa_policy=self.numa_config.get("policy"),
            cross_numa_access=self.numa_config.get("cross_numa_access"),
            irq_locality_enabled=self.numa_config.get("irq_affinity", {}).get(
                "enabled"
            ),
            variance_risk_factors=self.numa_config.get("variance_risk_factors"),
        )

        return summary

    def print_summary(self) -> None:
        """Print formatted test summary to console."""
        summary = self.get_summary()

        print("\n" + "=" * 80)
        print(f"📊 TEST SUMMARY: {summary.test_name}")
        print("=" * 80)

        # Configuration info
        print("\n⚙️  Configuration:")
        print(f"   NUMA Enabled:        {summary.numa_enabled}")
        if summary.numa_enabled:
            numa_policy_str = summary.numa_policy or "N/A"
            print(f"   NUMA Policy:         {numa_policy_str}")
            cross_numa = summary.cross_numa_access or False
            print(f"   Cross-NUMA Access:   {cross_numa}")
            irq_locality = summary.irq_locality_enabled or False
            print(f"   IRQ Locality:        {irq_locality}")
            if summary.variance_risk_factors:
                risks = ", ".join(summary.variance_risk_factors)
                print(f"   ⚠️  Risk Factors:      {risks}")

        # Statistical summary
        iterations_str = f"{summary.total_iterations} iterations"
        print(f"\n📈 Statistics ({iterations_str}):")
        print(f"   Mean:                {summary.mean:.2f} {summary.unit}")
        print(f"   Std Dev:             {summary.std_dev:.2f} {summary.unit}")
        print(f"   CV% (σ/μ×100):       {summary.cv_percent:.2f}%")
        print(f"   Min:                 {summary.min_value:.2f} {summary.unit}")
        print(f"   Median:              {summary.median:.2f} {summary.unit}")
        print(f"   Max:                 {summary.max_value:.2f} {summary.unit}")
        print(f"   P95:                 {summary.p95:.2f} {summary.unit}")
        print(f"   P99:                 {summary.p99:.2f} {summary.unit}")

        # Variance quality indicator
        print("\n🎯 Variance Quality:")
        if summary.cv_percent < 5:
            print("   ✅ Excellent (CV% < 5%)")
        elif summary.cv_percent < 10:
            print("   ✅ Good (CV% < 10%)")
        elif summary.cv_percent < 20:
            print("   ⚠️  Moderate (CV% < 20%)")
        else:
            print("   ❌ High variance (CV% ≥ 20%)")

        # Runtime info
        avg_duration = summary.total_duration_sec / summary.total_iterations
        print("\n⏱️  Runtime:")
        print(f"   Total Duration:      {summary.total_duration_sec:.1f} sec")
        print(f"   Avg per Iteration:   {avg_duration:.1f} sec")

        print("=" * 80 + "\n")

    def print_iterations_table(self) -> None:
        """Print detailed iteration results in table format."""
        if not self.iterations:
            return

        print(f"\n📋 Iteration Details: {self.test_name}")
        print("-" * 80)
        headers = (
            f"{'Iter':<6} {'Value':<15} {'Unit':<10} "
            f"{'Duration':<12} {'Timestamp':<20}"
        )
        print(headers)
        print("-" * 80)

        for it in self.iterations:
            print(
                f"{it.iteration:<6} "
                f"{it.value:<15.2f} "
                f"{it.unit:<10} "
                f"{it.duration_sec:<12.1f} "
                f"{it.timestamp:<20}"
            )

        print("-" * 80 + "\n")

    def save_summary(self, output_dir: Path) -> Path:
        """
        Save summary and iteration details to JSON.

        Returns:
            Path to saved summary file
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        summary = self.get_summary()

        # Prepare output data
        output = {
            "summary": asdict(summary),
            "iterations": [asdict(it) for it in self.iterations],
            "numa_config": self.numa_config,
        }

        # Save to file
        summary_file = output_dir / f"{self.test_name}_runtime_summary.json"
        with open(summary_file, "w") as f:
            json.dump(output, f, indent=2)

        print(f"💾 Saved summary to: {summary_file}")
        return summary_file

    def compare_with_baseline(self, baseline_file: Path) -> Dict:
        """
        Compare current results with baseline run.

        TEMPORARY: For quick comparison during testing.

        Args:
            baseline_file: Path to baseline summary JSON

        Returns:
            Dict with comparison metrics
        """
        baseline_file = Path(baseline_file)
        if not baseline_file.exists():
            return {"error": f"Baseline file not found: {baseline_file}"}

        with open(baseline_file) as f:
            baseline_data = json.load(f)

        baseline_summary = baseline_data.get("summary", {})
        current_summary = asdict(self.get_summary())

        baseline_mean = baseline_summary.get("mean", 0)
        baseline_cv = baseline_summary.get("cv_percent", 0)

        current_mean = current_summary.get("mean", 0)
        current_cv = current_summary.get("cv_percent", 0)

        mean_delta_pct = (
            ((current_mean - baseline_mean) / baseline_mean * 100)
            if baseline_mean > 0
            else 0
        )
        cv_delta_pct = (
            ((current_cv - baseline_cv) / baseline_cv * 100) if baseline_cv > 0 else 0
        )
        cv_absolute_delta = current_cv - baseline_cv

        # Determine improvement status
        improved = current_cv < baseline_cv
        regressed = current_cv > baseline_cv and mean_delta_pct < -5

        comparison = {
            "test_name": self.test_name,
            "baseline_mean": baseline_mean,
            "current_mean": current_mean,
            "performance_diff_percent": round(mean_delta_pct, 2),
            "baseline_cv": baseline_cv,
            "current_cv": current_cv,
            "cv_delta_pct": round(cv_delta_pct, 2),
            "variance_improvement_percent": round(-cv_absolute_delta, 2),
            "improved": improved,
            "regressed": regressed,
            "status": (
                "✅ Improved"
                if improved
                else ("❌ Regressed" if regressed else "➖ Neutral")
            ),
        }

        return comparison

    def print_comparison(self, baseline_file: Path) -> None:
        """Print formatted comparison with baseline."""
        comparison = self.compare_with_baseline(baseline_file)

        if "error" in comparison:
            print(f"⚠️  {comparison['error']}")
            return

        print("\n" + "=" * 80)
        print(f"🔬 BASELINE COMPARISON: {comparison['test_name']}")
        print("=" * 80)

        print("\n📊 Throughput:")
        print(f"   Baseline:            {comparison['baseline_mean']:.2f}")
        print(f"   Current:             {comparison['current_mean']:.2f}")
        print(f"   Δ Mean:              {comparison['performance_diff_percent']:+.2f}%")

        print("\n📉 Variance (CV%):")
        print(f"   Baseline CV%:        {comparison['baseline_cv']:.2f}%")
        print(f"   Current CV%:         {comparison['current_cv']:.2f}%")
        cv_delta_pct = comparison["cv_delta_pct"]
        print(f"   Δ CV% (relative):    {cv_delta_pct:+.2f}%")
        cv_improvement = comparison["variance_improvement_percent"]
        print(f"   Δ CV% (absolute):    {cv_improvement:+.2f}%")

        print("\n🎯 Result:")
        print(f"   {comparison['status']}")

        print("=" * 80 + "\n")


# Example integration with ch_tests_tool.py
# TEMPORARY: Remove after validation


def example_usage():
    """Example of how to integrate with test execution."""

    # In ch_tests_tool.py, at start of metrics test:
    # tracker = NumaRuntimeTracker(test_name=testcase)

    # After each iteration:
    # tracker.add_iteration(value=iops_value, unit="IOPS", duration_sec=60.0)

    # At test completion:
    # summary = tracker.get_summary(numa_config=self._get_numa_metadata())
    # tracker.print_summary()
    # tracker.print_iterations_table()
    # tracker.save_summary(log_path)

    # Optional: Compare with baseline if available
    # baseline_file = log_path / f"{testcase}_baseline_runtime_summary.json"
    # if baseline_file.exists():
    #     tracker.print_comparison(baseline_file)

    pass


if __name__ == "__main__":
    # Demo usage
    tracker = NumaRuntimeTracker(test_name="block_fio_random_read_4k")

    # Simulate 10 test iterations
    import random

    for i in range(10):
        # Simulated IOPS with some variance
        iops = random.gauss(50000, 2500)
        tracker.add_iteration(value=iops, unit="IOPS", duration_sec=60.0)

    # Print summary
    tracker.print_summary()
    tracker.print_iterations_table()

    # Example NUMA config
    numa_config = {
        "numa_enabled": False,
        "policy": None,
        "cross_numa_access": False,
        "irq_affinity": {"enabled": False},
        "variance_risk_factors": [],
    }

    # Save with NUMA config
    tracker.get_summary(numa_config)
    tracker.save_summary(Path("./demo_output"))
