import os
from pathlib import PurePath

WORKING_PATH = "working"

KEY_RUN_ROOT_PATH = "RUN_ROOT_PATH"

__prefix = "LISA_"


def get_run_root_path() -> PurePath:
    return get_env(KEY_RUN_ROOT_PATH)


def get_working_path() -> PurePath:
    return get_run_root_path().joinpath(WORKING_PATH)


def set_env(name: str, value: str, isSecret: bool = False) -> None:
    name = f"{__prefix}{name}"
    os.environ[name] = value


def get_env(name: str) -> str:
    name = f"{__prefix}{name}"
    return os.environ[name]
