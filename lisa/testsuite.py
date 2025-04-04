# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

import copy
import logging
import traceback
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from time import sleep
from typing import Any, Callable, Dict, List, Optional, Type, Union

from func_timeout import FunctionTimedOut, func_timeout  # type: ignore
from retry import retry

from lisa import notifier, schema, search_space
from lisa.environment import Environment, EnvironmentSpace, EnvironmentStatus
from lisa.feature import Feature
from lisa.features import SerialConsole
from lisa.messages import TestResultMessage, TestStatus, _is_completed_status
from lisa.operating_system import OperatingSystem, Windows
from lisa.util import (
    BadEnvironmentStateException,
    LisaException,
    PassedException,
    SkippedException,
    TcpConnectionException,
    constants,
    fields_to_dict,
    get_datetime_path,
    hookspec,
    is_unittest,
    plugin_manager,
    set_filtered_fields,
)
from lisa.util.logger import (
    Logger,
    add_handler,
    create_file_handler,
    get_logger,
    remove_handler,
)
from lisa.util.perf_timer import Timer, create_timer

_all_suites: Dict[str, TestSuiteMetadata] = {}
_all_cases: Dict[str, TestCaseMetadata] = {}


def _call_with_timeout(
    method: Callable[..., Any],
    timeout: int,
    test_kwargs: Dict[str, Any],
) -> None:
    try:
        # if timeout is greater than 0, then wrap the timeout method. but if
        # it's zero or negative, not wrap the timeout. The reason is the timeout
        # will raise exception, if the timeout value is greater than 7 days. So
        # not to call it, if timeout is not a positive value.
        if timeout > 0:
            func_timeout(
                timeout=timeout,
                func=method,
                kwargs=test_kwargs,
            )
        else:
            method(**test_kwargs)
    except FunctionTimedOut:
        # FunctionTimedOut is a special exception. If it's not captured
        # explicitly, it will make the whole program exit.
        raise TimeoutError(f"time out in {timeout} seconds.")


@dataclass
class TestResult:
    # id is used to identify the unique test result
    id_: str
    runtime_data: TestCaseRuntimeData
    status: TestStatus = TestStatus.QUEUED
    elapsed: float = 0
    message: str = ""
    environment: Optional[Environment] = None
    check_results: Optional[search_space.ResultReason] = None
    information: Dict[str, Any] = field(default_factory=dict)
    log_file: str = ""
    stacktrace: Optional[str] = None
    retried_times: int = 0
    _log_file_handler: Optional[logging.FileHandler] = None
    _case_log_path: Optional[Path] = None

    def __post_init__(self, *args: Any, **kwargs: Any) -> None:
        self._send_result_message()
        self._timer: Timer

        self._environment_information: Dict[str, Any] = {}
        # parent_log = get_logger("suite", self.runtime_data.metadata.suite.name)
        self.log = get_logger("case", self.name)

    @property
    def is_queued(self) -> bool:
        return self.status == TestStatus.QUEUED

    @property
    def can_run(self) -> bool:
        return self.status in [TestStatus.QUEUED, TestStatus.ASSIGNED]

    @property
    def is_completed(self) -> bool:
        return _is_completed_status(self.status)

    @property
    def name(self) -> str:
        return self.runtime_data.metadata.name

    @property
    def environment_information(self) -> Dict[str, Any]:
        # It's used by subtests.
        if not self._environment_information and self.environment:
            self._environment_information = self.environment.get_information(
                force_run=False
            )

        return self._environment_information

    @hookspec
    def update_test_result_message(self, message: TestResultMessage) -> None:
        ...

    def handle_exception(
        self, exception: Exception, log: Logger, phase: str = ""
    ) -> None:
        self.stacktrace = traceback.format_exc()

        if phase:
            phase = f"{phase} "
        if isinstance(exception, SkippedException):
            log.info(f"case skipped: {exception}")
            log.debug("case skipped", exc_info=exception)
            # case is skipped dynamically
            self.set_status(
                TestStatus.SKIPPED,
                f"{phase}skipped: {exception}",
            )
        elif isinstance(exception, PassedException):
            log.info(f"case passed with warning: {exception}")
            log.debug("case passed with warning", exc_info=exception)
            # case can be passed with a warning.
            self.set_status(
                TestStatus.PASSED,
                f"{phase}warning: {exception}",
            )
        elif isinstance(exception, BadEnvironmentStateException) or isinstance(
            exception, TcpConnectionException
        ):
            log.error("case failed with environment in bad state", exc_info=exception)
            self.set_status(TestStatus.FAILED, f"{phase}{exception}")

            assert self.environment
            self.environment.status = EnvironmentStatus.Bad
        else:
            if self.runtime_data.ignore_failure:
                log.info(
                    f"case failed and ignored. "
                    f"{exception.__class__.__name__}: {exception}"
                )
                self.set_status(TestStatus.ATTEMPTED, f"{phase}{exception}")
            else:
                log.error("case failed", exc_info=exception)
                self.set_status(
                    TestStatus.FAILED,
                    f"{phase}failed. {exception.__class__.__name__}: {exception}",
                )

    def set_status(
        self, new_status: TestStatus, message: Union[str, List[str]]
    ) -> None:
        send_result = False
        if message:
            if isinstance(message, str):
                message = [message]
            if self.message:
                message.insert(0, self.message)
            self.message = "\n".join(message)
            send_result = True
        if self.status != new_status:
            self.status = new_status
            if new_status == TestStatus.RUNNING:
                self._timer = create_timer()
            send_result = True
        if send_result:
            self._send_result_message(self.stacktrace)

    def check_environment(
        self,
        environment: Environment,
        # The environment platform may not be associated to the environment at
        # early stage, so pass it in to validate.
        environment_platform_type: str = "",
        save_reason: bool = False,
    ) -> bool:
        requirement = self.runtime_data.metadata.requirement
        assert requirement.environment

        check_result = search_space.ResultReason()
        if environment_platform_type:
            check_result = self.check_platform(environment_platform_type)

        if check_result.result:
            check_result = requirement.environment.check(environment.capability)

        if (
            check_result.result
            and requirement.os_type
            and environment.status == EnvironmentStatus.Connected
        ):
            for node in environment.nodes.list():
                # the UT has no OS initialized, skip the check
                if not hasattr(node, "os"):
                    continue
                # use __mro__ to match any super types.
                # for example, Ubuntu satisfies Linux
                node_os_capability = search_space.SetSpace[Type[OperatingSystem]](
                    is_allow_set=True, items=type(node.os).__mro__
                )
                os_result = requirement.os_type.check(node_os_capability)
                # If one of OS mismatches, mark the test case is skipped. It
                # assumes no more env can meet the requirements, instead of
                # checking the rest envs one by one. The reason is this checking
                # is a dynamic checking, and it needs to be checked in each
                # deployed environment. It may cause to deploy a lot of
                # environment for checking. In another hand, the OS should be
                # the same for all environments in the same lisa runner. So it's
                # safe to skip a test case on first os mismatched.
                if not os_result.result:
                    raise SkippedException(f"OS type mismatch: {os_result.reasons}")
        if save_reason:
            if self.check_results:
                self.check_results.merge(check_result)
            else:
                self.check_results = check_result
        return check_result.result

    def get_elapsed(self) -> float:
        if not hasattr(self, "_timer"):
            return 0.0

        return self._timer.elapsed(False)

    def check_platform(
        self, environment_platform_type: str
    ) -> search_space.ResultReason:
        result = search_space.ResultReason()

        assert environment_platform_type, "platform type is not defined"
        environment_platform_type_set = search_space.SetSpace[str](
            is_allow_set=True, items=[environment_platform_type]
        )
        # only check platform, when it's defined.
        if (
            not self.runtime_data.requirement
            or not self.runtime_data.requirement.platform_type
            or len(self.runtime_data.requirement.platform_type.items) == 0
        ):
            return result

        test_supported_platforms = self.runtime_data.requirement.platform_type

        result = environment_platform_type_set.check(test_supported_platforms)

        return result

    def subscribe_log(self, log: Logger) -> None:
        add_handler(self._get_log_file_handler(), log)

    def unsubscribe_log(self, log: Logger) -> None:
        remove_handler(self._get_log_file_handler(), log)

    def get_case_log_path(self) -> Path:
        if not self._case_log_path:
            self._case_log_path = self.__create_case_log_path()
        return self._case_log_path

    def _get_log_file_handler(self) -> logging.FileHandler:
        if not self._log_file_handler:
            case_log_path = self.get_case_log_path()
            case_log_file = case_log_path / f"{case_log_path.name}.log"
            self._log_file_handler = create_file_handler(case_log_file, self.log)
            self.log_file = case_log_file.relative_to(
                constants.RUN_LOCAL_LOG_PATH
            ).as_posix()
        return self._log_file_handler

    def close_log_file_handler(self) -> None:
        if self._log_file_handler:
            remove_handler(self._log_file_handler, self.log)
            self._log_file_handler.close()
            self._log_file_handler = None

    def capture_serial_console_log(self) -> None:
        if not self.environment:
            raise LisaException("Environment is not set for saving environment logs")
        nodes = self.environment.nodes
        for node in nodes.list():
            if hasattr(node, "features") and node.features.is_supported(SerialConsole):
                serial_console = node.features[SerialConsole]
                log_dir = self.get_case_log_path() / Path(f"serial_console_{node.name}")
                log_dir.mkdir(parents=True)
                serial_console.get_console_log(log_dir, force_run=True)

    def _send_result_message(self, stacktrace: Optional[str] = None) -> None:
        self.elapsed = self.get_elapsed()

        fields = ["status", "elapsed", "id_", "log_file"]
        result_message = TestResultMessage()
        set_filtered_fields(self, result_message, fields=fields)

        metadata_fields = [
            "area",
            "category",
            "tags",
            "description",
            "priority",
            "owner",
        ]
        metadata_information = fields_to_dict(
            src=self.runtime_data.metadata, fields=metadata_fields
        )
        self.information.update(metadata_information)

        # get information of default node, and send to notifier.
        if self.environment:
            # force refresh information, when test result status is changed. The
            # refreshed information is not used so far. But in case it's needed
            # in future, keep it up to date.
            self._environment_information = self.environment.get_information()
            self.information.update(self._environment_information)

            self.information["environment"] = self.environment.name
            # if no nodes and case skipped, it means no environment deployed.
            if (
                result_message.status == TestResult.status.SKIPPED
                and len(self.environment.nodes) == 0
            ):
                vm_size = self.information.get("vmsize", None)
                # if vmsize passed from runbook, we override it.
                if vm_size and len(vm_size.split(",")) > 1:
                    self.information["vmsize"] = "NotAssigned"
        result_message.information.update(self.information)
        result_message.message = self.message[0:2048] if self.message else ""
        result_message.name = self.runtime_data.metadata.name
        result_message.full_name = self.runtime_data.metadata.full_name
        result_message.suite_name = self.runtime_data.metadata.suite.name
        result_message.suite_full_name = self.runtime_data.metadata.suite.full_name
        result_message.stacktrace = stacktrace

        # some extensions may need to update or fill information.
        plugin_manager.hook.update_test_result_message(message=result_message)

        notifier.notify(result_message)

    @retry(exceptions=FileExistsError, tries=30, delay=0.1)
    def __create_case_log_path(self) -> Path:
        case_name = self.runtime_data.name
        while True:
            path = (
                constants.RUN_LOCAL_LOG_PATH
                / "tests"
                / f"{get_datetime_path()}-{case_name}"
            )
            if not path.exists():
                break
            sleep(0.1)
        # avoid to create folder for UT
        if not is_unittest():
            path.mkdir(parents=True)
        return path


@dataclass
class TestCaseRequirement:
    environment: Optional[EnvironmentSpace] = None
    environment_status: EnvironmentStatus = EnvironmentStatus.Connected
    platform_type: Optional[search_space.SetSpace[str]] = None
    os_type: Optional[search_space.SetSpace[Type[OperatingSystem]]] = None


def _create_test_case_requirement(
    node: schema.NodeSpace,
    supported_platform_type: Optional[List[str]] = None,
    unsupported_platform_type: Optional[List[str]] = None,
    supported_os: Optional[List[Type[OperatingSystem]]] = None,
    unsupported_os: Optional[List[Type[OperatingSystem]]] = None,
    supported_features: Optional[
        List[Union[Type[Feature], schema.FeatureSettings, str]]
    ] = None,
    unsupported_features: Optional[
        List[Union[Type[Feature], schema.FeatureSettings, str]]
    ] = None,
    environment_status: EnvironmentStatus = EnvironmentStatus.Connected,
) -> TestCaseRequirement:
    if supported_features:
        node.features = search_space.SetSpace[schema.FeatureSettings](
            is_allow_set=True,
            items=[Feature.get_feature_settings(x) for x in supported_features],
        )
    if unsupported_features:
        node.excluded_features = search_space.SetSpace[schema.FeatureSettings](
            is_allow_set=False,
            items=[Feature.get_feature_settings(x) for x in unsupported_features],
        )
    nodes: List[schema.NodeSpace] = [node]

    platform_types = search_space.create_set_space(
        supported_platform_type, unsupported_platform_type, "platform type"
    )
    # Most test cases are applied to Linux, exclude Windows by default.
    if unsupported_os is None and supported_os is None:
        unsupported_os = [Windows]
    os = search_space.create_set_space(supported_os, unsupported_os, "operating system")

    return TestCaseRequirement(
        environment=EnvironmentSpace(nodes=nodes),
        platform_type=platform_types,
        os_type=os,
        environment_status=environment_status,
    )


def node_requirement(
    node: schema.NodeSpace,
    supported_platform_type: Optional[List[str]] = None,
    unsupported_platform_type: Optional[List[str]] = None,
    supported_os: Optional[List[Type[OperatingSystem]]] = None,
    unsupported_os: Optional[List[Type[OperatingSystem]]] = None,
    supported_features: Optional[
        List[Union[Type[Feature], schema.FeatureSettings, str]]
    ] = None,
    unsupported_features: Optional[
        List[Union[Type[Feature], schema.FeatureSettings, str]]
    ] = None,
    environment_status: EnvironmentStatus = EnvironmentStatus.Connected,
) -> TestCaseRequirement:
    return _create_test_case_requirement(
        node,
        supported_platform_type,
        unsupported_platform_type,
        supported_os,
        unsupported_os,
        supported_features,
        unsupported_features,
        environment_status,
    )


def simple_requirement(
    min_count: int = 1,
    min_core_count: int = 1,
    min_gpu_count: int = 0,
    min_memory_mb: Optional[int] = None,
    min_nic_count: Optional[int] = None,
    min_data_disk_count: Optional[int] = None,
    disk: Optional[schema.DiskOptionSettings] = None,
    network_interface: Optional[schema.NetworkInterfaceOptionSettings] = None,
    supported_platform_type: Optional[List[str]] = None,
    unsupported_platform_type: Optional[List[str]] = None,
    supported_os: Optional[List[Type[OperatingSystem]]] = None,
    unsupported_os: Optional[List[Type[OperatingSystem]]] = None,
    supported_features: Optional[
        List[Union[Type[Feature], schema.FeatureSettings, str]]
    ] = None,
    unsupported_features: Optional[
        List[Union[Type[Feature], schema.FeatureSettings, str]]
    ] = None,
    environment_status: EnvironmentStatus = EnvironmentStatus.Connected,
) -> TestCaseRequirement:
    """
    define a simple requirement to support most test cases.
    """
    node = schema.NodeSpace()
    node.node_count = search_space.IntRange(min=min_count)
    node.core_count = search_space.IntRange(min=min_core_count)
    node.gpu_count = search_space.IntRange(min=min_gpu_count)
    if min_memory_mb:
        node.memory_mb = search_space.IntRange(min=min_memory_mb)

    if min_data_disk_count or disk:
        if not disk:
            disk = schema.DiskOptionSettings()
        if min_data_disk_count:
            disk.data_disk_count = search_space.IntRange(min=min_data_disk_count)
        node.disk = disk

    if min_nic_count or network_interface:
        if not network_interface:
            network_interface = schema.NetworkInterfaceOptionSettings()
        if min_nic_count:
            network_interface.nic_count = search_space.IntRange(min=min_nic_count)
        node.network_interface = network_interface

    return _create_test_case_requirement(
        node,
        supported_platform_type,
        unsupported_platform_type,
        supported_os,
        unsupported_os,
        supported_features,
        unsupported_features,
        environment_status,
    )


DEFAULT_REQUIREMENT = simple_requirement()


class TestSuiteMetadata:
    def __init__(
        self,
        area: str,
        category: str,
        description: str,
        tags: Optional[List[str]] = None,
        name: str = "",
        requirement: TestCaseRequirement = DEFAULT_REQUIREMENT,
        owner: str = "Microsoft",
        full_name: str = "",
    ) -> None:
        self.name = name
        self.full_name = full_name
        self.cases: List[TestCaseMetadata] = []
        self.tags: List[str] = tags if tags else []

        self.area = area
        self.category = category
        if tags:
            self.tags = tags
        else:
            self.tags = []
        self.description = description
        self.requirement = requirement
        self.owner = owner

    def __call__(self, test_class: Type[TestSuite]) -> Callable[..., object]:
        self.test_class = test_class
        if not self.name:
            self.name = test_class.__name__
        self.full_name = test_class.__qualname__
        _add_suite_metadata(self)

        @wraps(self.test_class)
        def wrapper(
            test_class: Type[TestSuite],
            metadata: TestSuiteMetadata,
        ) -> TestSuite:
            return test_class(metadata)

        return wrapper


class TestCaseMetadata:
    def __init__(
        self,
        description: str,
        priority: int = 2,
        timeout: int = 3600,
        use_new_environment: bool = False,
        owner: str = "",
        requirement: Optional[TestCaseRequirement] = None,
    ) -> None:
        self.suite: TestSuiteMetadata

        self.priority = priority
        self.description = description
        self.timeout = timeout
        self.use_new_environment = use_new_environment
        if requirement:
            self.requirement = requirement

        self._owner = owner

    def __getattr__(self, key: str) -> Any:
        # return attributes of test suite, if it's not redefined in case level
        assert self.suite, "suite is not set before use metadata"
        return getattr(self.suite, key)

    def __call__(self, func: Callable[..., None]) -> Callable[..., None]:
        self.name = func.__name__
        self.full_name = func.__qualname__
        self.qualname = func.__qualname__

        self._func = func
        _add_case_metadata(self)

        @wraps(self._func)
        def wrapper(*args: Any, **kwargs: Any) -> None:
            parameters: Dict[str, Any] = {}
            for name in kwargs.keys():
                if name in func.__annotations__:
                    parameters[name] = kwargs[name]
            func(*args, **parameters)

        return wrapper

    @property
    def owner(self) -> str:
        if self._owner:
            return self._owner

        return self.suite.owner


class TestCaseRuntimeData:
    def __init__(self, metadata: TestCaseMetadata):
        self.metadata = metadata

        # all runtime setting fields
        self.select_action: str = ""
        self.times: int = 1
        self.retry: int = 0
        self.timeout: int = metadata.timeout
        self.use_new_environment: bool = metadata.use_new_environment
        self.ignore_failure: bool = False
        self.environment_name: str = ""

    def __getattr__(self, key: str) -> Any:
        # return attributes of metadata for convenient
        assert self.metadata
        return getattr(self.metadata, key)

    def __repr__(self) -> str:
        return (
            f"name: {self.metadata.name}, "
            f"action: {self.select_action}, "
            f"times: {self.times}, retry: {self.retry}, "
            f"new_env: {self.use_new_environment}, "
            f"ignore_failure: {self.ignore_failure}, "
            f"env_name: {self.environment_name}"
        )

    def clone(self) -> TestCaseRuntimeData:
        cloned = TestCaseRuntimeData(self.metadata)
        fields = [
            constants.TESTCASE_SELECT_ACTION,
            constants.TESTCASE_TIMES,
            constants.TESTCASE_RETRY,
            constants.TESTCASE_USE_NEW_ENVIRONMENT,
            constants.TESTCASE_IGNORE_FAILURE,
            constants.ENVIRONMENT,
        ]
        set_filtered_fields(self, cloned, fields)
        return cloned


class TestSuite:
    def __init__(
        self,
        metadata: TestSuiteMetadata,
    ) -> None:
        super().__init__()
        self._metadata = metadata
        self._should_stop = False
        self.__log = get_logger("suite", metadata.name)

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        ...

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        ...

    def start(
        self,
        environment: Environment,
        # test cases to run, must be a test method in this class.
        case_results: List[TestResult],
        # case accessible variables
        case_variables: Dict[str, Any],
    ) -> None:
        suite_error_message = ""

        # set the environment is not new, when it's used by any suite.
        environment.is_new = False
        test_kwargs = {
            "environment": environment,
            "log": self.__log,
            "node": environment.default_node,
            # copy to prevent the data is changed and effect other cases.
            "variables": copy.copy(case_variables),
        }

        is_suite_continue = True
        suite_log = self.__log
        suite_error_stacktrace = None
        if hasattr(self, "before_suite"):
            raise LisaException("before_suite is not supported. Please use before_case")
        if hasattr(self, "after_suite"):
            raise LisaException("after_suite is not supported. Please use after_case")
        #  replace to case's logger temporarily
        for case_result in case_results:
            case_result.environment = environment
            case_log = case_result.log
            case_result.subscribe_log(environment.log)
            case_log_path = case_result.get_case_log_path()

            case_part_path = self.__get_test_part_path(case_log_path)
            case_working_path = self.__get_case_working_path(case_part_path)
            case_unique_name = case_log_path.name

            case_kwargs = test_kwargs.copy()
            case_kwargs.update({"case_name": case_unique_name})
            case_kwargs.update({"log": case_log})
            case_kwargs.update({"log_path": case_log_path})
            case_kwargs.update({"working_path": case_working_path})
            case_kwargs.update({"part_path": case_part_path})
            case_kwargs.update({"result": case_result})

            case_log.info(
                f"test case '{case_result.runtime_data.full_name}' is running"
            )
            is_continue: bool = is_suite_continue
            total_timer = create_timer()
            case_result.set_status(TestStatus.RUNNING, "")

            # check for positive value just to be clearer
            case_timeout = (
                max(
                    case_result.runtime_data.timeout,
                    case_result.runtime_data.metadata.timeout,
                )
                if (
                    case_result.runtime_data.timeout
                    and case_result.runtime_data.timeout > 0
                )
                else case_result.runtime_data.metadata.timeout
            )

            if is_continue:
                is_continue = self.__before_case(
                    case_result=case_result,
                    timeout=case_timeout,
                    test_kwargs=case_kwargs,
                    log=case_log,
                )
            else:
                case_result.stacktrace = suite_error_stacktrace
                case_result.set_status(TestStatus.SKIPPED, suite_error_message)

            if is_continue:
                self.__run_case(
                    case_result=case_result,
                    timeout=case_timeout,
                    test_kwargs=case_kwargs,
                    log=case_log,
                )

            self.__after_case(
                case_result=case_result,
                timeout=case_timeout,
                test_kwargs=case_kwargs,
                log=case_log,
            )

            if case_result.status == TestStatus.FAILED:
                try:
                    case_result.capture_serial_console_log()
                except Exception as e:
                    suite_log.debug(
                        f"exception thrown during serial console log read. [{e}]"
                    )

            case_log.info(
                f"result: {case_result.status.name}, " f"elapsed: {total_timer}"
            )
            case_result.unsubscribe_log(environment.log)
            case_result.close_log_file_handler()

            if self._should_stop:
                suite_log.info("received stop message, stop run")
                break

    def stop(self) -> None:
        self._should_stop = True

    def __get_test_part_path(self, log_path: Path) -> Path:
        if is_unittest():
            return Path()

        return Path(log_path.parts[-2]) / log_path.parts[-1]

    def __get_case_working_path(self, test_part_path: Path) -> Path:
        if is_unittest():
            return Path()

        # The working path should be the same name as log_path, so it's easy to
        # associated. Unlike the log path, the working path won't be created, because
        # it's not used in most cases. So it doesn't need to be created too. The
        # test case should create it, when it's used.
        working_path = constants.RUN_LOCAL_WORKING_PATH / test_part_path
        return working_path

    def __before_case(
        self,
        case_result: TestResult,
        timeout: int,
        test_kwargs: Dict[str, Any],
        log: Logger,
    ) -> bool:
        result: bool = True

        timer = create_timer()
        try:
            _call_with_timeout(
                self.before_case,
                timeout=timeout,
                test_kwargs=test_kwargs,
            )
        except Exception as identifier:
            case_result.handle_exception(identifier, log, "before_case")
            result = False

        log.debug(f"before_case end in {timer}")
        return result

    def __after_case(
        self,
        case_result: TestResult,
        timeout: int,
        test_kwargs: Dict[str, Any],
        log: Logger,
    ) -> None:
        timer = create_timer()
        try:
            _call_with_timeout(
                self.after_case,
                timeout=timeout,
                test_kwargs=test_kwargs,
            )
        except Exception as identifier:
            # after case doesn't impact test case result.
            log.error("after_case failed", exc_info=identifier)
        log.debug(f"after_case end in {timer}")

    def __run_case(
        self,
        case_result: TestResult,
        timeout: int,
        test_kwargs: Dict[str, Any],
        log: Logger,
    ) -> None:
        timer = create_timer()
        case_name = case_result.runtime_data.name
        test_method = getattr(self, case_name)

        try:
            _call_with_timeout(
                test_method,
                timeout=timeout,
                test_kwargs=test_kwargs,
            )
            if case_result.environment is not None:
                nodes = case_result.environment.nodes
                for node in nodes.list():
                    if node.assert_kernel_error_after_test:
                        node.check_kernel_error()
            case_result.set_status(TestStatus.PASSED, "")
        except Exception as identifier:
            case_result.handle_exception(exception=identifier, log=log)
        log.debug(f"case end in {timer}")


def get_suites_metadata() -> Dict[str, TestSuiteMetadata]:
    return _all_suites


def get_cases_metadata() -> Dict[str, TestCaseMetadata]:
    return _all_cases


def _add_suite_metadata(metadata: TestSuiteMetadata) -> None:
    key = metadata.test_class.__name__
    exist_metadata = _all_suites.get(key)
    if exist_metadata is None:
        _all_suites[key] = metadata
    else:
        raise LisaException(
            f"duplicate test class name: {key}, "
            f"new: [{metadata}], exists: [{exist_metadata}]"
        )

    class_prefix = f"{key}."
    for test_case in _all_cases.values():
        if test_case.full_name.startswith(class_prefix):
            _add_case_to_suite(metadata, test_case)
    log = get_logger("init", "test")
    log.info(
        f"registered test suite '{key}' "
        f"with test cases: '{', '.join([case.name for case in metadata.cases])}'"
    )


def _add_case_metadata(metadata: TestCaseMetadata) -> None:
    qualname = metadata.qualname
    if _all_cases.get(qualname) is None:
        _all_cases[qualname] = metadata
    else:
        raise LisaException(
            f"found duplicate test class name: {qualname}. "
            "Check there is no duplicate test class name, "
            "and not import by extension twice."
        )

    # this should be None in current observation.
    # the methods are loaded prior to test class
    # in case logic is changed, so keep this logic
    #   to make two collection consistent.
    class_name = qualname.split(".")[0]
    test_suite = _all_suites.get(class_name)
    if test_suite:
        log = get_logger("init", "test")
        log.debug(f"add case '{metadata.name}' to suite '{test_suite.name}'")
        _add_case_to_suite(test_suite, metadata)


def _add_case_to_suite(
    test_suite: TestSuiteMetadata, test_case: TestCaseMetadata
) -> None:
    test_case.suite = test_suite
    test_case.full_name = f"{test_suite.name}.{test_case.name}"
    test_suite.cases.append(test_case)


plugin_manager.add_hookspecs(TestResult)
