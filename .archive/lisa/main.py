import asyncio
import sys
import traceback
from datetime import datetime
from logging import DEBUG, INFO
from pathlib import Path

from retry import retry  # type: ignore

from lisa.parameter_parser.argparser import parse_args
from lisa.util import constants, get_datetime_path
from lisa.util.logger import get_logger, set_level, set_log_file
from lisa.util.perf_timer import create_timer


@retry(FileExistsError, tries=10, delay=0)  # type: ignore
def create_run_path(root_path: Path) -> Path:
    current_time = datetime.utcnow()
    date = current_time.strftime("%Y%m%d")
    date_time = get_datetime_path(current_time)
    run_path = Path(f"{date}/{date_time}")
    local_path = root_path.joinpath(run_path)
    if local_path.exists():
        raise FileExistsError(f"{local_path} exists, and not found an unique path.")
    return run_path


async def main() -> int:
    total_timer = create_timer()
    log = get_logger()
    exit_code: int = 0
    try:
        runtime_root = Path("runtime").absolute()

        constants.CACHE_PATH = runtime_root.joinpath("cache")
        constants.CACHE_PATH.mkdir(parents=True, exist_ok=True)
        # create run root path
        runs_path = runtime_root.joinpath("runs")
        logic_path = create_run_path(runs_path)
        local_path = runs_path.joinpath(logic_path)
        local_path.mkdir(parents=True)

        constants.RUN_ID = logic_path.name
        constants.RUN_LOCAL_PATH = local_path
        constants.RUN_LOGIC_PATH = logic_path

        args = parse_args()

        if args.debug:
            log_level = DEBUG
        else:
            log_level = INFO
        set_level(log_level)

        set_log_file(f"{local_path}/lisa-host.log")

        log.info(f"Python version: {sys.version}")
        log.info(f"local time: {datetime.now().astimezone()}")
        log.debug(f"command line args: {sys.argv}")
        log.info(f"run local path: {runtime_root}")

        exit_code = await args.func(args)
        assert isinstance(exit_code, int), f"actual: {type(exit_code)}"
    finally:
        log.info(f"completed in {total_timer}")

    return exit_code


if __name__ == "__main__":
    exit_code = 0
    try:
        exit_code = asyncio.run(main())
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
