# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import sys
import traceback
from datetime import datetime
from logging import DEBUG, INFO
from pathlib import Path, PurePath
from typing import Tuple

from retry import retry

from lisa.parameter_parser.argparser import parse_args
from lisa.util import constants, get_datetime_path
from lisa.util.logger import create_file_handler, get_logger, set_level
from lisa.util.perf_timer import create_timer
from lisa.variable import add_secrets_from_pairs


@retry(FileExistsError, tries=10, delay=0.2)  # type: ignore
def generate_run_path(root_path: Path) -> Tuple[PurePath, Path]:
    # Get current time and generate a Run ID.
    current_time = datetime.utcnow()
    date_of_today = current_time.strftime("%Y%m%d")
    time_of_today = get_datetime_path(current_time)
    logic_path = PurePath(f"{date_of_today}/{time_of_today}")
    local_path = root_path.joinpath(logic_path)
    if local_path.exists():
        raise FileExistsError(
            f"The run path '{local_path}' already exists, "
            f"and not found an unique path."
        )
    local_path.mkdir(parents=True)
    return logic_path, local_path


def initialize_runtime_folder() -> None:
    runtime_root = Path("runtime").absolute()

    cache_path = runtime_root.joinpath("cache")
    cache_path.mkdir(parents=True, exist_ok=True)
    constants.CACHE_PATH = cache_path

    # Layout the run time folder structure.
    runs_path = runtime_root.joinpath("runs")
    logic_path, local_path = generate_run_path(runs_path)

    constants.RUN_ID = logic_path.name
    constants.RUN_LOGIC_PATH = logic_path
    constants.RUN_LOCAL_PATH = local_path


def main() -> int:
    total_timer = create_timer()
    log = get_logger()
    exit_code: int = 0

    try:
        initialize_runtime_folder()

        args = parse_args()

        log_level = DEBUG if (args.debug) else INFO
        set_level(log_level)

        create_file_handler(
            Path(f"{constants.RUN_LOCAL_PATH}/lisa-{constants.RUN_ID}.log")
        )

        log.info(f"Python version: {sys.version}")
        log.info(f"local time: {datetime.now().astimezone()}")

        # We don't want command line args logging to leak any provided
        # secrets, if any ("s:key:value" syntax)
        add_secrets_from_pairs(args.variables)

        log.debug(f"command line args: {sys.argv}")
        log.info(f"run local path: {constants.RUN_LOCAL_PATH}")

        exit_code = args.func(args)
        assert isinstance(exit_code, int), f"actual: {type(exit_code)}"
    finally:
        log.info(f"completed in {total_timer}")

    return exit_code


if __name__ == "__main__":
    exit_code = 0
    try:
        exit_code = main()
    except Exception as exception:
        exit_code = -1
        log = get_logger()
        try:
            log.exception(exception)
        except Exception:
            # if there is any exception in log class, they have to be caught and show
            # on console only
            traceback.print_exc()
    finally:
        sys.exit(exit_code)
