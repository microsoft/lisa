import logging
import os
import time
from typing import Dict, List, Optional, Union, cast

# to prevent circular import, hard code it here.
ENV_KEY_RUN_LOCAL_PATH = "LISA_RUN_LOCAL_PATH"
DEFAULT_LOG_NAME = "LISA"


class Logger(logging.Logger):
    def lines(
        self,
        level: int,
        content: Union[str, List[str], Dict[str, str]],
        prefix: str = "",
    ) -> None:
        if isinstance(content, str):
            content = content.splitlines(False)
        elif isinstance(content, dict):
            temp_content: List[str] = []
            for key in content:
                temp_content.append(f"{key}: {content[key]}")
            content = temp_content
        for line in content:
            if prefix:
                self.log(level, f"{prefix}{line}")
            else:
                self.log(level, line)


_root_logger: Optional[Logger] = None


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
    logging.setLoggerClass(Logger)
    global _root_logger
    _root_logger = cast(Logger, logging.getLogger(DEFAULT_LOG_NAME))


def set_level(level: int) -> None:
    assert _root_logger
    _root_logger.setLevel(level)


def get_logger(
    name: str = "", id_: str = "", parent: Optional[Logger] = None
) -> Logger:
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
        logger = cast(Logger, _root_logger.getChild(name))

    return logger
