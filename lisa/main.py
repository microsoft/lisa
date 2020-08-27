import sys
from datetime import datetime
from logging import DEBUG, INFO
from pathlib import Path

from retry import retry  # type: ignore

from lisa.parameter_parser.argparser import parse_args
from lisa.util import constants
from lisa.util.logger import get_logger, set_level, set_log_file


@retry(FileExistsError, tries=10, delay=0)  # type: ignore
def create_run_path(root_path: Path) -> Path:
    date = datetime.utcnow().strftime("%Y%m%d")
    time = datetime.utcnow().strftime("%H%M%S-%f")[:-3]
    run_path = Path(f"{date}/{date}-{time}")
    local_path = root_path.joinpath(run_path)
    if local_path.exists():
        raise FileExistsError(f"{local_path} exists, and not found an unique path.")
    return run_path


def main() -> None:
    runtime_root = Path("runtime").absolute()

    constants.CACHE_PATH = runtime_root.joinpath("cache")
    constants.CACHE_PATH.mkdir(parents=True, exist_ok=True)
    # create run root path
    runs_path = runtime_root.joinpath("runs")
    logic_path = create_run_path(runs_path)
    local_path = runtime_root.joinpath(logic_path)
    local_path.mkdir(parents=True)

    constants.RUN_ID = logic_path.name
    constants.RUN_LOCAL_PATH = local_path
    constants.RUN_LOGIC_PATH = logic_path

    args = parse_args()

    set_log_file(f"{runtime_root}/lisa-host.log")

    log = get_logger()
    log.info(f"Python version: {sys.version}")
    log.info(f"local time: {datetime.now().astimezone()}")
    log.info(f"command line args: {sys.argv}")
    log.info(f"run local path: {runtime_root}")

    if args.debug:
        log_level = DEBUG
    else:
        log_level = INFO
    set_level(log_level)

    args.func(args)


if __name__ == "__main__":
    exit_code = 0
    try:
        main()
    except Exception as exception:
        log = get_logger()
        log.exception(exception)
        exit_code = -1
    finally:
        sys.exit(exit_code)
