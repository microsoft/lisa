import asyncio
from lisa.core.platform_factory import platform_factory
from lisa.core.runtimeObject import RuntimeObject
from lisa.core.environment import Environment
import os
from lisa.core.package import import_module
from lisa import log
from lisa.test_runner.lisarunner import LISARunner
from lisa.parameter_parser.parser import parse


def _load_extends(extends_config):
    if extends_config is not None:
        paths = extends_config.get("paths")
        if paths is not None:
            for path in paths:
                import_module(path)


def _initialize(args):

    # make sure extensions in lisa is loaded
    base_module_path = os.path.dirname(__file__)
    import_module(base_module_path, logDetails=False)

    # merge all parameters
    config = parse(args)
    runtime_object = RuntimeObject(config)

    # load external extensions
    extends_config = config.getExtensions()
    _load_extends(extends_config)

    # initialize environment
    environment_config = config.getEnvironment()
    environment = Environment.loadEnvironment(environment_config)
    runtime_object.environment = environment

    # initialize platform
    platform_config = config.getPlatform()
    runtime_object.platform = platform_factory.initializePlatform(platform_config)

    runtime_object.validate()

    return runtime_object


def run(args):
    runtime_object = _initialize(args)
    runner = LISARunner()
    awaitable = runner.start()
    asyncio.run(awaitable)


# check configs
def check(args):
    _initialize(args)


def list_start(args):
    runtime_object = _initialize(args)
    log.info("list information here")
