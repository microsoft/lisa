# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import copy
from functools import partial
from typing import Any, Callable, Dict, List, Optional, cast

from lisa import SkippedException, notifier, schema, search_space
from lisa.action import ActionStatus
from lisa.environment import (
    Environment,
    Environments,
    EnvironmentStatus,
    load_environments,
)
from lisa.messages import TestStatus
from lisa.platform_ import (
    Platform,
    PlatformMessage,
    WaitMoreResourceError,
    load_platform,
)
from lisa.runner import BaseRunner
from lisa.testselector import select_testcases
from lisa.testsuite import TestCaseRequirement, TestResult, TestSuite
from lisa.util import LisaException, constants, deep_update_dict
from lisa.util.parallel import Task, check_cancelled
from lisa.variable import VariableEntry


class LisaRunner(BaseRunner):
    @classmethod
    def type_name(cls) -> str:
        return constants.TESTCASE_TYPE_LISA

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize(*args, **kwargs)
        self._is_prepared = False

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
        self._prepare_environments(
            platform=self.platform,
        )

        # sort environments by status
        available_environments = self._sort_environments(self.environments)
        available_results = [x for x in self.test_results if x.can_run]
        self._sort_test_results(available_results)

        # check deleteable environments
        delete_task = self._delete_unused_environments()
        if delete_task:
            return delete_task

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

                    environment_results = self._get_runnable_test_results(
                        test_results=can_run_results, environment=environment
                    )

                    if not environment_results:
                        continue

                    task = self._associate_environment_test_results(
                        environment=environment, test_results=environment_results
                    )
                    # there is more checking conditions. If some conditions doesn't
                    # meet, the task is None. If so, not return, and try next
                    # conditions or skip this test case.
                    if task:
                        return task
                if not any(x.is_in_use for x in available_environments):
                    # no environment in used, and not fit. those results cannot be run.
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
        super().close()

    def _associate_environment_test_results(
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
            selected_test_results = self._get_test_results_to_run(
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
            selected_test_results = self._get_test_results_to_run(
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
        # check deleteable environments
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

    def _prepare_environments(
        self,
        platform: Platform,
    ) -> None:
        if self._is_prepared:
            return

        runbook_environments = load_environments(self._runbook.environment)
        if not runbook_environments:
            # if no runbook environment defined, generate from requirements
            self._merge_test_requirements(
                test_results=self.test_results,
                existing_environments=runbook_environments,
                platform_type=self.platform.type_name(),
            )

        prepared_environments: List[Environment] = []
        for candidate_environment in runbook_environments.values():
            try:
                prepared_environment = platform.prepare_environment(
                    candidate_environment
                )
                prepared_environments.append(prepared_environment)
            except Exception as identifier:
                if (
                    candidate_environment.source_test_result
                    and candidate_environment.source_test_result.is_queued
                ):
                    matched_results = [candidate_environment.source_test_result]
                else:
                    matched_results = self._get_runnable_test_results(
                        test_results=self.test_results,
                        environment=candidate_environment,
                    )
                if not matched_results:
                    self._log.info(
                        "No requirement of test case is suitable for the preparation "
                        f"error of the environment '{candidate_environment.name}'. "
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
                        f"original exception: {identifier}"
                    )
                self._attach_failed_environment_to_result(
                    environment=candidate_environment,
                    result=matched_results[0],
                    exception=identifier,
                )

        # sort by environment source and cost cases
        # user defined should be higher priority than test cases' requirement
        prepared_environments.sort(key=lambda x: (not x.is_predefined, x.cost))

        self._is_prepared = True
        self.environments = prepared_environments
        return

    def _deploy_environment_task(
        self, environment: Environment, test_results: List[TestResult]
    ) -> None:
        try:
            self.platform.deploy_environment(environment)
            assert (
                environment.status == EnvironmentStatus.Deployed
            ), f"actual: {environment.status}"
        except WaitMoreResourceError as identifier:
            self._log.info(
                f"[{environment.name}] waiting for more resource: "
                f"{identifier}, skip assigning case"
            )
            self._skip_test_results(
                test_results, additional_reason="no more resource to deploy"
            )
        except Exception as identifier:
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
            f"case count: {len(test_results)}, "
            f"status {environment.status.name}"
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
        test_suite.start(
            environment=environment,
            case_results=test_results,
            case_variables=case_variables,
        )

        # Some test cases may break the ssh connections. To reduce side effects
        # on next test cases, close the connection after each test run. It will
        # be connected on the next command automatically.
        environment.nodes.close()

        # keep failed environment, not to delete
        if (
            test_result.is_completed
            and test_result.status == TestStatus.FAILED
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

    def _delete_environment_task(
        self, environment: Environment, test_results: List[TestResult]
    ) -> None:
        """
        May be called async
        """
        # the predefined environment shouldn't be deleted, because it
        # serves all test cases.
        if (
            environment.status
            in [
                EnvironmentStatus.Deployed,
                EnvironmentStatus.Connected,
            ]
        ) or (
            environment.status == EnvironmentStatus.Prepared and environment.is_in_use
        ):
            try:
                self.platform.delete_environment(environment)
            except Exception as identifier:
                self._log.debug(
                    f"error on deleting environment '{environment.name}': {identifier}"
                )
        else:
            environment.status = EnvironmentStatus.Deleted

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
                try:
                    if result.check_environment(
                        environment=environment, save_reason=True
                    ) and (
                        not result.runtime_data.use_new_environment
                        or environment.is_new
                    ):
                        runnable_results.append(result)
                except SkippedException as identifier:
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

    def _get_test_results_to_run(
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

    def _merge_test_requirements(
        self,
        test_results: List[TestResult],
        existing_environments: Environments,
        platform_type: str,
    ) -> None:
        assert platform_type
        platform_type_set = search_space.SetSpace[str](
            is_allow_set=True, items=[platform_type]
        )

        # if platform defined requirement, replace the requirement from
        # test case.
        for test_result in test_results:
            platform_requirement = self._create_platform_requirement()
            test_req: TestCaseRequirement = test_result.runtime_data.requirement

            # check if there is platform requirement on test case
            if test_req.platform_type and len(test_req.platform_type) > 0:
                check_result = platform_type_set.check(test_req.platform_type)
                if not check_result.result:
                    test_result.set_status(TestStatus.SKIPPED, check_result.reasons)

            if test_result.can_run:
                assert test_req.environment

                environment_requirement = copy.copy(test_req.environment)
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
                        original_node_requirement.excluded_features = (
                            search_space.SetSpace(
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
                        )
                        platform_requirement.excluded_features = None

                        node_requirement = original_node_requirement.intersect(
                            platform_requirement
                        )

                        assert isinstance(platform_requirement.extended_schemas, dict)
                        assert isinstance(node_requirement.extended_schemas, dict)
                        node_requirement.extended_schemas = deep_update_dict(
                            platform_requirement.extended_schemas,
                            node_requirement.extended_schemas,
                        )
                        environment_requirement.nodes[index] = node_requirement

                env = existing_environments.from_requirement(environment_requirement)
                if env:
                    # if env prepare or deploy failed and the test result is not
                    # run, the failure will attach to this test result.
                    env.source_test_result = test_result

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
