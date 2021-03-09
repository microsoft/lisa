# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import copy
import itertools
from functools import partial
from logging import FileHandler
from typing import Any, Dict, List, Optional

from lisa import schema
from lisa.action import Action
from lisa.testsuite import TestResult, TestStatus
from lisa.util import BaseClassMixin, constants, run_in_threads
from lisa.util.logger import create_file_handler, get_logger, remove_handler
from lisa.util.subclasses import Factory


def parse_testcase_filters(raw_filters: List[Any]) -> List[schema.BaseTestCaseFilter]:
    if raw_filters:
        filters: List[schema.BaseTestCaseFilter] = []
        factory = Factory[schema.BaseTestCaseFilter](schema.BaseTestCaseFilter)
        for raw_filter in raw_filters:
            if constants.TYPE not in raw_filter:
                raw_filter[constants.TYPE] = constants.TESTCASE_TYPE_LISA
            filter = factory.create_runbook(raw_filter)
            filters.append(filter)
    else:
        filters = [schema.TestCase(name="test", criteria=schema.Criteria(area="demo"))]
    return filters


class BaseRunner(BaseClassMixin):
    """
    Base runner of other runners.
    """

    def __init__(self, runbook: schema.Runbook) -> None:
        super().__init__()
        self._runbook = runbook

        self._log = get_logger(self.type_name())
        self._log_handler: Optional[FileHandler] = None
        self.canceled = False

    def run(self, id_: str) -> List[TestResult]:
        # do not put this logic to __init__, since the mkdir takes time.
        if self.type_name() == constants.TESTCASE_TYPE_LISA:
            # default lisa runner doesn't need separated handler.
            self._working_folder = constants.RUN_LOCAL_PATH
        else:
            # create separated folder and log for each runner.
            runner_path_name = f"{self.type_name()}_runner"
            self._working_folder = constants.RUN_LOCAL_PATH / runner_path_name
            self._log_file_name = str(self._working_folder / f"{runner_path_name}.log")
            self._working_folder.mkdir(parents=True, exist_ok=True)
            self._log_handler = create_file_handler(self._log_file_name, self._log)
        return self._run(id_)

    def _run(self, id_: str) -> List[TestResult]:
        raise NotImplementedError()

    def close(self) -> None:
        if self._log_handler:
            remove_handler(self._log_handler)


class RootRunner(Action):
    """
    The entry runner, which starts other runners.
    """

    def __init__(self, runbook: schema.Runbook) -> None:
        super().__init__()
        self.exit_code: int = 0

        self._runbook = runbook
        self._log = get_logger("RootRunner")
        self._runners: List[BaseRunner] = []

    async def start(self) -> None:
        await super().start()

        self._initialize_runners()
        raw_results = self._start_run()

        test_results = list(itertools.chain(*raw_results))
        self._output_results(test_results)

        # pass failed count to exit code
        self.exit_code = sum(1 for x in test_results if x.status == TestStatus.FAILED)

    async def stop(self) -> None:
        await super().stop()
        # TODO: to be implemented

    async def close(self) -> None:
        await super().close()

    def _completed_callback(self, future: Any) -> None:
        """
        exit sub tests, once received cancellation message from executor.
        """
        # future is False, if it's called explicitly by run_in_threads.
        if not future or future.cancelled() or future.exception():
            self._log.debug(f"set cancel signal on future: {future}")
            for runner in self._runners:
                runner.canceled = True

    def _initialize_runners(self) -> None:
        # group filters by runner type
        runner_filters: Dict[str, List[schema.BaseTestCaseFilter]] = {}
        for raw_filter in self._runbook.testcase_raw:
            # by default run all filtered cases unless 'enable' is specified as false
            filter = schema.BaseTestCaseFilter.schema().load(raw_filter)  # type:ignore
            if filter.enable:
                raw_filters: List[schema.BaseTestCaseFilter] = runner_filters.get(
                    filter.type, []
                )
                if not raw_filters:
                    runner_filters[filter.type] = raw_filters
                raw_filters.append(raw_filter)
            else:
                self._log.debug(f"Skip disabled filter: {raw_filter}.")

        # initialize runners
        factory = Factory[BaseRunner](BaseRunner)
        for runner_name, raw_filters in runner_filters.items():
            self._log.debug(
                f"create runner {runner_name} with {len(raw_filters)} filter(s)."
            )

            runbook = copy.copy(self._runbook)
            # keep filters to current runner's only.
            runbook.testcase = parse_testcase_filters(raw_filters)
            runner = factory.create_by_type_name(runner_name, runbook=runbook)

            self._runners.append(runner)

    def _output_results(self, test_results: List[TestResult]) -> None:
        self._log.info("________________________________________")
        result_count_dict: Dict[TestStatus, int] = dict()
        for test_result in test_results:
            self._log.info(
                f"{test_result.runtime_data.metadata.full_name:>50}: "
                f"{test_result.status.name:<8} {test_result.message}"
            )
            result_count = result_count_dict.get(test_result.status, 0)
            result_count += 1
            result_count_dict[test_result.status] = result_count

        self._log.info("test result summary")
        self._log.info(f"  TOTAL      : {len(test_results)}")
        for key in TestStatus:
            count = result_count_dict.get(key, 0)
            if key == TestStatus.ATTEMPTED and count == 0:
                # attempted is confusing, if user don't know it.
                # so hide it, if there is no attempted cases.
                continue
            self._log.info(f"    {key.name:<9}: {count}")

    def _start_run(self) -> List[List[TestResult]]:
        raw_results: List[List[TestResult]] = []
        # in case all of runners are disabled
        if self._runners:
            try:
                raw_results = run_in_threads(
                    [
                        partial(runner.run, id_=runner.type_name())
                        for runner in self._runners
                    ],
                    completed_callback=self._completed_callback,
                    log=self._log,
                )
            finally:
                for runner in self._runners:
                    runner.close()
        return raw_results
