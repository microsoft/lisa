from argparse import Namespace
from pathlib import Path

import yaml

from lisa.parameter_parser.config import Config
from lisa.util.logger import log


def parse(args: Namespace) -> Config:
    path = Path(args.config).absolute()

    log.info(f"load config from: {path}")
    if not path.exists():
        raise FileNotFoundError(path)

    with open(path, "r") as file:
        data = yaml.safe_load(file)

    log.debug(f"final config data: {data}")
    base_path = path.parent
    log.debug(f"base path is {base_path}")
    config = Config(base_path, data)
    return config
