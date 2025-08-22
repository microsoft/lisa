from pathlib import Path
from typing import List, Optional

from lisa import (
    Environment,
    TestCaseMetadata,
    TestResult,
    TestSuite,
    TestSuiteMetadata,
    schema,
    search_space,
    simple_requirement,
)
from lisa.operating_system import Debian, Ubuntu
from lisa.tools import VcRunner
from lisa.util import SkippedException


@TestSuiteMetadata(
    area="virtual_client",
    category="performance",
    description="""
        This test suite runs the performance test cases with Virtual Client.
    """,
)
class VirtualClient(TestSuite):
    @TestCaseMetadata(
        description="""
            This test is to run redis workload testing with Virtual Client.
        """,
        priority=2,
        requirement=simple_requirement(
            supported_os=[Debian],
            min_count=2,
        ),
    )
    def perf_vc_redis(
        self, environment: Environment, result: TestResult, log_path: Path
    ) -> None:
        self._run_work_load(
            environment=environment,
            profile_name="PERF-REDIS",
            roles=["client"],
            test_result=result,
            log_path=log_path,
        )

    @TestCaseMetadata(
        description="""
            This test is to run PostgreSQL workload testing with Virtual Client.
        """,
        priority=3,
        requirement=simple_requirement(
            supported_os=[Debian],
            min_count=2,
            disk=schema.DiskOptionSettings(
                data_disk_count=2,
                data_disk_size=search_space.IntRange(min=256),
            ),
        ),
        timeout=3000,
    )
    def perf_vc_postgresql(
        self, environment: Environment, result: TestResult, log_path: Path
    ) -> None:
        node = environment.nodes[0]
        arch = node.os.get_kernel_information().hardware_platform  # type: ignore
        if arch == "aarch64":
            raise SkippedException(
                f"Virtual Client PostgreSQL doesn't support {arch} architecture."
            )
        if type(node.os) is Ubuntu and node.os.information.version < "20.4.0":
            raise SkippedException(
                f"Virtual Client PostgreSQL doesn't support distro {type(node.os)}"
                f" version {node.os.information.version}."
            )

        self._run_work_load(
            environment=environment,
            profile_name="PERF-POSTGRESQL-HAMMERDB-TPCC",
            test_result=result,
            timeout=45,
            log_path=log_path,
        )

    def _run_work_load(
        self,
        environment: Environment,
        profile_name: str,
        test_result: TestResult,
        log_path: Path,
        timeout: int = 10,
        roles: Optional[List[str]] = None,
    ) -> None:
        if roles is None:
            roles = ["client", "server"]

        vc_runner: VcRunner = VcRunner(environment, roles)
        vc_runner.run(
            node=environment.nodes[0],
            test_result=test_result,
            profile_name=profile_name,
            timeout=timeout,
            log_path=log_path,
        )
