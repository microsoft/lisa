from lisa.parameter_parser.argparser import parse_args
import os
import sys
from datetime import datetime
from logging import DEBUG, INFO

from lisa.common import env
from lisa.common.logger import init_log, log
from retry import retry

path_template = "runtime/results/{0}/{0}-{1}"


@retry(FileExistsError, tries=10, delay=0)
def create_result_path():
    date = datetime.utcnow().strftime("%Y%m%d")
    time = datetime.utcnow().strftime("%H%M%S-%f")[:-3]
    current_path = path_template.format(date, time)
    if os.path.exists(current_path):
        raise FileExistsError(
            "%s exists, and not found an unique path." % current_path
        )
    return current_path


def main():
    # create result path
    result_path = os.path.realpath(create_result_path())
    os.makedirs(result_path)
    env.set_env(env.RESULT_PATH, result_path)

    args = parse_args()

    init_log()
    log.info("Python version: %s" % sys.version)
    log.info("local time: %s", datetime.now().astimezone())
    log.info("command line args: %s" % sys.argv)
    log.info("result path: %s", env.get_env(env.RESULT_PATH))

    if args.debug:
        log_level = DEBUG
    else:
        log_level = INFO
    log.setLevel(log_level)
    log.info("show debug log: %s", args.debug)

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
