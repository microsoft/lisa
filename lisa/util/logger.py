import logging
import os
import time
from typing import Optional

# to prevent circular import, hard code it here.
ENV_KEY_RUN_LOCAL_PATH = "LISA_RUN_LOCAL_PATH"
DEFAULT_LOG_NAME = "LISA"

_root_logger: Optional[logging.Logger] = None


def init_loggger() -> None:
    format = "%(asctime)s.%(msecs)03d[%(levelname)-.1s]%(name)s %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=format,
        datefmt="%m%d %H:%M:%S",
        handlers=[
            logging.FileHandler(f"{os.getenv(ENV_KEY_RUN_LOCAL_PATH)}/lisa-host.log"),
            logging.StreamHandler(),
        ],
    )
    logging.Formatter.converter = time.gmtime
    global _root_logger
    _root_logger = logging.getLogger(DEFAULT_LOG_NAME)


def set_level(level: int) -> None:
    assert _root_logger
    _root_logger.setLevel(level)


def get_logger(
    name: str = "", id_: str = "", parent: Optional[logging.Logger] = None
) -> logging.Logger:
    if not name:
        name = ""
    if id_:
        name = f"{name}[{id_}]"
    assert _root_logger
    if not name:
        logger = _root_logger
    else:
        if parent:
            parent_name = parent.name
            if parent_name.startswith(f"{DEFAULT_LOG_NAME}."):
                parent_name = parent_name[len(DEFAULT_LOG_NAME) + 1 :]
            if not parent_name.endswith("]"):
                parent_name = f"{parent_name}."
            name = f"{parent_name}{name}"
        logger = _root_logger.getChild(name)
    logger.__setattr__("lines", _lines)

    return logger


def _lines(logger: logging.Logger, level: int, content: str, prefix: str = "") -> None:
    for line in content.splitlines(False):
        if prefix:
            logger.log(level, f"{prefix}{line}")
        else:
            logger.log(level, line)
