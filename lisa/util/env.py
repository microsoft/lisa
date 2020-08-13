import os
from pathlib import PurePath

KEY_RUN_LOCAL_PATH = "RUN_LOCAL_PATH"
KEY_RUN_PATH = "RUN_PATH"

__prefix = "LISA_"


def get_run_local_path() -> PurePath:
    return PurePath(get_env(KEY_RUN_LOCAL_PATH))


def get_run_path() -> PurePath:
    return PurePath(get_env(KEY_RUN_PATH))


def set_env(name: str, value: str, is_secret: bool = False) -> None:
    name = f"{__prefix}{name}"
    os.environ[name] = value


def get_env(name: str) -> str:
    name = f"{__prefix}{name}"
    return os.environ[name]
