# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, cast

from lisa.executable import Tool
from lisa.notifier import DiskPerformanceMessage
from lisa.operating_system import Debian, Posix, Redhat, Suse
from lisa.util import LisaException, dict_to_fields

from .git import Git


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
        r"([\w\W]*?)IOPS=(?P<iops>.+?)," r"([\w\W]*?).* lat.*avg=(?P<latency>.+?),",
        re.M,
    )

    @property
    def command(self) -> str:
        return "fio"

    @property
    def can_install(self) -> bool:
        return True

    def install(self) -> bool:
        posix_os: Posix = cast(Posix, self.node.os)
        posix_os.install_packages("fio")
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
        block_size: str = "4K",
        size_gb: int = 0,
        direct: bool = True,
        gtod_reduce: bool = False,
        ioengine: str = "libaio",
        group_reporting: bool = True,
        overwrite: bool = False,
    ) -> FIOResult:
        cmd = (
            f"--ioengine={ioengine} --bs={block_size} --filename={filename} "
            f"--readwrite={mode} --runtime={time} --iodepth={iodepth} "
            f"--numjob={numjob} --name={name}"
        )
        if direct:
            cmd += " --direct=1"
        if gtod_reduce:
            cmd += " --gtod_reduce=1"
        if size_gb:
            cmd += f" --size={size_gb}G"
        if group_reporting:
            cmd += " --group_reporting"
        if overwrite:
            cmd += " --overwrite=1"
        result = self.run(
            cmd,
            force_run=True,
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message=f"fail to run {cmd}",
        )
        matched_results = self._result_pattern.match(result.stdout)
        assert matched_results, "not found matched iops and latency from fio results."
        iops = matched_results.group("iops")
        if iops.endswith("k"):
            iops_value = Decimal(iops[:-1]) * 1000
        else:
            iops_value = Decimal(iops)
        latency = matched_results.group("latency")
        fio_result = FIOResult()
        fio_result.iops = iops_value
        fio_result.latency = Decimal(latency)
        fio_result.iodepth = iodepth
        fio_result.qdepth = iodepth * numjob
        fio_result.mode = mode
        return fio_result

    def create_performance_messages(
        self, fio_results_list: List[FIOResult]
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
            fio_result_message = DiskPerformanceMessage()
            fio_result_message = dict_to_fields(result, fio_result_message)
            fio_message.append(fio_result_message)
        return fio_message

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
            package_list = ["wget", "mdadm", "blktrace", "libaio1", "sysstat", "bc"]
        else:
            raise LisaException(
                f"tool {self.command} can't be installed in distro {self.node.os.name}."
            )
        for package in list(package_list):
            if posix_os.is_package_in_repo(package):
                posix_os.install_packages(package)

    def _install_from_src(self) -> bool:
        self._install_dep_packages()
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
            "ln -s /usr/local/bin/fio /usr/bin/fio", sudo=True, cwd=code_path
        ).assert_exit_code()
        return self._check_exists()
