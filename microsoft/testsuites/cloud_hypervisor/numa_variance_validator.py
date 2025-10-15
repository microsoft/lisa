# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
NUMA Variance Validation Utilities

TEMPORARY: For testing/validation of NUMA improvements.
Remove this file after Phase 3 validation is complete.

Owner: TBD
Reviewers: TBD
"""

import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class TestVarianceResult:
    """Variance metrics for a single test."""
    test_name: str
    baseline_mean: float
    baseline_std: float
    baseline_cv: float
    numa_mean: float
    numa_std: float
    numa_cv: float
    mean_delta_pct: float
    cv_delta_pct: float
    runtime_delta_pct: float
    improved: bool
    regressed: bool


class NumaVarianceValidator:
    """
    Validate NUMA variance improvements against acceptance criteria.
    
    TEMPORARY: Remove after validation complete.
    """
    
    def __init__(self, baseline_dir: Path, numa_dir: Path):
        self.baseline_dir = baseline_dir
        self.numa_dir = numa_dir
        self.results: List[TestVarianceResult] = []
    
    def analyze_test_results(self) -> Dict:
        """
        Analyze variance results and generate executive summary.
        
        Returns:
            Dict with summary metrics and roll-forward decision
        """
        # Parse baseline and NUMA results
        baseline_data = self._parse_results_dir(self.baseline_dir)
        numa_data = self._parse_results_dir(self.numa_dir)
        
        # Compare each test
        for test_name in baseline_data.keys():
            if test_name not in numa_data:
                continue
            
            result = self._compare_test(
                test_name,
                baseline_data[test_name],
                numa_data[test_name]
            )
            self.results.append(result)
        
        # Generate summary
        return self._generate_summary()
    
    def _parse_results_dir(self, results_dir: Path) -> Dict[str, Dict]:
        """Parse test results from directory."""
        results = {}
        
        # Look for result JSON files
        for json_file in results_dir.glob("*_results.json"):
            try:
                with open(json_file) as f:
                    data = json.load(f)
                    test_name = json_file.stem.replace("_results", "")
                    results[test_name] = data
            except Exception:
                continue
        
        return results
    
    def _compare_test(
        self, 
        test_name: str, 
        baseline: Dict, 
        numa: Dict
    ) -> TestVarianceResult:
        """Compare baseline vs NUMA results for a single test."""
        
        # Extract metrics (assuming format: {runs: [val1, val2, ...], runtime: sec})
        baseline_runs = baseline.get("runs", [])
        numa_runs = numa.get("runs", [])
        
        baseline_mean = statistics.mean(baseline_runs) if baseline_runs else 0
        baseline_std = statistics.stdev(baseline_runs) if len(baseline_runs) > 1 else 0
        baseline_cv = (baseline_std / baseline_mean * 100) if baseline_mean > 0 else 0
        
        numa_mean = statistics.mean(numa_runs) if numa_runs else 0
        numa_std = statistics.stdev(numa_runs) if len(numa_runs) > 1 else 0
        numa_cv = (numa_std / numa_mean * 100) if numa_mean > 0 else 0
        
        mean_delta_pct = ((numa_mean - baseline_mean) / baseline_mean * 100) if baseline_mean > 0 else 0
        cv_delta_pct = ((numa_cv - baseline_cv) / baseline_cv * 100) if baseline_cv > 0 else 0
        
        baseline_runtime = baseline.get("runtime", 0)
        numa_runtime = numa.get("runtime", 0)
        runtime_delta_pct = ((numa_runtime - baseline_runtime) / baseline_runtime * 100) if baseline_runtime > 0 else 0
        
        # Determine improvement/regression
        improved = numa_cv < baseline_cv  # Lower CV% = improved
        regressed = numa_cv > baseline_cv and mean_delta_pct < -5  # Higher CV% + >5% throughput loss
        
        return TestVarianceResult(
            test_name=test_name,
            baseline_mean=baseline_mean,
            baseline_std=baseline_std,
            baseline_cv=baseline_cv,
            numa_mean=numa_mean,
            numa_std=numa_std,
            numa_cv=numa_cv,
            mean_delta_pct=mean_delta_pct,
            cv_delta_pct=cv_delta_pct,
            runtime_delta_pct=runtime_delta_pct,
            improved=improved,
            regressed=regressed,
        )
    
    def _generate_summary(self) -> Dict:
        """Generate executive summary with roll-forward criteria."""
        
        if not self.results:
            return {"error": "No test results found"}
        
        total_tests = len(self.results)
        tests_improved = sum(1 for r in self.results if r.improved)
        tests_regressed = sum(1 for r in self.results if r.regressed)
        
        improvement_pct = (tests_improved / total_tests * 100) if total_tests > 0 else 0
        regression_pct = (tests_regressed / total_tests * 100) if total_tests > 0 else 0
        
        mean_deltas = [r.mean_delta_pct for r in self.results]
        cv_deltas = [r.cv_delta_pct for r in self.results]
        runtime_deltas = [r.runtime_delta_pct for r in self.results]
        
        mean_delta_median = statistics.median(mean_deltas) if mean_deltas else 0
        cv_delta_median = statistics.median(cv_deltas) if cv_deltas else 0
        runtime_delta_median = statistics.median(runtime_deltas) if runtime_deltas else 0
        
        # Roll-forward criteria
        meets_improvement_target = improvement_pct >= 70.0
        meets_runtime_target = runtime_delta_median <= 10.0
        ship_decision = meets_improvement_target and meets_runtime_target
        
        summary = {
            "total_tests": total_tests,
            "tests_improved": tests_improved,
            "tests_regressed": tests_regressed,
            "improvement_pct": round(improvement_pct, 1),
            "regression_pct": round(regression_pct, 1),
            "mean_delta_median": round(mean_delta_median, 2),
            "cv_delta_median": round(cv_delta_median, 2),
            "runtime_delta_median": round(runtime_delta_median, 2),
            "meets_improvement_target": meets_improvement_target,
            "meets_runtime_target": meets_runtime_target,
            "ship_decision": ship_decision,
            "ship_criteria": "≥70% tests improve CV% AND runtime ≤+10%",
        }
        
        return summary
    
    def print_executive_summary(self) -> None:
        """Print formatted executive summary table."""
        summary = self._generate_summary()
        
        if "error" in summary:
            print(f"Error: {summary['error']}")
            return
        
        print("\n" + "="*80)
        print("NUMA VARIANCE IMPROVEMENTS - EXECUTIVE SUMMARY")
        print("="*80)
        print("\n📊 RESULTS TABLE")
        print("-"*80)
        print(f"{'Metric':<30} {'Value':<20} {'Target':<15} {'Status':<10}")
        print("-"*80)
        
        # Tests improved
        status = "✅ PASS" if summary["meets_improvement_target"] else "❌ FAIL"
        print(f"{'Tests Improved':<30} {summary['tests_improved']} ({summary['improvement_pct']}%){'':<5} {'≥70%':<15} {status:<10}")
        
        # Tests regressed
        status = "✅ PASS" if summary["regression_pct"] <= 30 else "⚠️  WARN"
        print(f"{'Tests Regressed':<30} {summary['tests_regressed']} ({summary['regression_pct']}%){'':<5} {'≤30%':<15} {status:<10}")
        
        # Mean delta
        status = "✅ PASS" if abs(summary["mean_delta_median"]) <= 2 else "⚠️  WARN"
        print(f"{'Mean Δ (Median)':<30} {summary['mean_delta_median']:+.2f}%{'':<13} {'≤±2%':<15} {status:<10}")
        
        # CV delta
        status = "✅ PASS" if summary["cv_delta_median"] < 0 else "❌ FAIL"
        print(f"{'CV% Δ (Median)':<30} {summary['cv_delta_median']:+.2f}%{'':<13} {'<0%':<15} {status:<10}")
        
        # Runtime delta
        status = "✅ PASS" if summary["meets_runtime_target"] else "❌ FAIL"
        print(f"{'Runtime Δ':<30} {summary['runtime_delta_median']:+.2f}%{'':<13} {'≤+10%':<15} {status:<10}")
        
        print("-"*80)
        print()
        
        # Roll-forward decision
        print("🚀 ROLL-FORWARD DECISION")
        print("-"*80)
        print(f"Criteria: {summary['ship_criteria']}")
        print()
        if summary["ship_decision"]:
            print("✅ **SHIP** - All criteria met!")
        else:
            print("❌ **DO NOT SHIP** - Criteria not met")
            if not summary["meets_improvement_target"]:
                print(f"   - Improvement target missed: {summary['improvement_pct']:.1f}% < 70%")
            if not summary["meets_runtime_target"]:
                print(f"   - Runtime target missed: {summary['runtime_delta_median']:.2f}% > +10%")
        print("-"*80)
        print()
        
        # Detailed results
        print("📋 DETAILED TEST RESULTS")
        print("-"*80)
        print(f"{'Test Name':<40} {'CV% Δ':<12} {'Mean Δ':<12} {'Status':<15}")
        print("-"*80)
        
        for result in sorted(self.results, key=lambda r: r.cv_delta_pct):
            cv_str = f"{result.cv_delta_pct:+.1f}%"
            mean_str = f"{result.mean_delta_pct:+.1f}%"
            
            if result.improved:
                status = "✅ Improved"
            elif result.regressed:
                status = "❌ Regressed"
            else:
                status = "➖ Neutral"
            
            print(f"{result.test_name:<40} {cv_str:<12} {mean_str:<12} {status:<15}")
        
        print("-"*80)
        print()
        
        # Owner and reviewers footer
        print("👥 OWNERSHIP & REVIEW")
        print("-"*80)
        print("Owner (DRI):    TBD - Set before PR")
        print("Code Owners:    @microsoft/lisa-maintainers")
        print("Reviewers:      TBD - Add subject matter experts")
        print("="*80)
        print()


def validate_numa_improvements(baseline_dir: str, numa_dir: str) -> bool:
    """
    Main validation entry point.
    
    TEMPORARY: Remove after validation complete.
    
    Args:
        baseline_dir: Path to baseline test results
        numa_dir: Path to NUMA-enabled test results
    
    Returns:
        True if validation passes (ship criteria met), False otherwise
    """
    validator = NumaVarianceValidator(Path(baseline_dir), Path(numa_dir))
    validator.analyze_test_results()
    validator.print_executive_summary()
    
    summary = validator._generate_summary()
    return summary.get("ship_decision", False)


# Example usage (TEMPORARY - for testing)
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) != 3:
        print("Usage: python numa_variance_validator.py <baseline_dir> <numa_dir>")
        sys.exit(1)
    
    baseline_dir = sys.argv[1]
    numa_dir = sys.argv[2]
    
    ship = validate_numa_improvements(baseline_dir, numa_dir)
    sys.exit(0 if ship else 1)
