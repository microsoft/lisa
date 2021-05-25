# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any, Callable, Generic, List, Optional, TypeVar

from . import LisaException
from .logger import Logger

T_RESULT = TypeVar("T_RESULT")


class TaskManager(Generic[T_RESULT]):
    def __init__(self, max_workers: int, callback: Callable[[T_RESULT], None]) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._max_workers = max_workers
        self._futures: List[Future[T_RESULT]] = list()
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


def _cancel_threads(
    futures: List[Any],
    completed_callback: Optional[Callable[[Any], None]] = None,
) -> List[Any]:
    success_futures: List[Any] = []
    for future in futures:
        if future.done() and future.exception():
            # throw exception, if it's not here.
            future.result()
        elif not future.done():
            # cancel running threads. It may need cancellation callback
            result = future.cancel()
            if not result and completed_callback:
                # make sure it's status changed to canceled
                completed_callback(False)
            # join exception back to main thread
            future.result()
        else:
            success_futures.append(future)
    # return empty list to prevent cancel again.
    return success_futures


def run_in_threads(
    methods: List[Any],
    max_workers: int = 0,
    completed_callback: Optional[Callable[[Any], None]] = None,
    log: Optional[Logger] = None,
) -> List[Any]:
    """
    start methods in a thread pool
    """

    results: List[Any] = []
    if max_workers <= 0:
        max_workers = len(methods)
    with ThreadPoolExecutor(max_workers) as pool:
        futures = [pool.submit(method) for method in methods]
        if completed_callback:
            for future in futures:
                future.add_done_callback(completed_callback)
        try:
            while any(not x.done() for x in futures):
                # if there is any change, skip sleep to get faster
                changed = False
                for future in futures:
                    # join exceptions of subthreads to main thread
                    if future.done():
                        changed = True
                        # removed finished threads
                        futures.remove(future)
                        # exception will throw at this point
                        results.append(future.result())
                        break
                if not changed:
                    time.sleep(0.1)

        except KeyboardInterrupt:
            if log:
                log.info("received CTRL+C, stopping threads...")
            # support to interrupt runs on local debugging.
            futures = _cancel_threads(futures, completed_callback=completed_callback)
            pool.shutdown(True)
        finally:
            if log:
                log.debug("finalizing threads...")
            futures = _cancel_threads(futures, completed_callback=completed_callback)
        for future in futures:
            # exception will throw at this point
            results.append(future.result())
    return results


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
