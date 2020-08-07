import logging
import os
import time

# to prevent circular import, hard code it here.
env_result_path = "LISA_RESULT_PATH"


def log_lines(logLevel: int, content: str, prefix: str = "") -> None:
    for line in content.splitlines(False):
        if prefix:
            log.log(logLevel, f"{prefix} {line}")
        else:
            log.log(logLevel, line)


def init_log() -> None:
    format = "%(asctime)s.%(msecs)03d[%(levelname)-.1s]%(name)s %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=format,
        datefmt="%m%d %H:%M:%S",
        handlers=[
            logging.FileHandler(f"{os.getenv(env_result_path)}/lisa-host.log"),
            logging.StreamHandler(),
        ],
    )
    logging.Formatter.converter = time.gmtime


log = logging.getLogger("LISA")
