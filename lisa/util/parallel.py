# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from queue import Queue
from typing import (
    Any,
    Callable,
    Dict,
    Generic,
    Iterable,
    List,
    Optional,
    Set,
    Tuple,
    TypeVar,
)

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
        self._futures: Set[Future[T_RESULT]] = set()
        self._callback = callback
        self._cancelled = False
        self._future_task_map: Dict[Future[T_RESULT], Task[T_RESULT]] = {}
        self._is_verbose = is_verbose
        self._pending_tasks: Queue[Task[T_RESULT]] = Queue()
        self._process_lock = threading.Lock()
        self._stored_exceptions: Queue[Future[T_RESULT]] = Queue()
        self._caller_thread: Optional[threading.Thread] = None
        self._orphan_monitor: Optional[threading.Thread] = None

    def __enter__(self) -> Any:
        return self._pool.__enter__()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Optional[bool]:
        return self._pool.__exit__(exc_type, exc_val, exc_tb)

    def start_orphan_monitor(self) -> None:
        """Watch the calling thread and cancel work if it dies.

        When ``func_timeout`` kills a ``StoppableThread``, any
        ``ThreadPoolExecutor`` workers it spawned keep running because
        they are regular (non-stoppable) threads.  This monitor detects
        the death of the calling thread and:

        1. Sets the cancellation flag so no *pending* tasks are started.
        2. Cancels queued ``Future`` objects that haven't begun yet.
        3. Shuts down the pool without waiting, so the executor doesn't
           block on in-flight work.
        4. Marks all pool threads as daemon so they cannot prevent the
           process from exiting.
        """
        caller = threading.current_thread()
        if caller is threading.main_thread():
            # The main thread is never killed by func_timeout.
            return
        self._caller_thread = caller

        def _monitor() -> None:
            while caller.is_alive():
                time.sleep(0.5)
            # Caller was killed (most likely by func_timeout).
            self._log.debug(
                "Caller thread is no longer alive — cancelling remaining tasks."
            )
            self._cancelled = True
            # Cancel futures that haven't started yet.
            with self._process_lock:
                for future in self._futures:
                    future.cancel()
            # Prevent the pool from blocking on in-flight work and
            # ensure its threads won't keep the process alive.
            try:
                self._pool.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                # cancel_futures was added in Python 3.9
                self._pool.shutdown(wait=False)
            for t in self._pool._threads:
                t.daemon = True

        monitor = threading.Thread(target=_monitor, daemon=True, name="orphan-monitor")
        monitor.start()
        self._orphan_monitor = monitor

    @property
    def running_count(self) -> int:
        with self._process_lock:
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
        self._process_pending_tasks()
        with self._process_lock:
            return len(self._futures) < self._max_workers

    def wait_worker(self, return_condition: str = FIRST_COMPLETED) -> bool:
        """
        Return:
            True, if there is running worker.
        """

        self._process_pending_tasks()
        with self._process_lock:
            futures = tuple(self._futures)
        if futures:
            done, _ = wait(futures, return_when=return_condition)
            self._process_pending_tasks(done)
        self.join_exceptions()
        with self._process_lock:
            return len(self._futures) > 0

    def wait_for_all_workers(self) -> None:
        while True:
            if self._cancelled:
                self._pool.shutdown(wait=False)
                return
            self._process_pending_tasks()
            with self._process_lock:
                has_remaining = (
                    not self._pending_tasks.empty() or len(self._futures) > 0
                )
            if not has_remaining:
                self.join_exceptions()
                return
            self.wait_worker()

    def join_exceptions(self) -> None:
        # Delay join exceptions to main thread.
        while not self._stored_exceptions.empty():
            future = self._stored_exceptions.get()
            # exception will throw at this point
            future.result()

    def _collect_done_futures_locked(
        self,
        done_futures: Iterable[Future[T_RESULT]],
    ) -> List[Tuple[Future[T_RESULT], Task[T_RESULT]]]:
        completed: List[Tuple[Future[T_RESULT], Task[T_RESULT]]] = []
        for future in done_futures:
            if future not in self._futures:
                continue
            try:
                future.result()
            except Exception:
                # Publish failures before the future stops counting as active.
                self._stored_exceptions.put(future)
            self._futures.remove(future)
            completed.append((future, self._future_task_map.pop(future)))
        return completed

    def _complete_tasks(
        self,
        completed: List[Tuple[Future[T_RESULT], Task[T_RESULT]]],
    ) -> None:
        for future, task in completed:
            try:
                result = future.result()
            except Exception:
                task.close()
                continue
            task.close()

            # set result back for tracking order
            task.result = result

            if self._callback:
                self._callback(result)

    def _process_pending_tasks(
        self, done_futures: Iterable[Future[T_RESULT]] = ()
    ) -> None:
        new_futures: List[Future[T_RESULT]] = []
        completed: List[Tuple[Future[T_RESULT], Task[T_RESULT]]] = []
        with self._process_lock:
            completed = self._collect_done_futures_locked(done_futures)
            while (
                not self._pending_tasks.empty()
                and len(self._futures) < self._max_workers
            ):
                self.check_cancelled()
                task = self._pending_tasks.get()
                future: Future[T_RESULT] = self._pool.submit(task)
                self._future_task_map[future] = task
                self._futures.add(future)
                new_futures.append(future)

        # Register callbacks and process results outside the scheduler lock. A future
        # may already be complete, in which case add_done_callback invokes immediately.
        for future in new_futures:
            future.add_done_callback(self._on_future_done)
        self._complete_tasks(completed)

    def _on_future_done(self, future: Future[T_RESULT]) -> None:
        # Process the completed future and schedule next task. This runs in the
        # worker thread that completed the task.
        self._process_pending_tasks((future,))


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
    task_manager = TaskManager(max_workers=max(1, len(tasks)), callback=callback)
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
    if not tasks:
        return []

    # set a fixed size list to keep the order of results
    results: List[Optional[T_RESULT]] = [None] * len(tasks)
    wrapped_tasks: List[Task[T_RESULT]] = []

    task_manager = TaskManager[T_RESULT](
        max_workers=len(tasks), callback=lambda _: None
    )
    # If this call is running inside a StoppableThread (e.g. func_timeout),
    # the monitor will cancel pending work and shut down the pool when the
    # caller thread is killed, preventing orphaned executor threads.
    task_manager.start_orphan_monitor()

    for index, task in enumerate(tasks):
        task = Task(task_id=index, task=task, parent_logger=log)
        wrapped_tasks.append(task)
        task_manager.submit_task(task)

    task_manager.wait_for_all_workers()

    for wrapped_task in wrapped_tasks:
        results[wrapped_task.id] = wrapped_task.result

    return results  # type: ignore
