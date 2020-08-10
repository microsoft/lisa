import sys
from datetime import datetime
from logging import DEBUG, INFO
from pathlib import Path

from retry import retry  # type: ignore

from lisa.parameter_parser.argparser import parse_args
from lisa.util import env
from lisa.util.logger import init_log, log


@retry(FileExistsError, tries=10, delay=0)  # type: ignore
def create_run_root_path() -> Path:
    date = datetime.utcnow().strftime("%Y%m%d")
    time = datetime.utcnow().strftime("%H%M%S-%f")[:-3]
    current_path = f"runtime/runs/{date}/{date}-{time}"
    path_obj = Path(current_path)
    if path_obj.exists():
        raise FileExistsError(f"{current_path} exists, and not found an unique path.")
    return path_obj


def main() -> None:
    # create run root path
    run_root_path = create_run_root_path().absolute()
    run_root_path.mkdir(parents=True)
    env.set_env(env.KEY_RUN_ROOT_PATH, str(run_root_path))

    args = parse_args()

    init_log()
    log.info(f"Python version: {sys.version}")
    log.info(f"local time: {datetime.now().astimezone()}")
    log.info(f"command line args: {sys.argv}")
    log.info(f"run root path: {env.get_env(env.KEY_RUN_ROOT_PATH)}")

    if args.debug:
        log_level = DEBUG
    else:
        log_level = INFO
    log.setLevel(log_level)

    args.func(args)


if __name__ == "__main__":
    exitCode = 0
    try:
        main()
    except Exception as exception:
        log.exception(exception)
        exitCode = -1
    finally:
        sys.exit(exitCode)
