import json
import os
from datetime import datetime
from typing import Any, Dict, List, Type, cast

from retry import retry

from lisa import messages, notifier, schema
from lisa.testsuite import TestResultMessage, TestStatus
from lisa.util import LisaException, hookimpl, plugin_manager

from .common import get_extra_information, get_test_run_log_location
from .common_database import (
    DatabaseMixin,
    DatabaseSchema,
    get_test_cases,
    get_test_project,
    get_triage_from_db,
)
from .triage import Failure


class LsgDatabase(DatabaseMixin, notifier.Notifier):
    """
    It's a database notifier, output subscribed message to database.
    """

    _tables = [
        "TestRun",
        "TestResult",
        "SubTestResult",
        "TestFailure",
    ]

    def __init__(self, runbook: DatabaseSchema) -> None:
        DatabaseMixin.__init__(self, runbook, self._tables)
        notifier.Notifier.__init__(self, runbook)
        self._test_project = get_test_project(runbook)
        self._test_cases = get_test_cases(runbook)

    @classmethod
    def type_name(cls) -> str:
        return "lsg_database"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return DatabaseSchema

    @hookimpl
    def get_test_run_id(self) -> int:
        return self._test_run.Id  # type: ignore

    @hookimpl
    def get_test_result_db_id(self, result_id: str) -> int:
        test_result = self._test_results_cache.get(result_id, None)
        if test_result is None:
            raise LisaException("cannot find matched test result")
        return test_result.Id  # type: ignore

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize()
        self._test_results_cache: Dict[str, Any] = dict()

        self._log.info("initializing database notifier...")
        self.TestRun = self.base.classes.TestRun
        self.TestResult = self.base.classes.TestResult
        self.SubTestResult = self.base.classes.SubTestResult
        self.TestFailure = self.base.classes.TestFailure

        plugin_manager.register(self)

    def _add_test_result(self, message: TestResultMessage) -> None:
        date = datetime.utcnow()
        session = self.create_session()
        if message.id_ not in self._test_results_cache:
            test_result = self.TestResult(
                RunId=self._test_run.Id,
                CaseId=self._test_cases.get_id_by_name(message.full_name),
                CreatedDate=date,
                UpdatedDate=date,
                StartedDate=date,
                Status="QUEUED",
                FailureId=-1,
                Duration=message.elapsed,
                Image=message.information.pop("image", ""),
                KernelVersion=message.information.pop("kernel_version", ""),
                LISVersion=message.information.pop("lis_version", ""),
                HostVersion=message.information.pop("host_version", ""),
                Message=message.message,
                Location=message.information.pop("location", ""),
                Platform=message.information.pop("platform", ""),
                VMSize=message.information.pop("vmsize", ""),
                WALAVersion=message.information.pop("wala_version", ""),
                WALADistro=message.information.pop("wala_distro", ""),
                DistroVersion=message.information.pop("distro_version", ""),
                VMGeneration=message.information.pop("vm_generation", 0),
                LogUrl=message.information.pop("storage_log_path", ""),
                Information=json.dumps(get_extra_information(message)),
            )
            session.add(test_result)
            self._test_results_cache[message.id_] = test_result
            # it inserts multiple results, but it needs to return id
            # so bulk insert cannot be used here.
            self._log.debug("inserting test results into database...")
            self.commit_and_close_session(session)

    def _process_test_run_message(self, message: messages.MessageBase) -> None:
        run_message: messages.TestRunMessage = cast(messages.TestRunMessage, message)
        date = datetime.utcnow()
        session = self.create_session()
        if run_message.status == messages.TestRunStatus.INITIALIZING:
            assert run_message.test_pass, "The test_pass shouldn't be empty"
            test_project = self._test_project.get_test_project(run_message.test_project)
            test_pass = self._test_project.add_or_get_test_pass(
                run_message.test_pass, date, test_project
            )

            self._triage = get_triage_from_db(
                runbook=self.database_schema,
                test_project_name=test_project.Name,
                test_pass_name=test_pass.Name,
            )

            build_number = os.environ.get("BUILD_BUILDID")
            build_url = None
            if build_number:
                build_number = f"_build/results?buildId={build_number}&view=results"
                array: List[Any] = [
                    os.environ.get("SYSTEM_TEAMFOUNDATIONCOLLECTIONURI"),
                    os.environ.get("SYSTEM_TEAMPROJECTID"),
                    build_number,
                ]
                build_url = ("/").join(array)

            test_run = self.TestRun(
                TestPassId=test_pass.Id,
                Name=run_message.run_name,
                Tag=",".join(run_message.tags) if run_message.tags else "",
                StartedDate=date,
                UpdatedDate=date,
                CreatedDate=date,
                Status=run_message.status.name,
                BuildURL=build_url,
            )
            session.add(test_run)
            self._test_project_name = test_project.Name
            self._test_pass_name = test_pass.Name
            self._test_run = test_run
        elif run_message.status == messages.TestRunStatus.RUNNING:
            self._test_run.UpdatedDate = date
            self._test_run.Status = run_message.status.name
            session.add(self._test_run)

        elif (
            run_message.status == messages.TestRunStatus.FAILED
            or run_message.status == messages.TestRunStatus.SUCCESS
        ):
            self._test_run.Status = run_message.status.name
            self._test_run.UpdatedDate = date
            self._test_run.FinishedDate = date

            self._test_run.BuildURL = get_test_run_log_location(self._log)
            session.add(self._test_run)
            failures = self._triage.get_failures()

            # update failures
            used_ids: List[int] = []
            for failure in failures:
                if failure.updated_date:
                    used_ids.append(failure.id)

            session.query(self.TestFailure).filter(
                self.TestFailure.Id.in_(used_ids)
            ).update({"UpdatedDate": datetime.utcnow()}, synchronize_session=False)
        self.commit_and_close_session(session)

    def _process_test_result_message(self, message: TestResultMessage) -> None:
        date = datetime.utcnow()
        if message.status == TestStatus.QUEUED:
            self._test_cases.add_or_update_test_case(message)
        else:
            case_id = self._test_cases.get_id_by_name(message.full_name)
            self._add_test_result(message)
            failure_id = 0
            matched_failure = None
            if message.message:
                matched_failure = self._triage.match_test_failure(message, case_id)
                if matched_failure and isinstance(matched_failure, Failure):
                    failure_id = matched_failure.id
                else:
                    failure_id = -1
            result = self._test_results_cache.get(message.id_, None)
            if result is None:
                raise LisaException(
                    f"cannot find matched test result to update for case "
                    f"{message.full_name}"
                )
            result.RunId = self._test_run.Id
            result.CaseId = case_id
            result.FailureId = failure_id
            result.FinishedDate = date
            result.UpdatedDate = date
            result.Status = message.status.name
            result.KernelVersion = message.information.pop("kernel_version", "")
            result.LISVersion = message.information.pop("lis_version", "")
            result.HostVersion = message.information.pop("host_version", "")
            result.Message = message.message
            result.Location = message.information.pop("location", "")
            result.Platform = message.information.pop("platform", "")
            result.Image = message.information.pop("image", "")
            result.VMSize = message.information.pop("vmsize", "")
            result.Duration = message.elapsed
            result.WALAVersion = message.information.pop("wala_version", "")
            result.WALADistro = message.information.pop("wala_distro", "")
            result.DistroVersion = message.information.pop("distro_version", "")
            result.VMGeneration = message.information.pop("vm_generation", 0)
            result.LogUrl = message.information.pop("storage_log_path", "")
            result.Architecture = message.information.pop("hardware_platform", "")

            result.Information = json.dumps(get_extra_information(message))

            @retry(tries=5, delay=1, backoff=2)
            def add_with_retry() -> None:
                session = self.create_session()
                session.add(result)
                self.commit_and_close_session(session)

            add_with_retry()

    def _process_subtest_message(self, message: messages.MessageBase) -> None:
        subtest_message: messages.SubTestMessage = cast(
            messages.SubTestMessage, message
        )
        test_result = self._test_results_cache.get(subtest_message.id_, None)
        if test_result is None:
            raise LisaException(
                f"cannot find matched test result to update for case "
                f"{subtest_message.name}"
            )
        subtest_result = self.SubTestResult()
        subtest_result.TestResultId = test_result.Id
        subtest_result.Name = subtest_message.name
        subtest_result.Status = subtest_message.status.name
        subtest_result.Message = subtest_message.message
        subtest_result.Information = json.dumps(get_extra_information(subtest_message))

        session = self.create_session()
        session.add(subtest_result)
        self.commit_and_close_session(session)

    def _received_message(self, message: messages.MessageBase) -> None:
        if isinstance(message, messages.TestRunMessage):
            self._process_test_run_message(message)
        elif isinstance(message, TestResultMessage):
            self._process_test_result_message(message)
        elif isinstance(message, messages.SubTestMessage):
            self._process_subtest_message(message)
        else:
            raise LisaException(f"unsupported message type: {type(message)}")

    def _subscribed_message_type(self) -> List[Type[messages.MessageBase]]:
        return [
            TestResultMessage,
            messages.TestRunMessage,
            messages.SubTestMessage,
        ]
