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
from lisa.util.logger import log


def _load_extends(base_path: Path, extends_config: Optional[Dict[str, object]]) -> None:
    if extends_config is not None:
        paths_str = cast(List[str], extends_config.get(constants.PATHS))
        for path_str in paths_str:
            path = PurePath(path_str)
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
    _load_extends(config.base_path, config.getExtension())

    # initialize environment
    environment_factory = EnvironmentFactory()
    environment_factory.loadEnvironments(config.getEnvironment())

    # initialize platform
    factory = PlatformFactory()
    factory.initializePlatform(config.getPlatform())

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
    listAll = cast(Optional[bool], args.listAll)
    if args.type == constants.LIST_CASE:
        if listAll:
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
        raise Exception(f"unknown list type '{args.type}'")
    log.info("list information here")


def _validate() -> None:
    environment_config = Config().getEnvironment()
    warn_as_error: Optional[bool] = None
    if environment_config is not None:
        warn_as_error = cast(
            Optional[bool], environment_config.get(constants.WARN_AS_ERROR)
        )
    factory = EnvironmentFactory()
    enviornments = factory.environments
    platform = PlatformFactory().current
    for environment in enviornments.values():
        if environment.spec is not None and isinstance(platform, ReadyPlatform):
            _validateMessage(
                warn_as_error, "the ready platform cannot process environment spec"
            )


def _validateMessage(warn_as_error: Optional[bool], message: str) -> None:
    if warn_as_error:
        raise Exception(message)
    else:
        log.warn(message)
