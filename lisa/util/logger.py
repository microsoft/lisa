import logging
import time
from functools import partial
from typing import Dict, List, Optional, Union, cast

from lisa.util import LisaException

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

    def warn_or_raise(self, raise_error: bool, message: str) -> None:
        if raise_error:
            raise LisaException(message)
        else:
            self.warn(message)


_get_root_logger = partial(logging.getLogger, DEFAULT_LOG_NAME)

_format = "%(asctime)s.%(msecs)03d[%(levelname)-.1s]%(name)s %(message)s"
_datefmt = "%m%d %H:%M:%S"


def init_loggger() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=_format,
        datefmt=_datefmt,
        handlers=[logging.StreamHandler()],
    )
    logging.Formatter.converter = time.gmtime
    logging.setLoggerClass(Logger)


def set_log_file(path: str) -> None:
    root_logger = _get_root_logger()
    file_handler = logging.FileHandler(path)
    file_handler.setLevel(root_logger.level)
    file_handler.setFormatter(logging.Formatter(fmt=_format, datefmt=_datefmt))
    root_logger.addHandler(file_handler)


def set_level(level: int) -> None:
    root_logger = _get_root_logger()
    root_logger.setLevel(level)


def get_logger(
    name: str = "", id_: str = "", parent: Optional[Logger] = None
) -> Logger:
    if not name:
        name = ""
    if id_:
        name = f"{name}[{id_}]"
    root_logger = cast(Logger, _get_root_logger())
    if not name:
        logger = root_logger
    else:
        if parent:
            parent_name = parent.name
            if parent_name.startswith(f"{DEFAULT_LOG_NAME}."):
                parent_name = parent_name[len(DEFAULT_LOG_NAME) + 1 :]
            if not parent_name.endswith("]"):
                parent_name = f"{parent_name}."
            name = f"{parent_name}{name}"
        logger = cast(Logger, root_logger.getChild(name))
    return logger
