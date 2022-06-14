# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, List, Type, cast

import pytest
from _pytest.config import Config
from _pytest.reports import CollectReport, TestReport
from dataclasses_json import dataclass_json
from pytest_html.plugin import HTMLReport  # type: ignore

from lisa import schema
from lisa.messages import (
    MessageBase,
    TestResultMessage,
    TestRunMessage,
    TestRunStatus,
    TestStatus,
)
from lisa.notifier import Notifier
from lisa.secret import mask
from lisa.util import LisaException, constants


@dataclass_json()
@dataclass
class HtmlSchema(schema.Notifier):
    path: str = "lisa.html"
    """
    open html report in browser for convenient at local
    """
    auto_open: bool = False


class Html(Notifier):
    """
    This class leverage pytest-html to generate a beautiful html report. The reason of
    not using pytest directly, since we didn't find a way to support planing deployment.
    What we can implement in pytest is to cache unused environment, not able to detect
    when is right time to delete it. The Caching mechanism doesn't deal with resource
    efficiently, for example, 1) a vm holds compute quota in Azure, even it's shutted
    down.
    If someone knows how to plan test cases, and pick test cases dynamically during
    test running, feel free to let us know. We can leverage pytest better.
    """

    @classmethod
    def type_name(cls) -> str:
        return "html"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return HtmlSchema

    def finalize(self) -> None:
        runbook = cast(HtmlSchema, self.runbook)
        self._log.info(f"report: {self._report_path}")
        self._html_report.pytest_sessionfinish(session=self._session)
        if runbook.auto_open:
            import webbrowser

            webbrowser.open(f"file://{self._report_path}")

    def _received_message(self, message: MessageBase) -> None:
        if isinstance(message, TestRunMessage):
            self._received_test_run(message)
        elif isinstance(message, TestResultMessage):
            self._received_test_result(message)
        else:
            raise LisaException(f"received unknown message type: {message}")

    def _received_test_run(self, message: TestRunMessage) -> None:
        if message.status == TestRunStatus.INITIALIZING:
            self._html_report.pytest_sessionstart(self._session)
            self._html_report.title = message.run_name
            information = OrderedDict(
                {
                    "test project": message.test_project,
                    "test pass": message.test_pass,
                    "tags": message.tags,
                    "runbook_path": constants.RUNBOOK_FILE,
                    "runbook": mask(constants.RUNBOOK),
                }
            )
            setattr(  # noqa: B010
                self._config,
                "_metadata",
                OrderedDict(
                    {key: value for key, value in information.items() if value}
                ),
            )
        elif message.status == TestRunStatus.FAILED:
            report = CollectReport(
                nodeid="run failed",
                outcome="failed",
                longrepr=message.message,
                result=None,
            )
            self._html_report.pytest_collectreport(report)

    def _received_test_result(self, message: TestResultMessage) -> None:
        if message.status in [TestStatus.PASSED, TestStatus.FAILED, TestStatus.SKIPPED]:
            new_status: Any = message.status.name.lower()
            report = TestReport(
                nodeid=f"{message.id_}:{message.name}",
                location=("", None, ""),
                keywords=dict(),
                outcome=new_status,
                longrepr=message.message,
                when="call",
                duration=message.elapsed,
                duration_formatter="%H:%M:%S.%f",
            )
            if message.information:
                report.sections.append(
                    (
                        "information",
                        "\n".join(
                            [
                                f"{key}: {value}"
                                for key, value in message.information.items()
                            ]
                        ),
                    )
                )
            self._html_report.pytest_runtest_logreport(report)

    def _subscribed_message_type(self) -> List[Type[MessageBase]]:
        return [TestResultMessage, TestRunMessage]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        runbook = cast(HtmlSchema, self.runbook)
        # disable global capture, because it causes "handle is invalid" error in
        # Windows 11
        global_config = Config.fromdictargs({"capture": "no"}, {})
        self._session = pytest.Session.from_config(global_config)
        self._report_path = constants.RUN_LOCAL_LOG_PATH / runbook.path

        # enable capture in html config, so the detail log can output
        self._config = Config.fromdictargs({"self_contained_html": True}, {})
        self._html_report = HTMLReport(self._report_path, self._config)
