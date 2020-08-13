import asyncio
from argparse import Namespace
from pathlib import Path, PurePath
from typing import Dict, List, Optional, cast

from lisa.core.environmentFactory import EnvironmentFactory
from lisa.core.package import import_module
from lisa.core.platformFactory import PlatformFactory
from lisa.core.testFactory import TestFactory
from lisa.parameter_parser.config import Config
from lisa.parameter_parser.parser import parse
from lisa.sut_orchestrator.ready import ReadyPlatform
from lisa.test_runner.lisarunner import LISARunner
from lisa.util import constants
from lisa.util.exceptions import LisaException
from lisa.util.logger import log


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
    config = parse(args)

    # load external extension
    _load_extends(config.base_path, config.get_extension())

    # initialize environment
    environment_factory = EnvironmentFactory()
    environment_factory.load_environments(config.get_environment())

    # initialize platform
    factory = PlatformFactory()
    factory.initialize_platform(config.get_platform())

    _validate()


def run(args: Namespace) -> None:
    _initialize(args)

    platform = PlatformFactory().current

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
    if args.type == constants.LIST_CASE:
        if list_all:
            factory = TestFactory()
            for metadata in factory.cases.values():
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


def _validate() -> None:
    environment_config = Config().get_environment()
    warn_as_error = False
    if environment_config:
        warn_as_error = cast(
            bool, environment_config.get(constants.WARN_AS_ERROR, False)
        )
    factory = EnvironmentFactory()
    enviornments = factory.environments
    platform = PlatformFactory().current
    for environment in enviornments.values():
        if environment.spec is not None and isinstance(platform, ReadyPlatform):
            _validate_message(
                warn_as_error, "the ready platform cannot process environment spec"
            )


def _validate_message(warn_as_error: bool, message: str) -> None:
    if warn_as_error:
        raise LisaException(message)
    else:
        log.warn(message)
