import logging
import os
import time

# to prevent circular import, hard code it here.
env_key_run_local_path = "LISA_RUN_LOCAL_PATH"


def log_lines(level: int, content: str, prefix: str = "") -> None:
    for line in content.splitlines(False):
        if prefix:
            log.log(level, f"{prefix}{line}")
        else:
            log.log(level, line)


def init_log() -> None:
    format = "%(asctime)s.%(msecs)03d[%(levelname)-.1s]%(name)s %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=format,
        datefmt="%m%d %H:%M:%S",
        handlers=[
            logging.FileHandler(f"{os.getenv(env_key_run_local_path)}/lisa-host.log"),
            logging.StreamHandler(),
        ],
    )
    logging.Formatter.converter = time.gmtime


log = logging.getLogger("LISA")
