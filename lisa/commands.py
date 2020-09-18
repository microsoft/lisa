import asyncio
import functools
from argparse import Namespace
from typing import Iterable, Optional, cast

from lisa.parameter_parser.runbook import load as load_runbook
from lisa.test_runner.lisarunner import LisaRunner
from lisa.testselector import select_testcases
from lisa.testsuite import TestCaseRuntimeData
from lisa.util import LisaException, constants
from lisa.util.logger import get_logger

_get_init_logger = functools.partial(get_logger, "init")


def run(args: Namespace) -> None:
    runbook = load_runbook(args)

    runner = LisaRunner()
    runner.config(constants.CONFIG_RUNBOOK, runbook)
    awaitable = runner.start()
    asyncio.run(awaitable)


# check runbook
def check(args: Namespace) -> None:
    load_runbook(args)


def list_start(args: Namespace) -> None:
    runbook = load_runbook(args)
    list_all = cast(Optional[bool], args.list_all)
    log = _get_init_logger("list")
    if args.type == constants.LIST_CASE:
        if list_all:
            cases: Iterable[TestCaseRuntimeData] = select_testcases()
        else:
            cases = select_testcases(runbook.testcase)
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
