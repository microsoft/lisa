import logging
import sys
import time
from functools import partial
from typing import Any, Dict, List, Optional, TextIO, Union, cast

from lisa.secret import mask
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
            for key, value in content.items():
                temp_content.append(f"{key}: {value}")
            content = temp_content
        for line in content:
            if prefix:
                self.log(level, f"{prefix}{line}")
            else:
                self.log(level, line)

    def _log(
        self,
        level: int,
        msg: Any,
        args: Any,
        exc_info: Any = None,
        extra: Optional[Dict[str, Any]] = None,
        stack_info: bool = False,
        stacklevel: int = 1,
    ) -> None:
        """
        Low-level log implementation, proxied to allow nested logger adapters.
        """
        msg = self._filter_secrets(msg)
        args = self._filter_secrets(args)

        return super()._log(
            level,
            msg,
            args,
            exc_info=exc_info,
            extra=extra,
            stack_info=stack_info,
            stacklevel=stacklevel,
        )

    def _filter_secrets(self, value: Any) -> Any:
        if isinstance(value, str):
            value = mask(value)
        elif isinstance(value, Exception):
            value_args = list(value.args)
            for index, arg_item in enumerate(value.args):
                if isinstance(value_args[index], str):
                    value_args[index] = mask(arg_item)
            value.args = tuple(value_args)
        elif isinstance(value, tuple):
            value_list = self._filter_secrets(list(value))
            value = tuple(value_list)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                value[index] = self._filter_secrets(item)
        return value

    def warn_or_raise(self, raise_error: bool, message: str) -> None:
        if raise_error:
            raise LisaException(message)
        else:
            self.warning(message)


class LogWriter(object):
    def __init__(self, logger: Logger, level: int):
        self._level = level
        self._log = logger
        self._buffer: str = ""

    def write(self, message: str) -> None:
        self._buffer = "".join([self._buffer, message])
        if "\n" in message:
            self.flush()

    def flush(self) -> None:
        if len(self._buffer) > 0:
            self._log.lines(self._level, self._buffer)
            self._buffer = ""

    def close(self) -> None:
        self.flush()


_get_root_logger = partial(logging.getLogger, DEFAULT_LOG_NAME)

_format = logging.Formatter(
    fmt="%(asctime)s.%(msecs)03d %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_console_handler = logging.StreamHandler()


def init_loggger() -> None:
    logging.Formatter.converter = time.gmtime
    logging.setLoggerClass(Logger)
    logging.root.handlers = []

    root_logger = _get_root_logger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(_console_handler)

    _console_handler.setFormatter(_format)

    stdout_logger = get_logger("stdout")
    stderr_logger = get_logger("stderr")
    sys.stdout = cast(TextIO, LogWriter(stdout_logger, logging.INFO))
    sys.stderr = cast(TextIO, LogWriter(stderr_logger, logging.ERROR))


def set_log_file(path: str) -> None:
    root_logger = _get_root_logger()
    file_handler = logging.FileHandler(path, "w", "utf-8")
    # always include details in log file
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(_format)
    root_logger.addHandler(file_handler)


def set_level(level: int) -> None:
    _console_handler.setLevel(level)


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
