# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any, Callable, Generic, List, Optional, TypeVar

from . import LisaException

T_RESULT = TypeVar("T_RESULT")


class TaskManager(Generic[T_RESULT]):
    def __init__(self, max_workers: int, callback: Callable[[T_RESULT], None]) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._max_workers = max_workers
        self._futures: List[Future[T_RESULT]] = []
        self._callback = callback
        self._cancelled = False

    def __enter__(self) -> Any:
        return self._pool.__enter__()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Optional[bool]:
        return self._pool.__exit__(exc_type, exc_val, exc_tb)

    def submit_task(self, task: Callable[[], T_RESULT]) -> None:
        future: Future[T_RESULT] = self._pool.submit(task)
        self._futures.append(future)

    def cancel(self) -> None:
        self._cancelled = True

    def check_cancelled(self) -> None:
        if self._cancelled:
            raise LisaException("Tasks are cancelled")

    def has_idle_worker(self) -> bool:
        return len(self._futures) < self._max_workers

    def wait_worker(self) -> bool:
        """
        Return:
            True, if there is running worker.
        """

        done_futures, _ = wait(self._futures[:], return_when=FIRST_COMPLETED)
        for future in done_futures:
            # join exceptions of subthreads to main thread
            result = future.result()
            # removed finished threads
            self._futures.remove(future)
            # exception will throw at this point
            self._callback(result)
        return len(self._futures) > 0


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
