# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import pathlib
import re
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, cast

from lisa.executable import Tool
from lisa.messages import DiskPerformanceMessage, create_perf_message
from lisa.operating_system import BSD, CBLMariner, CentOs, Debian, Posix, Redhat, Suse
from lisa.util import LisaException, RepoNotExistException, constants
from lisa.util.process import Process

from .git import Git

if TYPE_CHECKING:
    from lisa.testsuite import TestResult


class FIOResult:
    qdepth: int = 0
    mode: str = ""
    iops: Decimal = Decimal(0)
    latency: Decimal = Decimal(0)
    iodepth: int = 0


FIOMODES = Enum(
    "FIOMODES",
    [
        "randread",
        "randwrite",
        "read",
        "write",
    ],
)


class IoEngine(Enum):
    IO_URING = "io_uring"
    LIBAIO = "libaio"
    POSIXAIO = "posixaio"

    def __str__(self) -> str:
        return self.value


class Fio(Tool):
    fio_repo = "https://github.com/axboe/fio/"
    branch = "fio-3.29"
    # iteration21: (groupid=0, jobs=64): err= 0: pid=6157: Fri Dec 24 08:55:21 2021
    # read: IOPS=3533k, BW=13.5GiB/s (14.5GB/s)(1617GiB/120003msec)
    # slat (nsec): min=1800, max=30492k, avg=11778.91, stdev=18599.91
    # clat (nsec): min=500, max=93368k, avg=130105.42, stdev=57833.37
    # lat (usec): min=18, max=93375, avg=142.51, stdev=59.57
    # get IOPS and total delay
    _result_pattern = re.compile(
        r"([\w\W]*?)IOPS=(?P<iops>.+?),([\w\W]*?).* lat.*avg=(?P<latency>.+?),",
        re.M | re.IGNORECASE,
    )

    @property
    def command(self) -> str:
        return "fio"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        try:
            posix_os.install_packages("fio")
        except RepoNotExistException as e:
            raise e
        except Exception as e:
            self._log.debug(f"failed to install fio from package: {e}")

        if not self._check_exists():
            self._install_from_src()
        return self._check_exists()

    def launch(
        self,
        name: str,
        filename: str,
        mode: str,
        iodepth: int,
        numjob: int,
        time: int = 120,
        ssh_timeout: int = 6400,
        block_size: str = "4K",
        size_gb: int = 0,
        direct: bool = True,
        gtod_reduce: bool = False,
        group_reporting: bool = True,
        overwrite: bool = False,
        time_based: bool = False,
        do_verify: bool = False,
        bsrange: str = "",
        verify_dump: bool = False,
        verify_fatal: bool = False,
        verify: str = "",
        ioengine: IoEngine = IoEngine.LIBAIO,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> FIOResult:
        cmd = self._get_command(
            name,
            filename,
            mode,
            iodepth,
            numjob,
            time,
            block_size,
            size_gb,
            direct,
            gtod_reduce,
            group_reporting,
            overwrite,
            time_based,
            do_verify,
            bsrange,
            verify_dump,
            verify_fatal,
            verify,
            ioengine,
        )
        result = self.run(
            cmd,
            force_run=True,
            sudo=True,
            cwd=cwd,
            timeout=ssh_timeout,
        )
        if result.exit_code != 0:
            raise LisaException(f"fail to run {cmd} with {result.stdout}")
        fio_result = self.get_result_from_raw_output(
            mode, result.stdout, iodepth, numjob
        )
        return fio_result

    def launch_async(
        self,
        name: str,
        filename: str,
        mode: str,
        iodepth: int,
        numjob: int,
        time: int = 120,
        block_size: str = "4K",
        size_gb: int = 0,
        direct: bool = True,
        gtod_reduce: bool = False,
        group_reporting: bool = True,
        overwrite: bool = False,
        time_based: bool = False,
        do_verify: bool = False,
        bsrange: str = "",
        verify_dump: bool = False,
        verify_fatal: bool = False,
        verify: str = "",
        ioengine: IoEngine = IoEngine.LIBAIO,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> Process:
        cmd = self._get_command(
            name,
            filename,
            mode,
            iodepth,
            numjob,
            time,
            block_size,
            size_gb,
            direct,
            gtod_reduce,
            group_reporting,
            overwrite,
            time_based,
            do_verify,
            bsrange,
            verify_dump,
            verify_fatal,
            verify,
            ioengine,
        )
        process = self.run_async(
            cmd,
            force_run=True,
            sudo=True,
            cwd=cwd,
        )

        # FIO output emits lines of the following form when it is running
        # (f=10): [M(10)][24.9%][r=70.0MiB/s,w=75.0MiB/s]
        # [r=70,w=75 IOPS][eta 03m:46s]
        # check if stdout buffers contain the string "eta" to
        # determine if it is running
        process.wait_output("eta")

        return process

    def get_result_from_raw_output(
        self, mode: str, output: str, iodepth: int, numjob: int
    ) -> FIOResult:
        # match raw output to get iops and latency
        matched_results = self._result_pattern.match(output)
        assert matched_results, "not found matched iops and latency from fio results."
        # 'K' in IOPS can be lower or upper case. forcing to lower for simplicity
        # read: IOPS=947k, BW=3701MiB/s (3880MB/s)(434GiB/120001msec)
        # read : io=803081MB, bw=6692.3MB/s, iops=1713.3K, runt=120001msec
        iops = matched_results.group("iops").lower()
        if iops.endswith("k"):
            iops_value = Decimal(iops[:-1]) * 1000
        else:
            iops_value = Decimal(iops)
        latency = matched_results.group("latency")

        # create fio result object
        fio_result = FIOResult()
        fio_result.iops = iops_value
        fio_result.latency = Decimal(latency)
        fio_result.iodepth = iodepth
        fio_result.qdepth = iodepth * numjob
        fio_result.mode = mode

        return fio_result

    def create_performance_messages(
        self,
        fio_results_list: List[FIOResult],
        test_name: str,
        test_result: "TestResult",
        other_fields: Optional[Dict[str, Any]] = None,
    ) -> List[DiskPerformanceMessage]:
        fio_message: List[DiskPerformanceMessage] = []
        mode_iops_latency: Dict[int, Dict[str, Any]] = {}
        for fio_result in fio_results_list:
            temp: Dict[str, Any] = {}
            if fio_result.qdepth in mode_iops_latency.keys():
                temp = mode_iops_latency[fio_result.qdepth]
            temp[f"{fio_result.mode}_iops"] = fio_result.iops
            temp[f"{fio_result.mode}_lat_usec"] = fio_result.latency
            temp["iodepth"] = fio_result.iodepth
            temp["qdepth"] = fio_result.qdepth
            temp["numjob"] = int(fio_result.qdepth / fio_result.iodepth)
            mode_iops_latency[fio_result.qdepth] = temp

        for result in mode_iops_latency.values():
            result_copy = result.copy()
            result_copy["tool"] = constants.DISK_PERFORMANCE_TOOL_FIO
            if other_fields:
                result_copy.update(other_fields)
            fio_result_message = create_perf_message(
                DiskPerformanceMessage, self.node, test_result, test_name, result_copy
            )
            fio_message.append(fio_result_message)
        return fio_message

    def _get_command(  # noqa: C901
        self,
        name: str,
        filename: str,
        mode: str,
        iodepth: int,
        numjob: int = 0,
        time: int = 120,
        block_size: str = "4K",
        size_gb: int = 0,
        direct: bool = True,
        gtod_reduce: bool = False,
        group_reporting: bool = True,
        overwrite: bool = False,
        time_based: bool = False,
        do_verify: bool = False,
        bsrange: str = "",
        verify_dump: bool = False,
        verify_fatal: bool = False,
        verify: str = "",
        ioengine: IoEngine = IoEngine.LIBAIO,
    ) -> str:
        if isinstance(self.node.os, BSD):
            ioengine = IoEngine.POSIXAIO

        cmd = (
            f"--ioengine={ioengine.value} --filename={filename} "
            f"--readwrite={mode} --iodepth={iodepth} "
            f"--name={name}"
        )

        if time:
            cmd += f" --runtime={time}"
        if block_size:
            cmd += f" --bs={block_size}"
        if numjob:
            cmd += f" --numjob={numjob}"
        if direct:
            cmd += " --direct=1"
        if gtod_reduce:
            cmd += " --gtod_reduce=1"
        if size_gb:
            cmd += f" --size={size_gb}M"
        if group_reporting:
            cmd += " --group_reporting"
        if overwrite:
            cmd += " --overwrite=1"
        if time_based:
            cmd += " --time_based"
        if do_verify:
            cmd += " --do_verify=1"
        if bsrange:
            cmd += f" --bsrange={bsrange}"
        if verify_dump:
            cmd += " --verify_dump=1"
        if verify_fatal:
            cmd += " --verify_fatal=1"
        if verify:
            cmd += f" --verify={verify}"

        return cmd

    def _install_dep_packages(self) -> None:
        posix_os: Posix = cast(Posix, self.node.os)
        if isinstance(self.node.os, Redhat):
            package_list = [
                "wget",
                "sysstat",
                "mdadm",
                "blktrace",
                "libaio",
                "bc",
                "libaio-devel",
                "gcc",
                "gcc-c++",
                "kernel-devel",
                "libpmem-devel",
            ]
        elif isinstance(self.node.os, Debian):
            package_list = [
                "pciutils",
                "gawk",
                "mdadm",
                "wget",
                "sysstat",
                "blktrace",
                "bc",
                "libaio-dev",
                "zlib1g-dev",
            ]
        elif isinstance(self.node.os, Suse):
            package_list = [
                "wget",
                "mdadm",
                "blktrace",
                "libaio1",
                "sysstat",
                "bc",
                "libaio-devel",
            ]
        elif isinstance(self.node.os, CBLMariner):
            package_list = [
                "wget",
                "build-essential",
                "sysstat",
                "blktrace",
                "libaio",
                "bc",
                "libaio-devel",
                "gcc",
                "kernel-devel",
                "kernel-headers",
                "binutils",
                "glibc-devel",
                "zlib-devel",
            ]
        else:
            raise LisaException(
                f"tool {self.command} can't be installed in distro {self.node.os.name}."
            )
        for package in list(package_list):
            if posix_os.is_package_in_repo(package):
                posix_os.install_packages(package)

    def _install_from_src(self) -> bool:
        self._install_dep_packages()
        if (
            isinstance(self.node.os, Redhat)
            and self.node.os.information.version < "8.0.0"
        ):
            posix_os: Posix = cast(Posix, self.node.os)
            if isinstance(self.node.os, CentOs):
                posix_os.install_packages("centos-release-scl")
            posix_os.install_packages(
                packages="devtoolset-8-gcc*", extra_args=["--skip-broken"]
            )
            self.node.execute("rm -f /bin/gcc", sudo=True, shell=True)
            self.node.execute(
                "ln -s /opt/rh/devtoolset-8/root/usr/bin/gcc /bin/gcc",
                sudo=True,
                shell=True,
            )
        tool_path = self.get_tool_path()
        self.node.shell.mkdir(tool_path, exist_ok=True)
        git = self.node.tools[Git]
        git.clone(self.fio_repo, tool_path)
        code_path = tool_path.joinpath("fio")
        git.checkout(
            ref="refs/heads/master", cwd=code_path, checkout_branch=self.branch
        )
        from .make import Make

        make = self.node.tools[Make]
        make.make_install(cwd=code_path)
        self.node.execute(
            "ln -sf /usr/local/bin/fio /usr/bin/fio", sudo=True, cwd=code_path
        ).assert_exit_code()
        return self._check_exists()
