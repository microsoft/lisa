import os
import sys
from datetime import datetime
from logging import DEBUG, INFO

from retry import retry

from lisa.parameter_parser.argparser import parse_args
from lisa.util import env
from lisa.util.logger import init_log, log


@retry(FileExistsError, tries=10, delay=0)  # type: ignore
def create_result_path() -> str:
    date = datetime.utcnow().strftime("%Y%m%d")
    time = datetime.utcnow().strftime("%H%M%S-%f")[:-3]
    current_path = f"runtime/results/{date}/{date}-{time}"
    if os.path.exists(current_path):
        raise FileExistsError(f"{current_path} exists, and not found an unique path.")
    return current_path


def main() -> None:
    # create result path
    result_path = os.path.realpath(create_result_path())
    os.makedirs(result_path)
    env.set_env(env.RESULT_PATH, result_path)

    args = parse_args()

    init_log()
    log.info(f"Python version: {sys.version}")
    log.info(f"local time: {datetime.now().astimezone()}")
    log.info(f"command line args: {sys.argv}")
    log.info(f"result path: {env.get_env(env.RESULT_PATH)}")

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
        # force all threads end.
        os._exit(exitCode)
