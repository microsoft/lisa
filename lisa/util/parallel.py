# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import concurrent.futures
import time
from typing import Any, Callable, List, Optional


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
    log: Optional[Any] = None,
) -> List[Any]:
    """
    start methods in a thread pool
    """

    results: List[Any] = []
    if max_workers <= 0:
        max_workers = len(methods)
    with concurrent.futures.ThreadPoolExecutor(max_workers) as pool:
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
