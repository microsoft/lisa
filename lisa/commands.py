import asyncio
import functools
from argparse import Namespace
from pathlib import Path, PurePath
from typing import Dict, Iterable, List, Optional, cast

from lisa.environment import get_environments, load_environments
from lisa.parameter_parser.config import Config, parse_to_config
from lisa.platform_ import get_current, initialize_platform
from lisa.sut_orchestrator.ready import ReadyPlatform
from lisa.test_runner.lisarunner import LISARunner
from lisa.testselector import select_testcases
from lisa.testsuite import TestCaseData
from lisa.util import constants
from lisa.util.exceptions import LisaException
from lisa.util.logger import get_logger
from lisa.util.module import import_module

_get_logger = functools.partial(get_logger, "init")


def _load_extends(base_path: Path, extends_config: Dict[str, object]) -> None:
    for p in cast(List[str], extends_config.get(constants.PATHS, list())):
        path = PurePath(p)
        if not path.is_absolute():
            path = base_path.joinpath(path)
        import_module(Path(path))


def _initialize(args: Namespace) -> Iterable[TestCaseData]:

    # make sure extension in lisa is loaded
    base_module_path = Path(__file__).parent
    import_module(base_module_path, logDetails=False)

    # merge all parameters
    config = parse_to_config(args)

    # load external extension
    _load_extends(config.base_path, config.get_extension())

    # initialize environment
    load_environments(config.get_environment())

    # initialize platform
    initialize_platform(config.get_platform())

    # filter test cases
    selected_cases = select_testcases(config.get_testcase())

    _validate(config)

    log = _get_logger()
    log.info(f"selected cases: {len(list(selected_cases))}")
    return selected_cases


def run(args: Namespace) -> None:
    selected_cases = _initialize(args)

    platform = get_current()

    runner = LISARunner()
    runner.config(constants.CONFIG_PLATFORM, platform)
    runner.config(constants.CONFIG_TEST_CASES, selected_cases)
    awaitable = runner.start()
    asyncio.run(awaitable)


# check configs
def check(args: Namespace) -> None:
    _initialize(args)


def list_start(args: Namespace) -> None:
    selected_cases = _initialize(args)
    list_all = cast(Optional[bool], args.list_all)
    log = get_logger("list")
    if args.type == constants.LIST_CASE:
        if list_all:
            cases: Iterable[TestCaseData] = select_testcases()
        else:
            cases = selected_cases
        for case_data in cases:
            log.info(
                f"case: {case_data.name}, suite: {case_data.metadata.suite.name}, "
                f"area: {case_data.suite.area}, "
                f"category: {case_data.suite.category}, "
                f"tags: {','.join(case_data.suite.tags)}, "
                f"priority: {case_data.priority}"
            )
    else:
        raise LisaException(f"unknown list type '{args.type}'")
    log.info("list information here")


def _validate(config: Config) -> None:
    environment_config = config.get_environment()
    warn_as_error = False
    if environment_config:
        warn_as_error = cast(
            bool, environment_config.get(constants.WARN_AS_ERROR, False)
        )

    enviornments = get_environments()
    platform = get_current()
    log = _get_logger()
    for environment in enviornments.values():
        if environment.spec is not None and isinstance(platform, ReadyPlatform):
            message = "the ready platform cannot process environment spec"
            if warn_as_error:
                raise LisaException(message)
            else:
                log.warn(message)
