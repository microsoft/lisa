# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import re
import uuid
from pathlib import PurePosixPath
from typing import Any, Dict, List

from assertpy import assert_that

from lisa import (
    Environment,
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
)
from lisa.microsoft.testsuites.performance.common import perf_disk
from lisa.messages import DiskSetupType, DiskType
from lisa.operating_system import Windows
from lisa.sut_orchestrator import CLOUD_HYPERVISOR
from lisa.testsuite import TestResult, simple_requirement
from lisa.tools import FileSystem, Lscpu, Lspci, Ls, Mkfs, Mount
from lisa.util import LisaException, SkippedException
from lisa.util.constants import DEVICE_TYPE_NVME

_PASSTHROUGH_NVME_MOUNT_DIR = "/mnt/passthrough_nvme"


@TestSuiteMetadata(
    area="storage passthrough",
    category="performance",
    description="""
    This test suite runs FIO storage performance benchmarks on NVMe devices
    that have been passed through to the guest VM via PCI device passthrough.
    """,
    requirement=simple_requirement(
        supported_platform_type=[CLOUD_HYPERVISOR],
        unsupported_os=[Windows],
    ),
)
class StoragePassthroughPerfTests(TestSuite):
    TIME_OUT = 12000

    @TestCaseMetadata(
        description="""
            Run FIO performance tests on a passthrough NVMe device inside the
            guest VM. The test discovers the first NVMe namespace visible in
            the guest, formats it with ext4, mounts it, then runs FIO against
            a file on that filesystem with configurable parameters.

            Requires a Cloud Hypervisor platform runbook with pci_nvme device
            passthrough configured, for example:

            platform:
              - type: cloud-hypervisor
                cloud-hypervisor:
                  device_pools:
                    - type: "pci_nvme"
                      devices:
                        pci_bdf:
                          - "0000:04:00.0"
                requirement:
                  cloud-hypervisor:
                    device_passthrough:
                      - pool_type: "pci_nvme"
                        managed: "yes"
                        count: 1

            The fio workload parameters can be customized via the
            ``fio_testcase_list`` runbook variable. If not set, defaults are
            used (4K block size, iodepth 1-256, 120s per iteration).
        """,
        priority=3,
        timeout=TIME_OUT,
        requirement=simple_requirement(
            supported_platform_type=[CLOUD_HYPERVISOR],
        ),
    )
    def perf_storage_passthrough_fio_test(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        result: TestResult,
        variables: Dict[str, Any],
    ) -> None:
        nvme_namespaces = self._get_passthrough_nvme_namespaces(node)
        if not nvme_namespaces:
            raise SkippedException(
                "No NVMe namespaces found in the guest VM. Ensure pci_nvme "
                "device passthrough is configured in the runbook."
            )

        nvme_device = nvme_namespaces[0]
        log.info(
            f"Found {len(nvme_namespaces)} passthrough NVMe namespace(s): "
            f"{nvme_namespaces}. Using '{nvme_device}' for FIO testing."
        )

        # Format, mount, and run FIO against a file on the filesystem.
        mount_point = _PASSTHROUGH_NVME_MOUNT_DIR
        node.shell.mkdir(PurePosixPath(mount_point), exist_ok=True)
        node.tools[Mkfs].format_disk(nvme_device, FileSystem.ext4)
        node.tools[Mount].mount(nvme_device, mount_point, options="nobarrier")

        try:
            core_count = node.tools[Lscpu].get_core_count()
            testcases = variables.get("fio_testcase_list", None)
            if not testcases or len(testcases) == 0:
                testcases = [
                    {
                        "start_iodepth": 1,
                        "max_iodepth": 256,
                        "block_size": 4,
                        "size_mb": 512,
                        "time": 120,
                    },
                ]

            failed_test_cases = []
            for testcase in testcases:
                try:
                    start_iodepth = testcase.get("start_iodepth", 1)
                    max_iodepth = testcase.get("max_iodepth", 256)
                    block_size = testcase.get("block_size", 4)
                    time = testcase.get("time", 120)
                    size_mb = testcase.get("size_mb", 512)
                    overwrite = testcase.get("overwrite", False)

                    test_name = f"passthrough_nvme_{block_size}K"
                    log.info(f"Running FIO testcase: {test_name}")

                    perf_disk(
                        node=node,
                        start_iodepth=start_iodepth,
                        max_iodepth=max_iodepth,
                        filename=f"fio_{uuid.uuid4()}",
                        test_result=result,
                        test_name=test_name,
                        numjob=core_count,
                        block_size=block_size,
                        time=time,
                        size_mb=size_mb,
                        overwrite=overwrite,
                        core_count=core_count,
                        disk_count=1,
                        disk_setup_type=DiskSetupType.raw,
                        disk_type=DiskType.nvme,
                        cwd=PurePosixPath(mount_point),
                    )
                except Exception as e:
                    log.warning(f"FIO testcase failed: {testcase}, error: {e}")
                    failed_test_cases.append(testcase)

            assert_that(
                failed_test_cases, f"Failed FIO testcases: {failed_test_cases}"
            ).is_empty()
        finally:
            node.tools[Mount].umount(nvme_device, mount_point)

    @TestCaseMetadata(
        description="""
            Verify that passthrough NVMe devices are visible inside the guest.
            This is a lightweight functional check that confirms the NVMe
            controller(s) and namespace(s) are present after device passthrough.
        """,
        priority=4,
        requirement=simple_requirement(
            supported_platform_type=[CLOUD_HYPERVISOR],
        ),
    )
    def verify_storage_passthrough_nvme_visible(
        self,
        log: Logger,
        node: Node,
        environment: Environment,
        result: TestResult,
    ) -> None:
        nvme_namespaces = self._get_passthrough_nvme_namespaces(node)
        if not nvme_namespaces:
            raise LisaException(
                "No NVMe namespaces found in the guest VM after device "
                "passthrough. Expected at least one NVMe device."
            )

        log.info(
            f"Verified {len(nvme_namespaces)} passthrough NVMe namespace(s): "
            f"{nvme_namespaces}"
        )

    def _get_passthrough_nvme_namespaces(self, node: Node) -> List[str]:
        lspci = node.tools[Lspci]
        nvme_devices = lspci.get_devices_by_type(DEVICE_TYPE_NVME, force_run=True)
        if not nvme_devices:
            return []

        ls = node.tools[Ls]
        ls_result = ls.run("-l /dev/nvme*n*", shell=True, sudo=True)
        namespace_pattern = re.compile(r"(/dev/nvme\d+n\d+)$", re.MULTILINE)
        namespaces = namespace_pattern.findall(ls_result.stdout)
        return sorted(namespaces)
