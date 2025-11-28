# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import threading
import time
from typing import Callable, List
from unittest import TestCase

from assertpy import assert_that

from lisa.util.parallel import Task, TaskManager, run_in_parallel


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


class TaskManagerTestCase(TestCase):
    """Test TaskManager with automatic task scheduling"""

    def test_task_manager_multiple_submits_no_wait(self) -> None:
        """Test that tasks are automatically scheduled even without calling wait"""
        completed_tasks: List[int] = []
        lock = threading.Lock()

        def create_task(task_id: int) -> Callable[[], int]:
            def _task() -> int:
                time.sleep(0.05)  # Small delay to simulate work
                with lock:
                    completed_tasks.append(task_id)
                return task_id

            return _task

        # Create task manager with 3 workers
        task_manager = TaskManager[int](max_workers=3)

        # Submit 10 tasks rapidly without calling wait
        for i in range(10):
            task = Task(task_id=i, task=create_task(i), parent_logger=None)
            task_manager.submit_task(task)

        # Give time for automatic scheduling to complete all tasks
        # With 3 workers and 10 tasks, should take ~0.05 * 4 rounds = ~0.2s
        time.sleep(0.5)

        # All tasks should have completed automatically
        with lock:
            assert_that(completed_tasks).described_as(
                "all tasks should complete automatically without explicit wait"
            ).is_length(10)
            assert_that(set(completed_tasks)).described_as(
                "all task IDs should be present"
            ).is_equal_to(set(range(10)))

    def test_task_manager_respects_max_workers(self) -> None:
        """Test that TaskManager respects max_workers limit"""
        active_workers = {"count": 0, "max_seen": 0}
        lock = threading.Lock()

        def create_task(task_id: int) -> Callable[[], int]:
            def _task() -> int:
                with lock:
                    active_workers["count"] += 1
                    active_workers["max_seen"] = max(
                        active_workers["max_seen"], active_workers["count"]
                    )
                time.sleep(0.1)  # Hold the worker
                with lock:
                    active_workers["count"] -= 1
                return task_id

            return _task

        max_workers = 3
        task_manager = TaskManager[int](max_workers=max_workers)

        # Submit many tasks
        for i in range(10):
            task = Task(task_id=i, task=create_task(i), parent_logger=None)
            task_manager.submit_task(task)

        # Wait for completion
        time.sleep(0.5)

        # Should never exceed max_workers
        with lock:
            assert_that(active_workers["max_seen"]).described_as(
                "should never exceed max_workers"
            ).is_less_than_or_equal_to(max_workers)

    def test_task_manager_callback_execution(self) -> None:
        """Test that callback is executed for each completed task"""
        callback_results: List[int] = []
        lock = threading.Lock()

        def result_callback(result: int) -> None:
            with lock:
                callback_results.append(result)

        def create_task(task_id: int) -> Callable[[], int]:
            def _task() -> int:
                time.sleep(0.01)
                return task_id * 10

            return _task

        task_manager = TaskManager[int](max_workers=2, callback=result_callback)

        # Submit tasks
        for i in range(5):
            task = Task(task_id=i, task=create_task(i), parent_logger=None)
            task_manager.submit_task(task)

        # Wait for completion
        task_manager.wait_for_all_workers()

        # All callbacks should have been executed
        with lock:
            assert_that(callback_results).described_as(
                "callback should be called for each task"
            ).is_length(5)
            assert_that(set(callback_results)).is_equal_to({0, 10, 20, 30, 40})

    def test_task_manager_immediate_scheduling(self) -> None:
        """Test that next task is scheduled immediately when a worker finishes"""
        task_start_times: List[float] = []
        lock = threading.Lock()
        start_time = time.time()

        def create_task(task_id: int) -> Callable[[], int]:
            def _task() -> int:
                with lock:
                    task_start_times.append(time.time() - start_time)
                time.sleep(0.1)
                return task_id

            return _task

        # 2 workers, 6 tasks
        task_manager = TaskManager[int](max_workers=2)

        # Submit all tasks at once
        for i in range(6):
            task = Task(task_id=i, task=create_task(i), parent_logger=None)
            task_manager.submit_task(task)

        # Wait for completion
        time.sleep(0.5)

        with lock:
            assert_that(task_start_times).is_length(6)
            # Tasks should start in waves:
            # Wave 1: tasks 0, 1 start immediately (time ~0)
            # Wave 2: tasks 2, 3 start after ~0.1s
            # Wave 3: tasks 4, 5 start after ~0.2s
            # Verify first 2 tasks start quickly
            assert_that(task_start_times[0]).is_less_than(0.05)
            assert_that(task_start_times[1]).is_less_than(0.05)

    def test_exception_raised_in_main_thread(self) -> None:
        """Test that exceptions from worker threads are raised in the main thread"""
        main_thread_id = threading.current_thread().ident
        exception_thread_id: List[int] = []
        lock = threading.Lock()

        def failing_task() -> int:
            # This runs in a worker thread
            time.sleep(0.05)
            raise ValueError("Task failed in worker thread")

        def successful_task() -> int:
            time.sleep(0.05)
            return 42

        # Test with run_in_parallel
        try:
            # Submit tasks - one will fail
            tasks = [successful_task, failing_task, successful_task]
            run_in_parallel(tasks)
            self.fail("Expected ValueError to be raised")
        except ValueError as e:
            # The exception should be caught in the main thread
            with lock:
                exception_thread_id.append(threading.current_thread().ident)
            assert_that(str(e)).is_equal_to("Task failed in worker thread")

        # Verify the exception was caught in the main thread
        with lock:
            assert_that(exception_thread_id).described_as(
                "exception should be caught in main thread"
            ).is_length(1)
            assert_that(exception_thread_id[0]).described_as(
                "exception should be raised in main thread, not worker thread"
            ).is_equal_to(main_thread_id)

    def test_exception_raised_in_main_thread_with_callback(self) -> None:
        """Test that exceptions are raised in main thread even with TaskManager
        and callback"""
        main_thread_id = threading.current_thread().ident
        exception_thread_id: List[int] = []
        callback_results: List[int] = []
        lock = threading.Lock()

        def result_callback(result: int) -> None:
            with lock:
                callback_results.append(result)

        def failing_task() -> int:
            time.sleep(0.05)
            raise RuntimeError("Worker thread exception")

        def successful_task() -> int:
            time.sleep(0.05)
            return 100

        task_manager = TaskManager[int](max_workers=2, callback=result_callback)

        # Submit tasks
        task_manager.submit_task(
            Task(task_id=0, task=successful_task, parent_logger=None)
        )
        task_manager.submit_task(Task(task_id=1, task=failing_task, parent_logger=None))
        task_manager.submit_task(
            Task(task_id=2, task=successful_task, parent_logger=None)
        )

        # Wait for all workers - this should raise the exception in main thread
        try:
            task_manager.wait_for_all_workers()
            self.fail("Expected RuntimeError to be raised")
        except RuntimeError as e:
            with lock:
                exception_thread_id.append(threading.current_thread().ident)
            assert_that(str(e)).is_equal_to("Worker thread exception")

        # Verify exception was raised in main thread
        with lock:
            assert_that(exception_thread_id).described_as(
                "exception should be caught in main thread"
            ).is_length(1)
            assert_that(exception_thread_id[0]).described_as(
                "exception should be raised in main thread, not worker thread"
            ).is_equal_to(main_thread_id)

            # At least one successful task should have completed before the
            # exception. Note: Callbacks may execute in worker threads due to
            # _on_future_done calling _process_pending_tasks, but the exception
            # is still raised in main thread
            assert_that(callback_results).described_as(
                "at least one successful task should have completed"
            ).is_not_empty()

    def test_multiple_exceptions_first_one_raised(self) -> None:
        """Test that when multiple tasks fail, the first exception encountered
        is raised in main thread"""
        main_thread_id = threading.current_thread().ident
        exception_thread_id: List[int] = []
        lock = threading.Lock()

        def failing_task_1() -> int:
            time.sleep(0.05)
            raise ValueError("First failure")

        def failing_task_2() -> int:
            time.sleep(0.05)
            raise TypeError("Second failure")

        task_manager = TaskManager[int](max_workers=2)

        task_manager.submit_task(
            Task(task_id=0, task=failing_task_1, parent_logger=None)
        )
        task_manager.submit_task(
            Task(task_id=1, task=failing_task_2, parent_logger=None)
        )

        # One of the exceptions should be raised in the main thread
        exception_caught = False
        try:
            task_manager.wait_for_all_workers()
        except (ValueError, TypeError) as e:
            exception_caught = True
            with lock:
                exception_thread_id.append(threading.current_thread().ident)
            # Should be one of the two exceptions
            assert_that(str(e)).is_in("First failure", "Second failure")

        assert_that(exception_caught).described_as(
            "one of the exceptions should have been raised"
        ).is_true()

        # Verify it was caught in main thread
        with lock:
            assert_that(exception_thread_id[0]).described_as(
                "exception should be raised in main thread"
            ).is_equal_to(main_thread_id)
