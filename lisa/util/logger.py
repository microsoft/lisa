# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
import logging
import sys
import time
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, TextIO, Union, cast

from lisa.secret import mask
from lisa.util import LisaException, filter_ansi_escape, is_unittest

# to prevent circular import, hard code it here.
ENV_KEY_RUN_LOCAL_PATH = "LISA_RUN_LOCAL_PATH"
DEFAULT_LOG_NAME = "lisa"


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
            line = filter_ansi_escape(line)
            line = line.strip("\r\n")
            # No good in logging empty lines (and they can happen via
            # SSH stdout)
            if not line or line.isspace():
                continue
            if prefix:
                self.log(level, f"{prefix}{line}")
            else:
                self.log(level, line)

    def dump_json(self, level: int, content: Any, prefix: str = "") -> None:
        if content:
            content = json.dumps(content, indent=2)
            self.lines(level=level, content=content, prefix=prefix)

    def warn_or_raise(self, raise_error: bool, message: str) -> None:
        if raise_error:
            raise LisaException(message)
        else:
            self.warning(message)

    def _log(
        self,
        level: int,
        msg: Any,
        args: Any,
        exc_info: Any = None,
        extra: Optional[Mapping[str, object]] = None,
        stack_info: bool = False,
        stacklevel: int = 1,
    ) -> None:
        """
        Low-level log implementation, proxies to allow nested logger adapters.
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


class LogWriter(object):
    def __init__(self, logger: Logger, level: int):
        self._level = level
        self._log = logger
        self._buffer: str = ""
        self._flushing: bool = False

    def write(self, message: str) -> None:
        if not self._flushing:
            self._buffer = "".join([self._buffer, message])
            if "\n" in message:
                self.flush()

    def flush(self) -> None:
        if len(self._buffer) > 0 and not self._flushing:
            self._flushing = True
            try:
                buffer = self._buffer
                self._buffer = ""
                self._log.lines(self._level, buffer)
            finally:
                self._flushing = False

    def close(self) -> None:
        self.flush()


_get_root_logger = partial(logging.getLogger, DEFAULT_LOG_NAME)

_format = logging.Formatter(
    fmt="%(asctime)s.%(msecs)03d[%(thread)d][%(levelname)s] %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_console_handler = logging.StreamHandler()
_original_stdout = sys.stdout
_original_stderr = sys.stderr


def init_logger() -> None:
    logging.Formatter.converter = time.gmtime
    logging.setLoggerClass(Logger)
    logging.root.handlers = []

    root_logger = _get_root_logger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(_console_handler)

    stdout_logger = get_logger("stdout")
    stderr_logger = get_logger("stderr")
    sys.stdout = cast(TextIO, LogWriter(stdout_logger, logging.INFO))
    sys.stderr = cast(TextIO, LogWriter(stderr_logger, logging.ERROR))


def uninit_logger() -> None:
    # release stdout and stderr. prevent some thread errors may overrides the
    # whole log file.
    sys.stdout = _original_stdout
    sys.stderr = _original_stderr


def enable_console_timestamp() -> None:
    _console_handler.setFormatter(_format)


def add_handler(
    handler: logging.Handler,
    logger: Optional[logging.Logger] = None,
    formatter: Optional[logging.Formatter] = None,
) -> None:
    if is_unittest():
        return

    if logger is None:
        logger = _get_root_logger()
    # always include details in log file
    handler.setLevel(logging.DEBUG)
    if not formatter:
        formatter = _format
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def remove_handler(
    log_handler: logging.Handler, logger: Optional[logging.Logger] = None
) -> None:
    if is_unittest():
        return

    if logger is None:
        logger = _get_root_logger()
    logger.removeHandler(log_handler)


def create_file_handler(
    path: Path,
    logger: Optional[logging.Logger] = None,
    formatter: Optional[logging.Formatter] = None,
) -> logging.FileHandler:
    # skip to create log file in UT
    if is_unittest():
        return None  # type: ignore

    file_handler = logging.FileHandler(path, "w", "utf-8")
    add_handler(file_handler, logger, formatter)
    return file_handler


def set_console_level(level: int) -> None:
    _console_handler.setLevel(level)


def get_logger(
    name: str = "", id_: str = "", parent: Optional[Logger] = None
) -> Logger:
    if not name:
        name = ""
    if id_:
        name = f"{name}[{id_}]"
    if not parent:
        parent = cast(Logger, _get_root_logger())
    logger: Logger = parent.getChild(name)

    return logger
