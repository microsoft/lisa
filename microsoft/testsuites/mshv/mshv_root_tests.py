# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
from pathlib import Path
from typing import Any, Dict

from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.testsuite import TestResult
from lisa.tools import Dmesg, KernelConfig, Ls, Service
from lisa.util import LisaException, SkippedException


@TestSuiteMetadata(
    area="mshv",
    category="functional",
    description="""
    This test suite contains tests that should be run on the
    Microsoft Hypervisor (MSHV) root partition. This test suite contains tests
    to check health of mshv root node.
    """,
)
class MshvHostTestSuite(TestSuite):
    mshvdiag_dmesg_pattern = re.compile(r"\[\s+\d+.\d+\]\s+mshv_diag:.*$")

    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        if not node.tools[KernelConfig].is_enabled("CONFIG_MSHV_DIAG"):
            raise SkippedException("MSHV_DIAG not enabled, skip")

        if not node.tools[Ls].path_exists("/dev/mshv_diag", sudo=True):
            raise LisaException(
                "mshv_diag device should exist, when CONFIG_MSHV_DIAG is enabled."
            )

    @TestCaseMetadata(
        description="""
        With mshv_diag module loaded, ensure mshvlog.service starts and runs
        successfully on MSHV root partitions. Also confirm there are no errors
        reported by mshv_diag module in dmesg.
        """,
        priority=4,
        timeout=30,  # 30 seconds
    )
    def verify_mshvlog_is_active(
        self,
        log: Logger,
        node: Node,
        variables: Dict[str, Any],
        environment: Environment,
        log_path: Path,
        result: TestResult,
    ) -> None:
        self._save_dmesg_logs(node, log_path)
        mshvlog_running = node.tools[Service].is_service_running("mshvlog")
        if not mshvlog_running:
            log.error("mshvlog service is not running on MSHV root partition.")

        assert_that(mshvlog_running).is_true()

        dmesg_logs = node.tools[Dmesg].get_output()
        mshvdiag_dmesg_logs = re.search(self.mshvdiag_dmesg_pattern, dmesg_logs)
        if mshvdiag_dmesg_logs is not None:
            log.error(
                f"mshv_diag module reported errors in dmesg: "
                f"{mshvdiag_dmesg_logs.group(0)}"
            )
        assert_that(mshvdiag_dmesg_logs).is_none()

        return

    def _save_dmesg_logs(self, node: Node, log_path: Path) -> None:
        dmesg_str = node.tools[Dmesg].get_output()
        dmesg_path = log_path / "dmesg"
        with open(str(dmesg_path), "w", encoding="utf-8") as f:
            f.write(dmesg_str)
