import fnmatch
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, cast

import yaml
from dataclasses_json import dataclass_json

from lisa import constants, messages, notifier, schema
from lisa.messages import MetricRelativity, TestResultMessage, TestStatus
from lisa.util import plugin_manager
from lisa.util.logger import get_logger


@dataclass_json()
@dataclass
class PerfEvaluationSchema(schema.Notifier):
    criteria_file: Optional[str] = "*_criteria.yml"
    criteria: Optional[Dict[str, Any]] = None
    output_file: Optional[str] = None
    statistics_times: Optional[int] = None
    fail_test_on_performance_failure: bool = False


@dataclass
class MetricCriteria:
    baseline: Optional[float] = None
    tolerance: Optional[float] = None
    max_allowed: Optional[float] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    target_value: Optional[float] = None
    tolerance_percent: Optional[float] = None

    def evaluate(
        self,
        actual_value: float,
        metric_relativity: Optional[MetricRelativity] = None,
    ) -> bool:
        if self.baseline is not None:
            if self.tolerance is not None:
                tolerance_value = self.baseline * (self.tolerance / 100.0)
                lower_bound = self.baseline - tolerance_value
                upper_bound = self.baseline + tolerance_value
                if actual_value < lower_bound or actual_value > upper_bound:
                    return False
            if self.max_allowed is not None and actual_value > self.max_allowed:
                return False
            return True
        return self._evaluate_legacy(actual_value, metric_relativity)

    def _evaluate_legacy(
        self,
        actual_value: float,
        metric_relativity: Optional[MetricRelativity] = None,
    ) -> bool:
        if self.min_value is not None and actual_value < self.min_value:
            return False
        if self.max_value is not None and actual_value > self.max_value:
            return False
        if self.target_value is not None and self.tolerance_percent is not None:
            tolerance = self.target_value * (self.tolerance_percent / 100.0)
            if metric_relativity == MetricRelativity.HigherIsBetter:
                return actual_value >= self.target_value - tolerance
            if metric_relativity == MetricRelativity.LowerIsBetter:
                return actual_value <= self.target_value + tolerance
            return abs(actual_value - self.target_value) <= tolerance
        return (
            self._evaluate_by_relativity(actual_value, metric_relativity)
            if metric_relativity and not self._has_explicit_criteria()
            else True
        )

    def _has_explicit_criteria(self) -> bool:
        return (
            self.min_value is not None
            or self.max_value is not None
            or self.target_value is not None
        )

    def _evaluate_by_relativity(
        self, actual_value: float, metric_relativity: MetricRelativity
    ) -> bool:
        if metric_relativity == MetricRelativity.HigherIsBetter:
            return actual_value > 0
        elif metric_relativity == MetricRelativity.LowerIsBetter:
            return actual_value >= 0
        return True

    def get_evaluation_message(
        self,
        actual_value: float,
        metric_relativity: Optional[MetricRelativity] = None,
    ) -> str:
        parts = []
        if self.baseline is not None:
            if self.tolerance is not None:
                tolerance_value = self.baseline * (self.tolerance / 100.0)
                lower_bound = self.baseline - tolerance_value
                upper_bound = self.baseline + tolerance_value
                within_tolerance = lower_bound <= actual_value <= upper_bound
                status = "√" if within_tolerance else "✗"
                parts.append(
                    f"{status} Baseline: {self.baseline} ±{self.tolerance}% "
                    f"(range: {lower_bound:.3f} - {upper_bound:.3f}, "
                    f"actual: {actual_value:.3f})"
                )
            else:
                parts.append(
                    f"ℹ Baseline: {self.baseline} "
                    f"(actual: {actual_value:.3f}, no tolerance set)"
                )
            if self.max_allowed is not None:
                within_max = actual_value <= self.max_allowed
                status = "√" if within_max else "✗"
                parts.append(
                    f"{status} Max allowed: {self.max_allowed} "
                    f"(actual: {actual_value:.3f})"
                )
            return (
                "; ".join(parts)
                if parts
                else f"Baseline: {self.baseline} (actual: {actual_value})"
            )
        return self._get_legacy_message(actual_value, metric_relativity)

    def _get_legacy_message(
        self,
        actual_value: float,
        metric_relativity: Optional[MetricRelativity] = None,
    ) -> str:
        parts = []
        if self.min_value is not None:
            status = "√" if actual_value >= self.min_value else "✗"
            parts.append(f"{status} Min: {self.min_value} (actual: {actual_value:.3f})")
        if self.max_value is not None:
            status = "√" if actual_value <= self.max_value else "✗"
            parts.append(f"{status} Max: {self.max_value} (actual: {actual_value:.3f})")
        if self.target_value is not None and self.tolerance_percent is not None:
            tolerance = self.target_value * (self.tolerance_percent / 100.0)
            if metric_relativity == MetricRelativity.HigherIsBetter:
                lower_bound = self.target_value - tolerance
                status = "√" if actual_value >= lower_bound else "✗"
                parts.append(
                    f"{status} Target: >={self.target_value - tolerance:.3f} "
                    f"({self.target_value} - {self.tolerance_percent}%) "
                    f"(actual: {actual_value:.3f})"
                )
            elif metric_relativity == MetricRelativity.LowerIsBetter:
                upper_bound = self.target_value + tolerance
                status = "√" if actual_value <= upper_bound else "✗"
                parts.append(
                    f"{status} Target: <={self.target_value + tolerance:.3f} "
                    f"({self.target_value} + {self.tolerance_percent}%) "
                    f"(actual: {actual_value:.3f})"
                )
            else:
                diff = abs(actual_value - self.target_value)
                status = "√" if diff <= tolerance else "✗"
                parts.append(
                    f"{status} Target: {self.target_value} "
                    f"±{self.tolerance_percent}% "
                    f"(actual: {actual_value:.3f}, diff: {diff:.2f})"
                )
        elif self.target_value is not None:
            parts.append(
                f"ℹ Target: {self.target_value} (actual: {actual_value:.3f}, "
                f"no tolerance set)"
            )
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
    def __init__(self, runbook: schema.TypedSchema) -> None:
        super().__init__(runbook)
        self._log = get_logger("notifier", self.__class__.__name__)
        self._criteria: Dict[str, Any] = {}
        self._evaluation_results: List[Dict[str, Any]] = []
        self._output_path: Optional[Path] = None
        self._failed_metrics: Dict[str, List[Dict[str, Any]]] = {}
        self._pending_messages: Dict[Any, List[messages.UnifiedPerfMessage]] = {}
        self._perf_runs_cache: Dict[Any, List[messages.UnifiedPerfMessage]] = {}
        plugin_manager.register(self)

    @classmethod
    def type_name(cls) -> str:
        return "perfevaluation"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return PerfEvaluationSchema

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        runbook = cast(PerfEvaluationSchema, self.runbook)
        if runbook.criteria:
            self._load_criteria_from_dict(runbook.criteria)
        elif runbook.criteria_file:
            self._load_criteria(runbook.criteria_file)
        else:
            self._log.debug("No criteria specified - neither file nor dict provided")
        if runbook.output_file:
            self._output_path = Path(runbook.output_file)
            if not self._output_path.is_absolute():
                self._output_path = constants.RUN_LOCAL_LOG_PATH / self._output_path
            self._output_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_criteria(self, criteria_pattern: str) -> None:
        criteria_files = self._find_criteria_files(criteria_pattern)
        if not criteria_files:
            return
        raw_data = self._load_and_merge_criteria_files(criteria_files)
        self._process_criteria_data(raw_data, len(criteria_files))

    def _find_criteria_files(self, criteria_pattern: str) -> List[Path]:
        package_dir = Path(__file__).parent
        if "*" in criteria_pattern:
            criteria_files = list(package_dir.glob(criteria_pattern))
            criteria_files = [
                f for f in criteria_files if f.suffix.lower() in [".yml", ".yaml"]
            ]
            if not criteria_files:
                self._log.debug(
                    f"No YAML criteria files found matching pattern: {criteria_pattern}"
                )
            return criteria_files
        else:
            criteria_path = Path(criteria_pattern)
            if not criteria_path.is_absolute():
                criteria_path = package_dir / criteria_pattern
            if criteria_path.exists():
                if criteria_path.suffix.lower() not in [".yml", ".yaml"]:
                    self._log.debug(
                        f"Criteria file is not YAML format: {criteria_path}"
                    )
                    return []
                return [criteria_path]
            else:
                self._log.debug(f"Criteria file not found: {criteria_path}")
                return []

    def _load_and_merge_criteria_files(
        self, criteria_files: List[Path]
    ) -> Dict[str, Any]:
        raw_criteria_data: Dict[str, Any] = {}
        for criteria_file in criteria_files:
            self._log.info(f"Loading criteria from: {criteria_file.name}")
            try:
                with open(criteria_file, "r", encoding="utf-8") as f:
                    file_data = yaml.safe_load(f)
                    if self._is_hierarchical_format(file_data):
                        if "hierarchical_data" not in raw_criteria_data:
                            raw_criteria_data["hierarchical_data"] = []
                        raw_criteria_data["hierarchical_data"].append(file_data)
                    else:
                        for key, value in file_data.items():
                            if key != "metadata":
                                if key in raw_criteria_data:
                                    self._log.debug(
                                        f"Overriding existing criteria for: {key}"
                                    )
                                raw_criteria_data[key] = value
            except Exception as e:
                self._log.debug(f"Failed to load criteria file {criteria_file}: {e}")
                continue
        return raw_criteria_data

    def _is_hierarchical_format(self, data: Dict[str, Any]) -> bool:
        return "groups" in data and isinstance(data.get("groups"), list)

    def _process_criteria_data(self, raw_data: Dict[str, Any], file_count: int) -> None:
        self._raw_criteria_data = raw_data
        self._criteria = {}
        criteria_count = 0

        self._log.debug(f"Processing criteria data, keys: {list(raw_data.keys())}")

        # Check if this is directly a hierarchical format (has 'groups' at top level)
        if self._is_hierarchical_format(raw_data):
            self._log.debug("Detected hierarchical format with 'groups' key")
            processed = self._process_hierarchical_format(raw_data)
            self._log.info(f"Processed {processed} groups from hierarchical format")
            criteria_count += processed
        else:
            self._log.debug("Not a hierarchical format (no 'groups' key or not a list)")

        # Also check for 'hierarchical_data' key (old format)
        if "hierarchical_data" in raw_data:
            hierarchical_count = 0
            for hier_data in raw_data["hierarchical_data"]:
                processed = self._process_hierarchical_format(hier_data)
                hierarchical_count += processed
            self._log.info(
                f"Processed {hierarchical_count} groups from hierarchical_data"
            )
            criteria_count += hierarchical_count

        for test_case, config in raw_data.items():
            if test_case in [
                "metadata",
                "hierarchical_data",
                "groups",
                "statistics_times",
                "error_threshold",
                "statistics_type",
            ]:
                continue
            if not isinstance(config, dict):
                self._log.debug(
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
        if "size_patterns" in config:
            self._criteria[test_case] = config
            return len(config["size_patterns"])
        else:
            return self._process_legacy_format(test_case, config)

    def _process_legacy_format(self, test_case: str, config: Dict[str, Any]) -> int:
        self._criteria[test_case] = {}
        criteria_count = 0
        for metric_name, metric_criteria in config.items():
            if not isinstance(metric_criteria, dict):
                self._log.debug(
                    f"Skipping {test_case}.{metric_name}: "
                    f"expected dict, got {type(metric_criteria)}"
                )
                continue
            criteria = MetricCriteria(
                min_value=metric_criteria.get("min_value"),
                max_value=metric_criteria.get("max_value"),
                target_value=metric_criteria.get("target_value"),
                tolerance_percent=metric_criteria.get("tolerance_percent"),
            )
            self._criteria[test_case][metric_name] = criteria
            criteria_count += 1
        return criteria_count

    def _process_hierarchical_format(self, hier_data: Dict[str, Any]) -> int:
        if not isinstance(hier_data, dict) or "groups" not in hier_data:
            return 0
        global_stats_times = hier_data.get("statistics_times", 1)
        global_threshold = hier_data.get("error_threshold", 0.1)
        global_stats_type = hier_data.get("statistics_type", "average")
        if not hasattr(self, "_hierarchical_data"):
            self._hierarchical_data = []
        for group in hier_data["groups"]:
            if not isinstance(group, dict):
                continue
            group_stats_times = group.get("statistics_times", global_stats_times)
            group_threshold = group.get("error_threshold", global_threshold)
            group_stats_type = group.get("statistics_type", global_stats_type)
            group_processed = {
                "name": group.get("name", "Unnamed Group"),
                "conditions": group.get("conditions", []),
                "metrics": {},
                "statistics_times": group_stats_times,
                "error_threshold": group_threshold,
                "statistics_type": group_stats_type,
            }
            for metric in group.get("metrics", []):
                if not isinstance(metric, dict) or "name" not in metric:
                    continue
                metric_name = metric["name"]
                final_threshold = metric.get("error_threshold", group_threshold)
                final_stats_times = metric.get("statistics_times", group_stats_times)
                final_stats_type = metric.get("statistics_type", group_stats_type)
                if final_threshold < 1:
                    tolerance_pct = final_threshold * 100
                else:
                    tolerance_pct = final_threshold
                if "baseline" in metric:
                    criteria = MetricCriteria(
                        baseline=metric.get("baseline"),
                        tolerance=tolerance_pct,
                        max_allowed=metric.get("max_allowed"),
                    )
                else:
                    criteria = MetricCriteria(
                        min_value=metric.get("min_value"),
                        max_value=metric.get("max_value"),
                        target_value=metric.get("target_value"),
                        tolerance_percent=tolerance_pct,
                    )
                group_processed["metrics"][metric_name] = {
                    "criteria": criteria,
                    "statistics_times": final_stats_times,
                    "statistics_type": final_stats_type,
                }
            self._hierarchical_data.append(group_processed)
        return len(hier_data["groups"])

    def _get_hierarchical_criteria(
        self, test_case_name: str, vm_size: str, metric_name: str
    ) -> Optional[MetricCriteria]:
        if not hasattr(self, "_hierarchical_data"):
            self._log.debug(
                f"[DEBUG] No hierarchical data found for {test_case_name}.{metric_name}"
            )
            return None
        self._log.debug(
            f"[DEBUG] Searching criteria for {test_case_name}.{metric_name}, "
            f"VM: {vm_size}, Total groups: {len(self._hierarchical_data)}"
        )
        for idx, group in enumerate(self._hierarchical_data):
            self._log.debug(
                f"[DEBUG] Checking group {idx}: {group.get('name', 'Unnamed')}"
            )
            self._log.debug(f"[DEBUG] Group conditions: {group['conditions']}")
            if self._matches_group_conditions(
                group["conditions"], test_case_name, vm_size
            ):
                self._log.debug(
                    f"[DEBUG] Group {idx} conditions matched! "
                    f"Metrics count: {len(group['metrics'])}"
                )
                self._log.debug(
                    f"[DEBUG] Available metrics in group: "
                    f"{list(group['metrics'].keys())}"
                )
                if metric_name in group["metrics"]:
                    self._log.debug(
                        f"[DEBUG] Metric {metric_name} found in group {idx}!"
                    )
                    metric_data = group["metrics"][metric_name]
                    criteria = metric_data["criteria"]
                    assert isinstance(criteria, MetricCriteria)
                    return criteria
                else:
                    self._log.debug(
                        f"[DEBUG] Metric {metric_name} NOT found in group {idx}"
                    )
            else:
                self._log.debug(f"[DEBUG] Group {idx} conditions did NOT match")
        self._log.debug(
            f"[DEBUG] No matching group found for "
            f"{test_case_name}.{metric_name} with VM {vm_size}"
        )
        return None

    def _matches_group_conditions(
        self, conditions: List[Dict[str, Any]], test_case_name: str, vm_size: str
    ) -> bool:
        for condition in conditions:
            matched = self._matches_single_condition(condition, test_case_name, vm_size)
            self._log.debug(
                f"[DEBUG] Condition check - name: {condition.get('name')}, "
                f"type: {condition.get('type')}, value: {condition.get('value')}, "
                f"test_case: {test_case_name}, vm_size: {vm_size}, matched: {matched}"
            )
            if not matched:
                return False
        return True

    def _matches_single_condition(
        self, condition: Dict[str, Any], test_case_name: str, vm_size: str
    ) -> bool:
        condition_name = condition.get("name")
        condition_type = condition.get("type")
        condition_value = condition.get("value")
        if (
            condition_name in ["test_suite", "test_case"]
            and condition_type == "metadata"
        ):
            if condition_value:
                return self._matches_pattern(test_case_name, str(condition_value))
        elif condition_name == "vm_size" and condition_type == "information":
            if condition_value:
                return self._matches_pattern(vm_size, str(condition_value))
        return False

    def get_statistics_config(
        self, test_case_name: str, vm_size: str
    ) -> Dict[str, Any]:
        if hasattr(self, "_hierarchical_data"):
            for group in self._hierarchical_data:
                if self._matches_group_conditions(
                    group["conditions"], test_case_name, vm_size
                ):
                    return {
                        "statistics_times": group.get("statistics_times", 1),
                        "statistics_type": group.get("statistics_type", "average"),
                        "error_threshold": group.get("error_threshold", 0.1),
                    }
        runbook = cast(PerfEvaluationSchema, self.runbook)
        return {
            "statistics_times": runbook.statistics_times or 1,
            "statistics_type": "average",
            "error_threshold": 0.1,
        }

    def _load_criteria_from_dict(self, criteria_dict: Dict[str, Any]) -> None:
        self._log.info("Loading criteria from runbook dict")
        self._log.info(f"Criteria dict keys: {list(criteria_dict.keys())}")
        self._log.info(f"Has 'groups' key: {'groups' in criteria_dict}")
        if "groups" in criteria_dict:
            self._log.info(f"Groups count: {len(criteria_dict['groups'])}")
        self._process_criteria_data(criteria_dict.copy(), 0)

    def _get_criteria_for_test(
        self,
        test_case_name: str,
        vm_size: str,
        metric_name: str,
    ) -> Optional[MetricCriteria]:
        if hasattr(self, "_hierarchical_data"):
            hierarchical_criteria = self._get_hierarchical_criteria(
                test_case_name, vm_size, metric_name
            )
            if hierarchical_criteria:
                return hierarchical_criteria
        test_criteria = self._criteria.get(test_case_name)
        if not test_criteria:
            return None
        return self._get_legacy_criteria(test_criteria, vm_size, metric_name)

    def _get_legacy_criteria(
        self, test_criteria: Any, vm_size: str, metric_name: str
    ) -> Optional[MetricCriteria]:
        if not isinstance(test_criteria, dict):
            return None
        if "size_patterns" in test_criteria:
            return self._get_size_pattern_criteria(
                test_criteria["size_patterns"], vm_size, metric_name
            )
        else:
            return self._get_direct_metric_criteria(test_criteria, metric_name)

    def _get_size_pattern_criteria(
        self, size_patterns: Dict[str, Any], vm_size: str, metric_name: str
    ) -> Optional[MetricCriteria]:
        exact_criteria = self._try_exact_size_match(size_patterns, vm_size, metric_name)
        if exact_criteria:
            return exact_criteria
        return self._try_pattern_match(size_patterns, vm_size, metric_name)

    def _try_exact_size_match(
        self, size_patterns: Dict[str, Any], vm_size: str, metric_name: str
    ) -> Optional[MetricCriteria]:
        if vm_size in size_patterns:
            pattern_criteria = size_patterns[vm_size]
            return self._extract_metric_criteria(pattern_criteria, metric_name)
        return None

    def _try_pattern_match(
        self, size_patterns: Dict[str, Any], vm_size: str, metric_name: str
    ) -> Optional[MetricCriteria]:
        for pattern, pattern_criteria in size_patterns.items():
            matches = self._matches_pattern(vm_size, pattern)
            self._log.debug(f"Pattern matching: '{vm_size}' vs '{pattern}' = {matches}")
            if matches:
                self._log.debug(
                    f"Found matching pattern '{pattern}', using immediately"
                )
                return self._extract_metric_criteria(pattern_criteria, metric_name)
        return None

    def _extract_metric_criteria(
        self, pattern_criteria: Any, metric_name: str
    ) -> Optional[MetricCriteria]:
        if not isinstance(pattern_criteria, dict):
            return None
        if metric_name in pattern_criteria:
            return self._build_metric_criteria(pattern_criteria[metric_name])
        metric_key = self._get_metric_key(metric_name)
        if metric_key in pattern_criteria:
            return self._build_metric_criteria(pattern_criteria[metric_key])
        return None

    def _get_direct_metric_criteria(
        self, test_criteria: Dict[str, Any], metric_name: str
    ) -> Optional[MetricCriteria]:
        if metric_name in test_criteria:
            criteria_value = test_criteria[metric_name]
            if isinstance(criteria_value, MetricCriteria):
                return criteria_value
        return None

    def _build_metric_criteria(self, metric_criteria: Any) -> Optional[MetricCriteria]:
        if isinstance(metric_criteria, dict):
            return MetricCriteria(
                min_value=metric_criteria.get("min_value"),
                max_value=metric_criteria.get("max_value"),
                target_value=metric_criteria.get("target_value"),
                tolerance_percent=metric_criteria.get("tolerance_percent"),
            )
        return None

    def _get_metric_key(self, metric_name: str) -> str:
        return metric_name

    def _matches_pattern(self, vm_size: str, pattern: str) -> bool:
        if pattern == "default":
            return True
        if vm_size == pattern:
            return True
        if fnmatch.fnmatch(vm_size, pattern):
            return True
        return self._fuzzy_match_vm_size(vm_size, pattern)

    def _fuzzy_match_vm_size(self, vm_size: str, pattern: str) -> bool:
        regex_pattern = pattern.replace("*", "[^_]*")
        flexible_patterns = [
            regex_pattern,
            regex_pattern.lower(),
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
                continue
        if self._match_vm_family(vm_size, pattern):
            return True
        return False

    def _match_vm_family(self, vm_size: str, pattern: str) -> bool:
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
        if pat_family != "*" and vm_family.upper() != pat_family.upper():
            return False
        if pat_size_num != "*" and vm_size_num != pat_size_num:
            return False
        if pat_variant not in ["*", ""] and pat_variant != "*":
            if pat_variant not in vm_variant and vm_variant not in pat_variant:
                return False
        if pat_version != "*" and vm_version != pat_version:
            return False
        self._log.debug(
            f"VM family match: '{vm_size}' matched '{pattern}' by family analysis"
        )
        return True

    def _calculate_pattern_specificity(self, pattern: str) -> int:
        if pattern == "default":
            return 0
        wildcard_count = pattern.count("*") + pattern.count("?")
        return len(pattern) - wildcard_count

    def _subscribed_message_type(self) -> List[Type[messages.MessageBase]]:
        return [messages.UnifiedPerfMessage, messages.TestResultMessage]

    def _received_message(self, message: messages.MessageBase) -> None:
        if isinstance(message, messages.UnifiedPerfMessage):
            self._collect_or_evaluate_message(message)
        elif isinstance(message, messages.TestResultMessage):
            self._evaluate_pending_messages_for_test(message.name)

    def _collect_or_evaluate_message(
        self, perf_message: messages.UnifiedPerfMessage
    ) -> None:
        test_case_name = perf_message.test_case_name
        metric_name = perf_message.metric_name
        vm_size = perf_message.vmsize or "unknown"
        stats_config = self.get_statistics_config(test_case_name, vm_size)
        statistics_times = stats_config.get("statistics_times", 1)
        statistics_type = stats_config.get("statistics_type", "average")
        message_key = (test_case_name, vm_size, metric_name)
        self._log.info(
            f"[PerfRun] Collected run: test_case={test_case_name}, "
            f"metric={metric_name}, value={perf_message.metric_value}, VM={vm_size}"
        )
        if message_key not in self._perf_runs_cache:
            self._perf_runs_cache[message_key] = []
        self._perf_runs_cache[message_key].append(perf_message)
        runs_for_key = self._perf_runs_cache[message_key]
        run_count = len(runs_for_key)
        self._log.debug(
            f"[PerfRun] perf_runs count for {test_case_name}.{metric_name} "
            f"(VM: {vm_size}): {run_count}/{statistics_times}"
        )
        if run_count >= statistics_times:
            runs_to_evaluate = runs_for_key[-statistics_times:]
            self._log.info(
                f"[PerfRun] Aggregation: test_case={test_case_name}, "
                f"metric={metric_name}, "
                f"values={[m.metric_value for m in runs_to_evaluate]}, VM={vm_size}"
            )
            self._aggregate_and_evaluate(
                message_key,
                runs_to_evaluate,
                statistics_type,
            )
        elif statistics_times <= 1:
            self._evaluate_performance_message(perf_message)

    def _evaluate_pending_messages_for_test(self, test_case_name: str) -> None:
        keys_to_process = [
            key for key in self._pending_messages.keys() if key[1] == test_case_name
        ]
        for message_key in keys_to_process:
            messages_list = self._pending_messages[message_key]
            if messages_list:
                vm_size = message_key[2]
                stats_config = self.get_statistics_config(test_case_name, vm_size)
                statistics_type = stats_config.get("statistics_type", "average")
                self._log.debug(
                    f"Test {test_case_name} completed with "
                    f"{len(messages_list)} pending messages, evaluating..."
                )
                self._aggregate_and_evaluate(
                    message_key, messages_list, statistics_type
                )
            del self._pending_messages[message_key]

    def _aggregate_and_evaluate(
        self,
        message_key: Any,
        messages_list: List[messages.UnifiedPerfMessage],
        statistics_type: str,
    ) -> None:
        if not messages_list:
            return
        self._log.info(
            f"[PerfRun] Aggregating total {len(messages_list)} runs for "
            f"{messages_list[0].test_case_name}.{messages_list[0].metric_name} "
            f"(VM: {messages_list[0].vmsize})"
        )
        for idx, msg in enumerate(messages_list, 1):
            self._log.info(
                f"[PerfRun] Run#{idx}: value={msg.metric_value}, test_case="
                f"{msg.test_case_name}, metric={msg.metric_name}, VM={msg.vmsize}, "
                f"test_result_id={getattr(msg, 'test_result_id', None)}, "
                f"timestamp={getattr(msg, 'timestamp', None)}"
            )
        values = [msg.metric_value for msg in messages_list]
        if statistics_type == "max":
            aggregated_value = max(values)
        elif statistics_type == "min":
            aggregated_value = min(values)
        elif statistics_type == "median":
            sorted_values = sorted(values)
            n = len(sorted_values)
            if n % 2 == 1:
                aggregated_value = sorted_values[n // 2]
            else:
                aggregated_value = (
                    sorted_values[n // 2 - 1] + sorted_values[n // 2]
                ) / 2
        else:
            aggregated_value = sum(values) / len(values)
        aggregated_message = messages_list[0]
        original_value = aggregated_message.metric_value
        aggregated_message.metric_value = aggregated_value
        test_case_name, vm_size, metric_name = message_key
        self._log.info(
            f"[PerfRun] Aggregated {len(values)} runs for "
            f"{test_case_name}.{metric_name} (VM: {vm_size}) using {statistics_type}: "
            f"values={values}, result={aggregated_value:.3f}"
        )
        self._log.info(
            "[PerfEvaluate] Aggregated evaluation for "
            f"{test_case_name}.{metric_name} (VM: {vm_size}, "
            f"value: {aggregated_value:.3f})"
        )
        self._evaluate_performance_message(aggregated_message)
        aggregated_message.metric_value = original_value

    def _evaluate_performance_message(
        self, perf_message: messages.UnifiedPerfMessage
    ) -> None:
        test_case_name = perf_message.test_case_name
        metric_name = perf_message.metric_name
        actual_value = perf_message.metric_value
        vm_size = perf_message.vmsize or "unknown"
        self._log.info(
            f"[PerfEvaluate] Evaluating {test_case_name}.{metric_name} "
            f"value={actual_value} (VM: {vm_size})"
        )
        metric_criteria = self._get_criteria_for_test(
            test_case_name, vm_size, metric_name
        )
        relativity_val = "NA"
        if perf_message.metric_relativity:
            relativity_val = perf_message.metric_relativity.value
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
                self._log.debug(log_msg)
                failed_metric = {
                    "metric_name": metric_name,
                    "actual_value": actual_value,
                    "unit": perf_message.metric_unit,
                    "evaluation_message": eval_msg,
                    "vm_size": vm_size,
                }
                if test_case_name not in self._failed_metrics:
                    self._failed_metrics[test_case_name] = []
                self._failed_metrics[test_case_name].append(failed_metric)
                self._send_test_failure_message(
                    perf_message, f"Performance criteria not met: {eval_msg}"
                )
        else:
            msg = f"No criteria defined for {test_case_name}.{metric_name}"
            evaluation_result["evaluation_message"] = msg
            self._log.debug(f"{msg} {unit_info} (VM: {vm_size}, value: {actual_value})")
        self._evaluation_results.append(evaluation_result)

    def finalize(self) -> None:
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
            self._log.info(f"Failed criteria: {', '.join(failed_metrics)}")
        if self._output_path:
            try:
                with open(self._output_path, "w", encoding="utf-8") as f:
                    json.dump(summary, f, indent=2, ensure_ascii=False)
                self._log.info(f"Results written to {self._output_path}")
            except Exception as e:
                self._log.error(f"Failed to write results: {e}")

    def _modify_message(self, message: messages.MessageBase) -> None:
        if isinstance(message, TestResultMessage):
            self._log.debug(
                f"[DEBUG] _modify_message called - name: {message.name}, "
                f"full_name: {message.full_name}, status: {message.status}"
            )
            self._log.debug(
                f"[DEBUG] Available failed_metrics keys: "
                f"{list(self._failed_metrics.keys())}"
            )
            if hasattr(message, "perf_runs"):
                message.perf_runs = []
                for key, runs in self._perf_runs_cache.items():
                    if key[0] in message.full_name or key[0] in message.name:
                        for m in runs:
                            run_info = {
                                "test_case_name": m.test_case_name,
                                "metric_name": m.metric_name,
                                "metric_value": m.metric_value,
                                "vmsize": m.vmsize,
                                "time": str(m.time) if hasattr(m, "time") else None,
                                "run_uuid": str(uuid.uuid4()),
                            }
                            message.perf_runs.append(run_info)
                            self._log.info(
                                f"[PerfRun] Write to message.perf_runs: test_case="
                                f"{m.test_case_name}, metric={m.metric_name}, "
                                f"value={m.metric_value}, VM={m.vmsize}"
                            )
            for failed_key in self._failed_metrics.keys():
                if failed_key in message.full_name or failed_key in message.name:
                    failed_metrics = self._failed_metrics[failed_key]
                    summary_msg = (
                        f"Performance evaluation failed: {len(failed_metrics)} "
                        f"metric(s) did not meet criteria"
                    )
                    message.perf_evaluation_summary = {
                        "failed_metrics_count": len(failed_metrics),
                        "failed_metrics": failed_metrics,
                        "summary": summary_msg,
                    }
                    runbook = cast(PerfEvaluationSchema, self.runbook)
                    fail_on_perf = getattr(
                        runbook, "fail_test_on_performance_failure", False
                    )
                    if fail_on_perf and message.status != TestStatus.FAILED:
                        original_message = message.message or ""
                        perf_summary = (
                            f"Performance criteria failed: {len(failed_metrics)} "
                            f"metrics"
                        )
                        message.status = TestStatus.FAILED
                        if original_message:
                            message.message = f"{original_message}\n{perf_summary}"
                        else:
                            message.message = perf_summary
                        self._log.info(
                            f"Test {failed_key} failed due to performance "
                            f"criteria: {len(failed_metrics)} metrics did not "
                            f"meet requirements"
                        )
                    break

    def _send_test_failure_message(
        self, perf_message: messages.UnifiedPerfMessage, reason: str
    ) -> None:
        test_key = perf_message.test_case_name
        self._log.info(f"Performance failure in {test_key}: {reason}")
