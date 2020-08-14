import asyncio
from argparse import Namespace
from logging import Logger
from pathlib import Path, PurePath
from typing import Dict, List, Optional, cast

from lisa.environment import factory as env_factory
from lisa.parameter_parser.config import Config, parse_to_config
from lisa.platform_ import factory as platform_factory
from lisa.sut_orchestrator.ready import ReadyPlatform
from lisa.test_runner.lisarunner import LISARunner
from lisa.testsuite import factory as test_factory
from lisa.util import constants
from lisa.util.exceptions import LisaException
from lisa.util.logger import get_logger
from lisa.util.module import import_module


def _load_extends(base_path: Path, extends_config: Dict[str, object]) -> None:
    for p in cast(List[str], extends_config.get(constants.PATHS, list())):
        path = PurePath(p)
        if not path.is_absolute():
            path = base_path.joinpath(path)
        import_module(Path(path))


def _initialize(args: Namespace) -> None:

    # make sure extension in lisa is loaded
    base_module_path = Path(__file__).parent
    import_module(base_module_path, logDetails=False)

    # merge all parameters
    config = parse_to_config(args)

    # load external extension
    _load_extends(config.base_path, config.get_extension())

    # initialize environment
    env_factory.load_environments(config.get_environment())

    # initialize platform
    platform_factory.initialize_platform(config.get_platform())

    log = get_logger("init")
    _validate(config, log)


def run(args: Namespace) -> None:
    _initialize(args)

    platform = platform_factory.current

    runner = LISARunner()
    runner.config(constants.CONFIG_PLATFORM, platform)
    awaitable = runner.start()
    asyncio.run(awaitable)


# check configs
def check(args: Namespace) -> None:
    _initialize(args)


def list_start(args: Namespace) -> None:
    _initialize(args)
    list_all = cast(Optional[bool], args.list_all)
    log = get_logger("list")
    if args.type == constants.LIST_CASE:
        if list_all:
            for metadata in test_factory.cases.values():
                log.info(
                    f"case: {metadata.name}, suite: {metadata.suite.name}, "
                    f"area: {metadata.suite.area}, "
                    f"category: {metadata.suite.category}, "
                    f"tags: {','.join(metadata.suite.tags)}, "
                    f"priority: {metadata.priority}"
                )
        else:
            log.error("TODO: cannot list selected cases yet.")
    else:
        raise LisaException(f"unknown list type '{args.type}'")
    log.info("list information here")


def _validate(config: Config, log: Logger) -> None:
    environment_config = config.get_environment()
    warn_as_error = False
    if environment_config:
        warn_as_error = cast(
            bool, environment_config.get(constants.WARN_AS_ERROR, False)
        )

    enviornments = env_factory.environments
    platform = platform_factory.current
    for environment in enviornments.values():
        if environment.spec is not None and isinstance(platform, ReadyPlatform):
            _validate_message(
                warn_as_error, "the ready platform cannot process environment spec", log
            )


def _validate_message(warn_as_error: bool, message: str, log: Logger) -> None:
    if warn_as_error:
        raise LisaException(message)
    else:
        log.warn(message)
