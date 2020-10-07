from typing import Dict, List, Optional

from lisa import schema, search_space
from lisa.environment import Environment, Environments, load_environments
from lisa.platform_ import WaitMoreResourceError, load_platform
from lisa.testselector import select_testcases
from lisa.testsuite import (
    LisaTestCase,
    LisaTestCaseMetadata,
    TestCaseRequirement,
    TestResult,
    TestStatus,
)
from lisa.util.logger import get_logger

log = get_logger("runner")


# TODO: This entire function is one long string of side-effects.
# We need to reduce this function's complexity to remove the
# disabled warning, and not rely solely on side effects.
async def run(runbook: schema.Runbook) -> List[TestResult]:  # noqa: C901
    # select test cases
    selected_test_cases = select_testcases(runbook.testcase)

    selected_test_results = [
        TestResult(runtime_data=case) for case in selected_test_cases
    ]

    # load predefined environments
    candidate_environments = load_environments(runbook.environment)

    platform = load_platform(runbook.platform)
    # get environment requirements
    _merge_test_requirements(
        test_results=selected_test_results,
        existing_environments=candidate_environments,
        platform_type=platform.type_name(),
    )

    # there may not need to handle requirements, if all environment are predefined
    prepared_environments = platform.prepare_environments(candidate_environments)

    can_run_results = selected_test_results
    # request environment then run test s
    for environment in prepared_environments:
        try:
            is_needed: bool = False
            can_run_results = [x for x in can_run_results if x.can_run]
            can_run_results.sort(key=lambda x: x.runtime_data.metadata.suite.name)
            new_env_can_run_results = [
                x for x in can_run_results if x.runtime_data.use_new_environment
            ]

            if not can_run_results:
                # no left tests, break the loop
                log.debug(f"no more test case to run, skip env [{environment.name}]")
                break

            # check if any test need this environment
            if any(
                case.can_run and case.check_environment(environment, True)
                for case in can_run_results
            ):
                is_needed = True

            if not is_needed:
                log.debug(
                    f"env[{environment.name}] skipped "
                    f"as not meet any case requirement"
                )
                continue

            try:
                platform.deploy_environment(environment)
            except WaitMoreResourceError as identifier:
                log.warning(
                    f"[{environment.name}] waiting for more resource: "
                    f"{identifier}, skip assiging case"
                )
                continue

            if not environment.is_ready:
                log.warning(
                    f"[{environment.name}] is not deployed successfully, "
                    f"skip assiging case"
                )
                continue

            # once environment is ready, check updated capability
            log.info(f"start running cases on {environment.name}")
            # try a case need new environment firstly
            for new_env_result in new_env_can_run_results:
                if new_env_result.check_environment(environment, True):
                    await _run_suite(environment=environment, cases=[new_env_result])
                    break

            # grouped test results by test suite.
            grouped_cases: List[TestResult] = []
            current_test_suite: Optional[LisaTestCaseMetadata] = None
            for test_result in can_run_results:
                if (
                    test_result.can_run
                    and test_result.check_environment(environment, True)
                    and not test_result.runtime_data.use_new_environment
                ):
                    if (
                        test_result.runtime_data.metadata.suite != current_test_suite
                        and grouped_cases
                    ):
                        # run last batch cases
                        await _run_suite(environment=environment, cases=grouped_cases)
                        grouped_cases = []

                    # append new test cases
                    current_test_suite = test_result.runtime_data.metadata.suite
                    grouped_cases.append(test_result)

            if grouped_cases:
                await _run_suite(environment=environment, cases=grouped_cases)
        finally:
            if environment and environment.is_ready:
                platform.delete_environment(environment)

    # not run as there is no fit environment.
    for case in can_run_results:
        if case.can_run:
            reasons = "no available environment"
            if case.check_results and case.check_results.reasons:
                reasons = f"{reasons}: {case.check_results.reasons}"

            case.set_status(TestStatus.SKIPPED, reasons)

    result_count_dict: Dict[TestStatus, int] = dict()
    for test_result in selected_test_results:
        log.info(
            f"{test_result.runtime_data.metadata.full_name:>30}: "
            f"{test_result.status.name:<8} {test_result.message}"
        )
        result_count = result_count_dict.get(test_result.status, 0)
        result_count += 1
        result_count_dict[test_result.status] = result_count

    log.info("test result summary")
    log.info(f"  TOTAL      : {len(selected_test_results)}")
    for key in TestStatus:
        log.info(f"    {key.name:<9}: {result_count_dict.get(key, 0)}")

    return selected_test_results


async def _run_suite(environment: Environment, cases: List[TestResult]) -> None:

    assert cases
    suite_metadata = cases[0].runtime_data.metadata.suite
    test_suite: LisaTestCase = suite_metadata.test_class(
        environment,
        cases,
        suite_metadata,
    )
    for case in cases:
        case.env = environment.name
    await test_suite.start()


def _merge_test_requirements(
    test_results: List[TestResult],
    existing_environments: Environments,
    platform_type: str,
) -> None:
    """TODO: This function modifies `test_results` and `existing_environments`."""
    assert platform_type
    platform_type_set = search_space.SetSpace[str](
        is_allow_set=True, items=[platform_type]
    )
    for test_result in test_results:
        test_req: TestCaseRequirement = test_result.runtime_data.requirement

        # check if there is playform requirement on test case
        if test_req.platform_type and len(test_req.platform_type) > 0:
            check_result = test_req.platform_type.check(platform_type_set)
            if not check_result.result:
                test_result.set_status(TestStatus.SKIPPED, check_result.reasons)

        if test_result.can_run:
            assert test_req.environment
            # if case need a new env to run, force to create one.
            # if not, get or create one.
            if test_result.runtime_data.use_new_environment:
                existing_environments.from_requirement(test_req.environment)
            else:
                existing_environments.get_or_create(test_req.environment)
