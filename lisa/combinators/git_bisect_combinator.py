import pathlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

from dataclasses_json import dataclass_json

from lisa import messages, notifier, schema
from lisa.combinator import Combinator
from lisa.messages import KernelBuildMessage, TestResultMessage, TestStatus
from lisa.node import Node, quick_connect
from lisa.tools.git import Git, GitBisect
from lisa.util import LisaException, constants, field_metadata

STOP_PATTERNS = ["first bad commit", "This means the bug has been fixed between"]


# Combinator requires a node to clone the source code.
@dataclass_json()
@dataclass
class GitBisectCombinatorSchema(schema.Combinator):
    connection: Optional[schema.RemoteNode] = field(
        default=None, metadata=field_metadata(required=True)
    )
    repo: str = field(
        default="",
        metadata=field_metadata(
            required=True,
        ),
    )
    good_commit: str = field(
        default="",
        metadata=field_metadata(
            required=True,
        ),
    )
    bad_commit: str = field(
        default="",
        metadata=field_metadata(
            required=True,
        ),
    )


# GitBisect Combinator is a loop that runs "expanded" phase
# of runbook until the bisect is complete.
# There can be any number of expanded phases, but the
# GitBisectTestResult notifier should have on boolean/None output per
# phase.


class GitBisectCombinator(Combinator):
    def __init__(
        self,
        runbook: GitBisectCombinatorSchema,
        **kwargs: Any,
    ) -> None:
        super().__init__(runbook)
        self._iteration = 0
        self._result_notifier = GitBisectResult(schema.Notifier())
        notifier.register_notifier(self._result_notifier)
        self._source_path: pathlib.PurePath
        self._node: Optional[Node] = None

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self._clone_source()
        if self._source_path:
            self._start_bisect()
        else:
            raise LisaException(
                "Source path is not set. Please check the source clone."
            )

    @classmethod
    def type_name(cls) -> str:
        return constants.COMBINATOR_GITBISECT

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return GitBisectCombinatorSchema

    def _next(self) -> Optional[Dict[str, Any]]:
        _next: Optional[Dict[str, Any]] = None
        self._process_result()
        if not self._check_bisect_complete():
            _next = {}
            _next["ref"] = self._get_current_commit_hash()
        else:
            self._log.info("Bisect Complete")
        self._result_notifier.result = None
        self._iteration += 1
        return _next

    def _process_result(self) -> None:
        if self._iteration == 0:
            return
        if self._result_notifier.result is not None:
            results = self._result_notifier.result
            if results:
                self._bisect_good()
            else:
                self._bisect_bad()
        else:
            raise LisaException(
                "Bisect combinator does not get result for next iteration. Please check"
                " GitBisectResult notifier."
            )

    def _get_remote_node(self) -> Node:
        if not self._node or not self._node.is_connected:
            self._node = quick_connect(self.runbook.connection, "source_node")
        return self._node

    def _clone_source(self) -> None:
        node = self._get_remote_node()
        git = node.tools[Git]
        self._source_path = git.clone(
            url=self.runbook.repo, cwd=node.working_path, timeout=1200
        )
        node.close()

    def _start_bisect(self) -> None:
        node = self._get_remote_node()
        git_bisect = node.tools[GitBisect]
        git_bisect.start(cwd=self._source_path)
        git_bisect.good(cwd=self._source_path, ref=self.runbook.good_commit)
        git_bisect.bad(cwd=self._source_path, ref=self.runbook.bad_commit)
        node.close()

    def _bisect_bad(self) -> None:
        node = self._get_remote_node()
        git_bisect = node.tools[GitBisect]
        git_bisect.bad(cwd=self._source_path)
        node.close()

    def _bisect_good(self) -> None:
        node = self._get_remote_node()
        git_bisect = node.tools[GitBisect]
        git_bisect.good(cwd=self._source_path)
        node.close()

    def _check_bisect_complete(self) -> bool:
        node = self._get_remote_node()
        git_bisect = node.tools[GitBisect]
        result = git_bisect.check_bisect_complete(cwd=self._source_path)
        node.close()
        return result

    def _get_current_commit_hash(self) -> str:
        node = self._get_remote_node()
        git = node.tools[Git]
        result = git.get_current_commit_hash(cwd=self._source_path)
        node.close()
        return result


class GitBisectResult(notifier.Notifier):
    @classmethod
    def type_name(cls) -> str:
        return "git_bisect_result"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return schema.Notifier

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        self.result: Optional[bool] = None

    def _received_message(self, message: messages.MessageBase) -> None:
        if isinstance(message, messages.TestResultMessage):
            self._update_test_result(message)
        elif isinstance(message, messages.KernelBuildMessage):
            self._update_result(message.is_success)
        else:
            raise LisaException(f"Received unsubscribed message type: {type(message)}")

    def _update_test_result(self, message: messages.TestResultMessage) -> None:
        if message.is_completed:
            if message.status == TestStatus.FAILED:
                self._update_result(False)
            elif message.status == TestStatus.PASSED:
                self._update_result(True)

    def _update_result(self, result: bool) -> None:
        current_result = self.result
        if current_result is not None:
            self.result = current_result and result
        else:
            self.result = result

    def _subscribed_message_type(self) -> List[Type[messages.MessageBase]]:
        return [TestResultMessage, KernelBuildMessage]
