# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from pathlib import PurePosixPath

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.sut_orchestrator import AZURE, READY
from lisa.sut_orchestrator.azure.tools import KvpClient
from lisa.tools import Pgrep
from lisa.util import get_matched_str


@TestSuiteMetadata(
    area="kvp",
    category="functional",
    description="""
    This test suite verify the KVP service runs well on Azure and Hyper-V
    platforms. The KVP is used to communicate between Windows host and guest VM.
    """,
    requirement=simple_requirement(supported_platform_type=[AZURE, READY]),
)
class Kvp(TestSuite):
    # lrwx------ 1 root root 64 Oct 18 19:05 9 -> /dev/vmbus/hv_kvp
    _hv_kvp_pattern = re.compile(r".* /dev/vmbus/(hv_kvp)$", re.M)

    @TestCaseMetadata(
        description="""
    Verify KVP daemon installed, running, permission correct.

    1. verify that the KVP Daemon is running.
    2. run the KVP client tool and verify that the data pools are created and
       accessible.
    3. check kvp_pool file permission is 644.
    4. check kernel version supports hv_kvp.
    5. Check if KVP pool 3 file has a size greater than zero.
    6. At least 11 items are present in pool 3, and verify record count is
       correct.
    """,
        priority=1,
    )
    def verify_kvp(self, node: Node, log: Logger) -> None:
        # 1. verify that the KVP Daemon is running.
        pgrep = node.tools[Pgrep]
        processes = pgrep.get_processes("hypervkvpd|hv_kvp_daemon")
        assert_that(
            processes,
            "cannot find running kvp daemon, or find multiple running kvp processes.",
        ).is_length(1)
        kvp_daemon_pid = processes[0].id

        # 2. run the KVP client tool
        kvp_client = node.tools[KvpClient]
        pool_count = kvp_client.get_pool_count()
        assert_that(pool_count, "kvp pool count must be 5").is_equal_to(5)

        # 3. check kvp_pool file permission is 644.
        for i in range(pool_count):
            stat = node.shell.stat(PurePosixPath(f"/var/lib/hyperv/.kvp_pool_{i}"))
            assert_that(
                stat.st_mode,
                f"the permission of /var/lib/hyperv/.kvp_pool_{i} must be 644",
            ).is_equal_to(0o100644)

        # 4. check kernel version supports hv_kvp.
        result = node.execute(
            f"ls -al /proc/{kvp_daemon_pid}/fd",
            sudo=True,
            expected_exit_code=0,
            expected_exit_code_failure_message="error on list kvp process fd",
        )
        hv_kvp = get_matched_str(result.stdout, self._hv_kvp_pattern)
        assert_that(
            hv_kvp,
            f"Cannot find hv_kvp in '/proc/{kvp_daemon_pid}/fd'. "
            "the kernel may not support hv_kvp.",
        ).is_equal_to("hv_kvp")

        # 5. Check if KVP pool 3 file has a size greater than zero.
        stat = node.shell.stat(PurePosixPath("/var/lib/hyperv/.kvp_pool_3"))
        assert_that(
            stat.st_size,
            "the file size of '/var/lib/hyperv/.kvp_pool_3' must be greater than zero",
        ).is_greater_than(0)

        # 6. At least 11 items are present in pool 3.
        records = kvp_client.get_pool_records(3)
        assert_that(
            len(records), "pool 3 must have at least 11 records"
        ).is_greater_than_or_equal_to(11)
