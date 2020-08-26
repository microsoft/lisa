import asyncio
import functools
from argparse import Namespace
from pathlib import Path, PurePath
from typing import Dict, Iterable, List, Optional, cast

import lisa.parameter_parser.runbook as runbook_ops
from lisa.environment import environments, load_environments
from lisa.platform_ import initialize_platforms, load_platforms, platforms
from lisa.schema import Runbook
from lisa.sut_orchestrator.ready import ReadyPlatform
from lisa.test_runner.lisarunner import LISARunner
from lisa.testselector import select_testcases
from lisa.testsuite import TestCaseData
from lisa.util import constants
from lisa.util.exceptions import LisaException
from lisa.util.logger import get_logger
from lisa.util.module import import_module

_get_init_logger = functools.partial(get_logger, "init")


def _load_extends(base_path: Path, extends_runbook: Dict[str, object]) -> None:
    for p in cast(List[str], extends_runbook.get(constants.PATHS, list())):
        path = PurePath(p)
        if not path.is_absolute():
            path = base_path.joinpath(path)
        import_module(Path(path))


def _initialize(args: Namespace) -> Iterable[TestCaseData]:
    # make sure extension in lisa is loaded
    base_module_path = Path(__file__).parent
    import_module(base_module_path, logDetails=False)

    initialize_platforms()

    # merge all parameters
    path = Path(args.runbook).absolute()
    data = runbook_ops.load(path)

    # load extended modules
    if constants.EXTENSION in data:
        _load_extends(path.parent, data[constants.EXTENSION])

    # validate runbook, after extensions loaded
    runbook = runbook_ops.validate(data)

    log = _get_init_logger()
    constants.RUN_NAME = f"lisa_{runbook.name}_{constants.RUN_ID}"
    log.info(f"run name is {constants.RUN_NAME}")
    # initialize environment
    load_environments(runbook.environment)

    # initialize platform
    load_platforms(runbook.platform)

    # filter test cases
    selected_cases = select_testcases(runbook.testcase)

    _validate(runbook)

    log.info(f"selected cases: {len(list(selected_cases))}")
    return selected_cases


def run(args: Namespace) -> None:
    selected_cases = _initialize(args)

    runner = LISARunner()
    runner.config(constants.CONFIG_PLATFORM, platforms.default)
    runner.config(constants.CONFIG_TEST_CASES, selected_cases)
    awaitable = runner.start()
    asyncio.run(awaitable)


# check runbook
def check(args: Namespace) -> None:
    _initialize(args)


def list_start(args: Namespace) -> None:
    selected_cases = _initialize(args)
    list_all = cast(Optional[bool], args.list_all)
    log = _get_init_logger("list")
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


def _validate(runbook: Runbook) -> None:
    if runbook.environment:
        log = _get_init_logger()
        for environment in environments.values():
            if environment.runbook is not None and isinstance(
                platforms.default, ReadyPlatform
            ):
                log.warn_or_raise(
                    runbook.environment.warn_as_error,
                    "the ready platform cannot process environment spec",
                )
