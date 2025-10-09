# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import time
from typing import Callable, List
from unittest import TestCase

from assertpy import assert_that

from lisa.util.parallel import run_in_parallel


class ParallelTestCase(TestCase):
    def test_run_in_parallel_basic(self) -> None:
        """Test basic parallel execution with simple tasks"""

        def task1() -> int:
            return 1

        def task2() -> int:
            return 2

        def task3() -> int:
            return 3

        tasks = [task1, task2, task3]
        results = run_in_parallel(tasks)

        assert_that(results).described_as("should have 3 results").is_length(3)
        assert_that(results).described_as(
            "results should match task order"
        ).is_equal_to([1, 2, 3])

    def test_run_in_parallel_maintains_order(self) -> None:
        """Test that results are returned in the same order as input tasks"""

        def slow_task() -> str:
            time.sleep(0.1)
            return "slow"

        def fast_task() -> str:
            return "fast"

        # Even though fast_task completes first, the order should be preserved
        tasks = [slow_task, fast_task, slow_task, fast_task]
        results = run_in_parallel(tasks)

        assert_that(results).described_as(
            "results should preserve task order"
        ).is_equal_to(["slow", "fast", "slow", "fast"])

    def test_run_in_parallel_single_task(self) -> None:
        """Test parallel execution with single task"""

        def single_task() -> str:
            return "single"

        tasks = [single_task]
        results = run_in_parallel(tasks)

        assert_that(results).is_length(1)
        assert_that(results[0]).is_equal_to("single")

    def test_run_in_parallel_with_exception(self) -> None:
        """Test that exceptions in tasks are properly propagated"""

        def failing_task() -> int:
            raise ValueError("Task failed")

        def successful_task() -> int:
            return 42

        tasks = [successful_task, failing_task, successful_task]

        with self.assertRaises(ValueError):
            run_in_parallel(tasks)

    def test_run_in_parallel_with_shared_state(self) -> None:
        """Test parallel execution with tasks accessing shared state"""
        # Note: This test demonstrates potential race conditions
        # The implementation should handle concurrent access appropriately

        counter = {"value": 0}

        def increment_task() -> int:
            # Simple read operation
            return counter["value"]

        tasks = [increment_task for _ in range(5)]
        results = run_in_parallel(tasks)

        # All tasks should read the same initial value
        assert_that(results).described_as("all tasks read same value").is_equal_to(
            [0, 0, 0, 0, 0]
        )

    def test_run_in_parallel_with_delayed_tasks(self) -> None:
        """Test parallel execution with tasks that have delays"""
        start_time = time.time()

        def delayed_task(delay: float) -> Callable[[], float]:
            def _task() -> float:
                time.sleep(delay)
                return delay

            return _task

        # Create 5 tasks with 0.1 second delay each
        # If running in parallel, should take ~0.1 seconds total
        # If running sequentially, would take ~0.5 seconds
        tasks: List[Callable[[], float]] = [delayed_task(0.1) for _ in range(5)]
        results: List[float] = run_in_parallel(tasks)

        elapsed = time.time() - start_time

        assert_that(results).is_equal_to([0.1, 0.1, 0.1, 0.1, 0.1])
        # Should complete in less than 0.3 seconds if truly parallel
        # (allowing some overhead)
        assert_that(elapsed).described_as(
            "should complete in parallel, not sequentially"
        ).is_less_than(0.3)
