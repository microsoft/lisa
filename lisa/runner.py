# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import copy
import time
import timeit
from logging import FileHandler
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict, Iterator, List, Optional

from lisa import notifier, schema, transformer
from lisa.action import Action
from lisa.combinator import Combinator
from lisa.parameter_parser.runbook import RunbookBuilder
from lisa.testsuite import TestResult, TestResultMessage, TestStatus
from lisa.util import BaseClassMixin, InitializableMixin, LisaException, constants
from lisa.util import logger
from lisa.util.logger import Logger, create_file_handler, get_logger, remove_handler
from lisa.util.parallel import Task, TaskManager, cancel, set_global_task_manager
from lisa.util.perf_timer import create_timer
from lisa.util.subclasses import Factory
from lisa.variable import VariableEntry, get_case_variables, replace_variables


def parse_testcase_filters(raw_filters: List[Any]) -> List[schema.BaseTestCaseFilter]:
    if raw_filters:
        filters: List[schema.BaseTestCaseFilter] = []
        factory = Factory[schema.BaseTestCaseFilter](schema.BaseTestCaseFilter)
        for raw_filter in raw_filters:
            if constants.TYPE not in raw_filter:
                raw_filter[constants.TYPE] = constants.TESTCASE_TYPE_LISA
            filter = factory.load_typed_runbook(raw_filter)
            filters.append(filter)
    else:
        filters = [schema.TestCase(name="test", criteria=schema.Criteria(area="demo"))]
    return filters


def print_results(
    test_results: List[Any],
    output_method: Callable[[str], Any],
) -> None:
    output_method("________________________________________")
    result_count_dict: Dict[TestStatus, int] = {}
    for test_result in test_results:
        if isinstance(test_result, TestResult):
            result_name = test_result.runtime_data.metadata.full_name
            result_status = test_result.status
        elif isinstance(test_result, TestResultMessage):
            result_name = test_result.name
            result_status = test_result.status
        else:
            raise LisaException(f"Unknown result type: '{type(test_result)}'")
        output_method(
            f"{result_name:>50}: {result_status.name:<8} {test_result.message}"
        )
        result_count = result_count_dict.get(result_status, 0)
        result_count += 1
        result_count_dict[result_status] = result_count

    output_method("test result summary")
    output_method(f"    TOTAL    : {len(test_results)}")
    for key in TestStatus:
        count = result_count_dict.get(key, 0)
        if key == TestStatus.ATTEMPTED and count == 0:
            # attempted is confusing if user don't know it.
            # so hide it if there is no attempted cases.
            continue
        output_method(f"    {key.name:<9}: {count}")


class CodeTimer:
    def __init__(self, name: str, log: Logger):
        self.name = " '" + name + "'" if name else ""
        self.log = log

    def __enter__(self):
        self.start = timeit.default_timer()

    def __exit__(self, exc_type, exc_value, traceback):
        self.took = (timeit.default_timer() - self.start) * 1000.0
        self.log.debug("Code block" + self.name + " took: " + str(self.took) + " ms")


class BaseRunner(BaseClassMixin, InitializableMixin):
    """
    Base runner of other runners. And other runners derived from this one.
    """

    def __init__(
        self,
        runbook: schema.Runbook,
        index: int,
        case_variables: Dict[str, Any],
    ) -> None:
        super().__init__()
        self._runbook = runbook

        self.id = f"{self.type_name()}_{index}"
        self._task_id = -1
        self._log = get_logger("runner", str(index))
        self._log_handler: Optional[FileHandler] = None
        self._case_variables = case_variables
        self._timer = create_timer()
        self.canceled = False

    def __repr__(self) -> str:
        return self.id

    @property
    def is_done(self) -> bool:
        raise NotImplementedError()

    def fetch_task(self) -> Optional[Task[List[TestResult]]]:
        """

        return:
            The runnable task, which can return test results
        """
        raise NotImplementedError()

    def close(self) -> None:
        if self._log_handler:
            remove_handler(self._log_handler)
            self._log_handler.close()
        self._log.debug(f"Runner finished in {self._timer.elapsed()}s.")

    def get_unique_task_id(self) -> int:
        self._task_id += 1
        return self._task_id

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
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
            self._log_handler = create_file_handler(
                Path(self._log_file_name), self._log
            )

    def __eq__(self, o: object) -> bool:
        return self.id == o.id


class RootRunner(Action):
    """
    The entry root runner, which starts other runners.
    """

    def __init__(self, runbook_builder: RunbookBuilder) -> None:
        super().__init__()
        self.exit_code: int = 0

        self._runbook_builder = runbook_builder

        self._log = get_logger("RootRunner")
        self._runners: List[BaseRunner] = []
        self._results: List[TestResult] = []
        self._results_lock: Lock = Lock()

    async def start(self) -> None:
        await super().start()

        try:
            transformer.run(self._runbook_builder)

            # update runbook for notifiers
            raw_data = copy.deepcopy(self._runbook_builder.raw_data)
            constants.RUNBOOK = replace_variables(
                raw_data, self._runbook_builder._variables
            )
            runbook = self._runbook_builder.resolve()
            self._runbook_builder.dump_variables()

            self._max_concurrency = runbook.concurrency
            self._log.debug(f"max concurrency is {self._max_concurrency}")

            self._start_loop()
        except Exception as identifer:
            cancel()
            raise identifer
        finally:
            for runner in self._runners:
                runner.close()

        print_results(self._results, self._log.info)

        # pass failed count to exit code
        self.exit_code = sum(1 for x in self._results if x.status == TestStatus.FAILED)

    async def stop(self) -> None:
        await super().stop()
        # TODO: to be implemented

    async def close(self) -> None:
        await super().close()

    def _fetch_runners(self) -> Iterator[BaseRunner]:
        root_runbook = self._runbook_builder.resolve(self._runbook_builder.variables)

        if root_runbook.combinator:
            combinator_factory = Factory[Combinator](Combinator)
            combinator = combinator_factory.create_by_runbook(root_runbook.combinator)

            del self._runbook_builder.raw_data[constants.COMBINATOR]
            self._log.debug(
                f"found combinator '{combinator.type_name()}', to expand runbook."
            )
            combinator.initialize()
            while True:
                variables = combinator.fetch(self._runbook_builder.variables)
                if variables is None:
                    break
                sub_runbook = self._runbook_builder.resolve(variables)
                runners = self._generate_runners(sub_runbook, variables)
                for runner in runners:
                    yield runner
        else:
            # no combinator, use the root runbook
            for runner in self._generate_runners(
                root_runbook, self._runbook_builder.variables
            ):
                yield runner

    def _generate_runners(
        self, runbook: schema.Runbook, variables: Dict[str, VariableEntry]
    ) -> Iterator[BaseRunner]:
        # group filters by runner type
        case_variables = get_case_variables(variables)
        runner_filters: Dict[str, List[schema.BaseTestCaseFilter]] = {}
        for raw_filter in runbook.testcase_raw:
            # by default run all filtered cases unless 'enable' is specified as false
            filter = schema.load_by_type(schema.BaseTestCaseFilter, raw_filter)
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

            # keep filters to current runner's only.
            runbook.testcase = parse_testcase_filters(raw_filters)
            runner = factory.create_by_type_name(
                type_name=runner_name,
                runbook=runbook,
                index=len(self._runners),
                case_variables=case_variables,
            )
            runner.initialize()
            self._runners.append(runner)
            yield runner

    def _callback_completed(self, results: List[TestResult]) -> None:
        self._results_lock.acquire()
        try:
            self._results.extend(results)
        finally:
            self._results_lock.release()

    def _start_loop(self) -> None:  # noqa: C901
        # in case all of runners are disabled
        runner_iterator = self._fetch_runners()
        remaining_runners: List[BaseRunner] = []
        try:
            for _ in range(self._max_concurrency):
                remaining_runners.append(next(runner_iterator))
        except StopIteration:
            self._log.debug(f"no more runner found, total {len(remaining_runners)}")

        if self._runners:
            run_message = notifier.TestRunMessage(
                status=notifier.TestRunStatus.RUNNING,
            )
            notifier.notify(run_message)

            task_manager = TaskManager[List[TestResult]](
                self._max_concurrency, self._callback_completed
            )

            # set the global task manager for cancellation check
            set_global_task_manager(task_manager)
            has_more_runner = True

            # run until no more task and all runner are closed
            while task_manager.wait_worker() or remaining_runners:
                self._log.info("Idle workers available. Checking runners...")

                assert task_manager.has_idle_worker()

                # runners shouldn't mark them done, until all task completed. It
                # can be checked by test results status or other signals.
                assert remaining_runners, (
                    f"no remaining runners, but there are running tasks. "
                    f"{task_manager._futures}"
                )

                with CodeTimer("has idle worker loop", self._log):
                    while task_manager.has_idle_worker():
                        for runner in remaining_runners:
                            self._log.info(f"Checking runner {runner.id} for tasks...")
                            while not runner.is_done and task_manager.has_idle_worker():
                                # fetch a task and submit
                                with CodeTimer("fetch task", self._log):
                                    task = runner.fetch_task()
                                if task:
                                    with CodeTimer("submit task", self._log):
                                        task_manager.submit_task(task)
                                else:
                                    # current runner may not be done, but it doesn't
                                    # have task temporarily. The root runner can start
                                    # tasks from next runner.
                                    self._log.debug(
                                        f"No task available for runner: {runner.id}"
                                    )
                                    break

                        [
                            runner.close()
                            for runner in remaining_runners
                            if runner.is_done
                        ]
                        remaining_runners = [
                            runner for runner in remaining_runners if not runner.is_done
                        ]
                        self._log.info(
                            f"remaining runners {[x.id for x in remaining_runners]}"
                            f"Idle workers : {task_manager.has_idle_worker()}"
                        )

                        if task_manager.has_idle_worker():
                            if has_more_runner:
                                # Add new runner if idle workers are available.
                                try:
                                    remaining_runners.append(next(runner_iterator))
                                    self._log.info(
                                        f"Added runner {remaining_runners[-1].id}"
                                    )
                                except StopIteration:
                                    has_more_runner = False
                            else:
                                # Reduce CPU utilization from infinite loop when idle
                                # workers are present but no task to run.
                                self._log.info(
                                    f"Idle worker available but no runner available..."
                                )
                                time.sleep(1)

                        if not remaining_runners and not has_more_runner:
                            break
