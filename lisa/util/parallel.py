# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from queue import Queue
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

        self.result: Optional[T_RESULT] = None

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
        self._pending_tasks: Queue[Task[T_RESULT]] = Queue()
        self._process_lock = threading.Lock()
        self._stored_exceptions: Queue[Future[T_RESULT]] = Queue()

    def __enter__(self) -> Any:
        return self._pool.__enter__()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Optional[bool]:
        return self._pool.__exit__(exc_type, exc_val, exc_tb)

    @property
    def running_count(self) -> int:
        return len(self._futures)

    def submit_task(self, task: Task[T_RESULT]) -> None:
        self._pending_tasks.put(task)
        self._process_pending_tasks()

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
        self.join_exceptions()
        return len(self._futures) > 0

    def wait_for_all_workers(self) -> None:
        while True:
            self._process_pending_tasks()
            has_remaining = not self._pending_tasks.empty() or self.wait_worker()
            if not has_remaining:
                break
            time.sleep(0)

        assert_that(has_remaining).is_false()

    def join_exceptions(self) -> None:
        # Delay join exceptions to main thread.
        while not self._stored_exceptions.empty():
            future = self._stored_exceptions.get()
            # exception will throw at this point
            future.result()

    def _process_done_futures(self) -> None:
        for future in self._futures[:]:
            if future.done():
                success = False
                try:
                    result = future.result()
                    success = True
                except Exception:
                    # save exceptions of subthreads to main thread
                    self._stored_exceptions.put(future)
                finally:
                    # removed finished threads
                    self._futures.remove(future)
                task = self._future_task_map.pop(future)
                task.close()
                if success:
                    # set result back for tracking order
                    task.result = result

                    # exception will throw at this point
                    if self._callback:
                        self._callback(result)

    def _process_pending_tasks(self) -> None:
        new_futures: List[Future[T_RESULT]] = []
        with self._process_lock:
            while not self._pending_tasks.empty() and self.has_idle_worker():
                self.check_cancelled()
                task = self._pending_tasks.get()
                future: Future[T_RESULT] = self._pool.submit(task)
                self._future_task_map[future] = task
                self._futures.append(future)
                new_futures.append(future)

        # Add a callback to trigger scheduling when this future completes
        # It cannot be in the lock, because if it's finished the done callback will
        # be called immediately. It causes deadlock.
        for future in new_futures:
            future.add_done_callback(self._on_future_done)

    def _on_future_done(self, future: Future[T_RESULT]) -> None:
        # Process the completed future and schedule next task. This runs in the
        # worker thread that completed the task.
        self._process_pending_tasks()


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
    Run tasks in parallel, wait for all to complete, and return the results in the same
    order as the input tasks.
    """
    # set a fixed size list to keep the order of results
    results: List[Optional[T_RESULT]] = [None] * len(tasks)
    wrapped_tasks: List[Task[T_RESULT]] = []

    task_manager = TaskManager[T_RESULT](
        max_workers=len(tasks), callback=lambda _: None
    )

    for index, task in enumerate(tasks):
        task = Task(task_id=index, task=task, parent_logger=log)
        wrapped_tasks.append(task)
        task_manager.submit_task(task)

    task_manager.wait_for_all_workers()

    for wrapped_task in wrapped_tasks:
        results[wrapped_task.id] = wrapped_task.result

    return results  # type: ignore
