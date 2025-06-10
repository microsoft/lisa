from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Type

from dataclasses_json import dataclass_json

from lisa import schema
from lisa.testsuite import get_cases_metadata
from lisa.util import field_metadata

from .common import TestPassCacheStatus
from .test_pass_combinator import TestPassCombinator, TestPassCombinatorSchema


@dataclass_json()
@dataclass
class BaselineTestPassCombinatorSchema(TestPassCombinatorSchema):
    images: List[str] = field(
        default_factory=list, metadata=field_metadata(required=True)
    )
    location: str = ""


class BaselineTestPassCombinator(TestPassCombinator):
    TIMEOUT_IN_SECONDS = 3600

    def __init__(self, runbook: BaselineTestPassCombinatorSchema) -> None:
        TestPassCombinator.__init__(self, runbook)
        self.start_time = datetime.now()

    @classmethod
    def type_name(cls) -> str:
        return "baseline_test_pass_combinator"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return BaselineTestPassCombinatorSchema

    def _initialize_test_pass_cache(self) -> None:
        runbook: BaselineTestPassCombinatorSchema = self.runbook
        test_pass_cache_count = self._get_test_pass_cache_count()
        if test_pass_cache_count == 0:
            # Add images to testpasscache.
            # Use SQL statement as ORM is not efficient for bulk insert.
            session = self.create_session()
            self._log.info(
                f"Adding runs for TestPassCache Testpass : {self.runbook.test_pass}"
            )
            for image in runbook.images:
                sql = """
                    INSERT INTO
                    TestPassCache(TestPassId, TestCaseName, Image,
                                    Location, Status, CreatedDate)
                    VALUES
                """
                testcase_metadata = get_cases_metadata()
                testcases = [
                    testcase_metadata[key].full_name
                    for key in testcase_metadata.keys()
                    if testcase_metadata[key].priority < 5
                ]

                vars = {}
                vars["testpassid"] = self.test_pass_id
                for test_idx, test_name in enumerate(testcases):
                    sql += f"""
                    (:testpassid, :{test_idx}_0, :{test_idx}_1, :{test_idx}_2,
                    :{test_idx}_3, getutcdate()),
                    """
                    vars[f"{test_idx}_0"] = test_name
                    vars[f"{test_idx}_1"] = image
                    vars[f"{test_idx}_2"] = runbook.location
                    vars[f"{test_idx}_3"] = TestPassCacheStatus.NOT_STARTED
                sql = sql.strip()[:-1] + ";"
                session.execute(sql, vars)
                self.commit_and_close_session(session)
        else:
            # Reset running status.
            self._set_test_pass_cache_status(
                TestPassCacheStatus.RUNNING, TestPassCacheStatus.NOT_STARTED
            )

    def _next(self) -> Optional[Dict[str, Any]]:
        curr_time = datetime.now()
        if (curr_time - self.start_time).seconds > self.TIMEOUT_IN_SECONDS:
            self._log.info("Baseline Combinator timeout reached. Exiting.")
            return None
        return super()._next()
