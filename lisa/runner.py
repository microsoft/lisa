from typing import Union, cast

from lisa import schema
from lisa.action import Action
from lisa.util import LisaException, constants
from lisa.util.logger import get_logger


def initialize_testcase(runbook: schema.Runbook) -> None:
    runbook.testcase = []
    if runbook.testcase_raw:
        for case_raw in runbook.testcase_raw:
            if constants.TYPE in case_raw:
                case_type = case_raw[constants.TYPE]
            else:
                case_type = constants.TESTCASE_TYPE_LISA

            if case_type == constants.TESTCASE_TYPE_LISA:
                case_runbook: Union[schema.TestCase, schema.LegacyTestCase] = cast(
                    schema.TestCase,
                    schema.TestCase.schema().load(case_raw),  # type:ignore
                )
            elif case_type == constants.TESTCASE_TYPE_LEGACY:
                case_runbook = cast(
                    schema.LegacyTestCase,
                    schema.LegacyTestCase.schema().load(case_raw),  # type:ignore
                )
            else:
                raise LisaException(f"unknown test case type: {case_type}")
            runbook.testcase.append(case_runbook)
    else:
        runbook.testcase = [
            schema.TestCase(name="test", criteria=schema.Criteria(area="demo"))
        ]
