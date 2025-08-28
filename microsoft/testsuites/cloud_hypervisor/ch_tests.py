# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
from pathlib import Path
from typing import Any, Dict

from lisa import (
    Logger,
    Node,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    node_requirement,
    schema,
    search_space,
)
from lisa.operating_system import CBLMariner, Ubuntu
from lisa.testsuite import TestResult
from lisa.tools import Dmesg, Journalctl, Ls, Lscpu, Modprobe, Usermod
from lisa.util import SkippedException
from microsoft.testsuites.cloud_hypervisor.ch_tests_tool import CloudHypervisorTests


@TestSuiteMetadata(
    area="cloud-hypervisor",
    category="community",
    description="""
    This test suite is for executing the tests maintained in the
    upstream cloud-hypervisor repo.
    """,
)
class CloudHypervisorTestSuite(TestSuite):
    def before_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        if not isinstance(node.os, (CBLMariner, Ubuntu)):
            raise SkippedException(
                f"Cloud Hypervisor tests are not implemented in LISA for {node.os.name}"
            )
        node.tools[Modprobe].load("openvswitch")
        self._ensure_virtualization_enabled(node)

        variables: Dict[str, Any] = kwargs["variables"]
        use_ms_clh_repo = variables.get("use_ms_clh_repo", None)
        if use_ms_clh_repo == "yes":
            self._set_ms_clh_param(variables)

    def after_case(self, log: Logger, **kwargs: Any) -> None:
        node = kwargs["node"]
        node.tools[Modprobe].remove(["openvswitch"])

        journalctl = node.tools[Journalctl]
        docker_log = journalctl.logs_for_unit(
            unit_name="docker",
            sudo=True,
        )
        log.debug(f"Journalctl Docker Logs: {docker_log}")

        dmesg = node.tools[Dmesg]
        dmesg_log = dmesg.get_output(no_debug_log=True, force_run=True)
        log.debug(f"Dmesg Logs: {dmesg_log}")

    @TestCaseMetadata(
        description="""
            Runs cloud-hypervisor integration tests.
        """,
        priority=3,
        timeout=CloudHypervisorTests.CASE_TIME_OUT,
        requirement=node_requirement(
            node=schema.NodeSpace(
                core_count=search_space.IntRange(min=16),
                memory_mb=search_space.IntRange(min=16 * 1024),
            ),
        ),
    )
    def verify_cloud_hypervisor_integration_tests(
        self,
        node: Node,
        log_path: Path,
        result: TestResult,
        variables: Dict[str, Any],
    ) -> None:
        hypervisor = self._get_hypervisor_param(node)
        ref = variables.get("cloudhypervisor_ref", "")
        # below variable expects a comma separated list of full testnames
        include_list, exclude_list = get_test_list(
            variables, "ch_integration_tests_included", "ch_integration_tests_excluded"
        )
        node.tools[CloudHypervisorTests].run_tests(
            result,
            "integration",
            hypervisor,
            log_path,
            ref,
            include_list,
            exclude_list,
        )

    @TestCaseMetadata(
        description="""
            Runs cloud-hypervisor live migration tests.
        """,
        priority=3,
        timeout=CloudHypervisorTests.CASE_TIME_OUT,
        requirement=node_requirement(
            node=schema.NodeSpace(
                core_count=search_space.IntRange(min=16),
                memory_mb=search_space.IntRange(min=16 * 1024),
            ),
        ),
    )
    def verify_cloud_hypervisor_live_migration_tests(
        self,
        node: Node,
        log_path: Path,
        result: TestResult,
        variables: Dict[str, Any],
    ) -> None:
        hypervisor = self._get_hypervisor_param(node)
        ref = variables.get("cloudhypervisor_ref", "")
        # below variable expects a comma separated list of full testnames
        include_list, exclude_list = get_test_list(
            variables,
            "ch_live_migration_tests_included",
            "ch_live_migration_tests_excluded",
        )
        node.tools[CloudHypervisorTests].run_tests(
            result,
            "integration-live-migration",
            hypervisor,
            log_path,
            ref,
            include_list,
            exclude_list,
        )

    @TestCaseMetadata(
        description="""
            Runs cloud-hypervisor performance metrics tests.
        """,
        priority=3,
        timeout=CloudHypervisorTests.PERF_CASE_TIME_OUT,
    )
    def verify_cloud_hypervisor_performance_metrics_tests(
        self,
        node: Node,
        log_path: Path,
        result: TestResult,
        variables: Dict[str, Any],
    ) -> None:
        hypervisor = self._get_hypervisor_param(node)
        ref = variables.get("cloudhypervisor_ref", "")
        # below variable expects a comma separated list of full testnames
        include_list, exclude_list = get_test_list(
            variables,
            "ch_perf_tests_included",
            "ch_perf_tests_excluded",
        )
        subtest_timeout = variables.get("ch_perf_subtest_timeout", None)
        node.tools[CloudHypervisorTests].run_metrics_tests(
            result,
            hypervisor,
            log_path,
            ref,
            include_list,
            exclude_list,
            subtest_timeout,
        )

    def _ensure_virtualization_enabled(self, node: Node) -> None:
        virtualization_enabled = node.tools[Lscpu].is_virtualization_enabled()
        mshv_exists = node.tools[Ls].path_exists(path="/dev/mshv", sudo=True)
        kvm_exists = node.tools[Ls].path_exists(path="/dev/kvm", sudo=True)
        if not virtualization_enabled and not mshv_exists and not kvm_exists:
            raise SkippedException("Virtualization is not enabled in hardware")
        # add user to mshv group for access to /dev/mshv
        if mshv_exists:
            node.tools[Usermod].add_user_to_group("mshv", sudo=True)

    def _get_hypervisor_param(self, node: Node) -> str:
        kvm_exists = node.tools[Ls].path_exists(path="/dev/kvm", sudo=True)
        if kvm_exists:
            return "kvm"
        mshv_exists = node.tools[Ls].path_exists(path="/dev/mshv", sudo=True)
        if mshv_exists:
            return "mshv"
        return ""

    def _set_ms_clh_param(self, variables: Dict[str, Any]) -> None:
        # Get access token from testing infra to clone the repo
        ms_access_token = variables.get("ms_access_token", None)

        # Get URL for MS CLH repo
        ms_clh_repo = variables.get("ms_clh_repo", None)

        # Get GUEST VM type, set default to NON-CVM
        clh_guest_vm_type = variables.get("clh_guest_vm_type", "NON-CVM")

        # Check if MS Guest kernel/hypervisor-fw/OVMF-fw need to be used
        # Dom0 VHD is shipped with those binaries now
        # Default, we will use upstream CLH binaries only
        use_ms_guest_kernel = variables.get("use_ms_guest_kernel", "NO")
        use_ms_hypervisor_fw = variables.get("use_ms_hypervisor_fw", "NO")
        use_ms_ovmf_fw = variables.get("use_ms_ovmf_fw", "NO")
        use_ms_bz_image = variables.get("use_ms_bz_image", "NO")

        # Below three params are for running block_* clh perf test
        # with no disk caching and with direct mode. By Default, we
        # will not run it with data-disk and it would not add direct=on
        # if run_without_cache is not set to YES
        use_datadisk = variables.get("ch_tests_use_datadisk", "")
        use_pmem = variables.get("ch_tests_use_pmem", "")
        pmem_config = variables.get("ch_tests_pmem_config", "")
        disable_disk_cache = variables.get("ch_tests_disable_disk_cache", "")
        mibps_block_size_kb = variables.get("ch_tests_mibps_block_size_kb", "")
        iops_block_size_kb = variables.get("ch_tests_iops_block_size_kb", "")

        if not ms_access_token:
            raise SkippedException("Access Token is needed while using MS-CLH")
        if not ms_clh_repo:
            raise SkippedException("CLH URL is needed while using MS-CLH")

        CloudHypervisorTests.use_ms_clh_repo = True
        CloudHypervisorTests.ms_access_token = ms_access_token
        CloudHypervisorTests.ms_clh_repo = ms_clh_repo
        CloudHypervisorTests.clh_guest_vm_type = clh_guest_vm_type
        if use_ms_guest_kernel == "YES":
            CloudHypervisorTests.use_ms_guest_kernel = use_ms_guest_kernel
        if use_ms_hypervisor_fw == "YES":
            CloudHypervisorTests.use_ms_hypervisor_fw = use_ms_hypervisor_fw
        if use_ms_ovmf_fw == "YES":
            CloudHypervisorTests.use_ms_ovmf_fw = use_ms_ovmf_fw
        if use_ms_bz_image == "YES":
            CloudHypervisorTests.use_ms_bz_image = use_ms_bz_image

        if mibps_block_size_kb:
            CloudHypervisorTests.mibps_block_size_kb = mibps_block_size_kb
        if iops_block_size_kb:
            CloudHypervisorTests.iops_block_size_kb = iops_block_size_kb
        if use_pmem:
            CloudHypervisorTests.use_pmem = use_pmem
            if pmem_config:
                CloudHypervisorTests.pmem_config = pmem_config
        if use_datadisk:
            CloudHypervisorTests.use_datadisk = use_datadisk
        if disable_disk_cache:
            CloudHypervisorTests.disable_disk_cache = disable_disk_cache


def get_test_list(variables: Dict[str, Any], var1: str, var2: str) -> Any:
    tests_raw = variables.get(var1, "")
    test_list1 = tests_raw.split(",") if tests_raw else None
    tests_raw = variables.get(var2, "")
    test_list2 = tests_raw.split(",") if tests_raw else None
    return test_list1, test_list2
