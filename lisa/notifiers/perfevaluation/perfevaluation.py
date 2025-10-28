# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import fnmatch
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, cast

from dataclasses_json import dataclass_json

from lisa import constants, messages, notifier, schema
from lisa.messages import MetricRelativity
from lisa.util.logger import get_logger


class UnitConverter:
    """Helper class to convert between different units"""

    # Unit conversion factors (to base unit)
    CONVERSIONS = {
        # Time units (base: seconds)
        "seconds": 1.0,
        "milliseconds": 0.001,
        "microseconds": 0.000001,
        "ms": 0.001,
        "us": 0.000001,
        # Data rate units (base: bps - bits per second)
        "bps": 1.0,
        "Kbps": 1000.0,
        "Mbps": 1000000.0,
        "Gbps": 1000000000.0,
        # Data size units (base: bytes)
        "bytes": 1.0,
        "KB": 1024.0,
        "MB": 1024.0 * 1024.0,
        "GB": 1024.0 * 1024.0 * 1024.0,
        "kilobytes": 1024.0,
        # Frequency units (base: Hz)
        "Hz": 1.0,
        "KHz": 1000.0,
        "MHz": 1000000.0,
        "GHz": 1000000000.0,
        # Performance units (no conversion needed)
        "IOPS": 1.0,
        "requests/sec": 1.0,
        "cycles/byte": 1.0,
        "%": 1.0,
    }

    @classmethod
    def convert_value(
        cls, value: float, from_unit: str, to_unit: str
    ) -> Optional[float]:
        """Convert value from one unit to another"""
        if from_unit == to_unit or not from_unit or not to_unit:
            return value

        from_factor = cls.CONVERSIONS.get(from_unit)
        to_factor = cls.CONVERSIONS.get(to_unit)

        if from_factor is None or to_factor is None:
            # Cannot convert - units not in conversion table
            return None

        # Convert to base unit, then to target unit
        base_value = value * from_factor
        converted_value = base_value / to_factor
        return converted_value

    @classmethod
    def are_compatible(cls, unit1: str, unit2: str) -> bool:
        """Check if two units can be converted between each other"""
        if not unit1 or not unit2:
            return True  # Allow comparison if either unit is missing

        # Find unit families
        unit1_family = cls._get_unit_family(unit1)
        unit2_family = cls._get_unit_family(unit2)

        return unit1_family == unit2_family

    @classmethod
    def _get_unit_family(cls, unit: str) -> str:
        """Get the unit family for a given unit"""
        time_units = {"seconds", "milliseconds", "microseconds", "ms", "us"}
        data_rate_units = {"bps", "Kbps", "Mbps", "Gbps"}
        data_size_units = {"bytes", "KB", "MB", "GB", "kilobytes"}
        frequency_units = {"Hz", "KHz", "MHz", "GHz"}

        if unit in time_units:
            return "time"
        elif unit in data_rate_units:
            return "data_rate"
        elif unit in data_size_units:
            return "data_size"
        elif unit in frequency_units:
            return "frequency"
        else:
            return "other"


@dataclass_json()
@dataclass
class PerfEvaluationSchema(schema.Notifier):
    # Support single file, pattern for multiple files, or direct dict criteria
    criteria_file: Optional[str] = "*_criteria.json"
    criteria: Optional[Dict[str, Any]] = None
    output_file: Optional[str] = None


@dataclass
class MetricCriteria:
    """Represents performance criteria for a specific metric"""

    min_value: Optional[float] = None
    max_value: Optional[float] = None
    target_value: Optional[float] = None
    tolerance_percent: Optional[float] = None
    expected_unit: Optional[str] = None
    actual_unit: Optional[str] = None

    def evaluate(
        self, actual_value: float, metric_relativity: Optional[MetricRelativity] = None
    ) -> bool:
        """Evaluate if the actual value meets the criteria"""
        # Convert units if necessary
        converted_value, _ = self._convert_value_if_needed(actual_value)
        if converted_value is None:
            # Cannot convert - units incompatible
            return False

        # Basic range check
        if self.min_value is not None and converted_value < self.min_value:
            return False
        if self.max_value is not None and converted_value > self.max_value:
            return False

        # Target value tolerance check
        if self.target_value is not None and self.tolerance_percent is not None:
            tolerance = self.target_value * (self.tolerance_percent / 100.0)
            if abs(converted_value - self.target_value) > tolerance:
                return False

        # Smart evaluation based on metric_relativity
        if metric_relativity and not self._has_explicit_criteria():
            return self._evaluate_by_relativity(converted_value, metric_relativity)

        return True

    def _has_explicit_criteria(self) -> bool:
        """Check if explicit criteria (min/max/target) are defined"""
        return (
            self.min_value is not None
            or self.max_value is not None
            or self.target_value is not None
        )

    def _evaluate_by_relativity(
        self, actual_value: float, metric_relativity: MetricRelativity
    ) -> bool:
        """Evaluate based on metric relativity when no explicit criteria"""
        # For HigherIsBetter, check if value is positive and not zero
        if metric_relativity == MetricRelativity.HigherIsBetter:
            return actual_value > 0

        # For LowerIsBetter, check if value is non-negative
        elif metric_relativity == MetricRelativity.LowerIsBetter:
            return actual_value >= 0

        # Default case
        return True

    def _convert_value_if_needed(
        self, actual_value: float
    ) -> tuple[Optional[float], str]:
        """Convert actual value to expected unit if needed"""
        if not self.expected_unit or not self.actual_unit:
            # No unit conversion needed
            return actual_value, "no conversion needed"

        if self.expected_unit == self.actual_unit:
            # Same units, no conversion needed
            return actual_value, f"same unit ({self.actual_unit})"

        # Try to convert
        converted = UnitConverter.convert_value(
            actual_value, self.actual_unit, self.expected_unit
        )

        if converted is None:
            # Cannot convert - incompatible units
            conversion_info = (
                f"incompatible units: {self.actual_unit} -> {self.expected_unit}"
            )
            return None, conversion_info

        conversion_info = (
            f"converted {actual_value} {self.actual_unit} to "
            f"{converted:.6f} {self.expected_unit}"
        )
        return converted, conversion_info

    def get_evaluation_message(
        self, actual_value: float, metric_relativity: Optional[MetricRelativity] = None
    ) -> str:
        """Get a descriptive message about the evaluation result"""
        # Convert units if necessary
        converted_value, conversion_info = self._convert_value_if_needed(actual_value)

        # Check for unit conversion issues
        if "incompatible" in conversion_info:
            return f"✗ Unit conversion failed: {conversion_info}"

        # Use converted value for criteria checks
        eval_value = converted_value if converted_value is not None else actual_value

        parts = []
        if self.min_value is not None:
            status = "√" if eval_value >= self.min_value else "✗"
            parts.append(f"{status} Min: {self.min_value} (actual: {eval_value:.3f})")
        if self.max_value is not None:
            status = "√" if eval_value <= self.max_value else "✗"
            parts.append(f"{status} Max: {self.max_value} (actual: {eval_value:.3f})")
        if self.target_value is not None and self.tolerance_percent is not None:
            tolerance = self.target_value * (self.tolerance_percent / 100.0)
            diff = abs(eval_value - self.target_value)
            status = "√" if diff <= tolerance else "✗"
            parts.append(
                f"{status} Target: {self.target_value} "
                f"±{self.tolerance_percent}% "
                f"(actual: {eval_value:.3f}, diff: {diff:.2f})"
            )

        # If no explicit criteria, show smart evaluation based on relativity
        if not parts and metric_relativity:
            if metric_relativity == MetricRelativity.HigherIsBetter:
                status = "√" if actual_value > 0 else "✗"
                parts.append(
                    f"{status} HigherIsBetter check: "
                    f"value > 0 (actual: {actual_value})"
                )
            elif metric_relativity == MetricRelativity.LowerIsBetter:
                status = "√" if actual_value >= 0 else "✗"
                parts.append(
                    f"{status} LowerIsBetter check: "
                    f"value >= 0 (actual: {actual_value})"
                )

        if parts:
            return "; ".join(parts)
        else:
            return f"No criteria defined (actual: {actual_value})"


class PerfEvaluation(notifier.Notifier):
    """
    Performance evaluation notifier that validates UnifiedPerfMessage results
    against predefined criteria loaded from a JSON configuration file.
    """

    def __init__(self, runbook: schema.TypedSchema) -> None:
        super().__init__(runbook)
        self._log = get_logger("notifier", self.__class__.__name__)
        self._criteria: Dict[str, Any] = {}
        self._evaluation_results: List[Dict[str, Any]] = []
        self._output_path: Optional[Path] = None

    @classmethod
    def type_name(cls) -> str:
        return "perfevaluation"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return PerfEvaluationSchema

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        runbook = cast(PerfEvaluationSchema, self.runbook)

        # Load criteria from either file or direct dict
        if runbook.criteria:
            self._load_criteria_from_dict(runbook.criteria)
        elif runbook.criteria_file:
            self._load_criteria(runbook.criteria_file)
        else:
            self._log.warning("No criteria specified - neither file nor dict provided")

        if runbook.output_file:
            self._output_path = Path(runbook.output_file)
            if not self._output_path.is_absolute():
                self._output_path = constants.RUN_LOCAL_LOG_PATH / self._output_path
            self._output_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_criteria(self, criteria_pattern: str) -> None:
        """Load performance criteria from JSON file(s)"""
        criteria_files = self._find_criteria_files(criteria_pattern)
        if not criteria_files:
            return

        raw_data = self._load_and_merge_criteria_files(criteria_files)
        self._process_criteria_data(raw_data, len(criteria_files))

    def _find_criteria_files(self, criteria_pattern: str) -> List[Path]:
        """Find criteria files matching the pattern"""
        package_dir = Path(__file__).parent

        if "*" in criteria_pattern:
            # Load all matching criteria files
            criteria_files = list(package_dir.glob(criteria_pattern))
            if not criteria_files:
                self._log.warning(
                    f"No criteria files found matching pattern: {criteria_pattern}"
                )
            return criteria_files
        else:
            # Single file
            criteria_path = Path(criteria_pattern)
            if not criteria_path.is_absolute():
                criteria_path = package_dir / criteria_pattern

            if criteria_path.exists():
                return [criteria_path]
            else:
                self._log.warning(f"Criteria file not found: {criteria_path}")
                return []

    def _load_and_merge_criteria_files(
        self, criteria_files: List[Path]
    ) -> Dict[str, Any]:
        """Load and merge criteria from multiple JSON files"""
        raw_criteria_data: Dict[str, Any] = {}

        for criteria_file in criteria_files:
            self._log.info(f"Loading criteria from: {criteria_file.name}")
            try:
                with open(criteria_file, "r", encoding="utf-8") as f:
                    file_data = json.load(f)

                    # Merge data (skip metadata sections)
                    for key, value in file_data.items():
                        if key != "metadata":
                            if key in raw_criteria_data:
                                self._log.warning(
                                    f"Overriding existing criteria for: {key}"
                                )
                            raw_criteria_data[key] = value

            except Exception as e:
                self._log.warning(f"Failed to load criteria file {criteria_file}: {e}")
                continue

        return raw_criteria_data

    def _process_criteria_data(self, raw_data: Dict[str, Any], file_count: int) -> None:
        """Process loaded criteria data into structured format"""
        self._raw_criteria_data = raw_data
        self._criteria = {}
        criteria_count = 0

        for test_case, config in raw_data.items():
            if test_case == "metadata":
                continue

            if not isinstance(config, dict):
                self._log.warning(
                    f"Skipping {test_case}: expected dict, got {type(config)}"
                )
                continue

            processed_count = self._process_test_case_criteria(test_case, config)
            criteria_count += processed_count

        if file_count > 0:
            self._log.info(
                f"Loaded {criteria_count} criteria configurations from "
                f"{file_count} files for {len(self._criteria)} test cases"
            )
        else:
            self._log.info(
                f"Loaded {criteria_count} criteria configurations from "
                f"runbook dict for {len(self._criteria)} test cases"
            )

    def _process_test_case_criteria(
        self, test_case: str, config: Dict[str, Any]
    ) -> int:
        """Process criteria for a single test case"""
        if "size_patterns" in config:
            # New format with size patterns - store for later pattern matching
            self._criteria[test_case] = config
            return len(config["size_patterns"])
        else:
            # Legacy format - direct metrics mapping
            return self._process_legacy_format(test_case, config)

    def _process_legacy_format(self, test_case: str, config: Dict[str, Any]) -> int:
        """Process legacy format criteria"""
        self._criteria[test_case] = {}
        criteria_count = 0

        for metric_name, metric_criteria in config.items():
            if not isinstance(metric_criteria, dict):
                self._log.warning(
                    f"Skipping {test_case}.{metric_name}: "
                    f"expected dict, got {type(metric_criteria)}"
                )
                continue

            criteria = MetricCriteria(
                min_value=metric_criteria.get("min_value"),
                max_value=metric_criteria.get("max_value"),
                target_value=metric_criteria.get("target_value"),
                tolerance_percent=metric_criteria.get("tolerance_percent"),
                expected_unit=metric_criteria.get("unit"),
            )
            self._criteria[test_case][metric_name] = criteria
            criteria_count += 1

        return criteria_count

    def _load_criteria_from_dict(self, criteria_dict: Dict[str, Any]) -> None:
        """Load performance criteria from a dictionary"""
        self._log.info("Loading criteria from runbook dict")
        self._process_criteria_data(criteria_dict.copy(), 0)  # 0 indicates dict source

    def _get_criteria_for_test(
        self,
        test_case_name: str,
        vm_size: str,
        metric_name: str,
        metric_unit: Optional[str] = None,
    ) -> Optional[MetricCriteria]:
        """Get criteria for test case, VM size, metric, and unit"""
        test_criteria = self._criteria.get(test_case_name)
        if not test_criteria:
            return None

        # Check if this uses size_patterns structure
        if isinstance(test_criteria, dict) and "size_patterns" in test_criteria:
            size_patterns = test_criteria["size_patterns"]

            # First try exact VM size match
            if vm_size in size_patterns:
                pattern_criteria = size_patterns[vm_size]
                if (
                    isinstance(pattern_criteria, dict)
                    and metric_name in pattern_criteria
                ):
                    metric_criteria = pattern_criteria[metric_name]
                    if isinstance(metric_criteria, dict):
                        expected_unit = metric_criteria.get("unit")
                        return MetricCriteria(
                            min_value=metric_criteria.get("min_value"),
                            max_value=metric_criteria.get("max_value"),
                            target_value=metric_criteria.get("target_value"),
                            tolerance_percent=metric_criteria.get("tolerance_percent"),
                            expected_unit=expected_unit,
                            actual_unit=metric_unit,
                        )

            # Then try pattern matching - use first match found
            best_match = None
            for pattern, pattern_criteria in size_patterns.items():
                matches = self._matches_pattern(vm_size, pattern)
                self._log.debug(
                    f"Pattern matching: '{vm_size}' vs '{pattern}' = {matches}"
                )
                if matches:
                    self._log.debug(
                        f"Found matching pattern '{pattern}', using immediately"
                    )
                    best_match = pattern_criteria
                    break  # Use first match, don't continue searching

            if best_match and isinstance(best_match, dict):
                # Look for metric name in criteria
                if metric_name in best_match:
                    metric_criteria = best_match[metric_name]

                    # Check if this metric has unit validation/conversion
                    if isinstance(metric_criteria, dict):
                        expected_unit = metric_criteria.get("unit")

                        # Create criteria with unit information for conversion
                        return MetricCriteria(
                            min_value=metric_criteria.get("min_value"),
                            max_value=metric_criteria.get("max_value"),
                            target_value=metric_criteria.get("target_value"),
                            tolerance_percent=metric_criteria.get("tolerance_percent"),
                            expected_unit=expected_unit,
                            actual_unit=metric_unit,
                        )

                # Fallback: Try old unit-based key format
                metric_key = self._get_metric_key(metric_name, metric_unit)
                if metric_key in best_match:
                    metric_criteria = best_match[metric_key]
                    if isinstance(metric_criteria, dict):
                        return MetricCriteria(
                            min_value=metric_criteria.get("min_value"),
                            max_value=metric_criteria.get("max_value"),
                            target_value=metric_criteria.get("target_value"),
                            tolerance_percent=metric_criteria.get("tolerance_percent"),
                        )
        else:
            # Legacy format - direct metric lookup
            if isinstance(test_criteria, dict) and metric_name in test_criteria:
                criteria_value = test_criteria[metric_name]
                if isinstance(criteria_value, MetricCriteria):
                    return criteria_value

        return None

    def _get_metric_key(self, metric_name: str, metric_unit: Optional[str]) -> str:
        """Generate metric key with unit for criteria lookup"""
        if metric_unit:
            return f"{metric_name}_{metric_unit}"
        return metric_name

    def _matches_pattern(self, vm_size: str, pattern: str) -> bool:
        """Check if VM size matches the pattern with fuzzy matching"""
        # "default" pattern matches any VM size
        if pattern == "default":
            return True

        # Try exact match first
        if vm_size == pattern:
            return True

        # Try standard wildcard matching
        if fnmatch.fnmatch(vm_size, pattern):
            return True

        # Enhanced fuzzy matching for VM sizes
        return self._fuzzy_match_vm_size(vm_size, pattern)

    def _fuzzy_match_vm_size(self, vm_size: str, pattern: str) -> bool:
        """Enhanced fuzzy matching for VM size patterns"""

        # Convert pattern to regex for more flexible matching
        # Handle common VM naming patterns

        # Replace * with regex equivalent, but be smarter about it
        regex_pattern = pattern.replace("*", "[^_]*")

        # Handle common VM size variations
        # Standard_D2ads_v5 should match Standard_D2*_v5
        # Standard_D4s_v3 should match Standard_D4*_v*

        # Make the pattern more flexible
        # Replace specific characters that might vary
        flexible_patterns = [
            # Original pattern
            regex_pattern,
            # Case insensitive
            regex_pattern.lower(),
            # Handle missing 's' (e.g., D2ads vs D2s)
            regex_pattern.replace("s_", "_").replace("_s", "_"),
        ]

        vm_size_lower = vm_size.lower()

        for flex_pattern in flexible_patterns:
            try:
                if re.match(f"^{flex_pattern}$", vm_size, re.IGNORECASE):
                    self._log.debug(
                        f"Fuzzy match: '{vm_size}' matched '{pattern}' "
                        f"using pattern '{flex_pattern}'"
                    )
                    return True
                if re.match(f"^{flex_pattern}$", vm_size_lower, re.IGNORECASE):
                    self._log.debug(
                        f"Fuzzy match: '{vm_size}' matched '{pattern}' "
                        f"using lowercase pattern '{flex_pattern}'"
                    )
                    return True
            except re.error:
                # If regex fails, continue to next pattern
                continue

        # Additional fuzzy logic for VM families
        # Extract family and size info
        if self._match_vm_family(vm_size, pattern):
            return True

        return False

    def _match_vm_family(self, vm_size: str, pattern: str) -> bool:
        """Match VM by family and size characteristics"""

        # Extract VM components: Standard_D<size><variant>_v<version>
        vm_match = re.match(
            r"Standard_([A-Z])(\d+)([a-z]*)_v(\d+)", vm_size, re.IGNORECASE
        )
        pattern_match = re.match(
            r"Standard_([A-Z])(\d+|\*)([a-z*]*)_v(\d+|\*)", pattern, re.IGNORECASE
        )

        if not vm_match or not pattern_match:
            return False

        vm_family, vm_size_num, vm_variant, vm_version = vm_match.groups()
        pat_family, pat_size_num, pat_variant, pat_version = pattern_match.groups()

        # Check family match (D, E, F, etc.)
        if pat_family != "*" and vm_family.upper() != pat_family.upper():
            return False

        # Check size match
        if pat_size_num != "*" and vm_size_num != pat_size_num:
            return False

        # Check variant match (s, ads, etc.) - more flexible
        if pat_variant not in ["*", ""] and pat_variant != "*":
            # If pattern specifies variant, VM should contain it or be compatible
            if pat_variant not in vm_variant and vm_variant not in pat_variant:
                return False

        # Check version match
        if pat_version != "*" and vm_version != pat_version:
            return False

        self._log.debug(
            f"VM family match: '{vm_size}' matched '{pattern}' " f"by family analysis"
        )
        return True

    def _calculate_pattern_specificity(self, pattern: str) -> int:
        """Calculate pattern specificity for priority ordering"""
        if pattern == "default":
            return 0  # Lowest priority

        # Count wildcards - fewer wildcards = more specific
        wildcard_count = pattern.count("*") + pattern.count("?")
        # Base specificity on pattern length minus wildcards
        return len(pattern) - wildcard_count

    def _subscribed_message_type(self) -> List[Type[messages.MessageBase]]:
        return [messages.UnifiedPerfMessage]

    def _received_message(self, message: messages.MessageBase) -> None:
        if isinstance(message, messages.UnifiedPerfMessage):
            self._evaluate_performance_message(message)

    def _evaluate_performance_message(
        self, perf_message: messages.UnifiedPerfMessage
    ) -> None:
        """Evaluate a UnifiedPerfMessage against the loaded criteria"""
        test_case_name = perf_message.test_case_name
        metric_name = perf_message.metric_name
        actual_value = perf_message.metric_value
        vm_size = perf_message.vmsize or "unknown"

        # Use new pattern matching method to get criteria
        metric_criteria = self._get_criteria_for_test(
            test_case_name, vm_size, metric_name, perf_message.metric_unit
        )

        relativity_val = "NA"
        if perf_message.metric_relativity:
            relativity_val = perf_message.metric_relativity.value

        # Log pattern matching result for debugging
        unit_info = (
            f"({perf_message.metric_unit})" if perf_message.metric_unit else "(no unit)"
        )
        if metric_criteria:
            self._log.debug(
                f"Found criteria for {test_case_name}.{metric_name} {unit_info} "
                f"with VM size {vm_size}"
            )
        else:
            self._log.debug(
                f"No criteria for {test_case_name}.{metric_name} {unit_info} "
                f"with VM size {vm_size}"
            )

        evaluation_result = {
            "timestamp": str(perf_message.time) if perf_message.time else "",
            "test_case_name": test_case_name,
            "metric_name": metric_name,
            "metric_value": actual_value,
            "metric_unit": perf_message.metric_unit,
            "metric_relativity": relativity_val,
            "tool": perf_message.tool,
            "platform": perf_message.platform,
            "vmsize": perf_message.vmsize,
            "role": perf_message.role,
            "criteria_defined": metric_criteria is not None,
            "criteria_met": True,
            "evaluation_message": "",
        }

        if metric_criteria:
            criteria_met = metric_criteria.evaluate(
                actual_value, perf_message.metric_relativity
            )
            eval_msg = metric_criteria.get_evaluation_message(
                actual_value, perf_message.metric_relativity
            )

            evaluation_result.update(
                {"criteria_met": criteria_met, "evaluation_message": eval_msg}
            )

            status = "✓" if criteria_met else "✗"
            log_msg = (
                f"{status} {test_case_name}.{metric_name} "
                f"(VM: {vm_size}): {eval_msg}"
            )

            if criteria_met:
                self._log.info(log_msg)
            else:
                self._log.warning(log_msg)
                # Record test failure for later reporting
                self._send_test_failure_message(
                    perf_message, f"Performance criteria not met: {eval_msg}"
                )
        else:
            msg = f"No criteria defined for {test_case_name}.{metric_name}"
            evaluation_result["evaluation_message"] = msg
            self._log.debug(f"{msg} {unit_info} (VM: {vm_size}, value: {actual_value})")

        self._evaluation_results.append(evaluation_result)

    def finalize(self) -> None:
        """Finalize the evaluation and optionally write results to file"""
        if not self._evaluation_results:
            self._log.info("No performance evaluations performed.")
            return

        total = len(self._evaluation_results)
        with_criteria = [r for r in self._evaluation_results if r["criteria_defined"]]
        criteria_count = len(with_criteria)
        met_count = len([r for r in with_criteria if r["criteria_met"]])
        failed_count = criteria_count - met_count

        success_rate = (
            100.0 if criteria_count == 0 else (met_count / criteria_count * 100)
        )

        summary = {
            "summary": {
                "total_evaluations": total,
                "evaluations_with_criteria": criteria_count,
                "evaluations_without_criteria": total - criteria_count,
                "criteria_met": met_count,
                "criteria_failed": failed_count,
                "success_rate_percent": success_rate,
            },
            "evaluations": self._evaluation_results,
        }

        self._log.info(
            f"Evaluation Summary: {met_count}/{criteria_count} "
            f"criteria met ({success_rate:.1f}%)"
        )

        if failed_count > 0:
            failed_metrics = [
                f"{r['test_case_name']}.{r['metric_name']}"
                for r in with_criteria
                if not r["criteria_met"]
            ]
            self._log.warning(f"Failed criteria: {', '.join(failed_metrics)}")

        if self._output_path:
            try:
                with open(self._output_path, "w", encoding="utf-8") as f:
                    json.dump(summary, f, indent=2, ensure_ascii=False)
                self._log.info(f"Results written to {self._output_path}")
            except Exception as e:
                self._log.error(f"Failed to write results: {e}")

    def _send_test_failure_message(
        self, perf_message: messages.UnifiedPerfMessage, reason: str
    ) -> None:
        """Log performance failure information"""
        test_key = perf_message.test_case_name
        self._log.warning(f"Performance failure in {test_key}: {reason}")
