from datetime import datetime
from typing import Any, Dict, Optional, Type

from lisa import schema

from .common import TestPassCacheStatus
from .test_pass_combinator import TestPassCombinator, TestPassCombinatorSchema


class SmokeTestPassCombinator(TestPassCombinator):
    TIMEOUT_IN_SECONDS = 3600

    @classmethod
    def type_name(cls) -> str:
        return "smoke_test_pass_combinator"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return TestPassCombinatorSchema

    def _initialize_test_pass_cache(self) -> None:
        test_pass_cache_count = self._get_test_pass_cache_count()
        self.start_time = datetime.now()
        if test_pass_cache_count == 0:
            # Add images to testpasscache.
            # Use SQL statement as ORM is not efficient for bulk insert.
            session = self.create_session()
            self._log.info(
                f"Adding distros to TestPassCache for "
                f"Testpass : {self.runbook.test_pass}"
            )
            sql = f"""
                INSERT INTO
                TestPassCache(TestPassId, Location, Image, TestCaseName,
                                Status, CreatedDate)
                SELECT :testpassid, Location, FullName, 'Provisioning.smoke_test',
                '{TestPassCacheStatus.NOT_STARTED}', getutcdate()
                FROM View_Distinct_MarketplaceDistros
            """
            session.execute(sql, {"testpassid": self.test_pass_id})
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
