# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re

from assertpy import assert_that

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
)
from lisa.operating_system import BSD
from lisa.sut_orchestrator import AZURE, HYPERV, READY
from lisa.sut_orchestrator.azure.tools import KvpClient
from lisa.tools import Pgrep, Stat
from lisa.util import get_matched_str


@TestSuiteMetadata(
    area="kvp",
    category="functional",
    description="""
    This test suite verify the KVP service runs well on Azure and Hyper-V
    platforms. The KVP is used to communicate between Windows host and guest VM.
    """,
    requirement=simple_requirement(supported_platform_type=[AZURE, READY, HYPERV]),
)
class Kvp(TestSuite):
    # lrwx------ 1 root root 64 Oct 18 19:05 9 -> /dev/vmbus/hv_kvp
    _hv_kvp_pattern = re.compile(r".* /dev/vmbus/(hv_kvp)\r?$", re.M)

    @TestCaseMetadata(
        description="""
    Verify KVP daemon installed, running, permission correct.

    1. run the KVP client tool and verify that the data pools are created and
       accessible.
    2. check kvp_pool file permission is 644.
    3. verify that the KVP Daemon is running.
    4. check kernel version supports hv_kvp.
    5. Check if KVP pool 3 file has a size greater than zero.
    6. At least 11 items are present in pool 3, and verify record count is
       correct.
    """,
        priority=1,
    )
    def verify_kvp(self, node: Node, log: Logger) -> None:
        if isinstance(node.os, BSD):
            kvp_pool_path = "/var/db/hyperv/pool"
            kvp_process_name = "hv_kvp_daemon"
            kvp_file_permission = 600
        else:
            kvp_pool_path = "/var/lib/hyperv"
            kvp_process_name = "hypervkvpd|hv_kvp_daemon"
            kvp_file_permission = 644

        # 1. run the KVP client tool
        kvp_client = node.tools[KvpClient]
        pool_count = kvp_client.get_pool_count()
        assert_that(pool_count, "kvp pool count must be 5").is_equal_to(5)

        # 2. check kvp_pool file permission is 644.
        for i in range(pool_count):
            permission = node.tools[Stat].get_file_permission(
                f"{kvp_pool_path}/.kvp_pool_{i}", sudo=True
            )
            assert_that(
                permission,
                f"the permission of {kvp_pool_path}/.kvp_pool_{i} must be 644",
            ).is_equal_to(kvp_file_permission)

        # 3. verify that the KVP Daemon is running.
        pgrep = node.tools[Pgrep]
        processes = pgrep.get_processes(kvp_process_name)
        assert_that(
            processes,
            "cannot find running kvp daemon, or find multiple running kvp processes.",
        ).is_length(1)
        kvp_daemon_pid = processes[0].id

        # 4. check kernel version supports hv_kvp.
        if not isinstance(node.os, BSD):
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
        block3_size = node.tools[Stat].get_total_size(
            f"{kvp_pool_path}/.kvp_pool_3", sudo=True
        )
        assert_that(
            block3_size,
            f"the file size of '{kvp_pool_path}/.kvp_pool_3' must be greater than zero",
        ).is_greater_than(0)

        # 6. At least 11 items are present in pool 3.
        records = kvp_client.get_pool_records(3)
        assert_that(
            len(records), "pool 3 must have at least 11 records"
        ).is_greater_than_or_equal_to(11)
