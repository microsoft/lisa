# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, TextIO, Type

from lisa import messages, notifier, schema
from lisa.environment import EnvironmentMessage, EnvironmentStatus
from lisa.messages import TestResultMessage
from lisa.util import LisaException, constants
from lisa.util.perf_timer import create_timer


@dataclass
class TestResultInformation:
    id: str
    name: str
    status: str = ""
    environment: str = ""
    started_time: Optional[datetime] = None


@dataclass
class EnvironmentInformation:
    name: str
    status: str
    information: str
    prepared_time: Optional[datetime] = None
    deployed_time: Optional[datetime] = None
    deleted_time: Optional[datetime] = None
    results: List[TestResultInformation] = field(default_factory=list)


@dataclass
class Event:
    name: str
    action: str
    time: datetime


class EnvironmentStats(notifier.Notifier):
    """
    This notifier uses to troubleshoot the environment lifecycle, and which test
    cases are run on which environment.
    """

    @classmethod
    def type_name(cls) -> str:
        return "env_stats"

    @classmethod
    def type_schema(cls) -> Type[schema.TypedSchema]:
        return schema.Notifier

    def finalize(self) -> None:
        self._update_information(True)

    def _received_message(self, message: messages.MessageBase) -> None:
        if isinstance(message, TestResultMessage):
            self._process_test_result_message(message)
        elif isinstance(message, EnvironmentMessage):
            self._process_environment_message(message)
        else:
            raise LisaException(f"unsupported message received, {type(message)}")

    def _subscribed_message_type(self) -> List[Type[messages.MessageBase]]:
        return [TestResultMessage, EnvironmentMessage]

    def _initialize(self, *args: Any, **kwargs: Any) -> None:
        env_path = constants.RUN_LOCAL_LOG_PATH / "environments"
        env_path.mkdir(exist_ok=True, parents=True)
        self._file_path = env_path / "environment_stats.log"

        self._last_updated_time = create_timer()
        # result update at most 1 time per second
        self._update_frequency = 1
        self._test_results: Dict[str, TestResultInformation] = {}
        self._environments: Dict[str, EnvironmentInformation] = {}

    def _process_test_result_message(self, test_result: TestResultMessage) -> None:
        result_info = self._test_results.get(test_result.id_, None)
        if not result_info:
            result_info = TestResultInformation(
                id=test_result.id_, name=test_result.full_name
            )
            self._test_results[test_result.id_] = result_info
        result_info.status = str(test_result.status)
        env_name = test_result.information.get("environment", "")
        if env_name:
            environment_info = self._environments.get(env_name, None)
            assert (
                environment_info
            ), f"cannot find environment for test result: {test_result}"
            result_info.environment = env_name
            if result_info not in environment_info.results:
                environment_info.results.append(result_info)

        self._update_information()

    def _process_environment_message(self, environment: EnvironmentMessage) -> None:
        env_info = self._environments.get(environment.name, None)
        if not env_info:
            env_info = EnvironmentInformation(
                name=environment.name,
                status=environment.status.name,
                information=str(environment.runbook),
            )
            self._environments[environment.name] = env_info

        env_info.status = environment.status.name
        if environment.status == EnvironmentStatus.Prepared:
            env_info.prepared_time = datetime.now()
        elif environment.status == EnvironmentStatus.Deployed:
            env_info.deployed_time = datetime.now()
        elif environment.status == EnvironmentStatus.Deleted:
            env_info.deleted_time = datetime.now()

        self._update_information(force=True)

    def _update_information(self, force: bool = False) -> None:
        if self._last_updated_time.elapsed(False) > self._update_frequency or force:
            with open(self._file_path, "w") as f:
                self._dump_environments(f)
            self._last_updated_time = create_timer()

    def _dump_environments(self, f: TextIO) -> None:
        f.write(
            f"{'name':<15} {'status':<15} {'prepared_time':<30} {'deployed_time':<30} "
            f"{'deleted_time':<30} results\n"
        )
        for env_result in self._environments.values():
            f.write(
                f"{env_result.name:<15} {env_result.status:<15} "
                f"{str(env_result.prepared_time):<30} "
                f"{str(env_result.deployed_time):<30} "
                f"{str(env_result.deleted_time):<30} "
                f"{', '.join([x.id for x in env_result.results])}\n"
            )
        f.write("\n")

        for env_result in self._environments.values():
            f.write(f"{env_result.name}\t{env_result.information}\n")
        f.write("\n")

        for test_result in self._test_results.values():
            f.write(f"{test_result.id:<20} {test_result.name:<30} {test_result}\n")
        f.write("\n")
