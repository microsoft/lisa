import sys

from lisa.common.logger import log


def main():
    log.info("Python version: %s" % sys.version)
    log.info("args: %s" % sys.argv)


if __name__ == "__main__":
    try:
        main()
    except Exception as exception:
        log.exception(exception)
        raise
