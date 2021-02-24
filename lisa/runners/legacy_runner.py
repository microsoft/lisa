import glob
import itertools
import os
import re
import shutil
import time
from functools import partial
from pathlib import Path
from typing import Any, Dict, Iterable, List, Pattern

from retry import retry  # type: ignore

from lisa import schema
from lisa.node import Node
from lisa.runner import BaseRunner
from lisa.testsuite import TestCaseMetadata, TestCaseRuntimeData, TestResult, TestStatus
from lisa.tools import Git
from lisa.util import InitializableMixin, LisaException, constants, run_in_threads
from lisa.util.logger import Logger, create_file_handler, get_logger, remove_handler
from lisa.util.process import Process

# TestResults\2021-02-07-18-04-09-OX53\LISAv2-Test-OX53.log
ROOT_LOG_FILE_PATTERN = re.compile(
    r"TestResults[\\/][\d-]{20}.{4}[\\/]LISAv2-Test-.{4}\.log$"
)

# TestResults\2021-02-07-18-04-09-OX53\LISAv2-Test-OX53.log
# TestResults\2021-02-07-18-04-36-OX53-1\LISAv2-Test-OX53-1.log
LOG_FILE_PATTERN = re.compile(
    r"TestResults[\\/][\d-]{20}[^\\/]+[\\/]LISAv2-Test-.+\.log$"
)

# TestResults\2021-02-08-08-31-24-AI57\VERIFY-LINUX-CONFIGURATION\LISAv2-Test-AI57.log
# TestResults\2021-02-07-18-04-36-OX53-1\VERIFY-DEPLOYMENT-PROVISION\LISAv2-Test-OX53-1.log
CASE_LOG_FILE_PATTERN = re.compile(
    r"TestResults[\\/][\d-]{20}.+[\\/].+[\\/]LISAv2-Test-.+\.log$"
)


class LegacyRunner(BaseRunner):
    """
    Runner of LISAv2. It's old version of current LISA(v3).
    To avoid confusing on V1, V2, V3... So use Legacy in name.
    """

    @classmethod
    def type_name(cls) -> str:
        return constants.TESTCASE_TYPE_LEGACY

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.exit_code: int = 0
        # leverage Node logic to run local processes.
        self._local = Node.create(
            index=-1,
            node_type=constants.ENVIRONMENTS_NODES_LOCAL,
            capability=schema.NodeSpace(),
            logger_name="LISAv2",
        )
        self.canceled = False

    def _run(self, id_: str) -> List[TestResult]:
        self._log_handler = create_file_handler(self._log_file_name, self._local.log)
        lisav2_configurations: List[schema.LegacyTestCase] = self._runbook.testcase

        # clone code
        for index, config in enumerate(lisav2_configurations):
            git = self._local.tools[Git]
            git.clone(
                config.repo,
                cwd=self._working_folder,
                branch=config.branch,
                dir_name=self._get_dir_name(id_, index),
            )

        # start run for each configuration
        raw_results: List[List[TestResult]] = run_in_threads(
            [
                partial(self._start_sub_test, self._get_dir_name(id_, index), config)
                for index, config in enumerate(lisav2_configurations)
            ],
            completed_callback=self._completed_callback,
        )

        test_results = list(itertools.chain(*raw_results))

        self._log.debug("legacy runner exited")
        return test_results

    def close(self) -> None:
        super().close()
        assert self._log_handler
        remove_handler(
            self._log_handler,
            self._local.log,
        )

    def _completed_callback(self, future: Any) -> None:
        """
        exit sub tests, once received cancellation message from executor.
        """
        # future is False, if it's called explictly by run_in_threads.
        if not future or future.cancelled() or future.exception():
            self._log.debug(f"received cancel notification on {future}")
            self.canceled = True

    def _start_sub_test(
        self, id_: str, configuration: schema.LegacyTestCase
    ) -> List[TestResult]:
        """
        entry point of each LISAv2 process.
        """
        # start LISAv2 process
        code_path = self._working_folder / id_
        process = self._local.execute_async(
            f"powershell {code_path}\\{configuration.command}",
            cwd=code_path,
            no_info_log=True,
            no_error_log=True,
        )

        # track test progress
        log = get_logger(id_=id_, parent=self._log)
        try:
            results = _track_progress(
                process=process, working_dir=code_path, log=log, runner=self, id_=id_
            )
        finally:
            if process.is_running():
                log.debug("killing LISAv2 process")
                process.kill()
        return results

    def _get_dir_name(self, id_: str, index: int) -> str:
        return f"{id_}_{index}"


class ResultStateManager:
    """
    All discover methods in LogParser are stateless, and this class merge them together.
    """

    def __init__(self, id_: str, log: Logger) -> None:
        self._results: List[TestResult] = []
        self.log = log
        self.id_ = id_

    def set_states(
        self,
        all_cases: List[Dict[str, str]],
        running_cases: List[Dict[str, str]],
        completed_cases: List[Dict[str, str]],
    ) -> None:
        self._extend_all_results(all_cases=all_cases)

        self._set_running_results(running_cases=running_cases)

        self._set_completed_results(completed_cases=completed_cases)

    @property
    def results(self) -> List[TestResult]:
        return self._results

    def _extend_all_results(self, all_cases: List[Dict[str, str]]) -> None:
        """
        The test case list is in single file, and the order is stable.
        So just extend the list, if more test cases found.
        """
        if len(self._results) < len(all_cases):
            for i in range(len(self._results), len(all_cases)):
                case_metadata = TestCaseMetadata("")
                case_metadata.name = all_cases[i]["name"]
                case_metadata.full_name = f"legacy.{case_metadata.name}"
                case_runtime_data = TestCaseRuntimeData(case_metadata)
                # create result message for new cases
                result = TestResult(
                    id_=f"{self.id_}_{len(self._results)}",
                    runtime_data=case_runtime_data,
                )
                self._results.append(result)

    def _set_running_results(self, running_cases: List[Dict[str, str]]) -> None:
        # copy a list to find changed cases
        new_running_cases = running_cases[:]
        not_matched_results = [
            x for x in self._results if x.status != TestStatus.NOTRUN
        ]
        # remove existing running case, left new running casesl
        for running_case in running_cases:
            for result in not_matched_results:
                if self._is_matched_infomation(result, running_case):
                    new_running_cases.remove(running_case)
                    not_matched_results.remove(result)
                    break
        try:
            assert (
                not not_matched_results
            ), f"not matched should be empty, but {not_matched_results}"
        except AssertionError as identifier:
            # provide more information for troubleshooting
            self.log.info(f"parsed running cases: {[running_cases]}")
            raise identifier

        # set new running case information
        notrun_results = [x for x in self._results if x.status == TestStatus.NOTRUN]
        for running_case in new_running_cases:
            name = running_case["name"]
            for result in notrun_results:
                if result.name == name:
                    # initialize new running case
                    running_case["status"] = str(TestStatus.RUNNING.name)
                    self._set_result(result, information=running_case)
                    # every not run just match one
                    notrun_results.remove(result)
                    break

    def _set_completed_results(self, completed_cases: List[Dict[str, str]]) -> None:

        new_completed_cases = completed_cases[:]
        not_matched_results = [
            x
            for x in self._results
            if x.status not in [TestStatus.NOTRUN, TestStatus.RUNNING]
        ]
        # remove existing completed case
        for completed_case in completed_cases:
            for result in not_matched_results:
                if self._is_matched_infomation(result, completed_case):
                    new_completed_cases.remove(completed_case)
                    not_matched_results.remove(result)
                    break
        try:
            assert (
                not not_matched_results
            ), f"not matched should be empty, but {not_matched_results}"
        except AssertionError as identifier:
            # provide more information for troubleshooting
            self.log.info(f"parsed completed cases: {[completed_cases]}")
            raise identifier

        # set new completed case information
        running_results = [x for x in self._results if x.status == TestStatus.RUNNING]
        for completed_case in new_completed_cases:
            for result in running_results:
                if self._is_matched_infomation(result, completed_case):
                    # complete a case
                    self._set_result(
                        result,
                        information=completed_case,
                    )
                    # every running result just match one
                    running_results.remove(result)
                    break

    def _get_name(self, name: str) -> str:
        return f"legacy.{name}"

    def _get_case_key(
        self, name: str, image: str, location: str, vmsize: str = ""
    ) -> str:
        # vmsize is nullable due to lack of information on sequence run
        return f"{name}|{image}|{location}|{vmsize}"

    def _is_matched_infomation(
        self, result: TestResult, information: Dict[str, str]
    ) -> bool:
        if result.name != information["name"]:
            # case name doesn't match
            return False

        if "image" not in result.information or "location" not in result.information:
            # it's not a case that have full information
            return False

        # In sequence run, there is no vm size log line.
        # So, when image and location is found, the case can be added.
        result_vmsize = result.information.get("vmsize", "")
        information_vmsize = information.get("vmsize", "")
        if not result_vmsize or not information_vmsize:
            result_vmsize = ""
            information_vmsize = ""

        result_key = self._get_case_key(
            result.name,
            result.information["image"],
            result.information["location"],
            result_vmsize,
        )
        information_key = self._get_case_key(
            information["name"],
            information["image"],
            information["location"],
            information_vmsize,
        )

        return result_key == information_key

    def _set_result(
        self,
        result: TestResult,
        information: Dict[str, str],
    ) -> None:
        """
        Fill information to test result
        """
        information = information.copy()
        parsed_name = information.pop("name")
        assert (
            result.name == parsed_name
        ), f"result name '{result.name}' doesn't match parsed name '{parsed_name}'"

        raw_status = information.pop("status")
        if raw_status in ["FAIL", "ABORT"]:
            status: TestStatus = TestStatus.FAILED
        elif raw_status == "PASS":
            status = TestStatus.PASSED
        elif raw_status == "RUNNING":
            status = TestStatus.RUNNING
        elif raw_status == "SKIP":
            status = TestStatus.SKIPPED
        else:
            raise LisaException(f"unknown test status: {raw_status}")
        message = information.pop("message", "")
        result.information.update(information)
        if result.status != status:
            image = result.information.get("image", "")
            location = result.information.get("location", "")
            vmsize = result.information.get("vmsize", "")
            self.log.info(
                f"[{result.name}] status changed "
                f"from {result.status.name} to {status.name}, "
                f"image: '{image}', location: '{location}', vmsize: '{vmsize}'"
            )
        result.set_status(status, message)


class LogParser(InitializableMixin):

    # Some logs have multiple lines, so use header to match them.
    # it DOES NOT match latest line to prevent partial logged.
    # 02/07/2021 10:04:34 : [INFO ] OX53-4 is still running
    LOG_LINE = re.compile(
        # log line
        r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2} : \[.+\] (?P<message>[\w\W]*?)"
        # next log header, doesn't match latest line of log
        r"(?=\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2} : \[.+\] )",
        re.MULTILINE,
    )

    # Collected test: VERIFY-DEPLOYMENT-PROVISION from D:\code\...
    CASE_COLLECTED = re.compile(r"Collected test: (?P<name>.+) from ")

    # 4 Test Cases have been selected or expanded to be run in this LISAv2
    #  execution, other test cases may have been skipped due to test case native
    #  SetupConfig conflicts with current Run-LISAv2 parameters
    CASE_EXPANEDED = re.compile(
        r"(?P<count>\d+) Test Cases have been selected or "
        r"expanded to be run in this LISAv2 execution,"
    )

    # (1/1) testing started: VERIFY-DEPLOYMENT-PROVISION
    CASE_RUNNING = re.compile(r"\(\d+/\d+\) testing started: (?P<name>.*)")
    # find image and location information when case is running
    # SetupConfig: { ARMImageName: Canonical 0001-com-ubuntu-server-focal 20_04-lts
    #  20.04.202102010, TestLocation: westus2 }
    CASE_IMAGE_LOCATION = re.compile(
        r"SetupConfig: { ARMImageName: (?P<image>.+), TestLocation: (?P<location>.+) }"
    )
    # Test Location 'westus2' has VM Size 'Standard_DS1_v2' enabled and has enough
    #  quota for 'VERIFY-LINUX-CONFIGURATION' deployment
    CASE_VMSIZE = re.compile(
        r"Test Location '(?P<location>.+)' has VM Size '(?P<vmsize>.+)' enabled and "
        r"has enough quota for '(?P<name>.+)' deployment"
    )

    # SQLQuery:  INSERT INTO LISATestTelemetry
    #  (DateTimeUTC,TestPlatform,TestLocation,TestCategory,TestArea,TestName,TestResult,
    #  ExecutionTag,GuestDistro,KernelVersion,HardwarePlatform,LISVersion,HostVersion,
    #  VMSize,VMGeneration,ARMImage,OsVHD,LogFile,BuildURL,TestPassID,FailureReason,
    #  TestResultDetails) VALUES ('2021-2-7 8:44:44','Azure','westus2','Functional',
    #  'CORE','VERIFY-DEPLOYMENT-PROVISION','PASS','','Ubuntu 20.04.2 LTS (Focal Fossa)'
    #  ,'5.4.0-1039-azure','x86_64','NA','18362-10.0-3-0.3216','Standard_DS1_v2','',
    #  'Canonical 0001-com-ubuntu-server-focal 20_04-lts 20.04.202102010','',
    #  'https://eosgfileshare.blob.core.windows.net/lisav2logs/2021-2-7/VERIFY-
    #  DEPLOYMENT-PROVISION-637483130841316711.zip','','','','FirstBoot : PASS ;
    # FirstBoot : Call Trace Verification : PASS ;
    # Reboot : PASS ;
    # Reboot : Call Trace Verification : PASS ;
    # Networking: Synthetic;
    # ')
    CASE_COMPLETED = re.compile(
        r"SQLQuery\:  INSERT INTO LISATestTelemetry \(.*\) "
        r"VALUES \('.*?','.*?','(?P<location>.*?)','.*?','.*?','(?P<name>.*?)',"
        r"'(?P<status>.*?)','.*?','(?P<os>.*?)','(?P<kernel_version>.*?)','.*?','.*?',"
        r"'(?P<host_version>.*?)','(?P<vmsize>.*?)','.*?','(?P<image>.*?)','.*?',"
        r"'(?P<log_path>.*?)','.*?','.*?','.*?','(?P<message>[\w\W]*?)'\)"
    )

    def __init__(self, runner_log_path: str, log: Logger) -> None:
        self._runner_log_path = runner_log_path
        self._log = log

    def discover_cases(self) -> List[Dict[str, str]]:
        """
        Discover all cases names. The name may be duplicate by test matrix.
        """
        all_cases: List[Dict[str, str]] = []
        count: int = 1
        for line in self._line_iter():
            case_match = self.CASE_COLLECTED.match(line)
            if case_match:
                case = {"name": case_match["name"]}
                all_cases.append(case)
            count_match = self.CASE_EXPANEDED.match(line)
            if count_match:
                count = int(count_match["count"])
                break
        if all_cases:
            # expand for test matrix
            all_cases = all_cases * int(count / len(all_cases))
        return all_cases

    def discover_running_cases(self) -> List[Dict[str, str]]:
        cases: List[Dict[str, str]] = []
        for line in self._line_iter():
            case_match = self.CASE_RUNNING.match(line)
            if case_match:
                name = case_match["name"]
                current_case: Dict[str, str] = case_match.groupdict()
            image_match = self.CASE_IMAGE_LOCATION.match(line)
            if image_match:
                location = image_match["location"]
                current_case.update(image_match.groupdict())
                # In sequence run, there is no vm size log line.
                # So, when image and location is found, the case can be added.
                cases.append(current_case)
            vmsize_match = self.CASE_VMSIZE.match(line)
            if vmsize_match:
                temp_name = vmsize_match["name"]
                temp_location = vmsize_match["location"]
                assert name == temp_name, (
                    f"cannot match location between logs. "
                    f"current case is: '{name}', "
                    f"name in vmsize is: '{temp_name}'. {line}"
                )
                assert location == temp_location, (
                    f"cannot match location between logs. "
                    f"setup config is: '{location}', "
                    f"location in vmsize is: '{temp_location}'. {line}"
                )
                current_case.update(vmsize_match.groupdict())
        return cases

    def discover_completed_cases(self) -> List[Dict[str, str]]:
        cases: List[Dict[str, str]] = []
        for line in self._line_iter():
            case_match = self.CASE_COMPLETED.match(line)
            if case_match:
                current_case = case_match.groupdict()
                cases.append(current_case)
        return cases

    @retry(tries=10, jitter=1)  # type: ignore
    def _read_log(self) -> str:
        """
        V2 opens log file frequently to write content, copying may be failed due to
        conflict. So retry to make it more stable.
        """
        temp_file_name = f"{self._runner_log_path}_temp.log"
        shutil.copy2(self._runner_log_path, temp_file_name)
        with open(temp_file_name, "r") as file:
            content = file.read()
        os.remove(temp_file_name)
        return content

    def _line_iter(self) -> Iterable[str]:
        content = self._read_log()

        iterator = self.LOG_LINE.finditer(content)
        for match in iterator:
            yield match["message"]


def _find_matched_files(
    working_dir: Path, pattern: Pattern[str], log: Logger
) -> List[LogParser]:
    """
    return file parsers for matched files
    """
    log_file_pattern = str(working_dir / "TestResults/**/*.log")
    results: List[LogParser] = []
    for file_path in glob.glob(log_file_pattern, recursive=True):
        matched = pattern.findall(file_path)
        if matched:
            results.append(LogParser(file_path, log))
    return results


def _track_progress(
    process: Process, working_dir: Path, log: Logger, runner: LegacyRunner, id_: str
) -> List[TestResult]:
    # discovered all cases
    all_cases: List[Dict[str, str]] = []
    while process.is_running() and not runner.canceled:
        root_parsers = _find_matched_files(
            working_dir=working_dir, pattern=ROOT_LOG_FILE_PATTERN, log=log
        )
        assert len(root_parsers) <= 1, "found multiple root parsers. It's unexpected."
        if root_parsers:
            root_parser = root_parsers[0]
            all_cases = root_parser.discover_cases()
            if all_cases:
                log.info(f"found cases: {[x['name'] for x in all_cases]}")
                break
        time.sleep(5)

    case_states = ResultStateManager(id_=id_, log=log)
    # loop to check running and completed results
    while process.is_running() and not runner.canceled:
        running_cases: List[Dict[str, str]] = []
        completed_cases: List[Dict[str, str]] = []
        # discover running cases
        running_parsers = _find_matched_files(
            working_dir=working_dir, pattern=LOG_FILE_PATTERN, log=log
        )
        for parser in running_parsers:
            running_cases.extend(parser.discover_running_cases())

        # discover completed cases
        completed_parsers = _find_matched_files(
            working_dir=working_dir, pattern=CASE_LOG_FILE_PATTERN, log=log
        )
        for parser in completed_parsers:
            completed_cases.extend(parser.discover_completed_cases())

        # merge all dict to result status
        case_states.set_states(
            all_cases=all_cases,
            running_cases=running_cases,
            completed_cases=completed_cases,
        )
        time.sleep(5)

    return case_states.results
