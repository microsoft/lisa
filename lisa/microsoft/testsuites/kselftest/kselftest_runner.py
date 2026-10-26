# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import argparse
import os
import re
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import List, Tuple


def _get_timeout(runner: Path, collection: str) -> int:
    timeout = 45
    settings = runner.parent / collection / "settings"
    if settings.exists():
        for line in settings.read_text(encoding="utf-8").splitlines():
            field, separator, value = line.partition("#")[0].partition("=")
            if separator and field.strip() == "timeout":
                value = value.strip()
                if not value.isdigit():
                    raise ValueError(
                        f"Invalid kselftest timeout in {settings}: {value}"
                    )
                timeout = int(value)
    return timeout


def _kill_session(session_id: int) -> None:
    # The harness changes process groups, so killing only the runner's group
    # misses orphaned children that still own its output pipe.
    for stat_path in Path("/proc").glob("[0-9]*/stat"):
        try:
            stat = stat_path.read_text(encoding="utf-8")
            fields = stat.rsplit(")", 1)[1].split()
            if int(fields[3]) == session_id:
                os.kill(int(stat_path.parent.name), signal.SIGKILL)
        except (FileNotFoundError, ProcessLookupError):
            # Processes can exit between listing /proc and sending the signal.
            continue


def _run_test(runner: Path, test: str, timeout: float) -> Tuple[str, bool]:
    timed_out = False
    # A regular file keeps leaked descriptors from blocking output collection.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as output:
        process = subprocess.Popen(
            [str(runner), "-f", "-t", test],
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            _kill_session(process.pid)
            process.wait(timeout=5)
        output.seek(0)
        result = output.read()

    if not timed_out and process.returncode != 0:
        raise RuntimeError(
            f"kselftest runner failed for {test}, exit={process.returncode}:\n{result}"
        )
    if not timed_out and not re.search(
        r"^(?:not ok|ok)\s+\d+\s+selftests:", result, re.MULTILINE
    ):
        raise RuntimeError(f"kselftest runner produced no result for {test}:\n{result}")
    return result, timed_out


def run_tests(
    runner: Path,
    tests: List[str],
    result_file: Path,
    timeout: float,
    append: bool = False,
) -> None:
    deadline = time.monotonic() + timeout
    with result_file.open("a" if append else "w", encoding="utf-8") as log:
        for test in tests:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("kselftest execution exceeded its overall timeout")
            collection, name = test.split(":", 1)
            test_timeout = _get_timeout(runner, collection)
            # Give the upstream timeout time to report its own TAP result first.
            hard_timeout = (
                min(test_timeout + 10, remaining) if test_timeout else remaining
            )
            output, timed_out = _run_test(runner, test, hard_timeout)
            if timed_out:
                output += (
                    f"\n# LISA: kselftest runner did not finish within "
                    f"{hard_timeout:g} seconds; cleaned up its process session.\n"
                    f"not ok 1 selftests: {collection}: {name}"
                    f" # TIMEOUT {hard_timeout:g} seconds\n"
                )
            log.write(output)
            log.flush()
            print(output, end="", flush=True)
            if timed_out and hard_timeout == remaining:
                raise TimeoutError("kselftest execution exceeded its overall timeout")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--result-file", type=Path, required=True)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--append", action="store_true")
    parser.add_argument("tests", nargs="+")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    run_tests(
        args.runner,
        args.tests,
        args.result_file,
        args.timeout,
        args.append,
    )


if __name__ == "__main__":
    main()
