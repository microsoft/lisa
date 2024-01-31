# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import inspect
import re
from typing import Any, Dict, List, cast

from lisa import notifier
from lisa.executable import Tool
from lisa.messages import (
    CPUPerformanceMessage,
    DiskPerformanceMessage,
    MemoryPerformanceMessage,
    create_perf_message,
)
from lisa.operating_system import Posix
from lisa.util import LisaException, find_group_in_lines, find_groups_in_lines
from lisa.util.process import ExecutableResult


class Sysbench(Tool):
    @property
    def command(self) -> str:
        return "sysbench"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("sysbench")

        return self._check_exists()

    def __run_sysbench_test(
        self,
        test_type: str,
        threads: int,
        events: int,
        time_limit: int,
        validation: bool = True,
        extra_args: str = "",
    ) -> ExecutableResult:
        validate: str = "off"
        if validation:
            validate = "on"
        args = (
            f"{test_type} run --threads={threads} --events={events}"
            f" --validate={validate} --percentile=95"
            f" --verbosity=5 --histogram=on"
            f" --time={time_limit} --debug=on {extra_args}"
        )

        result: ExecutableResult = self.run(
            args,
            expected_exit_code=0,
            expected_exit_code_failure_message="Sysbench Test failed",
        )
        return result

    def run_cpu_perf(
        self,
        test_result: Any,
    ) -> None:
        threads: int = 1
        events: int = 0
        cpu_max_prime: int = 10000
        time_limit: int = 10

        extra_args: str = f" --cpu-max-prime={cpu_max_prime}"
        perf_msg: Dict[Any, Any] = {}
        testcase_name: str = inspect.stack()[1][3]
        res = self.__run_sysbench_test(
            test_type="cpu",
            threads=threads,
            events=events,
            time_limit=time_limit,
            extra_args=extra_args,
        )
        perf_msg = self.__process_cpu_perf_result(res.stdout)
        perf_msg["benchmark"] = f"prime_{cpu_max_prime}"

        self.__send_subtest_msg(
            message_type=CPUPerformanceMessage,
            test_name=testcase_name,
            test_result=test_result,
            other_fields=perf_msg,
        )

    def run_fileio_perf(
        self,
        test_result: Any,
        total_file: int = 128,
        io_ops: Any = None,
    ) -> None:
        threads: int = 1
        events: int = 0
        time_limit: int = 10
        file_io_mode: str = "sync"
        file_fsync_all: str = "off"
        file_fsync_mode: str = "fsync"
        file_fsync_end: bool = False
        block_size_in_kb: int = 16
        file_total_size_in_gb: int = 2
        file_async_backlog: int = 128
        file_fsync_freq: int = 100
        file_merged_requests: int = 0
        file_rw_ratio: float = 1.5

        total_size = file_total_size_in_gb * 1024 * 1024 * 1024
        block_size = block_size_in_kb * 1024
        valid_io_mode: List[str] = ["sync", "async", "mmap"]
        valid_fsync_mode: List[str] = ["fsync", "fdatasync"]
        valid_test_mode: List[str] = [
            "seqwr",
            "seqrd",
            "rndrd",
            "rndwr",
            "seqrewr",
            "rndrw",
        ]

        perf_msg: Dict[Any, Any] = {}
        testcase_name: str = inspect.stack()[1][3]
        fsync_end: str = "on" if file_fsync_end else "off"

        for operation in io_ops:
            if operation not in valid_test_mode:
                raise LisaException(
                    f"Invalid io_ops: '{operation}' "
                    f"Valid values: {', '.join(valid_test_mode)}"
                )
        if not io_ops:
            # Run default for all IO test_modes
            io_ops = valid_test_mode

        if file_io_mode not in valid_io_mode:
            raise LisaException(
                f"Invalid file_io_mode. Valid file_io_mode: {valid_io_mode}"
            )

        if file_fsync_mode not in valid_fsync_mode:
            raise LisaException(
                "Invalid file_fsync_mode. Valid file_fsync_mode: {valid_fsync_mode}"
            )

        for operation in io_ops:
            extra_args: str = (
                f" --file-test-mode={operation} --file-num={total_file}"
                f" --file-block-size={block_size}"
                f" --file-total-size={total_size}"
                f" --file-io-mode={file_io_mode}"
                f" --file-async-backlog={file_async_backlog}"
                f" --file-fsync-freq={file_fsync_freq}"
                f" --file-fsync-all={file_fsync_all}"
                f" --file-fsync-end={fsync_end}"
                f" --file-fsync-mode={file_fsync_mode}"
                f" --file-merged-requests={file_merged_requests}"
                f" --file-rw-ratio={file_rw_ratio}"
            )

            prepare_cmd: str = (
                f"fileio prepare --file-total-size={total_size} --file-num={total_file}"
            )
            self.run(
                prepare_cmd,
                force_run=True,
            )

            res = self.__run_sysbench_test(
                test_type="fileio",
                threads=threads,
                events=events,
                time_limit=time_limit,
                validation=False,
                extra_args=extra_args,
            )

            cleanup_cmd: str = (
                f"fileio cleanup --file-total-size={total_size} --file-num={total_file}"
            )
            self.run(
                cleanup_cmd,
                force_run=True,
            )

            perf_msg = self.__process_fileio_perf_result(
                res.stdout,
                operation,
            )
            perf_msg["file_fsync_all"] = file_fsync_all
            perf_msg["file_fsync_end"] = file_fsync_end
            perf_msg["total_file"] = total_file
            perf_msg["file_total_size_in_gb"] = file_total_size_in_gb
            perf_msg["file_async_backlog"] = file_async_backlog
            perf_msg["file_fsync_freq"] = file_fsync_freq
            perf_msg["file_merged_requests"] = file_merged_requests
            perf_msg["file_rw_ratio"] = file_rw_ratio
            perf_msg["file_ops"] = operation
            perf_msg["file_io_mode"] = file_io_mode
            perf_msg["file_fsync_mode"] = file_fsync_mode

            self.__send_subtest_msg(
                message_type=DiskPerformanceMessage,
                test_name=testcase_name,
                test_result=test_result,
                other_fields=perf_msg,
            )

    def run_memory_perf(
        self,
        test_result: Any,
        memory_oper: Any = None,
        memory_access_mode: Any = None,
    ) -> None:
        hugetlb: str = "off"
        threads: int = 1
        events: int = 0
        time_limit: int = 10
        memory_block_size_in_kb: int = 1
        memory_total_size_in_gb: int = 32
        memory_scope: str = "global"

        valid_mem_scope: List[str] = ["global", "local"]
        valid_mem_operation: List[str] = ["read", "write", "none"]
        valid_mem_access_mode: List[str] = ["seq", "rnd"]
        perf_msg: Dict[Any, Any] = {}
        testcase_name: str = inspect.stack()[1][3]

        # Calculate block/total memory size in bytes
        block_size = memory_block_size_in_kb * 1024
        total_mem_size = memory_total_size_in_gb * 1024 * 1024 * 1024

        if not memory_oper:
            # Run with default operation if not passed
            memory_oper = valid_mem_operation

        if not memory_access_mode:
            # Run with default access mode if not passed
            memory_access_mode = valid_mem_access_mode

        if memory_scope not in valid_mem_scope:
            raise LisaException(
                f"Invalid memory_scope. Valid memory_scope: {valid_mem_scope}"
            )

        for opr in memory_oper:
            if opr not in valid_mem_operation:
                raise LisaException(
                    f"Invalid memory_oper: '{opr}'"
                    f"Valid memory_oper: {valid_mem_operation}"
                )
        for acc in memory_access_mode:
            if acc not in valid_mem_access_mode:
                raise LisaException(
                    f"Invalid memory_access_mode: {acc}"
                    f"Valid memory_access_mode: {valid_mem_access_mode}"
                )

        for op in memory_oper:
            for access_mode in memory_access_mode:
                extra_args: str = (
                    f" --memory-block-size={block_size}"
                    f" --memory-total-size={total_mem_size}"
                    f" --memory-scope={memory_scope} --memory-hugetlb={hugetlb}"
                    f" --memory-oper={op} --memory-access-mode={access_mode}"
                )

                res = self.__run_sysbench_test(
                    test_type="memory",
                    threads=threads,
                    events=events,
                    time_limit=time_limit,
                    extra_args=extra_args,
                )

                perf_msg = self.__process_memory_perf_result(res.stdout)
                perf_msg["block_size_in_kb"] = memory_block_size_in_kb
                perf_msg["memory_total_size_in_gb"] = memory_total_size_in_gb
                perf_msg["scope"] = memory_scope
                perf_msg["hugetlb_on"] = hugetlb
                perf_msg["access_mode"] = access_mode
                perf_msg["operation"] = op
                perf_msg["threads"] = threads
                perf_msg["events"] = events
                perf_msg["time_limit_sec"] = time_limit

                self.__send_subtest_msg(
                    message_type=MemoryPerformanceMessage,
                    test_name=testcase_name,
                    test_result=test_result,
                    other_fields=perf_msg,
                )

    def __process_perf_result(
        self,
        data: str,
    ) -> Dict[Any, Any]:
        # Sample Output
        # ================
        # General statistics:
        # total time:                          10.0005s
        # total number of events:              27617

        # Latency (ms):
        #         min:                                    0.33
        #         avg:                                    0.36
        #         max:                                   10.14
        #         95th percentile:                        0.43
        #         sum:                                 9988.94

        # Threads fairness:
        #     events (avg/stddev):           27617.0000/0.00
        #     execution time (avg/stddev):   9.9889/0.00

        # DEBUG: Verbose per-thread statistics:

        # DEBUG:   thread #  0: min: 0.0003s  avg: 0.0004s  max: 0.0101s  events: 27617
        # DEBUG:                  total time taken by event execution: 9.9889s

        result: Dict[Any, Any] = {}

        # Extract total time using regular expression
        total_time_pattern = re.compile(r"total time:\s+(?P<total_time>[\d.]+s)")
        match = find_group_in_lines(
            lines=data,
            pattern=total_time_pattern,
            single_line=False,
        )
        if match:
            result["total_time"] = match["total_time"]

        # Extract total number of events using regular expression
        total_events_pattern = re.compile(
            r"total number of events:\s+(?P<total_events>\d+)"
        )
        match = find_group_in_lines(
            lines=data,
            pattern=total_events_pattern,
            single_line=False,
        )
        if match:
            result["total_events"] = match["total_events"]

        # Extract latency information using regular expressions
        latency_param = "latency_ms"
        latency_metrics_pattern = re.compile(
            r"(?P<metric>min|avg|max|95th percentile|sum):\s+(?P<value>[\d.]+)\s"
        )
        matches = find_groups_in_lines(
            lines=data,
            pattern=latency_metrics_pattern,
            single_line=False,
        )
        for match in matches:
            metric = match["metric"].strip().replace(" ", "_")
            if match["metric"] == "95th percentile":
                metric = "percentile_95"
            result[f"{metric}_{latency_param}"] = float(match["value"])

        # Extract thread event avg/stddev
        thread_events_pattern = re.compile(
            r"events \(avg/stddev\):\s+(?P<event_avg>[\d.]+)/(?P<event_stddev>[\d.]+)"
        )
        thread_events = find_groups_in_lines(
            lines=data,
            pattern=thread_events_pattern,
            single_line=False,
        )
        if thread_events:
            result["events_avg"] = thread_events[0]["event_avg"]
            result["events_stddev"] = thread_events[0]["event_stddev"]

        # Extract execution time avg/stddev
        thread_exec_time_pattern = re.compile(
            r"execution time \(avg/stddev\):\s+(?P<avg>[\d.]+)/(?P<std_dev>[\d.]+)"
        )
        exec_time = find_groups_in_lines(
            lines=data,
            pattern=thread_exec_time_pattern,
            single_line=False,
        )
        if exec_time:
            result["execution_time_avg"] = exec_time[0]["avg"]
            result["execution_time_stddev"] = exec_time[0]["std_dev"]

        return result

    def __process_memory_perf_result(
        self,
        data: str,
    ) -> Dict[Any, Any]:
        result: Dict[Any, Any] = self.__process_perf_result(data)

        operations_per_second = None
        total_mib_transferred = None
        mib_per_second = None

        # Extract Total operations and operations per second
        # Sample Output
        # Total operations: 65730837 (6571036.01 per second)
        total_operations_pattern = re.compile(
            r"Total operations: (?P<operation>\d+) \((?P<per_sec>[\d.]+) per second\)"
        )
        match = find_groups_in_lines(
            lines=data,
            pattern=total_operations_pattern,
            single_line=False,
        )
        if match:
            operations_per_second = float(match[0]["per_sec"])

        # Extract Total MiB transferred and MiB per second
        # Sample Output
        # 64190.27 MiB transferred (6417.03 MiB/sec)
        total_mib_transferred_pattern = re.compile(
            r"(?P<total_mib>[\d.]+) MiB transferred \((?P<per_sec>[\d.]+) MiB/sec\)"
        )
        match = find_groups_in_lines(
            lines=data,
            pattern=total_mib_transferred_pattern,
            single_line=False,
        )
        if match:
            total_mib_transferred = float(match[0]["total_mib"])
            mib_per_second = float(match[0]["per_sec"])

        result["operations_per_second"] = operations_per_second
        result["total_mib_transferred"] = total_mib_transferred
        result["mib_per_second"] = mib_per_second

        return result

    def __process_cpu_perf_result(
        self,
        data: str,
    ) -> Dict[Any, Any]:
        result: Dict[Any, Any] = self.__process_perf_result(data)

        # Extract CPU speed using regular expression, please refer below output
        # CPU speed:
        #   events per second:  2770.19
        cpu_speed_pattern = re.compile(
            r"events per second:\s+(?P<event_per_sec>[\d.]+)"
        )
        match = find_group_in_lines(
            lines=data,
            pattern=cpu_speed_pattern,
            single_line=False,
        )
        if match:
            result["cpu_speed"] = match["event_per_sec"]

        return result

    def __process_fileio_perf_result(
        self,
        data: str,
        ops: str,
    ) -> Dict[Any, Any]:
        result: Dict[Any, Any] = self.__process_perf_result(data)

        # Sample Output
        # ================
        # File operations:
        #     reads/s:                      2717.15
        #     writes/s:                     1811.43
        #     fsyncs/s:                     45.39

        # Throughput:
        #     read, MiB/s:                  42.46
        #     written, MiB/s:               28.30

        # List of all Modes
        # "seqwr", "seqrd", "rndrd", "rndwr", "seqrewr", "rndrw",
        is_random: bool = ops.find("rnd") >= 0
        is_rdwr: bool = ops.find("rw") >= 0
        is_read_ops: bool = ops.find("rd") >= 0 or is_rdwr
        is_write_ops: bool = ops.find("wr") >= 0 or is_rdwr

        if is_write_ops:
            reg_ex_io_per_sec = re.compile(r"writes/s:\s+(?P<write_per_sec>[\d.]+)")
            io_per_sec = find_group_in_lines(
                lines=data,
                pattern=reg_ex_io_per_sec,
                single_line=False,
            )
            key = "randwrite_iops" if is_random else "write_iops"
            if io_per_sec:
                result[key] = io_per_sec["write_per_sec"]
            else:
                result[key] = 0

        if is_read_ops:
            reg_ex_io_per_sec = re.compile(r"reads/s:\s+(?P<read_per_sec>[\d.]+)")
            io_per_sec = find_group_in_lines(
                lines=data,
                pattern=reg_ex_io_per_sec,
                single_line=False,
            )
            key = "randread_iops" if is_random else "read_iops"
            if io_per_sec:
                result[key] = io_per_sec["read_per_sec"]
            else:
                result[key] = 0

        reg_ex_fsyncs_per_sec = re.compile(r"fsyncs/s:\s+(?P<fsyncs_per_sec>[\d.]+)")
        fsyncs_per_sec = find_group_in_lines(
            lines=data,
            pattern=reg_ex_fsyncs_per_sec,
            single_line=False,
        )
        if fsyncs_per_sec:
            result["fsyncs_per_sec"] = fsyncs_per_sec["fsyncs_per_sec"]
        else:
            result["fsyncs_per_sec"] = 0

        if ops == "write" or ops == "all":
            reg_ex_mib_per_sec = re.compile(
                r"written, MiB/s:\s+(?P<wr_mib_per_sec>[\d.]+)"
            )
            mib_per_sec = find_group_in_lines(
                lines=data,
                pattern=reg_ex_mib_per_sec,
                single_line=False,
            )
            if mib_per_sec:
                result["write_mib_per_sec"] = mib_per_sec["wr_mib_per_sec"]
            else:
                result["write_mib_per_sec"] = 0
        if ops == "read" or ops == "all":
            reg_ex_mib_per_sec = re.compile(
                r"read, MiB/s:\s+(?P<rd_mib_per_sec>[\d.]+)"
            )
            mib_per_sec = find_group_in_lines(
                lines=data,
                pattern=reg_ex_mib_per_sec,
                single_line=False,
            )
            if mib_per_sec:
                result["read_mib_per_sec"] = mib_per_sec["rd_mib_per_sec"]
            else:
                result["read_mib_per_sec"] = 0

        return result

    def __send_subtest_msg(
        self,
        message_type: Any,
        test_result: Any,
        test_name: str,
        other_fields: Dict[str, Any],
    ) -> None:
        other_fields["tool"] = "sysbench"
        subtest_msg = create_perf_message(
            message_type,
            self.node,
            test_result,
            test_name,
            other_fields,
        )
        notifier.notify(subtest_msg)
