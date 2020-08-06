import asyncio
import os
from argparse import Namespace
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
        if paths is not None:
            for path in paths:
                if not os.path.isabs(path):
                    path = os.path.join(base_path, path)
                import_module(path)


def _initialize(args: Namespace) -> RuntimeObject:

    # make sure extension in lisa is loaded
    base_module_path = os.path.dirname(__file__)
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
                    "case: %s, suite: %s, area: %s, "
                    + "category: %s, tags: %s, priority: %s",
                    metadata.name,
                    metadata.suite.name,
                    metadata.suite.area,
                    metadata.suite.category,
                    ",".join(metadata.suite.tags),
                    metadata.priority,
                )
        else:
            log.error("TODO: cannot list selected cases yet.")
    else:
        raise Exception("unknown list type '%s'" % args.type)
    log.info("list information here")
