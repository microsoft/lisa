import sys
from datetime import datetime
from logging import DEBUG, INFO
from pathlib import Path

from retry import retry  # type: ignore

from lisa.parameter_parser.argparser import parse_args
from lisa.util import env
from lisa.util.logger import init_log, log


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
    local_path = Path("runtime").joinpath("runs").absolute()
    # create run root path
    run_path = create_run_path(local_path)
    local_path = local_path.joinpath(run_path)
    local_path.mkdir(parents=True)
    env.set_env(env.KEY_RUN_LOCAL_PATH, str(local_path))
    env.set_env(env.KEY_RUN_PATH, str(run_path))

    args = parse_args()

    init_log()
    log.info(f"Python version: {sys.version}")
    log.info(f"local time: {datetime.now().astimezone()}")
    log.info(f"command line args: {sys.argv}")
    log.info(f"run local path: {env.get_run_local_path()}")

    if args.debug:
        log_level = DEBUG
    else:
        log_level = INFO
    log.setLevel(log_level)

    args.func(args)


if __name__ == "__main__":
    exit_code = 0
    try:
        main()
    except Exception as exception:
        log.exception(exception)
        exit_code = -1
    finally:
        sys.exit(exit_code)
