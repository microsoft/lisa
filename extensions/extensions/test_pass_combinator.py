import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Type

from dataclasses_json import dataclass_json
from sqlalchemy import func  # type: ignore

from lisa import schema
from lisa.combinator import Combinator
from lisa.testsuite import TestStatus
from lisa.util import hookimpl, plugin_manager
from lisa.variable import VariableEntry

from .common import TestPassCacheStatus
from .common_database import DatabaseMixin, DatabaseSchema, get_test_project


@dataclass_json()
@dataclass
class TestPassCombinatorSchema(schema.Combinator, DatabaseSchema):
    test_project: str = ""
    test_pass: str = ""


class TestPassCombinator(DatabaseMixin, Combinator):
    """
    Get Images which are NotStarted in TestPassCache.
    """

    _tables = ["TestPassCache"]

    def __init__(self, runbook: TestPassCombinatorSchema) -> None:
        Combinator.__init__(self, runbook)
        DatabaseMixin.__init__(self, runbook, self._tables)

        assert runbook.test_project, "Test Project name is not set."
        assert runbook.test_pass, "Test Pass name is not set."
        self._test_project = get_test_project(runbook)
        self.index = 0

    @classmethod
    def type_name(cls) -> str:
        return "test_pass_combinator"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return TestPassCombinatorSchema

    def _initialize_test_pass_cache(self) -> None:
        raise NotImplementedError

    @hookimpl
    def on_run_finalize(self) -> None:
        self._update_test_pass_cache_status()

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        super()._initialize()
        self._log.info("Initializing test pass combinator...")
        self.TestPassCache = self.base.classes.TestPassCache

        # get test pass id
        date = datetime.utcnow()
        test_project = self._test_project.get_test_project(self.runbook.test_project)
        test_pass = self._test_project.add_or_get_test_pass(
            self.runbook.test_pass, date, test_project
        )
        self.test_pass_id = test_pass.Id
        self._log.debug(f"Test Pass ID : {self.test_pass_id}")

        # fetch images from TestPassCache
        self._initialize_test_pass_cache()
        self.items = self._get_testpass_cache_items()
        self.total_items = self._get_test_pass_cache_count()
        self._update_items_count()

        # register for `on_run_completed` hook
        plugin_manager.register(self)

    def _get_test_pass_cache_count(self) -> int:
        session = self.create_session()
        test_pass_cache_count: int = (
            session.query(func.count(self.TestPassCache.ID))
            .filter_by(TestPassId=self.test_pass_id)
            .scalar()
        )
        self.commit_and_close_session(session)
        return test_pass_cache_count

    def _get_test_pass_cache_running_count(self) -> int:
        session = self.create_session()
        test_pass_cache_running_count: int = (
            session.query(func.count(self.TestPassCache.ID))
            .filter_by(TestPassId=self.test_pass_id)
            .filter_by(Status=TestPassCacheStatus.RUNNING)
            .scalar()
        )
        self.commit_and_close_session(session)
        return test_pass_cache_running_count

    def _update_items_count(self) -> None:
        self.running_items = self._get_test_pass_cache_running_count()
        self.done_items = self.total_items - self.running_items
        self._log.info(
            f"Running : {self.running_items} | "
            f"Done : {self.done_items} | "
            f"Total : {self.total_items}"
        )

    def _set_test_pass_cache_status(self, old: str, new: str) -> None:
        session = self.create_session()
        date = datetime.utcnow()
        _ = (
            session.query(self.TestPassCache)
            .filter_by(TestPassId=self.test_pass_id)
            .filter_by(Status=old)
            .update(
                {
                    self.TestPassCache.Status: new,
                    self.TestPassCache.UpdatedDate: date,
                },
                synchronize_session=False,
            )
        )
        self.commit_and_close_session(session)

    def _get_testpass_cache_items(self) -> List[Tuple[Any, Any, Any]]:
        self._set_test_pass_cache_status(
            TestPassCacheStatus.NOT_STARTED, TestPassCacheStatus.RUNNING
        )

        # fetch TestPassCache items
        session = self.create_session()
        test_pass_cache_items: List[Tuple[Any, Any, Any]] = (
            session.query(
                self.TestPassCache.Image,
                self.TestPassCache.Location,
                self.TestPassCache.TestCaseName,
            )
            .filter_by(TestPassId=self.test_pass_id)
            .filter_by(Status=TestPassCacheStatus.RUNNING)
            .all()
        )

        # randomize order of TestPassCache items list
        random.shuffle(test_pass_cache_items)

        # log TestPassCache items count
        self._log.info(f"Found {len(test_pass_cache_items)} items to run.")

        self.commit_and_close_session(session)
        return test_pass_cache_items

    def _update_test_pass_cache_status(self) -> None:
        session = self.create_session()
        # Use SQL statement as ORM is not efficient for bulk updates.
        sql = f"""WITH Runnings AS (
                SELECT Id, TestPassId, LOWER(TestCaseName) as TestCaseName, Image,
                Location, UpdatedDate FROM TestPassCache
                WHERE TestPassId = :testpassid AND
                Status='{TestPassCacheStatus.RUNNING}'
            ),
            TestResults AS (
                SELECT TestResult.id as Id, LOWER(TestCase.Name) as TestCaseName,
                Status, Image, Location, TestResult.UpdatedDate as UpdatedDate
                FROM TestResult, TestCase
                WHERE TestResult.CaseId = TestCase.Id AND
                TestResult.Id IN (
                    SELECT max(TestResult.Id)
                    FROM TestRun,TestResult
                    WHERE TestRun.TestPassId = :testpassid AND
                    TestRun.Id = TestResult.RunId AND
                    (TestResult.Status = '{TestStatus.PASSED.name}' OR
                    TestResult.Status = '{TestStatus.FAILED.name}' OR
                    TestResult.Status = '{TestStatus.SKIPPED.name}' OR
                    TestResult.Status = '{TestStatus.ATTEMPTED.name}')
                    GROUP BY TestResult.Image, TestResult.CaseId
                )
            )
            UPDATE TestPassCache
            SET Status='{TestPassCacheStatus.DONE}', UpdatedDate=getutcdate()
            WHERE TestPassId = :testpassid AND ID IN (
            SELECT Runnings.ID FROM Runnings LEFT JOIN TestResults ON
                Runnings.TestCaseName = TestResults.TestCaseName AND
                Runnings.Image = TestResults.Image AND
                Runnings.Location = TestResults.Location
                WHERE TestResults.Id IS NOT NULL
            )
        """
        self._log.debug("Updating test pass cache status...")
        session.execute(sql, {"testpassid": self.test_pass_id})
        self.commit_and_close_session(session)
        self._update_items_count()

    def _next(self) -> Optional[Dict[str, Any]]:
        result: Optional[Dict[str, VariableEntry]] = None
        self._update_test_pass_cache_status()
        if self.index < len(self.items):
            result = {}
            result["marketplace_image"] = self.items[self.index][0]
            result["location"] = self.items[self.index][1]
            result["test_case_name"] = self.items[self.index][2].split(".")[-1]
            self.index += 1

            # log running items for debugging
            self._log.info(f"Running item : {result}")
        return result
