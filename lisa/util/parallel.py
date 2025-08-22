# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from concurrent.futures import (
    ALL_COMPLETED,
    FIRST_COMPLETED,
    Future,
    ThreadPoolExecutor,
    wait,
)
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar

from assertpy import assert_that

from lisa.util.logger import Logger, get_logger
from lisa.util.perf_timer import create_timer

from . import LisaException

T_RESULT = TypeVar("T_RESULT")  # noqa: N808


class Task(Generic[T_RESULT]):
    def __init__(
        self,
        task_id: int,
        task: Callable[[], T_RESULT],
        parent_logger: Optional[Logger],
        is_verbose: bool = False,
    ) -> None:
        self.id = task_id
        self._task = task
        self._lifecycle_timer = create_timer()
        self._wait_timer = create_timer()
        self._log = get_logger("Task", str(self.id), parent_logger)
        self._is_verbose = is_verbose
        if self._is_verbose:
            self._log.debug(f"Generate task: {self}")

    def close(self) -> None:
        self._lifecycle_timer.elapsed()
        wait_after_call = (
            self._lifecycle_timer.elapsed()
            - self._wait_timer.elapsed()
            - self._call_timer.elapsed()
        )
        if self._is_verbose:
            self._log.debug(
                f"Task finished. "
                f"Lifecycle time: {self._lifecycle_timer.elapsed_text()} "
                f"Wait time before call: {self._wait_timer.elapsed_text()} "
                f"Call time: {self._call_timer.elapsed_text()} "
                f"Wait time after call: {wait_after_call:.3f} sec"
            )

    def __call__(self) -> T_RESULT:
        self._wait_timer.elapsed()
        self._call_timer = create_timer()
        output = self._task()
        self._call_timer.elapsed()
        return output

    def __str__(self) -> str:
        task_message = str(self._task)
        task_message = (
            task_message if len(task_message) < 300 else f"{task_message[:300]}..."
        )
        return task_message

    def __repr__(self) -> str:
        return self.__str__()


class TaskManager(Generic[T_RESULT]):
    def __init__(
        self,
        max_workers: int,
        callback: Optional[Callable[[T_RESULT], None]] = None,
        is_verbose: bool = False,
    ) -> None:
        self._log = get_logger("TaskManager")
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._max_workers = max_workers
        self._futures: List[Future[T_RESULT]] = []
        self._callback = callback
        self._cancelled = False
        self._future_task_map: Dict[Future[T_RESULT], Task[T_RESULT]] = {}
        self._is_verbose = is_verbose

    def __enter__(self) -> Any:
        return self._pool.__enter__()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Optional[bool]:
        return self._pool.__exit__(exc_type, exc_val, exc_tb)

    @property
    def running_count(self) -> int:
        return len(self._futures)

    def submit_task(self, task: Task[T_RESULT]) -> None:
        future: Future[T_RESULT] = self._pool.submit(task)
        self._future_task_map[future] = task
        self._futures.append(future)

    def cancel(self) -> None:
        self._log.info("Called to cancel all tasks.")
        self._cancelled = True

    def check_cancelled(self) -> None:
        if self._cancelled:
            raise LisaException("Tasks are cancelled")

    def has_idle_worker(self) -> bool:
        self._process_done_futures()
        return len(self._futures) < self._max_workers

    def wait_worker(self, return_condition: str = FIRST_COMPLETED) -> bool:
        """
        Return:
            True, if there is running worker.
        """

        wait(self._futures[:], return_when=return_condition)
        self._process_done_futures()
        return len(self._futures) > 0

    def _process_done_futures(self) -> None:
        for future in self._futures[:]:
            if future.done():
                # join exceptions of subthreads to main thread
                result = future.result()
                # removed finished threads
                self._futures.remove(future)
                # exception will throw at this point
                if self._callback:
                    self._callback(result)
                self._future_task_map[future].close()
                self._future_task_map.pop(future)

    def wait_for_all_workers(self) -> None:
        remaining_worker_count = self.wait_worker(return_condition=ALL_COMPLETED)
        assert_that(remaining_worker_count).is_zero()


_default_task_manager: Optional[TaskManager[Any]] = None


def set_global_task_manager(task_manager: TaskManager[Any]) -> None:
    global _default_task_manager
    assert not _default_task_manager, "the default task manager can be set only once"
    _default_task_manager = task_manager


def cancel() -> None:
    if _default_task_manager:
        _default_task_manager.cancel()


def check_cancelled() -> None:
    if _default_task_manager:
        _default_task_manager.check_cancelled()


def run_in_parallel_async(
    tasks: List[Callable[[], T_RESULT]],
    callback: Callable[[T_RESULT], None],
    log: Optional[Logger] = None,
) -> TaskManager[T_RESULT]:
    """
    For concurrent complex tasks, returns the task manager after submitting
    """
    task_manager = TaskManager(max_workers=len(tasks), callback=callback)
    for index, task in enumerate(tasks):
        task_manager.submit_task(Task(task_id=index, task=task, parent_logger=log))
    return task_manager


def run_in_parallel(
    tasks: List[Callable[[], T_RESULT]], log: Optional[Logger] = None
) -> List[T_RESULT]:
    """
    The simple version of concurrency task. It wait all task complete
    """
    results: List[T_RESULT] = []

    def simple_collect_result(result: T_RESULT) -> None:
        """
        Because the task is wait for all completed, and then call back the result, so
        the results are ordered.
        """
        results.append(result)

    task_manager = run_in_parallel_async(tasks, simple_collect_result, log)
    task_manager.wait_for_all_workers()
    return results
