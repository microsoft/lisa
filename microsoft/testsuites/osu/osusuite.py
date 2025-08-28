# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path, PurePath, PurePosixPath

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.features import Gpu, GpuEnabled, SerialConsole
from lisa.operating_system import Debian, Posix, RPMDistro
from lisa.tools import Chmod, Ls, Lscpu, Make, Tar, Wget
from lisa.util import SkippedException, UnsupportedDistroException

OSU_MPI_LOCATION = (
    "https://mvapich.cse.ohio-state.edu/download/mvapich/mv2/mvapich2-2.3.7-1.tar.gz"
)
OSU_MPI_FILE_NAME = "mvapich2.tgz"

OSU_BENCH_LOCATION = (
    "http://mvapich.cse.ohio-state.edu/download/mvapich/osu-micro-benchmarks-6.2.tar.gz"
)
OSU_BENCH_FILE_NAME = "osu-bench.tgz"


@TestSuiteMetadata(
    area="hpc",
    category="performance",
    name="OSU Bench",
    description="""
    This test suite runs the OSU Micro-Benchmarks MPI test cases.
    """,
)
class OSUTestSuite(TestSuite):
    TIMEOUT = 200000

    @TestCaseMetadata(
        description="""
            This test case runs GPU/CPU MPI latency.

            Steps:
            1. Install MVAPICH;
            2. Install OSU Micro-Benchmarks;
            3. Run GPU/CPU collective/latency tests in a single node.

        """,
        timeout=TIMEOUT,
        requirement=simple_requirement(
            supported_features=[GpuEnabled(), SerialConsole],
        ),
        priority=2,
    )
    def perf_mpi_operations(self, node: Node, log: Logger, log_path: Path) -> None:
        if node.tools[Ls].path_exists("/opt/azurehpc/component_versions.txt"):
            _install_osu_mpi(node)
            path = _install_osu_bench(node)

            gpu_count = node.capability.gpu_count
            gpu = node.features[Gpu]
            expected_count = gpu.get_gpu_count_with_lspci()
            assert_that(gpu_count).described_as(
                "Expected device count didn't match actual device count from lspci!"
            ).is_equal_to(expected_count)

            nproc = node.tools[Lscpu].get_thread_count()
            tests = [
                "allgather",
                "allreduce",
                "alltoall",
                "bcast",
                "gather",
                "reduce_scatter",
                "reduce",
                "scatter",
            ]
            for test in tests:
                node.execute(
                    f"mpirun -np {nproc} python3.8 {path}/python/run.py"
                    f" --benchmark {test} --min 128 --max 10000000 >> "
                    f"{path}/osu_bench.log",  # 2>&1
                    expected_exit_code=0,
                    expected_exit_code_failure_message=(
                        f"failed to run mpirun {test} benchmark"
                    ),
                    timeout=1200,
                    shell=True,
                    sudo=True,
                )
            log.info("OSU MPI tests finish!")
            osu_log_path = str(node.get_pure_path(f"{path}/osu_bench.log"))
            node.tools[Chmod].chmod(osu_log_path, "a+rwX", sudo=True)
            node.shell.copy_back(
                node.get_pure_path(osu_log_path), PurePath(log_path) / "osu_bench.log"
            )
        else:
            raise SkippedException("OSU MPI tests are not supported on non-HPC images.")


def _install_osu_mpi(node: Node) -> None:
    assert isinstance(node.os, Posix)
    if isinstance(node.os, Debian):
        node.os.install_packages(["libibverbs-dev", "gfortran", "bison"])
    elif isinstance(node.os, RPMDistro):
        node.os.install_packages(["rdma-core-devel", "gfortran", "bison"])
    else:
        raise UnsupportedDistroException(
            node.os, "osu test suite not implemented on this OS"
        )
    wget = node.tools[Wget]
    tar = node.tools[Tar]

    path = node.get_working_path()
    if node.shell.exists(path / OSU_MPI_FILE_NAME):
        return

    download_path = wget.get(
        url=OSU_MPI_LOCATION, filename=str(OSU_MPI_FILE_NAME), file_path=str(path)
    )
    tar.extract(download_path, dest_dir=str(path))

    source_code_folder_path = PurePosixPath(f"{path}/mvapich2-2.3.7-1")
    node.execute(
        "./configure --prefix=/usr/local/",
        cwd=source_code_folder_path,
        shell=True,
        expected_exit_code=0,
        expected_exit_code_failure_message="fail to run configure command",
    )
    node.tools[Make].make_install(cwd=source_code_folder_path)


def _install_osu_bench(node: Node) -> str:
    wget = node.tools[Wget]
    tar = node.tools[Tar]

    path = node.get_working_path()
    if node.shell.exists(path / OSU_BENCH_FILE_NAME):
        return str(path) + "/osu-micro-benchmarks-6.2"

    download_path = wget.get(
        url=OSU_BENCH_LOCATION, filename=str(OSU_BENCH_FILE_NAME), file_path=str(path)
    )
    tar.extract(download_path, dest_dir=str(path))
    assert isinstance(node.os, Posix)
    node.os.install_packages("python3.8-dev python3.8-distutils")
    node.execute(
        "curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py",
        shell=True,
        sudo=True,
        expected_exit_code=0,
    )
    node.execute("python3.8 get-pip.py", shell=True, sudo=True, expected_exit_code=0)
    node.execute(
        "pip3.8 install numpy numba mpi4py cupy-cuda116",
        shell=True,
        sudo=True,
        expected_exit_code=0,
    )
    node.execute(
        "export PATH=/usr/local/cuda/bin:$PATH; pip3.8 install pycuda",
        shell=True,
        sudo=True,
        expected_exit_code=0,
    )

    return str(path) + "/osu-micro-benchmarks-6.2"
