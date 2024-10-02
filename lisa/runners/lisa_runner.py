# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import copy
from functools import partial
from typing import Any, Callable, Dict, List, Optional, Set, cast

from lisa import (
    ResourceAwaitableException,
    SkippedException,
    development,
    notifier,
    schema,
    search_space,
    transformer,
)
from lisa.action import ActionStatus
from lisa.environment import (
    Environment,
    Environments,
    EnvironmentStatus,
    load_environments,
)
from lisa.messages import TestStatus
from lisa.platform_ import PlatformMessage, load_platform
from lisa.runner import BaseRunner
from lisa.testselector import select_testcases
from lisa.testsuite import TestCaseRequirement, TestResult, TestSuite
from lisa.util import (
    KernelPanicException,
    LisaException,
    NotMeetRequirementException,
    constants,
    deep_update_dict,
    is_unittest,
)
from lisa.util.parallel import Task, check_cancelled
from lisa.variable import VariableEntry


class LisaRunner(BaseRunner):
    @classmethod
    def type_name(cls) -> str:
        return constants.TESTCASE_TYPE_LISA

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)

        # select test cases
        selected_test_cases = select_testcases(filters=self._runbook.testcase)

        # create test results
        self.test_results = [
            TestResult(f"{self.id}_{index}", runtime_data=case)
            for index, case in enumerate(selected_test_cases)
        ]
        # load predefined environments
        self.platform = load_platform(self._runbook.platform)
        self.platform.initialize()
        platform_message = PlatformMessage(name=self.platform.type_name())
        notifier.notify(platform_message)

        # load development settings
        development.load_development_settings(self._runbook.dev)

        # set flag to enable guest nodes.
        self._guest_enabled = self.platform.runbook.guest_enabled

        # load environments
        runbook_environments = load_environments(self._runbook.environment)
        if not runbook_environments:
            # if no runbook environment defined, generate from requirements
            self._merge_test_requirements(
                test_results=self.test_results,
                existing_environments=runbook_environments,
                platform_type=self.platform.type_name(),
            )
        self.environments: List[Environment] = [
            x for x in runbook_environments.values()
        ]
        self._log.debug(
            f"Candidate environment count: {len(self.environments)}. "
            f"Guest enabled: {self._guest_enabled}."
        )

    @property
    def is_done(self) -> bool:
        is_all_results_completed = all(
            result.is_completed for result in self.test_results
        )
        # all environment should not be used and not be deployed.
        is_all_environment_completed = hasattr(self, "environments") and all(
            (not env.is_in_use)
            and (env.status in [EnvironmentStatus.Prepared, EnvironmentStatus.Deleted])
            for env in self.environments
        )
        return is_all_results_completed and is_all_environment_completed

    def fetch_task(self) -> Optional[Task[None]]:
        self._prepare_environments()

        self._cleanup_deleted_environments()
        self._cleanup_done_results()

        # sort environments by status
        available_environments = self._sort_environments(self.environments)
        available_results = self._sort_test_results(
            [x for x in self.test_results if x.can_run]
        )

        # check deletable environments
        delete_task = self._delete_unused_environments()
        if delete_task:
            return delete_task

        # Loop environments instead of test results, because it needs to reuse
        # environment as much as possible.
        if available_results and available_environments:
            for priority in range(6):
                can_run_results = self._get_results_by_priority(
                    available_results, priority
                )
                if not can_run_results:
                    continue

                # it means there are test cases and environment, so it needs to
                # schedule task.
                for environment in available_environments:
                    if environment.is_in_use:
                        # skip in used environments
                        continue

                    # Try to pick the designated test result from the current
                    # priority. So it may not be able to get the designed test
                    # result.
                    environment_results = [
                        x
                        for x in can_run_results
                        if environment.source_test_result
                        and x.id_ == environment.source_test_result.id_
                    ]
                    if not environment_results:
                        if (
                            not environment.is_predefined
                        ) and environment.status == EnvironmentStatus.Prepared:
                            # If the environment is not deployed, it will be
                            # skipped until the source test result is found. It
                            # makes sure the deployment failure attaches to the
                            # source test result.
                            continue
                        environment_results = self._get_runnable_test_results(
                            test_results=can_run_results, environment=environment
                        )

                    if not environment_results:
                        continue

                    task = self._dispatch_test_result(
                        environment=environment, test_results=environment_results
                    )
                    # there is more checking conditions. If some conditions doesn't
                    # meet, the task is None. If so, not return, and try next
                    # conditions or skip this test case.
                    if task:
                        return task
                if not any(
                    x.is_in_use or x.status == EnvironmentStatus.New
                    for x in available_environments
                ):
                    # if there is no environment in used, new, and results are
                    # not fit envs. those results cannot be run.
                    self._skip_test_results(can_run_results)
        elif available_results:
            # no available environments, so mark all test results skipped.
            self._skip_test_results(available_results)
            self.status = ActionStatus.SUCCESS
        return None

    def close(self) -> None:
        if hasattr(self, "environments") and self.environments:
            for environment in self.environments:
                self._delete_environment_task(environment, [])
        self.platform.cleanup()
        super().close()

    def _dispatch_test_result(
        self, environment: Environment, test_results: List[TestResult]
    ) -> Optional[Task[None]]:
        check_cancelled()

        assert test_results
        can_run_results = test_results
        # deploy
        if environment.status == EnvironmentStatus.Prepared and can_run_results:
            return self._generate_task(
                task_method=self._deploy_environment_task,
                environment=environment,
                test_results=can_run_results[:1],
            )

        # run on deployed environment
        can_run_results = [x for x in can_run_results if x.can_run]
        if environment.status == EnvironmentStatus.Deployed and can_run_results:
            selected_test_results = self._get_test_result_to_run(
                test_results=test_results, environment=environment
            )
            if selected_test_results:
                return self._generate_task(
                    task_method=self._run_test_task,
                    environment=environment,
                    test_results=selected_test_results,
                    case_variables=self._case_variables,
                )

            # Check if there is case to run in a connected environment. If so,
            # initialize the environment
            initialization_results = self._get_runnable_test_results(
                test_results=test_results,
                environment_status=EnvironmentStatus.Connected,
                environment=environment,
            )
            if initialization_results:
                return self._generate_task(
                    task_method=self._initialize_environment_task,
                    environment=environment,
                    test_results=initialization_results,
                )

        # run on connected environment
        can_run_results = [x for x in can_run_results if x.can_run]
        if environment.status == EnvironmentStatus.Connected and can_run_results:
            selected_test_results = self._get_test_result_to_run(
                test_results=test_results, environment=environment
            )
            if selected_test_results:
                return self._generate_task(
                    task_method=self._run_test_task,
                    environment=environment,
                    test_results=selected_test_results,
                    case_variables=self._case_variables,
                )

        return None

    def _delete_unused_environments(self) -> Optional[Task[None]]:
        available_environments = self._sort_environments(self.environments)
        # check deletable environments
        for environment in available_environments:
            # if an environment is in using, or not deployed, they won't be
            # deleted until end of runner.
            if environment.is_in_use or environment.status in [
                EnvironmentStatus.New,
                EnvironmentStatus.Prepared,
            ]:
                continue

            can_run_results = self._get_runnable_test_results(
                self.test_results, environment=environment
            )
            if not can_run_results:
                # no more test need this environment, delete it.
                self._log.debug(
                    f"generating delete environment task on '{environment.name}'"
                )
                return self._generate_task(
                    task_method=self._delete_environment_task,
                    environment=environment,
                    test_results=[],
                )
        return None

    def _prepare_environments(self) -> None:
        if all(x.status != EnvironmentStatus.New for x in self.environments):
            return

        proceeded_environments: List[Environment] = []
        for candidate_environment in self.environments:
            success = True
            if candidate_environment.status == EnvironmentStatus.New:
                success = self._prepare_environment(candidate_environment)
            if success:
                proceeded_environments.append(candidate_environment)

        # sort by environment source and cost cases
        # user defined should be higher priority than test cases' requirement
        proceeded_environments.sort(key=lambda x: (not x.is_predefined, x.cost))

        self.environments = proceeded_environments

    def _deploy_environment_task(
        self, environment: Environment, test_results: List[TestResult]
    ) -> None:
        try:
            try:
                # Attempt to deploy the environment
                self.platform.deploy_environment(environment)
                assert (
                    environment.status == EnvironmentStatus.Deployed
                ), f"actual: {environment.status}"
                self._reset_awaitable_timer("deploy")
            except ResourceAwaitableException as identifier:
                if self._is_awaitable_timeout("deploy"):
                    self._log.info(
                        f"[{environment.name}] timeout on waiting for more resource: "
                        f"{identifier}, skip assigning case."
                    )
                    raise SkippedException(identifier)
                else:
                    # rerun prepare to calculate resource again.
                    environment.status = EnvironmentStatus.New
        except Exception as identifier:
            if self._need_retry(environment):
                environment.status = EnvironmentStatus.New
            else:
                # Final attempt failed; handle the failure
                self._attach_failed_environment_to_result(
                    environment=environment,
                    result=test_results[0],
                    exception=identifier,
                )
                self._delete_environment_task(environment=environment, test_results=[])

    def _initialize_environment_task(
        self, environment: Environment, test_results: List[TestResult]
    ) -> None:
        self._log.debug(f"start initializing task on '{environment.name}'")
        assert test_results
        try:
            environment.initialize()
            assert (
                environment.status == EnvironmentStatus.Connected
            ), f"actual: {environment.status}"
            transformer.run(
                self._runbook_builder,
                phase=constants.TRANSFORMER_PHASE_ENVIRONMENT_CONNECTED,
                environment=environment,
            )
        except Exception as identifier:
            self._attach_failed_environment_to_result(
                environment=environment,
                result=test_results[0],
                exception=identifier,
            )
            self._delete_environment_task(environment=environment, test_results=[])

    def _run_test_task(
        self,
        environment: Environment,
        test_results: List[TestResult],
        case_variables: Dict[str, VariableEntry],
    ) -> None:
        self._log.debug(
            f"start running cases on '{environment.name}', "
            f"status {environment.status.name}, "
            f"guest enabled: {self._guest_enabled}"
        )
        assert test_results
        assert len(test_results) == 1, (
            f"single test result to run, " f"but {len(test_results)} found."
        )
        test_result = test_results[0]
        suite_metadata = test_result.runtime_data.metadata.suite
        test_suite: TestSuite = suite_metadata.test_class(
            suite_metadata,
        )
        # if a test case runs on a deployed environment, the environment will be
        # connected after it's initialized. It breaks the flow, so the
        # transformers are in the connected phase will be ignored. So mark this
        # kind of environment is dirty to prevent it run other test cases.
        if environment.status == EnvironmentStatus.Deployed:
            environment.mark_dirty()

        tested_environment = environment
        if self._guest_enabled:
            tested_environment = environment.get_guest_environment()

        test_suite.start(
            environment=tested_environment,
            case_results=test_results,
            case_variables=case_variables,
        )
        # release environment reference to optimize memory.
        test_result.environment = None

        # Some test cases may break the ssh connections. To reduce side effects
        # on next test cases, close the connection after each test run. It will
        # be connected on the next command automatically.
        tested_environment.nodes.close()
        # Try to connect node(s), if cannot access node(s) of this environment,
        # set the current environment as Bad. So that this environment won't be reused.
        if not is_unittest() and not tested_environment.nodes.test_connections():
            environment.status = EnvironmentStatus.Bad
            self._log.debug(
                f"set environment '{environment.name}' as bad, "
                f"because after test case '{test_result.name}', "
                f"node(s) cannot be accessible."
            )
            try:
                # check panic when node(s) in bad status
                environment.nodes.check_kernel_panics()
            except KernelPanicException as identifier:
                # not throw exception here, since it will cancel all tasks
                # just print log here and set test result status as failed
                test_result.set_status(TestStatus.FAILED, str(identifier))
                self._log.debug(
                    "found kernel panic from the node(s) of "
                    f"'{environment.name}': {identifier}"
                )
        tested_environment.nodes.close()

        # keep failed environment, not to delete
        if (
            test_result.status == TestStatus.FAILED
            and self.platform.runbook.keep_environment
            == constants.ENVIRONMENT_KEEP_FAILED
        ):
            self._log.debug(
                f"keep environment '{environment.name}', "
                f"because keep_environment is 'failed', "
                f"and test case '{test_result.name}' failed on it."
            )
            environment.status = EnvironmentStatus.Deleted

        # if an environment is in bad status, it will be deleted, not run more
        # test cases. But if the setting is to keep failed environment, it may
        # be kept in above logic.
        if environment.status == EnvironmentStatus.Bad or environment.is_dirty:
            self._log.debug(
                f"delete environment '{environment.name}', "
                f"because it's in Bad status or marked as dirty."
            )
            self._delete_environment_task(
                environment=environment, test_results=test_results
            )

        # Rerun test case, if the test case is not passed (failed or attempted),
        # and set to retry.
        if (
            test_result.status not in [TestStatus.PASSED, TestStatus.SKIPPED]
            and test_result.retried_times < test_result.runtime_data.retry
        ):
            self._log.debug(
                f"retry test case '{test_result.name}' on "
                f"environment '{environment.name}'"
            )
            self._delete_environment_task(
                environment=environment, test_results=test_results
            )
            environment.status = EnvironmentStatus.New

            test_result.retried_times += 1
            test_result.set_status(TestStatus.QUEUED, "")
            # clean up error message by set it to empty explicitly. The
            # set_status doesn't clean it, since it appends.
            test_result.message = ""
            test_result.environment = environment

    def _delete_environment_task(
        self, environment: Environment, test_results: List[TestResult]
    ) -> None:
        """
        May be called async
        """
        # the predefined environment shouldn't be deleted, because it
        # serves all test cases.
        if environment.status == EnvironmentStatus.Deleted or (
            environment.status == EnvironmentStatus.Prepared
            and not environment.is_in_use
        ):
            # The prepared only environment doesn't need to be deleted.
            # It may cause platform fail to delete non-existing environment.
            environment.status = EnvironmentStatus.Deleted
        else:
            try:
                self.platform.delete_environment(environment)
            except Exception as identifier:
                self._log.debug(
                    f"error on deleting environment '{environment.name}': {identifier}"
                )

    def _prepare_environment(self, environment: Environment) -> bool:
        success = True
        try:
            try:
                self.platform.prepare_environment(environment)
                self._reset_awaitable_timer("prepare")
            except ResourceAwaitableException as identifier:
                # if timed out, raise the exception and skip the test case. If
                # not, do nothing to keep env as new to try next time.
                if self._is_awaitable_timeout("prepare"):
                    raise SkippedException(identifier)
        except Exception as identifier:
            success = False

            matched_result = self._match_failed_environment_with_result(
                environment=environment,
                candidate_results=self.test_results,
                exception=identifier,
            )
            self._attach_failed_environment_to_result(
                environment=environment,
                result=matched_result,
                exception=identifier,
            )

        return success

    def _cleanup_deleted_environments(self) -> None:
        # remove reference to unused environments. It can save memory on big runs.
        new_environments: List[Environment] = []
        for environment in self.environments[:]:
            if environment.status != EnvironmentStatus.Deleted:
                new_environments.append(environment)
        self.environments = new_environments

    def _cleanup_done_results(self) -> None:
        # remove reference to completed test results. It can save memory on big runs.
        remaining_results: List[TestResult] = []
        for test_result in self.test_results[:]:
            if not test_result.is_completed:
                remaining_results.append(test_result)
        self.test_results = remaining_results

    def _get_results_by_priority(
        self, test_results: List[TestResult], priority: int
    ) -> List[TestResult]:
        if not test_results:
            return []

        test_results = [
            x for x in test_results if x.runtime_data.metadata.priority == priority
        ]

        return test_results

    def _generate_task(
        self,
        task_method: Callable[..., None],
        environment: Environment,
        test_results: List[TestResult],
        **kwargs: Any,
    ) -> Task[None]:
        assert not environment.is_in_use
        environment.is_in_use = True
        for test_result in test_results:
            # return assigned but not run cases
            if test_result.status == TestStatus.QUEUED:
                test_result.set_status(TestStatus.ASSIGNED, "")

        task = partial(
            self._run_task,
            task_method,
            environment=environment,
            test_results=test_results,
            **kwargs,
        )
        return Task(self.generate_task_id(), task, self._log)

    def _run_task(
        self,
        task_method: Callable[..., None],
        environment: Environment,
        test_results: List[TestResult],
        **kwargs: Any,
    ) -> None:
        assert environment.is_in_use
        task_method(environment=environment, test_results=test_results, **kwargs)

        for test_result in test_results:
            # return assigned but not run cases
            if test_result.status == TestStatus.ASSIGNED:
                test_result.set_status(TestStatus.QUEUED, "")
        environment.is_in_use = False

    def _match_failed_environment_with_result(
        self,
        environment: Environment,
        candidate_results: List[TestResult],
        exception: Exception,
    ) -> TestResult:
        if environment.source_test_result and environment.source_test_result.is_queued:
            matched_results = [environment.source_test_result]
        else:
            matched_results = self._get_runnable_test_results(
                test_results=candidate_results,
                environment=environment,
            )
        if not matched_results:
            self._log.info(
                "No requirement of test case is suitable for the preparation "
                f"error of the environment '{environment.name}'. "
                "Randomly attach a test case to this environment. "
                "This may be because the platform failed before populating the "
                "features into this environment.",
            )
            matched_results = [
                result for result in self.test_results if result.is_queued
            ]
        if not matched_results:
            raise LisaException(
                "There are no remaining test results to run, so preparation "
                "errors cannot be appended to the test results. Please correct "
                "the error and run again. "
                f"original exception: {exception}"
            )

        return matched_results[0]

    def _attach_failed_environment_to_result(
        self,
        environment: Environment,
        result: TestResult,
        exception: Exception,
    ) -> None:
        # make first fit test case failed by deployment,
        # so deployment failure can be tracked.
        environment.platform = self.platform
        result.environment = environment
        result.handle_exception(exception=exception, log=self._log, phase="deployment")
        self._log.info(
            f"'{environment.name}' attached to test case "
            f"'{result.runtime_data.metadata.full_name}({result.id_})': "
            f"{exception}"
        )
        # release environment reference to optimize memory.
        result.environment = None

    def _get_runnable_test_results(
        self,
        test_results: List[TestResult],
        use_new_environment: Optional[bool] = None,
        environment_status: Optional[EnvironmentStatus] = None,
        environment: Optional[Environment] = None,
    ) -> List[TestResult]:
        results = [
            x
            for x in test_results
            if x.is_queued
            and (
                use_new_environment is None
                or x.runtime_data.use_new_environment == use_new_environment
            )
            and (
                environment_status is None
                or x.runtime_data.metadata.requirement.environment_status
                == environment_status
            )
        ]
        if environment:
            runnable_results: List[TestResult] = []
            for result in results:
                # use guest environment to check
                tested_environment = environment
                if self._guest_enabled:
                    tested_environment = environment.get_guest_environment()
                try:
                    if result.check_environment(
                        environment=tested_environment,
                        environment_platform_type=self.platform.type_name(),
                        save_reason=True,
                    ) and (
                        not result.runtime_data.use_new_environment
                        or environment.is_new
                    ):
                        runnable_results.append(result)
                except SkippedException as identifier:
                    if not result.environment:
                        result.environment = environment
                    # when check the environment, the test result may be marked
                    # as skipped, due to the test result is assumed not to match
                    # any environment.
                    result.handle_exception(identifier, log=self._log, phase="check")
            results = runnable_results

        # only select one test case, which needs the new environment. Others
        # will be dropped to next environment.
        if sum(1 for x in results if x.runtime_data.use_new_environment) > 1:
            new_results: List[TestResult] = []
            has_new_result: bool = False
            for x in results:
                if x.runtime_data.use_new_environment:
                    # skip from second new result
                    if has_new_result:
                        continue
                    has_new_result = True
                    new_results.append(x)
                else:
                    new_results.append(x)
            results = new_results

        results = self._sort_test_results(results)
        return results

    def _get_test_result_to_run(
        self, test_results: List[TestResult], environment: Environment
    ) -> List[TestResult]:
        to_run_results = self._get_runnable_test_results(
            test_results=test_results,
            environment_status=environment.status,
            environment=environment,
        )
        if to_run_results:
            to_run_test_result = next(
                (x for x in to_run_results if x.runtime_data.use_new_environment),
                None,
            )
            if not to_run_test_result:
                to_run_test_result = to_run_results[0]
            to_run_results = [to_run_test_result]

        return to_run_results

    def _sort_environments(self, environments: List[Environment]) -> List[Environment]:
        results: List[Environment] = []
        # sort environments by the status list
        sorted_status = [
            EnvironmentStatus.Connected,
            EnvironmentStatus.Deployed,
            EnvironmentStatus.Prepared,
            EnvironmentStatus.New,
        ]
        if environments:
            for status in sorted_status:
                results.extend(
                    x for x in environments if x.status == status and x.is_alive
                )
        return results

    def _sort_test_results(self, test_results: List[TestResult]) -> List[TestResult]:
        results = test_results.copy()
        # sort by priority, use new environment, environment status and suite name.
        results.sort(
            key=lambda r: str(r.runtime_data.metadata.suite.name),
        )
        # this step make sure Deployed is before Connected
        results.sort(
            reverse=True,
            key=lambda r: str(r.runtime_data.metadata.requirement.environment_status),
        )
        results.sort(
            reverse=True,
            key=lambda r: str(r.runtime_data.use_new_environment),
        )
        results.sort(key=lambda r: r.runtime_data.metadata.priority)
        return results

    def _skip_test_results(
        self,
        test_results: List[TestResult],
        additional_reason: str = "no available environment",
    ) -> None:
        for test_result in test_results:
            if test_result.is_completed:
                # already completed, don't skip it.
                continue

            if test_result.check_results and test_result.check_results.reasons:
                reasons = f"{additional_reason}: {test_result.check_results.reasons}"
            else:
                reasons = additional_reason

            test_result.set_status(TestStatus.SKIPPED, reasons)

    def _get_ignored_features(self, nodes: List[schema.NodeSpace]) -> Set[str]:
        ignored_features: Set[str] = set()
        if hasattr(self, "platform") and self.platform.runbook.ignored_capability:
            ignored_capability = set(
                map(str.lower, self.platform.runbook.ignored_capability)
            )
            for node_requirement in nodes:
                for feature_set in [
                    node_requirement.features,
                    node_requirement.excluded_features,
                ]:
                    if feature_set:
                        for feature in list(feature_set):
                            if str(feature).lower() in ignored_capability:
                                feature_set.remove(feature)
                                ignored_features.add(str(feature))
        return ignored_features

    def _merge_test_requirements(
        self,
        test_results: List[TestResult],
        existing_environments: Environments,
        platform_type: str,
    ) -> None:
        assert platform_type

        cases_ignored_features: Dict[str, Set[str]] = {}
        # if platform defined requirement, replace the requirement from
        # test case.
        for test_result in test_results:
            # the platform requirement maybe used later, so it won't be a shared
            # object cross test results.
            platform_requirement = self._create_platform_requirement()
            test_req: TestCaseRequirement = test_result.runtime_data.requirement

            check_result = test_result.check_platform(platform_type)
            if not check_result.result:
                test_result.set_status(TestStatus.SKIPPED, check_result.reasons)
                continue

            if test_result.can_run:
                assert test_req.environment

                ignored_features = self._get_ignored_features(
                    test_req.environment.nodes
                )
                if ignored_features:
                    cases_ignored_features[test_result.name] = ignored_features

                environment_requirement = copy.deepcopy(test_req.environment)
                if platform_requirement:
                    for index, node_requirement in enumerate(
                        environment_requirement.nodes
                    ):
                        node_requirement_data: Dict[
                            str, Any
                        ] = node_requirement.to_dict()  # type: ignore

                        original_node_requirement = schema.load_by_type(
                            schema.NodeSpace, node_requirement_data
                        )

                        # Manage the union of the platform requirements and the node
                        # requirements before taking the intersection of
                        # the rest of the requirements.
                        platform_requirement.features = search_space.SetSpace(
                            True,
                            (
                                platform_requirement.features.items
                                if platform_requirement.features
                                else []
                            )
                            + (
                                original_node_requirement.features.items
                                if original_node_requirement.features
                                else []
                            ),
                        )
                        platform_requirement.excluded_features = search_space.SetSpace(
                            False,
                            (
                                platform_requirement.excluded_features.items
                                if platform_requirement.excluded_features
                                else []
                            )
                            + (
                                original_node_requirement.excluded_features.items
                                if original_node_requirement.excluded_features
                                else []
                            ),
                        )

                        try:
                            node_requirement = original_node_requirement.intersect(
                                platform_requirement
                            )
                        except NotMeetRequirementException as identifier:
                            test_result.set_status(TestStatus.SKIPPED, str(identifier))
                            break

                        assert isinstance(platform_requirement.extended_schemas, dict)
                        assert isinstance(node_requirement.extended_schemas, dict)
                        node_requirement.extended_schemas = deep_update_dict(
                            platform_requirement.extended_schemas,
                            node_requirement.extended_schemas,
                        )
                        environment_requirement.nodes[index] = node_requirement

            if test_result.can_run:
                # the requirement may be skipped by high platform requirement.
                env = existing_environments.from_requirement(environment_requirement)
                if env:
                    # if env prepare or deploy failed and the test result is not
                    # run, the failure will attach to this test result.
                    env.source_test_result = test_result
                    self._log.debug(
                        f"created environment '{env.name}' for {test_result.id_}"
                    )

        for case_name, ignored_features in cases_ignored_features.items():
            self._log.debug(
                f"the feature(s) {ignored_features} have "
                f"been ignored for case {case_name}"
            )

    def _create_platform_requirement(self) -> Optional[schema.NodeSpace]:
        if not hasattr(self, "platform"):
            return None

        platform_requirement_data = cast(
            schema.Platform, self.platform.runbook
        ).requirement
        if platform_requirement_data is None:
            return None

        platform_requirement: schema.NodeSpace = schema.load_by_type(
            schema.Capability, platform_requirement_data
        )
        # fill in required fields as max capability. So it can be
        # used as a capability in next steps to merge with test requirement.
        if not platform_requirement.disk:
            platform_requirement.disk = schema.DiskOptionSettings()
        if not platform_requirement.network_interface:
            platform_requirement.network_interface = (
                schema.NetworkInterfaceOptionSettings()
            )

        return platform_requirement
