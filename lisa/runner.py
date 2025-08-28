# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import copy
import time
from logging import FileHandler
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Type

from lisa import messages, notifier, schema, transformer
from lisa.action import Action
from lisa.combinator import Combinator
from lisa.environment import Environment
from lisa.messages import TestResultMessage, TestResultMessageBase, TestStatus
from lisa.notifier import register_notifier
from lisa.parameter_parser.runbook import RunbookBuilder
from lisa.util import BaseClassMixin, InitializableMixin, LisaException, constants
from lisa.util.logger import create_file_handler, get_logger, remove_handler
from lisa.util.parallel import Task, TaskManager, cancel, set_global_task_manager
from lisa.util.perf_timer import Timer, create_timer
from lisa.util.subclasses import Factory
from lisa.variable import VariableEntry, get_case_variables, replace_variables


def parse_testcase_filters(raw_filters: List[Any]) -> List[schema.BaseTestCaseFilter]:
    if raw_filters:
        filters: List[schema.BaseTestCaseFilter] = []
        factory = Factory[schema.BaseTestCaseFilter](schema.BaseTestCaseFilter)
        for raw_filter in raw_filters:
            if constants.TYPE not in raw_filter:
                raw_filter[constants.TYPE] = constants.TESTCASE_TYPE_LISA
            filters.append(factory.load_typed_runbook(raw_filter))
    else:
        filters = [schema.TestCase(name="test", criteria=schema.Criteria(area="demo"))]
    return filters


def print_results(
    test_results: List[TestResultMessageBase],
    output_method: Callable[[str], Any],
    add_ending: bool = False,
) -> None:
    def output_with_ending(message: str) -> None:
        if add_ending:
            output_method(f"{message}\n")
        else:
            output_method(message)

    output_with_ending("________________________________________")
    result_count_dict: Dict[TestStatus, int] = {}
    for test_result in test_results:
        if isinstance(test_result, TestResultMessage):
            result_name = test_result.full_name
        elif isinstance(test_result, messages.SubTestMessage):
            result_name = f"{test_result.name} ({test_result.parent_test})"
        else:
            raise LisaException(f"unknown result type: {type(test_result)}")
        result_status = test_result.status

        output_with_ending(
            f"{result_name:>50}: {result_status.name:<8} {test_result.message}"
        )
        result_count = result_count_dict.get(result_status, 0)
        result_count += 1
        result_count_dict[result_status] = result_count

    output_with_ending("test result summary")
    output_with_ending(f"    TOTAL    : {len(test_results)}")
    for key in TestStatus:
        count = result_count_dict.get(key, 0)
        if key == TestStatus.ATTEMPTED and count == 0:
            # attempted is confusing if user don't know it.
            # so hide it if there is no attempted cases.
            continue
        output_with_ending(f"    {key.name:<9}: {count}")


class RunnerResult(notifier.Notifier):
    """
    This is an internal notifier. It uses to collect test results for runner.
    """

    @classmethod
    def type_name(cls) -> str:
        # no type_name, not able to import from yaml book.
        return ""

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return schema.Notifier

    def _received_message(self, message: messages.MessageBase) -> None:
        assert isinstance(message, TestResultMessage), f"actual: {type(message)}"
        self.results[message.id_] = message

    def _subscribed_message_type(self) -> List[Type[messages.MessageBase]]:
        return [TestResultMessage]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self.results: Dict[str, TestResultMessage] = {}


class BaseRunner(BaseClassMixin, InitializableMixin):
    """
    Base runner of other runners. And other runners derived from this one.
    """

    def __init__(
        self,
        runbook_builder: RunbookBuilder,
        runbook: schema.Runbook,
        index: int,
        case_variables: Dict[str, Any],
    ) -> None:
        super().__init__()
        self._runbook_builder = runbook_builder
        self._runbook = runbook

        self.id = f"{self.type_name()}_{index}"
        self._task_id = -1
        self._log = get_logger("runner", str(index))
        self._log_handler: Optional[FileHandler] = None
        self._case_variables = case_variables
        self._timer = create_timer()

        self._wait_resource_timeout = runbook.wait_resource_timeout
        self._wait_resource_timers: Dict[str, Timer] = dict()
        self._wait_resource_logged: bool = False

        self.canceled = False

    def __repr__(self) -> str:
        return self.id

    @property
    def is_done(self) -> bool:
        raise NotImplementedError()

    def fetch_task(self) -> Optional[Task[None]]:
        """

        return:
            The runnable task, which can return test results
        """
        raise NotImplementedError()

    def close(self) -> None:
        self._log.debug(f"Runner finished in {self._timer.elapsed_text()}.")
        if self._log_handler:
            remove_handler(self._log_handler)
            self._log_handler.close()

    def generate_task_id(self) -> int:
        self._task_id += 1
        return self._task_id

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        # do not put this logic to __init__, since the mkdir takes time.
        # default lisa runner doesn't need separated handler.
        self._log_folder = constants.RUN_LOCAL_LOG_PATH
        self._working_folder = constants.RUN_LOCAL_WORKING_PATH
        if self.type_name() != constants.TESTCASE_TYPE_LISA:
            # create separated folder and log for each non-default runner.
            runner_path_name = f"{self.type_name()}_runner"
            self._log_folder = self._log_folder / runner_path_name
            self._log_file_name = str(self._log_folder / f"{runner_path_name}.log")
            self._log_folder.mkdir(parents=True, exist_ok=True)
            self._log_handler = create_file_handler(
                Path(self._log_file_name), self._log
            )

            self._working_folder = self._working_folder / runner_path_name

    def _is_awaitable_timeout(self, name: str) -> bool:
        _wait_resource_timer = self._wait_resource_timers.get(name, create_timer())
        self._wait_resource_timers[name] = _wait_resource_timer
        if _wait_resource_timer.elapsed(False) < self._wait_resource_timeout * 60:
            # wait a while to prevent called too fast
            if not self._wait_resource_logged:
                self._log.info(f"{name} waiting for more resource...")
                self._wait_resource_logged = True
            time.sleep(5)
            return False
        else:
            self._log.info(f"{name} timeout on waiting for more resource...")
            return True

    def _reset_awaitable_timer(self, name: str) -> None:
        _wait_resource_timer = self._wait_resource_timers.get(name, create_timer())
        _wait_resource_timer.reset()
        self._wait_resource_logged = False
        self._wait_resource_timers[name] = _wait_resource_timer

    def _need_retry(self, environment: Environment) -> bool:
        if environment.tried_times >= environment.retry:
            if environment.retry > 0:
                self._log.info(
                    f"Tried {environment.tried_times + 1} times, but failed again."
                )
            return False

        environment.tried_times += 1
        self._log.info(
            f"Retrying... (Attempt {environment.tried_times}/{environment.retry})"
        )
        return True


class RootRunner(Action):
    """
    The entry root runner, which starts other runners.
    """

    def __init__(self, runbook_builder: RunbookBuilder) -> None:
        super().__init__()
        self.exit_code: int = -1

        self._runbook_builder = runbook_builder

        self._log = get_logger("RootRunner")
        # this is to hold active runners, and will close them, if there is any
        # global error.
        self._runners: List[BaseRunner] = []
        self._runner_count: int = 0
        self._idle_logged: bool = False

    async def start(self) -> None:
        await super().start()

        self._results_collector: Optional[RunnerResult] = None
        try:
            transformer.run(
                self._runbook_builder, phase=constants.TRANSFORMER_PHASE_INIT
            )

            # update runbook for notifiers
            raw_data = copy.deepcopy(self._runbook_builder.raw_data)
            constants.RUNBOOK = replace_variables(
                raw_data, self._runbook_builder._variables
            )
            runbook = self._runbook_builder.resolve()
            self._runbook_builder.dump_variables()

            self._max_concurrency = runbook.concurrency
            self._log.debug(f"max concurrency is {self._max_concurrency}")

            self._results_collector = RunnerResult(schema.Notifier())
            register_notifier(self._results_collector)

            self._start_loop()
        except Exception as e:
            self._log.exception("canceling runner due to exception", exc_info=e)
            cancel()
            raise e
        finally:
            self._cleanup()

        if self._results_collector:
            results: List[TestResultMessageBase] = [
                x for x in self._results_collector.results.values()
            ]
            print_results(results, self._log.info)

            if any(x.status == TestStatus.QUEUED for x in results):
                # if there is any queued, it means there is some error in runner
                raise LisaException(
                    "Found queued test case, it's unexpected. See logs for details."
                )
            elif runbook.exit_with_failed_count:
                # pass failed count to exit code
                self.exit_code = sum(
                    1 for x in results if x.status == TestStatus.FAILED
                )
            else:
                self.exit_code = 0

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
                sub_runbook_builder = self._runbook_builder.derive(variables=variables)
                transformer.run(
                    sub_runbook_builder, phase=constants.TRANSFORMER_PHASE_EXPANDED
                )

                runners = self._generate_runners(sub_runbook_builder, variables)
                yield from runners

                transformer.run(
                    sub_runbook_builder,
                    phase=constants.TRANSFORMER_PHASE_EXPANDED_CLEANUP,
                )
        else:
            # no combinator, use the root runbook
            transformer.run(
                self._runbook_builder, phase=constants.TRANSFORMER_PHASE_EXPANDED
            )

            yield from self._generate_runners(
                self._runbook_builder, self._runbook_builder.variables
            )

            transformer.run(
                self._runbook_builder,
                phase=constants.TRANSFORMER_PHASE_EXPANDED_CLEANUP,
            )

    def _generate_runners(
        self, runbook_builder: RunbookBuilder, variables: Dict[str, VariableEntry]
    ) -> Iterator[BaseRunner]:
        # group filters by runner type
        runbook = runbook_builder.resolve(variables=variables)
        case_variables = get_case_variables(variables)
        runner_filters: Dict[str, List[schema.BaseTestCaseFilter]] = {}
        for raw_filter in runbook.testcase_raw:
            # by default run all filtered cases unless 'enable' is specified as false
            filter_ = schema.load_by_type(schema.BaseTestCaseFilter, raw_filter)
            if filter_.enabled:
                raw_filters: List[schema.BaseTestCaseFilter] = runner_filters.get(
                    filter_.type, []
                )
                if not raw_filters:
                    runner_filters[filter_.type] = raw_filters
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
                runbook_builder=runbook_builder,
                runbook=runbook,
                index=self._runner_count,
                case_variables=case_variables,
            )
            runner.initialize()
            self._runners.append(runner)
            self._runner_count += 1
            yield runner

    def _submit_runner_tasks(
        self,
        runner: BaseRunner,
        task_manager: TaskManager[None],
    ) -> bool:
        has_task: bool = False
        while not runner.is_done and task_manager.has_idle_worker():
            # fetch a task and submit
            task = runner.fetch_task()
            if task:
                if isinstance(task, Task):
                    task_manager.submit_task(task)
                else:
                    raise LisaException(f"Unknown task type: '{type(task)}'")
                has_task = True
            else:
                # current runner may not be done, but it doesn't
                # have task temporarily. The root runner can start
                # tasks from next runner.
                break
        return has_task

    def _start_loop(self) -> None:
        # in case all of runners are disabled
        runner_iterator = self._fetch_runners()
        remaining_runners: List[BaseRunner] = []

        run_message = messages.TestRunMessage(
            status=messages.TestRunStatus.RUNNING,
        )
        notifier.notify(run_message)

        task_manager = TaskManager[None](self._max_concurrency, is_verbose=True)

        # set the global task manager for cancellation check
        set_global_task_manager(task_manager)
        has_more_runner = True

        # run until no idle workers are available and all runner are closed
        while task_manager.wait_worker() or has_more_runner or remaining_runners:
            assert task_manager.has_idle_worker()

            # submit tasks until idle workers are available
            while task_manager.has_idle_worker():
                for runner in remaining_runners[:]:
                    has_task = self._submit_runner_tasks(runner, task_manager)
                    if runner.is_done:
                        runner.close()
                        remaining_runners.remove(runner)
                        self._runners.remove(runner)
                    if has_task:
                        # This makes the loop is deep first. It intends to
                        # complete the prior runners firstly, instead of start
                        # later runners.
                        continue

                if not self._idle_logged:
                    self._log.debug(
                        f"running count: {task_manager.running_count}, "
                        f"id: {[x.id for x in remaining_runners]} "
                    )

                if task_manager.has_idle_worker():
                    if has_more_runner:
                        # add new runner up to max concurrency if idle workers
                        # are available
                        try:
                            while len(remaining_runners) < self._max_concurrency:
                                runner = next(runner_iterator)
                                remaining_runners.append(runner)
                                self._log.debug(f"Added runner {runner.id}")
                        except StopIteration:
                            has_more_runner = False

                        self._idle_logged = False
                    else:
                        # reduce CPU utilization from infinite loop when idle
                        # workers are present but no task to run.
                        if not self._idle_logged:
                            self._log.debug(
                                "Idle worker available but no new runner..."
                            )
                            self._idle_logged = True
                        break

    def _cleanup(self) -> None:
        try:
            for runner in self._runners:
                runner.close()
        except Exception as e:
            self._log.warning(f"error on close runner: {e}")

        try:
            transformer.run(self._runbook_builder, constants.TRANSFORMER_PHASE_CLEANUP)
        except Exception as e:
            self._log.warning(f"error on run cleanup transformers: {e}")
