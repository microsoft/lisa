import asyncio
from argparse import Namespace
from pathlib import Path, PurePath
from typing import Dict, List, Optional, cast

from lisa.core.environmentFactory import EnvironmentFactory
from lisa.core.package import import_module
from lisa.core.platformFactory import PlatformFactory
from lisa.core.runtimeObject import RuntimeObject
from lisa.core.testFactory import TestFactory
from lisa.parameter_parser.parser import parse
from lisa.test_runner.lisarunner import LISARunner
from lisa.util import constants
from lisa.util.logger import log


def _load_extends(base_path: str, extends_config: Optional[Dict[str, object]]) -> None:
    if extends_config is not None:
        paths = cast(List[str], extends_config.get("paths"))
        base_path_obj = PurePath(base_path)
        for path in paths:
            path_obj = PurePath(path)
            if not path_obj.is_absolute():
                path_obj = base_path_obj.joinpath(path_obj)
            import_module(Path(path_obj))


def _initialize(args: Namespace) -> RuntimeObject:

    # make sure extension in lisa is loaded
    base_module_path = Path(__file__).parent
    import_module(base_module_path, logDetails=False)

    # merge all parameters
    config = parse(args)
    runtime_object = RuntimeObject(config)

    # load external extension
    extends_config = config.getExtension()
    _load_extends(config.base_path, extends_config)

    # initialize environment
    environments_config = config.getEnvironment()
    environment_factory = EnvironmentFactory()
    environment_factory.loadEnvironments(environments_config)

    # initialize platform
    platform_config = config.getPlatform()
    factory = PlatformFactory()
    runtime_object.platform = factory.initializePlatform(platform_config)

    runtime_object.validate()

    return runtime_object


def run(args: Namespace) -> None:
    runtime_object = _initialize(args)

    platform = runtime_object.platform

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
    if args.type == "case":
        if listAll is True:
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
