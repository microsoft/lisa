import os
from argparse import Namespace

import yaml

from lisa.parameter_parser.config import Config
from lisa.util.logger import log


def parse(args: Namespace) -> Config:
    path = args.config
    path = os.path.realpath(path)
    log.info(f"load config from: {path}")
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    with open(path, "r") as file:
        data = yaml.safe_load(file)

    log.debug(f"final config data: {data}")
    base_path = os.path.dirname(path)
    log.debug(f"base path is {base_path}")
    config = Config(base_path, data)
    return config
