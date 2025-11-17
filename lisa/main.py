# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


import subprocess
import sys
import traceback
from datetime import datetime, timezone
from logging import DEBUG, INFO, FileHandler
from pathlib import Path, PurePath
from typing import Optional

from retry import retry

# force to import all modules for reflection use
import lisa.mixin_modules  # noqa: F401
from lisa.parameter_parser.argparser import parse_args
from lisa.util import constants, get_datetime_path
from lisa.util.logger import (
    Logger,
    create_file_handler,
    get_logger,
    remove_handler,
    set_console_level,
    uninit_logger,
)
from lisa.util.perf_timer import create_timer
from lisa.variable import add_secrets_from_pairs

_runtime_root = Path("runtime").absolute()


def _normalize_path(path_type: str, path: Optional[Path] = None) -> Path:
    # Layout the run time folder structure.
    if path:
        # if log path is relative path, join with root.
        if not path.is_absolute():
            path = _runtime_root / path
    else:
        path = _runtime_root / path_type

    return path


def _dump_code_information(log: Logger) -> None:
    command = r'git log -1 "--pretty=format:%H%d %ci, %s"'
    output = subprocess.getoutput(command)
    log.info(f"git head: {output}")
    submodule_cmd = f"git submodule foreach --recursive {command}"
    output = subprocess.getoutput(submodule_cmd)
    if output:
        log.info(f"submodules: {output}")


@retry(FileExistsError, tries=10, delay=0.2)  # type: ignore
def test_path(
    log_root_path: Path, working_root_path: Path, run_id: str = ""
) -> PurePath:
    if run_id:
        # use predefined run_id
        logic_path = PurePath(run_id)
    else:
        # Get current time and generate a Run ID.
        current_time = datetime.now(timezone.utc)
        date_of_today = current_time.strftime("%Y%m%d")
        time_of_today = get_datetime_path(current_time)
        logic_path = PurePath(f"{date_of_today}/{time_of_today}")

    log_path = log_root_path / logic_path
    if log_path.exists():
        raise FileExistsError(
            f"The log path '{log_path}' already exists, "
            f"and not found an unique path."
        )
    working_path = working_root_path / logic_path
    if working_path.exists():
        raise FileExistsError(
            f"The working path '{working_path}' already exists, "
            f"and not found an unique path."
        )

    log_path.mkdir(parents=True)
    return logic_path


def initialize_runtime_folder(
    log_path: Optional[Path] = None,
    working_path: Optional[Path] = None,
    run_id: str = "",
) -> None:
    # Layout the run time folder structure.
    log_path = _normalize_path("log", log_path)
    working_path = _normalize_path("working", working_path)

    # Set cache path after working_path is normalized
    cache_path = working_path.parent / "cache"
    cache_path.mkdir(parents=True, exist_ok=True)
    constants.CACHE_PATH = cache_path

    logic_path = test_path(log_path, working_path, run_id=run_id)

    constants.RUN_ID = logic_path.name
    constants.RUN_LOGIC_PATH = logic_path
    constants.RUN_LOCAL_LOG_PATH = log_path / logic_path
    constants.RUN_LOCAL_WORKING_PATH = working_path / logic_path


def main() -> int:
    total_timer = create_timer()
    log = get_logger()
    exit_code: int = 0
    file_handler: Optional[FileHandler] = None

    try:
        args = parse_args()

        initialize_runtime_folder(args.log_path, args.working_path, args.run_id)

        log_level = DEBUG if (args.debug) else INFO
        set_console_level(log_level)

        file_handler = create_file_handler(
            Path(f"{constants.RUN_LOCAL_LOG_PATH}/lisa-{constants.RUN_ID}.log")
        )

        log.info(f"Python version: {sys.version}")
        log.info(f"local time: {datetime.now().astimezone()}")

        _dump_code_information(log)

        # We don't want command line args logging to leak any provided
        # secrets, if any ("s:key:value" syntax)
        add_secrets_from_pairs(args.variables)

        log.debug(f"command line args: {sys.argv}")
        log.info(
            f"run log path: {constants.RUN_LOCAL_LOG_PATH}, "
            f"working path: {constants.RUN_LOCAL_WORKING_PATH}"
        )

        exit_code = args.func(args)
        assert isinstance(exit_code, int), f"actual: {type(exit_code)}"
    finally:
        log.info(f"completed in {total_timer}")
        if file_handler:
            remove_handler(log_handler=file_handler, logger=log)
        uninit_logger()

    return exit_code


def cli() -> int:
    """
    CLI entry point
    """

    exit_code = 0
    try:
        exit_code = main()
    except Exception as exception:
        exit_code = -1
        log = get_logger()
        try:
            log.exception(exception)
        except Exception:
            # if there is any exception in log class,
            # they have to be caught and show on console only
            traceback.print_exc()
    finally:
        sys.exit(exit_code)


if __name__ == "__main__":
    cli()
