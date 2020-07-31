import os

RESULT_PATH = "RESULT_PATH"

__prefix = "LISA_"


def set_env(name: str, value: str, isSecret=False):
    name = "%s%s" % (__prefix, name)
    os.environ[name] = value


def get_env(name: str):
    name = "%s%s" % (__prefix, name)
    return os.environ[name]
