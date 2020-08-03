import asyncio
import os
from lisa.core.package import import_module, packages
from lisa import log, Platform
from lisa.test_runner.lisarunner import LISARunner
from lisa.parameter_parser.parser import parse
from lisa.core.platform_factory import platformFactory


def load_extends(extends_config):
    if extends_config is not None:
        paths = extends_config.get("paths")
        if paths is not None:
            for path in paths:
                import_module(path)


def build_factories(package_name):
    # platform factories
    for sub_class in Platform.__subclasses__():
        platformFactory.registerPlatform(sub_class)


def _initialize(args):
    base_module_path = os.path.dirname(__file__)
    import_module(base_module_path, logDetails=False)
    config = parse(args)
    extends_config = config.get("extends")
    load_extends(extends_config)
    for package_name in packages:
        build_factories(package_name)

    return config


def run(args):
    config = _initialize(args)
    runner = LISARunner()
    awaitable = runner.start()
    asyncio.run(awaitable)


def list_start(args):
    config = _initialize(args)
    log.info("list information here")
