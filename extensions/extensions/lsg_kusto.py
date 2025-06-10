import datetime
import io
import json
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, NamedTuple, Optional, Type, cast

from azure.identity import DefaultAzureCredential
from azure.kusto.data import KustoConnectionStringBuilder  # type: ignore
from azure.kusto.data.data_format import DataFormat  # type: ignore
from azure.kusto.ingest import (  # type: ignore
    ColumnMapping,
    IngestionProperties,
    QueuedIngestClient,
    ReportLevel,
)
from dataclasses_json import dataclass_json

from lisa import LisaException, messages, notifier, schema
from lisa.secret import add_secret
from lisa.testsuite import TestResultMessage, TestStatus
from lisa.util import fields_to_dict

from .common import get_case_ids_from_file, get_extra_information, get_triage_from_file
from .common_database import DatabaseSchema, get_test_cases, get_triage_from_db
from .triage import Failure


@dataclass_json()
@dataclass
class LsgKustoSchema(schema.Notifier):
    # fields to query test failure and test cases from database
    triage_database: Optional[DatabaseSchema] = None
    # If triage_database and triage_rules_path or test_cases_path are both set,
    # triage_rules_path and test_cases_path will be ignored.
    # fields to query test failure from file.
    triage_rules_path: Optional[str] = None
    # fields to query test cases from file.
    test_cases_path: Optional[str] = None

    cluster: str = ""
    database: str = ""
    teat_result_table: str = "TestResults"
    subtest_result_table: str = "SubTestResult"
    tenant_id: str = ""
    application_id: str = ""
    application_key: str = ""
    allow_all_tenants: bool = False

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        add_secret(self.application_key)


class LsgKusto(notifier.Notifier):
    _test_result_mapping: List[ColumnMapping] = [
        ColumnMapping(column_name="Id", path="$.Id", column_type="guid"),
        ColumnMapping(
            column_name="TestProjectName",
            path="$.TestProjectName",
            column_type="string",
        ),
        ColumnMapping(
            column_name="TestPassName", path="$.TestPassName", column_type="string"
        ),
        ColumnMapping(column_name="Name", path="$.Name", column_type="string"),
        ColumnMapping(column_name="Area", path="$.Area", column_type="string"),
        ColumnMapping(column_name="Category", path="$.Category", column_type="string"),
        ColumnMapping(column_name="Owner", path="$.Owner", column_type="string"),
        ColumnMapping(column_name="Priority", path="$.Priority", column_type="int"),
        ColumnMapping(column_name="RunName", path="$.RunName", column_type="string"),
        ColumnMapping(column_name="ResultId", path="$.id_", column_type="string"),
        ColumnMapping(column_name="FailureId", path="$.FailureId", column_type="long"),
        ColumnMapping(column_name="Started", path="$.Started", column_type="datetime"),
        ColumnMapping(
            column_name="Finished", path="$.Finished", column_type="datetime"
        ),
        ColumnMapping(
            column_name="Duration", path="$.Duration", column_type="timespan"
        ),
        ColumnMapping(column_name="Status", path="$.Status", column_type="string"),
        ColumnMapping(column_name="Image", path="$.image", column_type="string"),
        ColumnMapping(
            column_name="KernelVersion", path="$.kernel_version", column_type="string"
        ),
        ColumnMapping(
            column_name="LISVersion", path="$.lis_version", column_type="string"
        ),
        ColumnMapping(
            column_name="HostVersion", path="$.host_version", column_type="string"
        ),
        ColumnMapping(
            column_name="WALAVersion", path="$.wala_version", column_type="string"
        ),
        ColumnMapping(
            column_name="WALADistro", path="$.wala_distro", column_type="string"
        ),
        ColumnMapping(column_name="Location", path="$.location", column_type="string"),
        ColumnMapping(column_name="VMSize", path="$.vmsize", column_type="string"),
        ColumnMapping(column_name="Platform", path="$.platform", column_type="string"),
        ColumnMapping(column_name="Message", path="$.message", column_type="string"),
        ColumnMapping(
            column_name="VMGeneration", path="$.vm_generation", column_type="string"
        ),
        ColumnMapping(
            column_name="DistroVersion", path="$.distro_version", column_type="string"
        ),
        ColumnMapping(
            column_name="LogUrl", path="$.storage_log_path", column_type="string"
        ),
        ColumnMapping(
            column_name="Information", path="$.Information", column_type="string"
        ),
        ColumnMapping(
            column_name="FailureCategory",
            path="$.FailureCategory",
            column_type="string",
        ),
        ColumnMapping(
            column_name="FailureReason", path="$.FailureReason", column_type="string"
        ),
        ColumnMapping(
            column_name="FailureDescription",
            path="$.FailureDescription",
            column_type="string",
        ),
        ColumnMapping(
            column_name="BugUrl",
            path="$.BugUrl",
            column_type="string",
        ),
        ColumnMapping(
            column_name="Architecture",
            path="$.hardware_platform",
            column_type="string",
        ),
    ]

    _subtest_result_mapping: List[ColumnMapping] = [
        ColumnMapping(column_name="Id", path="$.Id", column_type="guid"),
        ColumnMapping(
            column_name="TestResultId", path="$.TestResultId", column_type="guid"
        ),
        ColumnMapping(column_name="Name", path="$.Name", column_type="string"),
        ColumnMapping(
            column_name="CreatedDate", path="$.CreatedDate", column_type="datetime"
        ),
        ColumnMapping(column_name="Status", path="$.Status", column_type="string"),
        ColumnMapping(column_name="Message", path="$.Message", column_type="string"),
        ColumnMapping(
            column_name="Information", path="$.Information", column_type="string"
        ),
    ]

    def __init__(self, runbook: LsgKustoSchema) -> None:
        notifier.Notifier.__init__(self, runbook)
        self._ingest_results: List[Any] = []
        if runbook.triage_database or runbook.triage_rules_path:
            self._need_triage = True
        else:
            self._need_triage = False

    @classmethod
    def type_name(cls) -> str:
        return "lsg_kusto"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return LsgKustoSchema

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        runbook = cast(LsgKustoSchema, self.runbook)

        if not runbook.cluster:
            raise LisaException("cluster must be set.")
        if not runbook.database:
            raise LisaException("database must be set.")

        if runbook.application_id and not runbook.application_key:
            if not runbook.cluster:
                raise LisaException("cluster must be set.")
            connection_string = KustoConnectionStringBuilder.with_aad_managed_service_identity_authentication(  # noqa: E501
                runbook.cluster, client_id=runbook.application_id
            )
        elif runbook.tenant_id and runbook.application_id and runbook.application_key:
            if not runbook.tenant_id:
                raise LisaException("tenant_id must be set.")
            self._log.debug("login by service principal name.")
            connection_string = (
                KustoConnectionStringBuilder.with_aad_application_key_authentication(
                    runbook.cluster,
                    runbook.application_id,
                    runbook.application_key,
                    runbook.tenant_id,
                )
            )
        else:
            #  to fix the issue https://github.com/Azure/azure-cli/issues/28915 temporally  # noqa: E501
            self._log.debug("login as current user.")
            if runbook.allow_all_tenants:
                # allow_all_tenants is used for cross-tenant authorization.
                self._log.debug("Kusto allow_all_tenants: true")
                credentials = DefaultAzureCredential(additionally_allowed_tenants=["*"])
            else:
                credentials = DefaultAzureCredential()
            connection_string = (
                KustoConnectionStringBuilder.with_aad_application_token_authentication(
                    runbook.cluster,
                    credentials.get_token(
                        "https://kusto.kusto.windows.net/.default",
                        tenant_id=runbook.tenant_id,  # It's Ok if tenant_id is not set
                    ).token,
                )
            )
        # Set authority_id to tenant_id for cross-tenant authorization.
        if runbook.tenant_id:
            connection_string.authority_id = runbook.tenant_id
        # Create an instance of QueuedIngestClient
        self._client = QueuedIngestClient(connection_string)

        self._test_result_ingestion_props = IngestionProperties(
            database=runbook.database,
            table=runbook.teat_result_table,
            data_format=DataFormat.SINGLEJSON,
            flush_immediately=True,
            column_mappings=self._test_result_mapping,
            report_level=ReportLevel.FailuresAndSuccesses,
        )

        self._subtest_result_ingestion_props = IngestionProperties(
            database=runbook.database,
            table=runbook.subtest_result_table,
            data_format=DataFormat.SINGLEJSON,
            flush_immediately=True,
            column_mappings=self._subtest_result_mapping,
            report_level=ReportLevel.FailuresAndSuccesses,
        )

        # cache kusto results for sub test results
        self._kusto_results_cache: Dict[str, Any] = dict()

        if runbook.triage_database:
            self._test_cases: Any = get_test_cases(runbook.triage_database)
        else:
            self._test_cases = dict()

        if runbook.test_cases_path:
            self._case_ids = get_case_ids_from_file(runbook.test_cases_path, self._log)

    def _subscribed_message_type(self) -> List[Type[messages.MessageBase]]:
        return [
            TestResultMessage,
            messages.TestRunMessage,
            messages.SubTestMessage,
        ]

    def _received_message(self, message: messages.MessageBase) -> None:
        if isinstance(message, messages.TestRunMessage):
            self._process_test_run_message(message)
        elif isinstance(message, TestResultMessage):
            self._process_test_result_message(message)
        elif isinstance(message, messages.SubTestMessage):
            self._process_subtest_message(message)
        else:
            raise LisaException(f"unsupported message type: {type(message)}")

    def _process_test_run_message(self, message: messages.MessageBase) -> None:
        run_message: messages.TestRunMessage = cast(messages.TestRunMessage, message)
        if run_message.status == messages.TestRunStatus.INITIALIZING:
            assert run_message.test_project, "The test_project shouldn't be empty"
            assert run_message.test_pass, "The test_pass shouldn't be empty"
            self._test_project_name = run_message.test_project
            self._test_pass_name = run_message.test_pass
            self._test_run_name = run_message.run_name

            if self.runbook.triage_database:
                self._triage = get_triage_from_db(
                    runbook=self.runbook.triage_database,
                    test_project_name=self._test_project_name,
                    test_pass_name=self._test_pass_name,
                )
            elif self.runbook.triage_rules_path:
                self._triage = get_triage_from_file(
                    file_path=self.runbook.triage_rules_path,
                    test_project_name=self._test_project_name,
                    test_pass_name=self._test_pass_name,
                    log=self._log,
                )

    def _process_test_result_message(self, message: TestResultMessage) -> None:
        if message.status == TestStatus.QUEUED:
            self._update_test_case(message)

            # check if result is already in the cache, if not, add it
            if message.id_ not in self._kusto_results_cache:
                self._kusto_results_cache[message.id_] = str(uuid.uuid4())

        elif message.is_completed:
            case = self._get_case_by_name(message.full_name)
            failure_id = 0
            matched_failure = None
            if message.message and self._need_triage:
                matched_failure = self._triage.match_test_failure(message, case.Id)
                if matched_failure and isinstance(matched_failure, Failure):
                    failure_id = matched_failure.id
                    self._log.debug(
                        f"test result {message.id_} matched failure {failure_id}"
                    )
                else:
                    failure_id = -1

            # get test result from cache
            test_result_id = self._kusto_results_cache.get(message.id_)
            assert test_result_id, "Kusto test result should be in the cache"

            result: Dict[str, Any] = fields_to_dict(
                src=message,
                fields=[x.properties["Path"][2:] for x in self._test_result_mapping],
                ignore_non_exists=True,
            )
            result.update(message.information)

            result["Id"] = test_result_id

            # test project
            result["TestProjectName"] = self._test_project_name
            result["TestPassName"] = self._test_pass_name

            # test case
            result["Name"] = case.Name
            result["Area"] = case.Area
            result["Category"] = case.Category
            result["Owner"] = case.Owner
            result["Priority"] = case.Priority

            # test run
            result["RunName"] = self._test_run_name

            # test result
            result["ResultId"] = message.id_
            result["Status"] = message.status.name
            duration = datetime.timedelta(seconds=message.elapsed)
            result["Duration"] = str(duration)
            result["Started"] = str(message.time - duration)
            result["Finished"] = str(message.time)

            # test failure
            result["FailureId"] = failure_id
            if matched_failure:
                result["FailureCategory"] = matched_failure.category
                result["FailureReason"] = matched_failure.reason
                result["FailureDescription"] = matched_failure.description
                result["BugUrl"] = matched_failure.bug_url

            # test environment information
            result["Information"] = get_extra_information(message)

            stream = io.StringIO(json.dumps(result))
            self._client.ingest_from_stream(stream, self._test_result_ingestion_props)

    def _process_subtest_message(self, message: messages.SubTestMessage) -> None:
        # get test result from cache
        test_result_id = self._kusto_results_cache.get(message.id_)
        assert test_result_id, "Kusto test result should be in the cache"

        result: Dict[str, Any] = fields_to_dict(
            src=message,
            fields=[x.properties["Path"][2:] for x in self._subtest_result_mapping],
            ignore_non_exists=True,
        )
        result["Id"] = str(uuid.uuid4())
        result["TestResultId"] = test_result_id
        result["Name"] = message.name
        result["CreatedDate"] = str(datetime.datetime.now())
        result["Status"] = message.status.name
        result["Message"] = message.message
        result["Information"] = message.information

        stream = io.StringIO(json.dumps(result))
        self._client.ingest_from_stream(stream, self._subtest_result_ingestion_props)

    def _update_test_case(self, message: TestResultMessage) -> None:
        if self.runbook.triage_database:
            self._test_cases.add_or_update_test_case(message)
        elif message.full_name not in self._test_cases:
            test_case = NamedTuple(
                "test_case",
                [
                    ("Id", int),
                    ("Name", str),
                    ("Owner", str),
                    ("Area", str),
                    ("Category", str),
                    ("Tag", str),
                    ("Priority", int),
                    ("Description", str),
                ],
            )
            information = message.information
            # no database supported or test cases file, the case id is 0
            test_case.Id = 0
            if self.runbook.test_cases_path:
                test_case.Id = self._case_ids.get(message.full_name, 0)
            test_case.Name = message.full_name
            test_case.Owner = information.get("owner", "")
            test_case.Area = information.get("area", "")
            test_case.Category = information.get("category", "")
            test_case.Tag = ",".join(information.get("tags", ""))
            test_case.Priority = int(information.get("priority", 2))
            test_case.Description = information.get("description", "")
            self._test_cases[message.full_name] = test_case

    def _get_case_by_name(self, full_name: str) -> Any:
        if self.runbook.triage_database:
            return self._test_cases.get_by_name(full_name)
        else:
            return self._test_cases[full_name]
