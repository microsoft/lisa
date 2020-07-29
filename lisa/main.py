import sys
import os
from datetime import datetime
from lisa.common.logger import log


def main():
    log.info("Python version: %s" % sys.version)
    log.info("command line args: %s" % sys.argv)
    log.info("local time: %s", datetime.now())
    log.info("result path: %s", os.environ["RESULT_PATH"])


if __name__ == "__main__":
    try:
        main()
    except Exception as exception:
        log.exception(exception)
        raise
