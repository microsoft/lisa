import asyncio
import functools
from argparse import Namespace
from typing import Iterable, Optional, cast

from lisa import notifier
from lisa.lisarunner import LisaRunner
from lisa.parameter_parser.runbook import load as load_runbook
from lisa.testselector import select_testcases
from lisa.testsuite import TestCaseRuntimeData
from lisa.util import LisaException, constants
from lisa.util.logger import get_logger
from lisa.util.perf_timer import create_timer

_get_init_logger = functools.partial(get_logger, "init")


def run(args: Namespace) -> int:
    runbook = load_runbook(args)

    if runbook.notifier:
        notifier.initialize(runbooks=runbook.notifier)
    run_message = notifier.TestRunMessage(
        status=constants.RUN_STATUS_RUNNING,
        test_project=runbook.test_project,
        test_pass=runbook.test_pass,
        run_name=constants.RUN_NAME,
        tags=runbook.tags,
    )
    notifier.notify(run_message)

    run_status = constants.RUN_STATUS_FAILED
    run_timer = create_timer()
    try:
        runner = LisaRunner(runbook)
        awaitable = runner.start()
        asyncio.run(awaitable)
        run_status = constants.RUN_STATUS_SUCCESS
    finally:
        run_message = notifier.TestRunMessage(
            status=run_status,
            test_project=runbook.test_project,
            test_pass=runbook.test_pass,
            run_name=constants.RUN_NAME,
            tags=runbook.tags,
            elapsed=run_timer.elapsed(),
        )
        notifier.notify(run_message)
        notifier.finalize()

    return runner.exit_code


# check runbook
def check(args: Namespace) -> int:
    load_runbook(args)
    return 0


def list_start(args: Namespace) -> int:
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
    return 0
